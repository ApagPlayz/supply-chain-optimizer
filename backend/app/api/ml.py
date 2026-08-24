"""
ML Intelligence API endpoints.

GET /ml/stress             — macro stress regime signal, or an explicit "unavailable"
GET /ml/model-comparison   — held-out + repeated-CV metrics for the SERVED estimator,
                             its three naive baselines, and the exact feature schema
GET /ml/lead-time          — predict FACTORY lead time for a (category, stock, price) query
GET /ml/model-info         — WHICH model actually served that prediction and from where
                             (MLflow `champion` alias vs the committed on-disk joblib)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.ml import get_ml_state
from app.ml.lead_time_model import (
    FEATURE_SCHEMA_VERSION,
    FeatureSchemaMismatch,
    MissingFeatureError,
    UnknownCategoryError,
    build_feature_row,
    known_categories,
    optional_record_keys,
    predict_lead_time,
    primary_category_feature,
    required_record_keys,
)
from app.ml.lead_time_labels import get_base_days
from app.ml.serving import SOURCE_NONE, get_serving_model, model_source
from app.models.component import Component

router = APIRouter(prefix="/ml", tags=["ml"])


# ── Serve-layer path sanitization ───────────────────────────────────────────
# Provenance is worth publishing; the filesystem of the machine that produced it
# is not. Absolute paths captured at fit time (a laptop home directory) or at
# import time (the Render container root) leak an identity and a host layout to
# every anonymous caller of a public endpoint, and they are meaningless to the
# reader anyway — what matters is WHICH FILE IN THIS REPO, i.e. the repo-relative
# path. Training-time capture is being fixed separately to store relative paths;
# this is the defence-in-depth layer that holds regardless of what an already
# built artifact happens to carry, including artifacts trained on another host.
#
# Rule: rewrite any absolute path to the part of it that is repo-relative, and
# if no repo anchor is present, keep only the basename.

# A repo-relative path starts at one of the repo's own top-level directories.
_REPO_ANCHOR_RE = re.compile(r"/(?:backend|frontend|docs|scripts|alembic|infra)/")
# Characters that can never be part of a path token we would rewrite.
_PATH_STOP_CHARS = set("\"'`()[]{}<>,;:=|*?!")
# A whitespace-free absolute path with at least two segments, not preceded by a
# word char, ':' or '/' (so "models:/lead_time_predictor@champion" is untouched).
_BARE_ABS_PATH_RE = re.compile(r"(?<![\w:/~.-])(?:/[\w.~@%+-]+){2,}")
# Last resort: never emit a username, whatever shape the path had.
_HOME_DIR_RE = re.compile(r"/(?:Users|home)/[^/\s]+")


def _path_token_start(text: str, pos: int) -> int:
    """Walk back from a repo anchor to the first character of the path token.

    Absolute paths on this project's own dev machine contain spaces ("Claude
    Projects/"), so a space is absorbed only when it looks like it sits INSIDE a
    path (the token so far does not start with '/', and the character before the
    space is a path-segment character). A space directly before a '/' is prose
    separation ("... and /opt/render/..."), and stops the walk.
    """
    i = pos
    while i > 0:
        c = text[i - 1]
        if c == " ":
            if i >= len(text) or text[i] == "/":
                break
            prev = text[i - 2] if i >= 2 else ""
            if not (prev.isalnum() or prev in "._-"):
                break
            i -= 1
            continue
        if c.isspace() or c in _PATH_STOP_CHARS:
            break
        i -= 1
    return i


def _path_token_end(text: str, pos: int) -> int:
    """Walk forward to the end of the path token, leaving sentence punctuation."""
    j, n = pos, len(text)
    while j < n and not text[j].isspace() and text[j] not in _PATH_STOP_CHARS:
        j += 1
    while j > pos and text[j - 1] == ".":
        j -= 1
    return j


def _relativize_anchored_paths(text: str) -> str:
    """`/anywhere/at/all/backend/x.csv` -> `backend/x.csv`."""
    out: List[str] = []
    idx = 0
    while True:
        m = _REPO_ANCHOR_RE.search(text, idx)
        if m is None:
            out.append(text[idx:])
            return "".join(out)
        start = _path_token_start(text, m.start())
        end = _path_token_end(text, m.end())
        # Only rewrite something that really is one absolute path token.
        if text[start] != "/" or text.startswith("//", start):
            out.append(text[idx:end])
        else:
            out.append(text[idx:start])
            # Keep only the repo-relative tail, starting at the anchor directory.
            out.append(text[m.start() + 1:end])
        idx = end


def sanitize_server_paths(text: str) -> str:
    """Strip host filesystem layout and identity out of a published string.

    Pure and total: safe to run over any response string, including prose that
    merely happens to mention a path in the middle of a sentence.
    """
    if not text or "/" not in text:
        return text
    out = _relativize_anchored_paths(text)
    # Anything still absolute has no repo anchor (a temp dir, a home directory):
    # keep only the file name, which is the only informative part.
    out = _BARE_ABS_PATH_RE.sub(lambda m: ".../" + m.group(0).rsplit("/", 1)[-1], out)
    return _HOME_DIR_RE.sub("/<user>", out)


def _sanitized(value: Any) -> Any:
    """Recursively sanitize strings inside a JSON-shaped value."""
    if isinstance(value, str):
        return sanitize_server_paths(value)
    if isinstance(value, dict):
        return {k: _sanitized(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitized(v) for v in value]
    return value


class StressResponse(BaseModel):
    """Macro stress regime read-out.

    ``available=False`` is a first-class outcome, not an error. The model is
    evaluated by expanding-window walk-forward and served only if it clears the
    ship gate (``ship_gate_policy``), which is a PROPER SCORING RULE: it must
    beat both persistence and climatology on Brier score and be adequately
    calibrated. Accuracy is reported but is not the gate — this model merely
    ties persistence on accuracy, and accuracy is blind to the probability the
    optimizer actually consumes.

    Model and baseline scores are always returned together, so neither can be
    quoted without the other. When the gate fails, ``stress_probability`` is the
    documented fallback 0.0 — "no macro surcharge is being priced" — and is NOT
    a model output.
    """
    available: bool
    stress_probability: float
    stress_source: str          # "model" | "unavailable_*"
    stress_level: str           # "low" | "moderate" | "high" | "unavailable"
    regime_active: bool
    # ── the SHIP GATE evidence: a proper scoring rule, not accuracy ─────────
    # The optimizer prices a risk premium off `stress_probability`, so the model
    # is judged on how good the PROBABILITY is. Both baselines are scored on the
    # identical walk-forward folds and are always returned together with it —
    # a Brier score without its baselines is not a claim.
    brier: Optional[float] = None
    baseline_brier: Optional[float] = None          # persistence, as a degenerate prob
    climatology_brier: Optional[float] = None       # training-window base rates
    log_loss: Optional[float] = None
    climatology_log_loss: Optional[float] = None
    calibration_slope: Optional[float] = None       # 1.0 = perfect; <1 = overconfident
    expected_calibration_error: Optional[float] = None
    # Accuracy is REPORTED but is NOT the gate — see ship_gate_policy.
    val_accuracy: Optional[float] = None
    baseline_accuracy: Optional[float] = None
    accuracy_delta_vs_baseline: Optional[float] = None
    shortage_recall: Optional[float] = None
    ship_gate_passed: Optional[bool] = None
    ship_gate_policy: Optional[str] = None
    ship_gate_reason: Optional[str] = None
    interpretation: str


class ModelMetrics(BaseModel):
    name: str
    kind: str = "model"              # "model" | "naive_baseline"
    rmse: float                      # single grouped 80/20 holdout — noisy on its own
    mae: float
    r2: float
    cv_splits: Optional[int] = None  # repeated FAMILY-GROUPED 80/20 splits
    cv_rmse_mean: Optional[float] = None
    cv_rmse_std: Optional[float] = None
    # BOTH are returned, always. cv_r2_median is the more robust summary on this
    # label distribution — a fold with little label variance blows R² up negative
    # regardless of absolute error — so the two can differ materially and WHICH one
    # is higher is not stable across panels (it was median 0.292 / mean 0.179 at
    # n=736; it is median 0.181 / mean 0.189 at n=810). Quoting either alone is a
    # choice, so the mean and its spread ship with the median, `r2_summary` states
    # both in one string, and the caveat derives the comparison rather than
    # asserting it (see `_which_r2_flatters`).
    cv_r2_mean: Optional[float] = None
    cv_r2_std: Optional[float] = None
    cv_r2_median: Optional[float] = None
    r2_summary: Optional[str] = None
    is_served: bool = False          # THIS row describes the deployed estimator


class ModelComparisonResponse(BaseModel):
    """Metrics for the lead-time bake-off, tied to what is actually deployed.

    ``metrics_describe_served_model`` is the honesty flag: it is True only when
    the estimator object returned by ``app.ml.serving.get_serving_model`` is
    IDENTICAL (``is``) to the fitted object whose metrics are reported as served.
    If the MLflow champion is some other version, or no model resolves, it is
    False and ``caveat`` says so — the endpoint will not publish an R² that does
    not describe the deployed model.
    """
    models: List[ModelMetrics]
    baselines: List[ModelMetrics]
    served_model: Optional[str]
    served_metrics: Optional[ModelMetrics]
    metrics_describe_served_model: bool
    model_source: str
    selection_metric: str
    beats_all_baselines: Optional[bool] = None
    toughest_baseline: Optional[str] = None
    skill_vs_toughest_baseline: Optional[float] = None
    # PAIRED per-fold comparison vs `toughest_baseline` on the IDENTICAL grouped
    # folds: mean RMSE reduction, its standard error, the fold win rate and a
    # p-value. Quote this, not two marginal standard deviations.
    paired_vs_toughest_baseline: Dict[str, Any] = {}
    training_samples: Optional[int]   # None until a retrain records it (no invented count)
    n_features: Optional[int] = None
    feature_schema_version: Optional[int] = None
    feature_columns: List[str] = []
    # Every DECLARED candidate feature that did not make the cut, with the
    # reason. A dropped feature is reported, never silent.
    feature_exclusions: List[Dict[str, Any]] = []
    # WHEN, from WHAT data, at WHICH commit this artifact was produced.
    provenance: Dict[str, Any] = {}
    ship_gate: Dict[str, Any] = {}
    # The three-number leakage progression — the most important number here.
    leakage_audit: Dict[str, Any] = {}
    n_manufacturers: Optional[int] = None
    evaluation: str
    caveat: str


class LeadTimePrediction(BaseModel):
    dk_category: str
    manufacturer: Optional[str] = None
    lifecycle_status: Optional[str] = None
    unit_price: float
    predicted_factory_lead_time_days: float
    # The exact columns the served estimator consumed, so a caller can see that
    # a parameter they passed was not part of the resolved schema. Empty unless
    # the caller passes ``?include_feature_names=true`` — the full list is 100+
    # one-hot column names and is already published by GET /ml/model-comparison
    # (`feature_columns`), so it is not worth carrying on every prediction.
    features_used: List[str] = []
    quantity_predicted: str = (
        "factory (replenishment) lead time in calendar days — NOT a delivery ETA"
    )
    base_days: int              # published category baseline, for context only
    model_used: str
    # Provenance of the estimator that produced the prediction:
    #   "mlflow_registry" = MLflow `champion` alias; "local_joblib" = committed artifact.
    model_source: str
    model_version: Optional[str] = None
    feature_schema_version: int = FEATURE_SCHEMA_VERSION
    # Exactly what the prediction was based on, so a caller can never wonder
    # whether a value was assumed rather than supplied or looked up.
    inputs_used: Dict[str, Any] = {}
    resolved_from: Optional[str] = None   # "component:<id>" when looked up from the DB


class ModelInfoResponse(BaseModel):
    """Serve-time provenance — what an interviewer (or the UI) can check."""
    model_source: str                      # mlflow_registry | local_joblib | none
    model_name: Optional[str] = None       # ridge | random_forest | gradient_boosting | mlp
    registered_model: Optional[str] = None # MLflow registered-model name, if any
    model_version: Optional[str] = None
    alias: Optional[str] = None            # "champion"
    run_id: Optional[str] = None
    model_uri: Optional[str] = None        # models:/...@champion  OR  /path/to/lead_time.joblib
    tracking_uri: Optional[str] = None
    selection_metric: Optional[str] = None
    selection_value: Optional[str] = None
    artifact_mtime: Optional[str] = None
    resolved_at: Optional[str] = None
    fallback_reason: Optional[str] = None  # why the registry was NOT used (honest, not hidden)
    n_training_samples: Optional[int] = None
    n_features: Optional[int] = None
    # ── FIT-TIME PROVENANCE: when, from what data, at which commit ───────────
    # metrics.joblib used to carry none of this, so "which panel produced this
    # model?" had no answer and a published R² could describe a configuration
    # that was never served. These are stamped at fit time by
    # app/ml/model_store.build_provenance and are what model CI gates on.
    training_provenance: Dict[str, Any] = {}
    # Provenance fields the artifact FAILED to record. Non-empty fails model CI.
    missing_provenance_fields: List[str] = []
    # ── STALENESS: a WARNING, never an error ────────────────────────────────
    # True when the panel on disk no longer hashes to what this artifact was
    # trained on — i.e. the weekly collector has added observations the served
    # model has never seen. Deliberately not a failure: a fresh collector commit
    # must not turn the build red, but it must not be invisible either.
    training_data_stale: Optional[bool] = None
    staleness_checked: bool = False
    staleness_detail: Optional[str] = None
    detail: str


@router.get("/stress", response_model=StressResponse)
def get_macro_stress():
    """
    The macro supply-chain stress regime signal — or an explicit statement that
    there isn't one.

    The model forecasts the NY Fed GSCPI regime one month ahead from lagged FRED
    series. It is subject to a HARD SHIP GATE: expanding-window walk-forward
    accuracy must beat the persistence baseline (regime_t = regime_{t-1})
    measured on the same folds. When it does not, this endpoint reports
    ``available=false`` with the exact numbers and reason, and the optimizer
    prices no macro stock-out premium.
    """
    state = get_ml_state()
    if state is None:
        return StressResponse(
            available=False,
            stress_probability=0.0,
            stress_source="unavailable_no_models",
            stress_level="unavailable",
            regime_active=False,
            interpretation="ML models not loaded. Run: python -m seeds.train_ml_models",
        )

    # Sanitized once, at the boundary: the "no regime artifact" branches below
    # quote `model_store.path(...)` verbatim in their reason strings, which on a
    # deploy is an absolute container path.
    status: Dict[str, Any] = dict(_sanitized(dict(getattr(state, "regime_status", None) or {})))
    gate: Dict[str, Any] = dict(status.get("ship_gate") or {})
    metrics: Dict[str, Any] = dict(status.get("metrics") or {})
    available = bool(status.get("available")) and state.regime_model is not None

    if not available:
        return StressResponse(
            available=False,
            # Documented, clearly-labelled default: no regime signal => no macro
            # surcharge. This is NOT a model output and must not be quoted as one.
            stress_probability=float(status.get("fallback_stress_prob", 0.0)),
            stress_source=str(status.get("source", "unavailable_no_artifact")),
            stress_level="unavailable",
            regime_active=False,
            brier=gate.get("brier"),
            baseline_brier=gate.get("baseline_brier"),
            climatology_brier=gate.get("climatology_brier"),
            calibration_slope=gate.get("calibration_slope"),
            val_accuracy=gate.get("val_accuracy"),
            baseline_accuracy=gate.get("baseline_accuracy"),
            accuracy_delta_vs_baseline=gate.get("accuracy_delta_vs_baseline"),
            shortage_recall=metrics.get("shortage_recall"),
            ship_gate_passed=False,
            ship_gate_policy=gate.get("policy"),
            ship_gate_reason=gate.get("reason") or status.get("reason"),
            interpretation=(
                "No macro stress signal is being served. "
                f"{status.get('reason') or gate.get('reason') or 'regime model unavailable'} "
                "The reported probability is a documented fallback (no macro surcharge is "
                "priced in the optimizer), not a prediction."
            ),
        )

    prob = state.current_stress_prob
    if prob >= 0.70:
        level, active = "high", True
    elif prob >= 0.35:
        level, active = "moderate", False
    else:
        level, active = "low", False

    return StressResponse(
        available=True,
        stress_probability=round(prob, 4),
        stress_source="model",
        stress_level=level,
        regime_active=active,
        brier=gate.get("brier"),
        baseline_brier=gate.get("baseline_brier"),
        climatology_brier=gate.get("climatology_brier"),
        log_loss=metrics.get("log_loss"),
        climatology_log_loss=metrics.get("climatology_log_loss"),
        calibration_slope=gate.get("calibration_slope"),
        expected_calibration_error=(metrics.get("calibration") or {}).get(
            "expected_calibration_error"
        ),
        val_accuracy=gate.get("val_accuracy"),
        baseline_accuracy=gate.get("baseline_accuracy"),
        accuracy_delta_vs_baseline=gate.get("accuracy_delta_vs_baseline"),
        shortage_recall=metrics.get("shortage_recall"),
        ship_gate_passed=True,
        ship_gate_policy=gate.get("policy"),
        ship_gate_reason=gate.get("reason"),
        interpretation=(
            f"Semiconductor shortage stress is {level} ({prob:.0%}). "
            + (
                "Current macro conditions match historical shortage regimes — "
                "expect extended lead times and availability risk premiums in the optimizer."
                if active else
                "Normal supply conditions — lead time estimates reflect baseline category averages."
            )
        ),
    )


def _which_r2_flatters(served: Optional["ModelMetrics"]) -> str:
    """State which R² summary is the higher one, from the numbers — not from memory.

    This sentence used to be hard-coded as "the median is the higher of the two
    here". It stopped being true when the panel grew (the served champion is now
    mean +0.189 vs median +0.181) and nothing caught it, because a claim asserted
    in a string cannot go stale loudly. Deriving it means the caveat is either
    right or absent.
    """
    if served is None:
        return "compare cv_r2_median against cv_r2_mean"
    mean, median = served.cv_r2_mean, served.cv_r2_median
    if mean is None or median is None:
        return "compare cv_r2_median against cv_r2_mean"
    if abs(mean - median) < 5e-4:
        return f"the two agree here ({median:+.3f})"
    higher = "median" if median > mean else "mean"
    return (
        f"the {higher} is the higher of the two here "
        f"(median {median:+.3f} vs mean {mean:+.3f})"
    )


@router.get("/model-comparison", response_model=ModelComparisonResponse)
def get_model_comparison():
    """
    Lead-time bake-off metrics, tied by object identity to the deployed estimator.

    Every row is the evaluation of a fitted object that lives in the same artifact
    as the one being served, and ``metrics_describe_served_model`` is computed by
    checking ``get_serving_model(state) is lead_time_models[name]["model"]`` — not
    by trusting a name in a metrics blob. If that identity check fails (e.g. an
    MLflow champion from a different run is serving), the flag is False and the
    caveat says the numbers do not describe the deployed model.

    Both a single 80/20 holdout AND repeated-split CV are reported. Quote the CV
    columns: n≈75 makes any single 15-point split unreliable. Three naive
    baselines (train-mean, always-210d = DigiKey's 30-week ceiling, and a
    category-mean lookup table) are returned alongside, because a 5-category
    one-hot model that merely matches a lookup table is a lookup table.
    """
    state = get_ml_state()
    if state is None or not state.lead_time_models:
        raise HTTPException(
            status_code=503,
            detail="ML models not loaded. Run: python -m seeds.train_ml_models",
        )

    prov: Dict[str, Any] = state.provenance or {}
    if prov.get("feature_schema_ok") is False:
        raise HTTPException(
            status_code=503,
            detail=(
                "Refusing to publish metrics: the persisted lead-time artifacts do not match "
                f"feature schema v{FEATURE_SCHEMA_VERSION} and are not being served. "
                f"{prov.get('feature_schema_error')} Run: python -m seeds.train_ml_models"
            ),
        )

    served_obj = get_serving_model(state)

    def _row(name: str, info: Dict[str, Any], kind: str, served: bool) -> ModelMetrics:
        return ModelMetrics(
            name=name, kind=kind,
            rmse=info["rmse"], mae=info["mae"], r2=info["r2"],
            cv_splits=info.get("cv_splits"),
            cv_rmse_mean=info.get("cv_rmse_mean"), cv_rmse_std=info.get("cv_rmse_std"),
            cv_r2_mean=info.get("cv_r2_mean"), cv_r2_std=info.get("cv_r2_std"),
            cv_r2_median=info.get("cv_r2_median"),
            r2_summary=(
                f"median {info['cv_r2_median']:.3f}, mean {info['cv_r2_mean']:.3f} "
                f"± {info.get('cv_r2_std', 0.0):.3f} over {info.get('cv_splits')} "
                "family-grouped folds"
                if info.get("cv_r2_median") is not None
                and info.get("cv_r2_mean") is not None
                else None
            ),
            is_served=served,
        )

    # Identity, not name-matching: which fitted object is actually answering?
    served_name: Optional[str] = None
    if served_obj is not None:
        for name, info in state.lead_time_models.items():
            if info.get("model") is served_obj:
                served_name = name
                break

    models_out = [
        _row(name, info, "model", name == served_name)
        for name, info in state.lead_time_models.items()
    ]
    models_out.sort(key=lambda m: (m.cv_rmse_mean if m.cv_rmse_mean is not None else m.rmse))

    raw_baselines: Dict[str, Any] = prov.get("lead_time_baselines") or {}
    baselines_out = [_row(n, i, "naive_baseline", False) for n, i in raw_baselines.items()]
    baselines_out.sort(key=lambda m: (m.cv_rmse_mean if m.cv_rmse_mean is not None else m.rmse))

    served_metrics = next((m for m in models_out if m.is_served), None)
    describes = served_metrics is not None

    if describes:
        tough = prov.get("lead_time_toughest_baseline")
        paired: Dict[str, Any] = dict(prov.get("lead_time_paired_vs_toughest_baseline") or {})
        caveat = (
            f"n={prov.get('n_training_samples')} observations from ONE distributor (DigiKey). "
            "Every split — the holdout, every CV fold and every baseline — is GROUPED BY PART "
            "FAMILY (base_product), because base_product alone explains R²=0.82 of the target "
            "IN SAMPLE (an identity-column ANOVA figure, not a model score) and an ungrouped "
            "split scores memorisation of a part family rather than prediction. Numbers from a "
            "random split would be far higher and meaningless: measured, the same estimator on "
            "the same rows goes R² +0.638 random -> +0.082 grouped by family -> -0.550 holding "
            "out whole manufacturers (docs/leakage_progression.json). "
            f"The honest comparison is the PAIRED one against '{tough}' on identical folds: "
            f"mean RMSE reduction {paired.get('mean_rmse_reduction_days')} "
            f"± {paired.get('std_error')} days, winning "
            f"{paired.get('folds_model_won')}/{paired.get('n_folds')} folds "
            f"(p={paired.get('paired_t_p_value')}). Read cv_rmse_mean, which is also the "
            "selection metric. If you show a single R², show cv_r2_median WITH "
            f"cv_r2_mean ± cv_r2_std beside it — {_which_r2_flatters(served_metrics)}, "
            "so quoting either one alone is a choice, not a summary. Above all, read `leakage_audit`: "
            "the same model on the same data scores far higher on a random split and "
            "far worse with whole manufacturers held out. The effective sample size for "
            "generalisation is the manufacturer count, not the row count."
        )
    elif served_obj is None:
        caveat = (
            "NO estimator is currently serving predictions, so none of these rows describes a "
            "deployed model. They are the recorded evaluation of the on-disk artifacts only."
        )
    else:
        caveat = (
            "The estimator answering predictions is NOT any of the fitted objects these metrics "
            f"were computed on (model_source={model_source(state)}). These numbers therefore do "
            "NOT describe the deployed model and must not be published as its accuracy."
        )

    return ModelComparisonResponse(
        models=models_out,
        baselines=baselines_out,
        served_model=served_name,
        served_metrics=served_metrics,
        metrics_describe_served_model=describes,
        model_source=model_source(state),
        selection_metric="cv_rmse_mean",
        beats_all_baselines=prov.get("lead_time_beats_baselines"),
        toughest_baseline=prov.get("lead_time_toughest_baseline"),
        skill_vs_toughest_baseline=prov.get("lead_time_skill_vs_toughest_baseline"),
        paired_vs_toughest_baseline=dict(
            prov.get("lead_time_paired_vs_toughest_baseline") or {}
        ),
        training_samples=prov.get("n_training_samples"),
        n_features=prov.get("n_features"),
        feature_schema_version=prov.get("feature_schema_version"),
        feature_columns=list(state.feature_columns or []),
        feature_exclusions=list(prov.get("feature_exclusions") or []),
        provenance=dict(prov.get("artifact_provenance") or {}),
        ship_gate=dict(prov.get("lead_time_ship_gate") or {}),
        leakage_audit=dict(prov.get("lead_time_leakage_audit") or {}),
        n_manufacturers=prov.get("lead_time_n_manufacturers"),
        evaluation=(
            "80/20 holdout plus repeated 80/20 splits, ALL grouped by part family "
            "(base_product); baselines scored on the identical folds; "
            "target = observed DigiKey factory lead time in days"
        ),
        caveat=caveat,
    )


#: Every record key any declared feature can consume, so the endpoint can accept
#: the full feature set regardless of which subset the current schema resolved to.
#: Adding a candidate to lead_time_model no longer silently breaks this endpoint —
#: `test_lead_time_endpoint_accepts_every_required_input` asserts the two agree.
def _record_from_component(component) -> Dict[str, Any]:
    """Build a prediction record from a persisted Component. No fabrication."""
    return {
        "dk_category": getattr(component, "digikey_category", None),
        "dk_subcategory": getattr(component, "digikey_subcategory", None),
        "category": getattr(component, "category", None),
        "manufacturer": getattr(component, "manufacturer", None),
        "lifecycle_status": getattr(component, "lifecycle_status", None),
        "is_normally_stocked": getattr(component, "normally_stocked", None),
        "parameter_count": getattr(component, "parameter_count", None),
        "package_case": getattr(component, "package_case", None),
        "htsus_code": getattr(component, "htsus_code", None),
        "rohs_status": getattr(component, "rohs_status", None),
        "unit_price": getattr(component, "digikey_unit_price", None),
        "max_break_qty": getattr(component, "max_break_qty", None),
        "price_break_count": getattr(component, "price_break_count", None),
    }


@router.get("/lead-time", response_model=LeadTimePrediction)
def predict_lead_time_endpoint(
    component_id: Optional[int] = None,
    mpn: Optional[str] = None,
    # ── explicit overrides / hypothetical parts ──────────────────────────────
    dk_category: Optional[str] = None,
    dk_subcategory: Optional[str] = None,
    category: Optional[str] = None,
    manufacturer: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
    package_case: Optional[str] = None,
    htsus_code: Optional[str] = None,
    rohs_status: Optional[str] = None,
    is_normally_stocked: Optional[bool] = None,
    parameter_count: Optional[int] = None,
    unit_price: Optional[float] = None,
    moq: Optional[float] = None,
    max_break_qty: Optional[int] = None,
    price_break_count: Optional[int] = None,
    include_feature_names: bool = False,
    db: Session = Depends(get_db),
):
    """
    Predict the FACTORY (replenishment) lead time for a part, in calendar days.

    Two ways to call it, and neither invents an input:

      * ``?component_id=42`` or ``?mpn=STM32F103C8T6`` — loads that part's REAL
        persisted DigiKey attributes and predicts from them. This is the normal
        call, and the one the UI makes.
      * explicit feature parameters — for a hypothetical part. Any parameter you
        pass also OVERRIDES the looked-up value, so you can ask "what if this
        part were Obsolete?".

    Which parameters are actually required depends on the schema resolved at fit
    time; ``GET /ml/model-comparison`` publishes ``feature_columns`` and this
    endpoint's 422 names the missing keys exactly. Nothing is defaulted: a
    missing required input is an error, never a silently-assumed value.

    The response echoes ``inputs_used``, so the caller can always see precisely
    what the prediction was based on. ``features_used`` (the full one-hot column
    list — 100+ names) is omitted by default to keep the payload small; pass
    ``?include_feature_names=true`` to get it, or fetch it once from
    ``GET /ml/model-comparison`` (``feature_columns``), which publishes the exact
    same list.
    """
    state = get_ml_state()
    if state is None or not state.lead_time_models:
        raise HTTPException(
            status_code=503,
            detail="ML models not loaded. Run: python -m seeds.train_ml_models",
        )
    model = get_serving_model(state)
    if model is None:
        prov_err = (state.provenance or {}).get("feature_schema_error")
        raise HTTPException(
            status_code=503,
            detail=(
                f"No serving model resolved. {prov_err or ''} "
                "Run: python -m seeds.train_ml_models"
            ).strip(),
        )
    feature_cols = list(state.feature_columns or [])

    record: Dict[str, Any] = {}
    resolved_from: Optional[str] = None
    if component_id is not None or mpn:
        query = db.query(Component)
        component = (
            query.filter(Component.id == component_id).first() if component_id is not None
            else query.filter(Component.mpn == mpn).first()
        )
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"no component with {'id ' + str(component_id) if component_id is not None else 'mpn ' + str(mpn)}",
            )
        record = _record_from_component(component)
        resolved_from = f"component:{component.id}"

    overrides = {
        "dk_category": dk_category, "dk_subcategory": dk_subcategory,
        "category": category, "manufacturer": manufacturer,
        "lifecycle_status": lifecycle_status, "package_case": package_case,
        "htsus_code": htsus_code, "rohs_status": rohs_status,
        "is_normally_stocked": is_normally_stocked, "parameter_count": parameter_count,
        "unit_price": unit_price, "moq": moq,
        "max_break_qty": max_break_qty, "price_break_count": price_break_count,
    }
    record.update({k: v for k, v in overrides.items() if v is not None})

    # moq is an offer attribute, not a part attribute, so a component lookup
    # cannot supply it. 100% of real offers carry moq=1 or more, and the schema
    # requires it, so default it to the universal minimum rather than 422-ing on
    # a value that is 1 for essentially every catalogue line.
    if "moq" in required_record_keys(feature_cols) and record.get("moq") is None:
        record["moq"] = 1.0

    # `optional_record_keys` names categoricals whose ``unseen_policy`` is
    # "other" — the trained schema already folds a None/absent value into the
    # explicit Unknown level and, if that level wasn't itself seen at fit time,
    # the `__other__` bucket (see `_fill` in app/ml/lead_time_model.py). That is
    # a real, trained fallback, not a fabricated prediction input — so these
    # keys belong in the record (even as None) rather than being absent from it.
    # Absent-from-dict and present-but-None are different things to `_fill`:
    # only the former raises `MissingFeatureError`. Audit item 8: the endpoint
    # used to declare these fields optional and then 422 on them one at a time
    # because they were never actually added to the record.
    for key in optional_record_keys(feature_cols):
        record.setdefault(key, None)

    if unit_price is not None and unit_price <= 0:
        raise HTTPException(status_code=422, detail="unit_price must be > 0")

    required = required_record_keys(feature_cols)
    missing = [k for k in required if record.get(k) is None]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    "missing required feature input(s) for the currently served schema"
                ),
                "missing": missing,
                "required_inputs": required,
                "optional_inputs": optional_record_keys(feature_cols),
                "hint": (
                    "pass ?component_id= or ?mpn= to load a real part's persisted "
                    "attributes, or supply the missing parameters explicitly"
                ),
                "resolved_from": resolved_from,
            },
        )

    try:
        predicted = predict_lead_time(model, build_feature_row(**record), feature_cols)
    except UnknownCategoryError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "refusing_feature": primary_category_feature(feature_cols),
                "known_categories": sorted(known_categories(feature_cols)),
            },
        ) from exc
    except MissingFeatureError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "required_inputs": required},
        ) from exc
    except FeatureSchemaMismatch as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{exc} Run: python -m seeds.train_ml_models",
        ) from exc

    prov = state.provenance or {}
    return LeadTimePrediction(
        dk_category=str(record.get("dk_category")),
        manufacturer=record.get("manufacturer"),
        lifecycle_status=record.get("lifecycle_status"),
        unit_price=round(float(record["unit_price"]), 4),
        predicted_factory_lead_time_days=round(predicted, 1),
        base_days=get_base_days(str(record.get("category") or record.get("dk_category"))),
        model_used=state.best_lead_time_model,
        model_source=model_source(state),
        model_version=prov.get("model_version"),
        feature_schema_version=prov.get("feature_schema_version") or FEATURE_SCHEMA_VERSION,
        # The full one-hot column list is ~100+ names (~7KB) and adds nothing most
        # callers need — it is already published in full by GET /ml/model-comparison
        # (`feature_columns`). Keep the default payload small; opt in when wanted.
        features_used=feature_cols if include_feature_names else [],
        inputs_used={k: v for k, v in record.items() if v is not None},
        resolved_from=resolved_from,
    )


@router.get("/model-info", response_model=ModelInfoResponse)
def get_model_info():
    """
    Where the served lead-time model actually came from.

    Two honest outcomes:
      * ``mlflow_registry`` — the model version carrying the ``champion`` alias in the
        MLflow Model Registry was loaded (``models:/lead_time_predictor@champion``).
      * ``local_joblib``   — no registry was reachable, so the committed
        ``backend/data/ml_models/lead_time.joblib`` is serving. This is the expected
        state on the Render free tier (no MLflow server is deployed) and
        ``fallback_reason`` says exactly why.

    Nothing here is inferred or decorative: it reports what the process loaded at
    startup (``app/ml/serving.load_ml_state``).
    """
    state = get_ml_state()
    if state is None:
        return ModelInfoResponse(
            model_source=SOURCE_NONE,
            detail="No ML models loaded. Run: python -m seeds.train_ml_models",
        )

    # Sanitized at the boundary, so every string derived below (including
    # `detail`, which quotes `fallback_reason`) is already free of host paths.
    prov: Dict[str, Any] = dict(_sanitized(dict(state.provenance or {})))
    src = prov.get("model_source", SOURCE_NONE)
    if src == "mlflow_registry":
        detail = (
            f"Serving MLflow champion: {prov.get('registered_model')} "
            f"v{prov.get('model_version')} (@{prov.get('alias')}) — estimator "
            f"'{prov.get('model_name')}', selected on {prov.get('selection_metric')}"
            f"={prov.get('selection_value')}."
        )
    elif src == "local_joblib":
        detail = (
            f"Serving on-disk artifact (estimator '{prov.get('model_name')}') — the MLflow "
            f"champion alias was NOT used because: {prov.get('fallback_reason')}. This is the "
            "expected path on the free-tier deploy, where no MLflow server exists; the joblib "
            "is committed for exactly this reason."
        )
    else:
        detail = "No serving model resolved."

    training_prov: Dict[str, Any] = dict(prov.get("artifact_provenance") or {})
    staleness: Dict[str, Any] = dict(prov.get("training_data_staleness") or {})
    missing_prov: List[str] = list(prov.get("missing_provenance_fields") or [])
    if missing_prov:
        detail += (
            f" PROVENANCE INCOMPLETE — the artifact does not record {missing_prov}, "
            "so which data produced it cannot be established. Retrain with "
            "`python -m seeds.train_ml_models`."
        )
    if staleness.get("stale"):
        detail += f" STALENESS WARNING — {staleness.get('detail')}"

    # Explicitly-passed fields must not also be splatted in from `prov`.
    explicit = {
        "detail", "training_provenance", "missing_provenance_fields",
        "training_data_stale", "staleness_checked", "staleness_detail",
    }
    allowed = set(ModelInfoResponse.model_fields) - explicit
    return ModelInfoResponse(
        **{k: v for k, v in prov.items() if k in allowed},
        training_provenance=training_prov,
        missing_provenance_fields=missing_prov,
        training_data_stale=staleness.get("stale"),
        staleness_checked=bool(staleness.get("checked")),
        staleness_detail=staleness.get("detail"),
        detail=detail,
    )
