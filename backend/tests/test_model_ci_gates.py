"""MODEL CI — the gates that would have caught what actually shipped.

Every assertion in this file is traceable to a defect that was live in this repo
and was found by hand, not by a test. The gates exist because the absence of
exactly this discipline is what let them ship.

  BUG 1  train and serve built different feature schemas, so every prediction was
         the constant 62.1085 days while a published R²=0.9291 described a
         configuration that was never served.
         -> ``test_served_predictions_are_not_near_constant``
            (plus the whole of ``test_lead_time_schema_contract.py``)

  BUG 2  a model that loses to its own baseline shipped anyway: ``retrain_lead_time``
         computed ``beats_baselines`` and then persisted regardless of the answer.
         -> ``test_committed_lead_time_artifact_passed_its_ship_gate``
            ``test_committed_lead_time_artifact_beat_every_baseline``
            ``test_committed_regime_artifact_agrees_with_its_ship_gate``

  BUG 3  feature admission asked "does this column exist?" instead of "is it ever
         populated?", so the model declined on 93% of real inputs.
         -> ``test_serve_coverage.py`` (answer-rate floor against the real DB)

  BUG 4  an API endpoint required a parameter it never declared -> 422 on every call.
         -> ``test_serve_coverage.test_lead_time_endpoint_declares_every_required_input``

  BUG 5  the metrics artifact carried no provenance, so you could not tell which
         data produced which model.
         -> ``test_committed_artifact_records_full_provenance``
            ``test_model_info_publishes_the_fit_time_provenance``
            ``test_training_data_staleness_is_reported_never_ignored`` (WARN only)

  BUG 6  a contract test silently stopped testing the thing it was written to
         catch, because the primary feature was renamed underneath it.
         -> the META block at the bottom of ``test_lead_time_schema_contract.py``

A second audit on 2026-08-16 attacked the GATES rather than the model, by
mutation, and found three of them could not fail plus one that could vanish:

  BUG 7  the persisted feature_cols could be PERMUTED and every gate passed.
         Swapping two numeric columns fed log(price) into the parameter_count
         slot: 7,707 of 8,000 predictions changed, mean |Δ| 44.8 d, max 196.7 d.
         The order assertions compared the artifact against a ROUND TRIP OF
         ITSELF, so they were self-consistent by construction.
         -> the COLUMN ORDER block in ``test_lead_time_schema_contract.py``

  BUG 8  no ABSOLUTE quality floor. The champion refit on SHUFFLED LABELS passed
         every gate: the ship-gate assertions read metrics.joblib's self-report,
         and the tests that actually executed the model measured SPREAD, never
         ERROR. A model could certify itself.
         -> ``test_committed_artifact_beats_a_naive_baseline_on_genuinely_held_out_data``
            ``test_the_quality_floor_rejects_a_model_fit_on_shuffled_labels``

  BUG 9  ``rm regime.joblib`` and the suite was green. The guard returned
         silently instead of skipping, so MODEL_CI_STRICT — which keys on
         ``report.skipped`` — never saw it, and the workflow's pre-flight file
         check omitted both regime artifacts.
         -> ``test_committed_regime_artifact_agrees_with_its_ship_gate``
            + the pre-flight list in ``.github/workflows/model-ci.yml``

  BUG 10 nothing asserted HOW MANY gates there are. Deleting one ``pytestmark``
         line collected 19 tests instead of 40 and still reported green.
         -> ``test_the_model_ci_gate_census_is_complete``

These run against the COMMITTED artifacts (``backend/data/ml_models/*.joblib``),
the COMMITTED observed panel and the COMMITTED ``supply_chain.db`` — the same
three things the deployed instance serves from. They skip cleanly on a checkout
that lacks them; under ``MODEL_CI_STRICT=1`` (set by the ``model-ci`` workflow)
a skip is promoted to a failure, because a gate that no-ops is not a gate.
"""
from __future__ import annotations

import ast
import copy
import re
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pytest

from app.ml import model_store
from app.ml.lead_time_model import (
    FEATURE_SCHEMA_VERSION,
    MODELS,
    MissingFeatureError,
    UnknownCategoryError,
    build_design_matrix,
    build_training_design,
    load_observed_panel,
    make_splits,
    predict_lead_time,
)
from app.ml.serving import get_serving_model, load_ml_state

pytestmark = pytest.mark.model_ci

BACKEND = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND / "supply_chain.db"
PANEL_PATH = BACKEND / "seeds" / "data" / "lead_time_panel" / "observed_lead_times.csv"

#: Served predictions must have at least this much relative spread across real
#: inputs. The constant-predictor bug produced a coefficient of variation of
#: EXACTLY zero (every answer 62.1085 d), so any positive floor catches it; 2% is
#: set low enough that it can only fire on genuine collapse, not on a model that
#: happens to be conservative.
MIN_PREDICTION_CV = 0.02

#: ...and at least this many distinct answers, so a two-valued step function
#: cannot pass the spread check on the strength of one outlier.
MIN_DISTINCT_PREDICTIONS = 25


@pytest.fixture(scope="module")
def metrics() -> dict:
    """The committed ``metrics.joblib`` — the artifact that makes the claims."""
    blob = model_store.load("metrics")
    if not blob:
        pytest.skip("no metrics.joblib — run `python -m seeds.train_ml_models`")
    return dict(blob)


@pytest.fixture(scope="module")
def served():
    """The real MLState, exactly as the API process loads it at startup."""
    if not model_store.models_exist():
        pytest.skip("no ML artifacts — run `python -m seeds.train_ml_models`")
    state = load_ml_state()
    if state is None or get_serving_model(state) is None:
        pytest.skip("no serving model resolved")
    return state


@pytest.fixture(scope="module")
def real_records() -> list[dict]:
    """Real (offer, component) pairs from the shipped database.

    The same record shape ``app/optimization/solve.py`` assembles per BOM line,
    so this exercises the production serving path rather than a fixture.
    """
    if not DB_PATH.exists():
        pytest.skip("no seeded database")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT o.price, o.moq, o.standard_pack, o.packaging,
                   c.category, c.digikey_category, c.digikey_subcategory, c.manufacturer,
                   c.lifecycle_status, c.normally_stocked, c.parameter_count,
                   c.package_case, c.htsus_code, c.rohs_status, c.digikey_unit_price,
                   c.max_break_qty, c.price_break_count
            FROM distributor_offers o
            JOIN components c ON c.id = o.component_id
        """).fetchall()
    except sqlite3.OperationalError as exc:
        pytest.skip(f"database predates the lead-time columns: {exc}")
    finally:
        conn.close()
    if not rows:
        pytest.skip("database has no offers")
    return [
        {
            "dk_category": r["digikey_category"],
            "dk_subcategory": r["digikey_subcategory"],
            "category": r["category"],
            "manufacturer": r["manufacturer"],
            "lifecycle_status": r["lifecycle_status"],
            "is_normally_stocked": r["normally_stocked"],
            "parameter_count": r["parameter_count"],
            "package_case": r["package_case"],
            "htsus_code": r["htsus_code"],
            "rohs_status": r["rohs_status"],
            "max_break_qty": r["max_break_qty"],
            "price_break_count": r["price_break_count"],
            "unit_price": (
                r["digikey_unit_price"] if r["digikey_unit_price"] is not None
                else r["price"]
            ),
            "moq": r["moq"],
            "packaging": r["packaging"],
            "standard_pack": r["standard_pack"],
        }
        for r in rows
    ]


# ── GATE: a model that loses to its own baseline must not be servable ────────
#
# BUG 2. `retrain_lead_time` computed `beats_baselines` and the training script
# then persisted the model regardless of the answer, so "we compare against
# baselines" was a reporting habit rather than a decision. The hard gate now
# lives in `evaluate_lead_time_ship_gate`; these assertions check that the
# artifact SITTING IN THE REPO is one that passed it — a gate you can bypass by
# committing a joblib by hand is not a gate.

def test_committed_lead_time_artifact_passed_its_ship_gate(metrics):
    gate = metrics.get("lead_time_ship_gate")
    assert gate, (
        "metrics.joblib records no lead_time_ship_gate. The committed model was "
        "produced by a training run that never asked whether it beat its baseline — "
        "which is exactly how a losing model shipped. Retrain with "
        "`python -m seeds.train_ml_models`."
    )
    assert gate.get("passed") is True, (
        f"the COMMITTED lead-time artifact failed its own ship gate: {gate.get('reason')}. "
        "A model that does not beat its naive baselines must not be in the repo, let "
        "alone served."
    )
    assert gate.get("policy"), "the ship gate must state the policy it applied"


def test_committed_lead_time_artifact_beat_every_baseline(metrics):
    """Not 'beat the easiest one'. Every one, including manufacturer-mean."""
    beaten = metrics.get("lead_time_ship_gate", {}).get("baselines_beaten") or {}
    assert beaten, "no baseline comparison was recorded — fails closed"
    lost = sorted(name for name, won in beaten.items() if not won)
    assert not lost, (
        f"the served model loses to naive baseline(s) {lost} on mean grouped-CV RMSE. "
        "A lookup table that beats the model IS the model."
    )
    assert metrics.get("lead_time_beats_baselines") is True

    paired = metrics.get("lead_time_paired_vs_toughest_baseline") or {}
    assert paired.get("available"), (
        "no PAIRED per-fold comparison against the toughest baseline was recorded. "
        "Two marginal standard deviations are the wrong test when both are scored on "
        "the same folds."
    )
    assert paired.get("significant_ci") is True, (
        f"the margin over {metrics.get('lead_time_toughest_baseline')!r} is not "
        f"separated from zero: 95% CI [{paired.get('ci95_low')}, {paired.get('ci95_high')}]"
    )


def test_committed_regime_artifact_agrees_with_its_ship_gate():
    """A regime model on disk must be one that passed; a failing one must be gone.

    The training script deletes ``regime.joblib`` when the gate fails, precisely so
    a stale failing model cannot keep answering. This asserts the repo state is
    consistent with that rule in both directions.

    THE HOLE THIS CLOSES (2026-08-16 mutation audit). ``rm regime.joblib`` and the
    whole suite still reported green. The old body ended in a bare ``return``
    whenever the artifact was absent: a silent PASS, which ``MODEL_CI_STRICT``
    cannot see because strict mode keys on ``report.skipped``. So the one control
    designed to catch a gate that stops testing was itself unreachable from here.

    Both regime artifacts ARE git-tracked (see ``.gitignore``, which re-includes
    ``regime.joblib`` and ``regime_features.joblib`` by name), so in CI their
    absence is never legitimate. Every no-op branch below is now a ``pytest.skip``,
    which strict mode promotes to a failure, and a recorded PASSING gate now
    *requires* the artifact to be present — the deletion is a hard failure rather
    than a quiet one.
    """
    blob = model_store.load("metrics")
    if not blob:
        pytest.skip("no metrics.joblib")
    gate = (blob or {}).get("regime_ship_gate") or {}
    on_disk = model_store.path("regime").exists()
    features_on_disk = model_store.path("regime_features").exists()

    if not gate:
        assert not on_disk, (
            "regime.joblib is committed but metrics.joblib records no regime_ship_gate — "
            "an ungated model is serving the macro stress probability the optimizer "
            "prices risk off"
        )
        pytest.skip(
            "metrics.joblib records no regime_ship_gate, so there is no verdict to hold "
            "the artifact to. Under MODEL_CI_STRICT this is a FAILURE: the committed "
            "metrics must carry the regime verdict."
        )

    if gate.get("passed") is True:
        # The direction the old code could not express. A gate that PASSED means an
        # artifact was persisted; if it is not here, it was deleted or lost, and the
        # served instance falls back to REGIME_UNAVAILABLE_STRESS_PROB while these
        # metrics keep advertising a model that beat its baselines.
        assert on_disk, (
            f"metrics.joblib records a PASSING regime ship gate ({gate.get('reason')}) "
            f"but {model_store.path('regime')} is not present. Both regime artifacts are "
            "git-tracked on purpose: without them the optimizer prices macro risk off a "
            "hardcoded fallback while /ml/model-info still publishes this verdict. "
            "Restore the artifact or retrain — do not ship the claim without the model."
        )
        assert features_on_disk, (
            f"{model_store.path('regime_features')} is missing; the pipeline cannot be "
            "scored without the feature frame it was fitted against"
        )

    if on_disk:
        assert gate.get("passed") is True, (
            f"regime.joblib is committed but its ship gate FAILED: {gate.get('reason')}. "
            "Delete the artifact or fix the model; do not ship both."
        )
        assert gate.get("brier") is not None and gate.get("baseline_brier") is not None, (
            "the regime gate must record the proper scoring rule and its baseline together"
        )


def test_the_served_estimator_is_the_one_the_metrics_describe(served, metrics):
    """Published numbers must describe the deployed object, by identity.

    BUG 1's other half: an R² of 0.9291 was published for a configuration that was
    never served. ``is``-identity, not a name in a blob.
    """
    served_obj = get_serving_model(served)
    named = metrics.get("best_lead_time_model")
    assert named, "metrics.joblib does not name a champion"
    match = [
        name for name, info in (served.lead_time_models or {}).items()
        if info.get("model") is served_obj
    ]
    assert match == [named], (
        f"the estimator answering predictions is {match or 'not in the artifact at all'}, "
        f"but the published metrics describe {named!r}. Those numbers do not describe "
        "the deployed model."
    )
    gate_best = (metrics.get("lead_time_ship_gate") or {}).get("best")
    assert gate_best in (None, named), (
        f"the ship gate cleared {gate_best!r} but {named!r} is being served"
    )


# ── GATE: an ABSOLUTE quality floor the artifact cannot self-certify ─────────
#
# THE HOLE (2026-08-16 mutation audit). The auditor refit the champion on
# SHUFFLED LABELS and committed it. Every gate passed. The gates above are the
# reason: they all read `metrics.joblib`'s own `lead_time_ship_gate` — the
# model's self-report — and a hand-committed artifact simply keeps whichever
# verdict the blob happens to carry. The only tests that actually EXECUTED the
# model measured SPREAD (coefficient of variation, distinct-value count, answer
# rate); a model fit on shuffled labels has perfectly healthy spread. Nothing
# anywhere measured ERROR.
#
# So this gate computes the error itself, from the committed artifact and the
# committed panel, and compares it to a naive baseline it also computes. Nothing
# is read from metrics.joblib. A model must not be able to certify itself.
#
# THE HELD-OUT SET IS REAL. `train_all_models` fits the persisted estimator on
# `tr0` only — the 80% side of ONE grouped split, `make_splits(..., n_splits=1,
# test_size=0.2, seed=42)`, grouped by part family so no family straddles it.
# The 20% `te0` side was never seen at fit time and is reconstructed here
# deterministically (verified: the recomputed holdout RMSE reproduces the
# artifact's own recorded single-split RMSE to the digit).
#
# MEASURED, at the artifact this gate ships with:
#     committed random_forest   holdout RMSE 71.57   R² +0.070   (-18.1% vs mean)
#     train_mean baseline       holdout RMSE 87.39   R² -0.387
#     shuffled-label refit      holdout RMSE 84.12   R² -0.285   (-3.7% vs mean)
# The floor is set between the two, on both metrics, so the audited mutation
# fails it and the honest artifact clears it with room.

#: The committed artifact must cut held-out RMSE by at least this much against
#: "predict the training mean". Measured 18.1%; the shuffled-label mutant managed
#: 3.7%. This is a FLOOR against a model that did not learn, not a performance
#: target — for what the model can actually do, see docs/LEAKAGE_PROGRESSION.md.
MIN_HELDOUT_RMSE_REDUCTION_VS_MEAN = 0.10

#: ...and it must explain some of the held-out variance rather than merely
#: hugging the mean. R² is measured against the HOLDOUT's own mean, so this is a
#: strictly harder question than beating `train_mean`: `train_mean` itself scores
#: -0.387 here. Every shuffled-label refit measured came out negative.
MIN_HELDOUT_R2 = 0.0

#: Why `train_mean` and not the toughest baseline: `manufacturer_mean` wins on
#: THIS single split (70.37 vs 71.57) and loses over the 20 grouped folds the
#: ship gate uses (73.92 vs 67.21). A 109-row split cannot settle a 6-day margin,
#: and pretending otherwise would make this gate flap. Beating the toughest
#: baseline is gated — paired, on 20 folds — by
#: `test_committed_lead_time_artifact_beat_every_baseline`. This gate answers a
#: different and more basic question: did the artifact learn anything at all?
_FLOOR_BASELINE = "train_mean"


@pytest.fixture(scope="module")
def heldout():
    """The exact rows ``train_all_models`` held back from the committed fit.

    Reconstructed, not recorded: ``build_training_design`` is the same function
    ``retrain_lead_time`` calls, and ``make_splits`` is seeded, so this is the
    identical partition — which is what makes the ``te0`` side genuinely unseen
    by the estimator sitting in ``data/ml_models/lead_time.joblib``.
    """
    if not PANEL_PATH.exists():
        pytest.skip("no observed panel — nothing to hold out")
    cols = model_store.load("feature_cols")
    if not cols:
        pytest.skip("no persisted feature_cols — run `python -m seeds.train_ml_models`")
    panel = load_observed_panel(PANEL_PATH)
    if panel is None or len(panel) < 30:
        pytest.skip("observed panel too small to hold anything out")
    design = build_training_design(panel)
    if len(design.y) < 30:
        pytest.skip("too few usable panel rows")
    X, rebuilt_cols = build_design_matrix(design.records, schema=design.schema)
    (tr, te), = make_splits(len(design.y), design.family_groups, n_splits=1)
    return {
        "X": X, "y": design.y, "train": tr, "test": te,
        "cols": list(rebuilt_cols), "persisted_cols": list(cols),
    }


def _score_on_holdout(model, hold) -> dict:
    """Held-out RMSE/R² for ``model`` and for the train-mean baseline.

    Everything here is computed from the artifact and the panel. Nothing is read
    from ``metrics.joblib`` — that is the entire point.
    """
    X, y, tr, te = hold["X"], hold["y"], hold["train"], hold["test"]
    pred = np.asarray(model.predict(X[te]), dtype=float)
    truth = np.asarray(y[te], dtype=float)
    base = np.full(truth.shape, float(np.mean(y[tr])))

    def _rmse(p):
        return float(np.sqrt(np.mean((p - truth) ** 2)))

    def _r2(p):
        denom = float(np.sum((truth - truth.mean()) ** 2))
        return 1.0 - float(np.sum((truth - p) ** 2)) / denom if denom > 0 else float("nan")

    rmse, base_rmse = _rmse(pred), _rmse(base)
    return {
        "n_holdout": int(len(te)),
        "rmse": rmse,
        "baseline_rmse": base_rmse,
        "rmse_reduction": (base_rmse - rmse) / base_rmse if base_rmse > 0 else 0.0,
        "r2": _r2(pred),
        "baseline_r2": _r2(base),
    }


def _assert_quality_floor(scored: dict, what: str = "the committed artifact") -> None:
    """GATE body. Factored out so the mutation test can fire it on a mutant."""
    assert scored["n_holdout"] >= 30, (
        f"only {scored['n_holdout']} held-out rows — too few to judge quality"
    )
    assert scored["rmse_reduction"] >= MIN_HELDOUT_RMSE_REDUCTION_VS_MEAN, (
        f"{what} cuts held-out RMSE by only {scored['rmse_reduction']:.1%} against "
        f"{_FLOOR_BASELINE} ({scored['rmse']:.2f} d vs {scored['baseline_rmse']:.2f} d) "
        f"on {scored['n_holdout']} rows it never saw; the floor is "
        f"{MIN_HELDOUT_RMSE_REDUCTION_VS_MEAN:.0%}. This number was computed here, from "
        "the artifact and the panel — it is NOT the ship-gate verdict recorded in "
        "metrics.joblib, which a hand-committed model carries whatever it likes. A model "
        "that cannot beat 'predict the mean' by a clear margin has not learned the task."
    )
    assert scored["r2"] > MIN_HELDOUT_R2, (
        f"{what} scores R² {scored['r2']:.4f} on held-out rows (floor "
        f"{MIN_HELDOUT_R2}); the train-mean baseline scores {scored['baseline_r2']:.4f}. "
        "R² is measured against the holdout's OWN mean, so a non-positive value means the "
        "squared error exceeds the entire label variance of families the model has never "
        "seen — it is tracking noise, not lead time."
    )


#: The message the staleness hatch below shouts. Kept as a constant so the
#: mutation test can assert on it and so grep finds one string, not two.
_RETRAIN = "python -m seeds.train_ml_models"


def _warn_and_xfail_if_the_panel_moved_past_the_artifact(heldout, metrics) -> None:
    """The staleness escape hatch — the SAME policy as the schema contract's GATE 2.

    THE LANDMINE THIS DEFUSES. ``collect-lead-times.yml`` commits a fresh DigiKey
    cross-section to the observed panel every Monday at 06:00 UTC, and the models
    are retrained by hand. When one of those snapshots introduces a ``category``
    (or manufacturer, or package) the artifact has never seen, the design
    recomputed from the panel legitimately grows one-hot columns the committed
    estimator was never fitted on. This is no longer hypothetical: the real
    2026-08-31 collector run landed in ``44e718c`` and took the panel from
    1,922 rows / 263 columns to **2,664 rows / 324 columns**, 61 new one-hot
    columns — 37 ``c=package_case=*``, 12 ``c=category=*``, 6
    ``c=dk_subcategory=*`` and 6 ``c=htsus_code=*``. (Until 2026-09-01 this
    docstring described a *simulated* run and said 352 columns; the measured
    figure is 324, which is also the only value consistent with the 263 + 61
    it states in the same breath. Recompute with ``build_observed_matrix``
    over ``observed_lead_times.csv`` — do not copy it from another document.)
    The width assertion below then fails, and
    because this gate is marked ``model_ci`` but NOT ``slow`` it fails in BOTH
    required checks (``ci.yml`` runs ``-m "not slow"``), so every deploy is blocked
    from the owner's next push — while the error message points at a file that is
    perfectly fine. The collector's own push does not run CI (GitHub's
    recursion prevention), so it arms silently and fires on unrelated work.

    ``test_lead_time_schema_contract.py::test_persisted_feature_cols_match_the_schema_recomputed_from_the_panel``
    already solved exactly this, and this is the same escape hatch, on the same
    condition, for the same reason (docs/MODEL_CI.md, staleness policy).

    WHY THIS CANNOT LAUNDER A BAD MODEL. The hatch opens only when BOTH are true:

      1. the recomputed column list actually differs from the persisted one — a
         panel that merely grew rows still produces the identical schema, and this
         gate then scores the artifact for real, as it always has; and
      2. ``check_training_data_staleness`` says the panel's sha256 is not the one
         the artifact recorded at fit time — i.e. the panel genuinely moved on.

    A CURRENT artifact (matching hash) can never take this path, so a champion that
    loses to ``train_mean`` still fails hard. ``test_the_staleness_hatch_cannot_launder_a_bad_model``
    is the mutation proof of that: it fires all four corners of the condition and
    then refits the champion on SHUFFLED LABELS with a current artifact and
    asserts this gate still turns red.

    WHY A WARNING+XFAIL AND NOT A SKIP. ``MODEL_CI_STRICT=1`` (set by
    ``model-ci.yml``) promotes a skipped ``model_ci`` gate to a FAILURE — correctly,
    since a gate that no-ops is bug 6 — but it exempts ``xfail``, which is a
    declared expectation rather than an absent gate. So a skip here would keep the
    deploy blocked, which is the defect. The ``xfail`` moves the headline count
    line from ``759 passed`` to ``758 passed, 1 xfailed`` — the one line every
    human reads — and the ``UserWarning`` carries the retrain command into the
    warnings summary of both workflows. Loud, not silent, and not red.
    """
    if list(heldout["cols"]) == list(heldout["persisted_cols"]):
        return                                  # schema unchanged — enforce the floor
    stale = model_store.check_training_data_staleness(metrics.get("provenance"))
    if not (stale.get("checked") and stale.get("stale")):
        return                                  # artifact is CURRENT — fail hard below

    prov = metrics.get("provenance") or {}
    message = (
        "MODEL ARTIFACT STALE — THE HELD-OUT QUALITY FLOOR WAS NOT ENFORCED. "
        f"The committed artifact was fitted on {len(heldout['persisted_cols'])} feature "
        f"columns from the panel it recorded at fit time "
        f"({prov.get('n_training_rows')} rows, trained {prov.get('trained_at')}), but the "
        f"panel in this checkout now resolves to {len(heldout['cols'])} columns — the "
        "weekly lead-time collector has added observations carrying levels the model has "
        "never seen, so there is no honest holdout to score it on. "
        f"RETRAIN AND COMMIT THE ARTIFACTS: `{_RETRAIN}`. "
        f"Staleness detail: {stale.get('detail')}"
    )
    warnings.warn(message, UserWarning, stacklevel=2)
    pytest.xfail(message)


def test_committed_artifact_beats_a_naive_baseline_on_genuinely_held_out_data(heldout):
    """THE absolute floor. Computed here; never read from the model's self-report."""
    lead_time = model_store.load("lead_time")
    metrics = model_store.load("metrics") or {}
    if not lead_time:
        pytest.skip("no lead_time.joblib — run `python -m seeds.train_ml_models`")
    best = metrics.get("best_lead_time_model")
    assert best in lead_time, (
        f"metrics.joblib names champion {best!r}, which is not in lead_time.joblib "
        f"({sorted(lead_time)}) — the floor cannot be applied to the served estimator"
    )
    _warn_and_xfail_if_the_panel_moved_past_the_artifact(heldout, metrics)
    assert heldout["cols"] == heldout["persisted_cols"], (
        "the design rebuilt from the panel does not match the persisted feature_cols, so "
        "this holdout is not the one the artifact was fitted against (see "
        "test_lead_time_schema_contract.py for the column-order gates)"
    )
    scored = _score_on_holdout(lead_time[best]["model"], heldout)
    _assert_quality_floor(scored, what=f"the committed {best!r} artifact")


def _fire_hatch(heldout_like, metrics_like) -> tuple[bool, list[str]]:
    """Run the hatch and report ``(did it open?, what did it shout?)``.

    ``pytest.xfail`` raises a BaseException, so it must be caught explicitly. The
    warning is CAPTURED rather than allowed to escape: this helper is used by the
    mutation proof below, which deliberately opens the hatch, and a "MODEL ARTIFACT
    STALE" warning emitted on every green run is exactly how a real one gets
    ignored.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            _warn_and_xfail_if_the_panel_moved_past_the_artifact(heldout_like, metrics_like)
        except BaseException as exc:                  # noqa: BLE001 — XFailed is not an Exception
            if type(exc).__name__ != "XFailed":
                raise
            return True, [str(w.message) for w in caught]
    return False, [str(w.message) for w in caught]


def _hatch_opened(heldout_like, metrics_like) -> bool:
    return _fire_hatch(heldout_like, metrics_like)[0]


def test_the_staleness_hatch_cannot_launder_a_bad_model(heldout, metrics, monkeypatch):
    """MUTATION PROOF for the escape hatch in the gate above.

    An escape hatch is a hole until someone has watched it refuse to open. A
    weakened gate is worse than no gate — every entry in the file header is a
    defect that shipped past one — so all four corners of the hatch's condition
    are fired here, and then the corner that actually matters is fired end to end:
    a CURRENT artifact whose champion loses to the naive baseline must still turn
    the build RED, hatch or no hatch.

    Every input is SYNTHESISED — both provenance blocks, both column lists and the
    champion — so this proof reads identically whether the committed artifact is
    current today or the weekly collector has already moved the panel past it. A
    mutation test that only works on a fresh checkout is just the next landmine.
    """
    prov = dict(metrics.get("provenance") or {})
    # Provenance whose recorded data hash IS the panel in this checkout, whatever
    # that panel currently happens to be. This is the "artifact is CURRENT" arm.
    prov_current = dict(prov, **model_store.build_provenance(
        training_data_path=PANEL_PATH,
        n_training_rows=prov.get("n_training_rows"),
    ))
    current_metrics = dict(metrics, provenance=prov_current)
    stale_metrics = dict(
        metrics, provenance=dict(prov_current, training_data_sha256="0" * 64)
    )

    fresh = model_store.check_training_data_staleness(prov_current)
    assert fresh.get("checked") is True and fresh.get("stale") is False, (
        f"could not synthesise a CURRENT artifact — the proof is inert: {fresh.get('detail')}"
    )
    moved = model_store.check_training_data_staleness(stale_metrics["provenance"])
    assert moved.get("checked") is True and moved.get("stale") is True, (
        f"could not synthesise a STALE artifact — the proof is inert: {moved.get('detail')}"
    )

    persisted = list(heldout["persisted_cols"])
    drifted = dict(heldout, cols=persisted + ["c=category=__mutant__"])
    unchanged = dict(heldout, cols=list(persisted))

    # CORNER 1 — schema drifted, artifact CURRENT. The panel did NOT move, so a
    # column list that disagrees is a real defect (a permuted or hand-edited
    # artifact, bug 7), not the collector. The hatch must stay shut.
    assert not _hatch_opened(drifted, current_metrics), (
        "the hatch opened for an artifact whose training-data hash still matches the "
        "panel on disk. That is not staleness — it is a schema defect, and it must "
        "fail hard."
    )
    # CORNER 2 — schema unchanged, artifact stale. Rows grew but the vocabulary did
    # not, so the holdout is still scoreable and the floor must still be enforced.
    assert not _hatch_opened(unchanged, stale_metrics), (
        "the hatch opened on staleness alone. A grown panel that resolves to the SAME "
        "columns can still be scored, so the quality floor must still run — otherwise "
        "every week between a collector commit and a retrain is an unguarded week."
    )
    # CORNER 3 — schema unchanged, artifact current: the ordinary enforced path.
    assert not _hatch_opened(unchanged, current_metrics)
    # CORNER 4 — schema drifted AND artifact stale: the ONE case the hatch is for.
    #            A hatch that cannot fire would leave the 2026-08-31 landmine armed.
    opened, shouted = _fire_hatch(drifted, stale_metrics)
    assert opened, (
        "the hatch did not fire for a drifted schema on a genuinely stale artifact — "
        "the weekly collector will block every deploy again"
    )
    # ...and it must SHOUT. A hatch that opens quietly is worse than one that fails.
    assert shouted, "the hatch opened without emitting a warning — that is silence"
    assert _RETRAIN in shouted[0] and "STALE" in shouted[0], (
        f"the hatch's warning must name the retrain command; it said: {shouted[0]!r}"
    )

    # THE MUTATION THAT MATTERS. Champion refit on SHUFFLED LABELS (the 2026-08-16
    # auditor's mutation), artifact CURRENT, schema unchanged: the gate must still
    # fail. If the hatch were widened to "stale OR drifted", this is what would
    # start passing.
    best = metrics.get("best_lead_time_model")
    if not best or best not in MODELS:
        pytest.skip("no champion blueprint to mutate")
    X, y, tr = heldout["X"], heldout["y"], heldout["train"]
    rng = np.random.default_rng(0)
    shuffled = np.asarray(y, dtype=float).copy()
    rng.shuffle(shuffled)
    mutant = copy.deepcopy(MODELS[best])
    mutant.fit(X[tr], shuffled[tr])

    real_load = model_store.load

    def _mutant_load(name):
        if name == "lead_time":
            return {best: {"model": mutant}}
        if name == "metrics":
            return current_metrics
        return real_load(name)

    monkeypatch.setattr(model_store, "load", _mutant_load)
    try:
        test_committed_artifact_beats_a_naive_baseline_on_genuinely_held_out_data(unchanged)
    except AssertionError:
        pass                                          # the floor turned red — correct
    except BaseException as exc:                      # noqa: BLE001 — xfail is BaseException
        pytest.fail(
            f"a shuffled-label champion on a CURRENT artifact did not FAIL the gate; it "
            f"raised {type(exc).__name__}: {exc}. The hatch is too wide — narrow it."
        )
    else:
        pytest.fail(
            "a shuffled-label champion on a CURRENT artifact PASSED the held-out quality "
            "floor. The gate is no longer a gate."
        )


def test_the_quality_floor_rejects_a_model_fit_on_shuffled_labels(heldout):
    """MUTATION PROOF for the gate above.

    Refits the champion blueprint on permuted labels — the auditor's mutation,
    which passed all 35 gates — and asserts the floor turns red. Three seeds,
    because one shuffle can get lucky on a 109-row split: seed 0 still beat the
    mean by 3.7%, which is precisely why the floor is 10% and why R² is checked
    alongside it. A gate that has never been watched failing is not a gate.
    """
    metrics = model_store.load("metrics") or {}
    best = metrics.get("best_lead_time_model")
    if not best or best not in MODELS:
        pytest.skip("no champion blueprint to mutate")

    X, y, tr = heldout["X"], heldout["y"], heldout["train"]
    caught = 0
    for seed in (0, 1, 2):
        rng = np.random.default_rng(seed)
        shuffled = np.asarray(y, dtype=float).copy()
        rng.shuffle(shuffled)
        mutant = copy.deepcopy(MODELS[best])
        mutant.fit(X[tr], shuffled[tr])
        scored = _score_on_holdout(mutant, heldout)
        with pytest.raises(AssertionError):
            _assert_quality_floor(scored, what=f"a shuffled-label refit (seed {seed})")
        caught += 1
    assert caught == 3, "every shuffled-label refit must be rejected by the floor"


# ── GATE: the served model must not be a (near-)constant ─────────────────────

def test_served_predictions_are_not_near_constant(served, real_records):
    """BUG 1, measured on production inputs.

    The constant predictor answered 62.1085 days for every part in the catalogue
    and no test noticed, because every other test built its own toy schema. This
    one runs the committed artifact over the committed database and measures the
    spread of what comes out.
    """
    model = get_serving_model(served)
    cols = served.feature_columns
    answers = []
    for record in real_records:
        try:
            answers.append(predict_lead_time(model, record, cols))
        except (MissingFeatureError, UnknownCategoryError):
            continue
    assert len(answers) >= 100, (
        f"only {len(answers)} of {len(real_records)} real rows produced a prediction — "
        "too few to judge whether the predictor is constant (see test_serve_coverage.py "
        "for the answer-rate gate)"
    )

    values = np.asarray(answers, dtype=float)
    distinct = len({round(v, 3) for v in answers})
    mean = float(values.mean())
    cv = float(values.std()) / mean if mean > 0 else 0.0
    assert distinct >= MIN_DISTINCT_PREDICTIONS, (
        f"the served model produced only {distinct} distinct values over "
        f"{len(answers)} real inputs (mean {mean:.2f} d). That is a lookup table at "
        "best and a constant at worst — the 62.1085-day bug had exactly one."
    )
    assert cv >= MIN_PREDICTION_CV, (
        f"served predictions have a coefficient of variation of {cv:.4f} "
        f"(floor {MIN_PREDICTION_CV}); mean {mean:.2f} d, sd {values.std():.4f}. "
        "The model is not responding to its inputs."
    )


def test_recorded_feature_schema_matches_the_code_that_serves_it(metrics, served):
    """A stale artifact must be rejected, not zero-filled into a constant."""
    assert metrics.get("feature_schema_version") == FEATURE_SCHEMA_VERSION, (
        f"the committed artifact was trained on feature schema "
        f"v{metrics.get('feature_schema_version')} but this build serves "
        f"v{FEATURE_SCHEMA_VERSION}. Retrain: `python -m seeds.train_ml_models`."
    )
    prov = served.provenance or {}
    assert prov.get("feature_schema_ok") is True, prov.get("feature_schema_error")
    assert metrics.get("n_features") == len(served.feature_columns or []), (
        "the recorded feature count disagrees with the persisted column list"
    )


# ── GATE: an artifact with no provenance is not shippable ────────────────────
#
# BUG 5. metrics.joblib carried no trained_at, no training-data hash, no row
# count and no git SHA, so there was no way to say which data produced which
# model — and therefore no way to notice that a published number described a
# configuration nobody was serving.

def test_committed_artifact_records_full_provenance(metrics):
    prov = metrics.get("provenance")
    assert prov, (
        "metrics.joblib carries NO provenance block. You cannot tell when this model "
        "was trained, from what data, or at which commit."
    )
    missing = model_store.missing_provenance_fields(prov)
    assert not missing, (
        f"the committed artifact does not record {missing}. Required: "
        f"{list(model_store.REQUIRED_PROVENANCE_FIELDS)}."
    )
    assert len(str(prov["training_data_sha256"])) == 64, "expected a sha256 hex digest"
    assert int(prov["n_training_rows"]) > 0
    assert prov.get("lead_time_status") == "trained", (
        "provenance records a training run that did not actually train"
    )


def test_provenance_row_count_agrees_with_the_published_sample_size(metrics):
    """One number, one meaning. ``/ml/model-comparison`` once claimed 8,731 —
    the offer count — as its training sample size."""
    prov = metrics.get("provenance") or {}
    assert prov.get("n_training_rows") == metrics.get("n_training_samples"), (
        f"provenance says {prov.get('n_training_rows')} training rows but the published "
        f"sample size is {metrics.get('n_training_samples')}"
    )


def test_model_info_publishes_the_fit_time_provenance(served, client):
    """Provenance that is recorded but not reachable is not provenance."""
    from app.ml import set_ml_state

    set_ml_state(served)
    resp = client.get("/api/v1/ml/model-info")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    prov = body.get("training_provenance") or {}
    for field in model_store.REQUIRED_PROVENANCE_FIELDS:
        assert prov.get(field) not in (None, ""), (
            f"GET /ml/model-info does not publish provenance field {field!r}"
        )
    assert body.get("missing_provenance_fields") == []
    assert body.get("staleness_detail"), "staleness must always be reported, either way"


# ── STALENESS: a WARNING, never a build failure ──────────────────────────────

def test_training_data_staleness_is_reported_never_ignored(metrics):
    """Make the weekly collector's growth visible without turning CI red.

    A GitHub Action appends a fresh DigiKey cross-section to the panel every
    Monday and commits it; the models are retrained by hand. Failing here would
    make every collector commit red and train everyone to ignore the signal. So
    this gate asserts only that the question is ASKED and ANSWERED — and emits a
    loud warning when the answer is "stale".
    """
    result = model_store.check_training_data_staleness(metrics.get("provenance"))
    assert result.get("detail"), "the staleness check must always say something"
    assert result.get("checked") is True, (
        f"staleness could not be evaluated: {result.get('detail')}. The panel is "
        "committed, so this must be answerable."
    )
    if result["stale"]:
        warnings.warn(
            f"MODEL ARTIFACT STALE (not a failure): {result['detail']}",
            UserWarning,
            stacklevel=2,
        )
    # Either way the two hashes must be recorded, so the report is auditable.
    assert result["artifact_data_sha256"] and result["current_data_sha256"]


def test_staleness_detects_a_changed_panel(tmp_path, metrics):
    """The staleness check must actually fire — a warning nobody can trigger is
    decoration. Point it at a panel with different bytes and prove it says so."""
    panel = tmp_path / "observed_lead_times.csv"
    panel.write_text("mpn,lead_time_weeks\nFAKE-1,12\n", encoding="utf-8")
    prov = dict(metrics.get("provenance") or {})
    result = model_store.check_training_data_staleness(prov, training_data_path=panel)
    assert result["checked"] is True
    assert result["stale"] is True
    assert result["severity"] == "warning"
    assert "STALE" in result["detail"]

    # ...and must NOT fire when the bytes match what was trained on.
    same = model_store.build_provenance(training_data_path=panel, n_training_rows=1)
    assert model_store.check_training_data_staleness(same, training_data_path=panel)[
        "stale"
    ] is False


# ── CENSUS: the gates must not be able to silently stop existing ─────────────
#
# THE HOLE (2026-08-16 mutation audit). Deleting ONE line —
# `pytestmark = pytest.mark.model_ci` at the top of the schema-contract file —
# dropped the model-CI run from 40 collected tests to 19, and it reported GREEN.
# Nothing anywhere asserted how many gates there are supposed to be, so the
# strongest possible attack on this suite (make the gates stop being gates) was
# also the quietest.
#
# `MODEL_CI_STRICT` does not help: it promotes a SKIPPED gate to a failure, and a
# decollected test is not skipped, it is absent. Absence is the one state a test
# cannot report on itself. So the census is taken from OUTSIDE any single test:
# statically, over the source of the whole tests/ tree, and then cross-checked
# against what pytest actually collected in this session.
#
# WHEN YOU ADD OR REMOVE A GATE, update MODEL_CI_GATE_CENSUS below. That edit is
# the point: the count is a declaration, and changing it is a deliberate act that
# shows up in review.

#: {test file: number of ``model_ci`` test functions it declares}.
MODEL_CI_GATE_CENSUS: dict[str, int] = {
    "test_lead_time_endpoint_contract.py": 5,
    "test_lead_time_schema_contract.py": 20,
    "test_model_ci_gates.py": 20,
    "test_serve_coverage.py": 7,
}

#: Sum of the above — the number `pytest -m model_ci` must collect.
EXPECTED_MODEL_CI_GATES = sum(MODEL_CI_GATE_CENSUS.values())


def _module_is_model_ci(tree: ast.Module) -> bool:
    """Does this module carry ``pytestmark = pytest.mark.model_ci`` at top level?"""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
        ):
            continue
        source = ast.dump(node.value)
        if "'model_ci'" in source or '"model_ci"' in source:
            return True
    return False


def _decorated_model_ci(node: ast.stmt) -> bool:
    return any(
        "model_ci" in ast.dump(dec)
        for dec in getattr(node, "decorator_list", [])
    )


def _static_census() -> dict[str, int]:
    """Count ``model_ci`` gates by reading the source, not by running anything.

    A test that has been decollected cannot report its own absence, so the census
    has to be taken from the outside.
    """
    census: dict[str, int] = {}
    for path in sorted((BACKEND / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_marked = _module_is_model_ci(tree)
        count = sum(
            1
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            and (module_marked or _decorated_model_ci(node))
        )
        if count:
            census[path.name] = count
    return census


def test_the_model_ci_gate_census_is_complete():
    """A gate that stops being collected must fail the build, not shrink it."""
    from tests.conftest import COLLECTED_MODEL_CI_NODEIDS

    static = _static_census()
    assert static == MODEL_CI_GATE_CENSUS, (
        "the set of model-CI gates changed and MODEL_CI_GATE_CENSUS was not updated.\n"
        f"  declared: {MODEL_CI_GATE_CENSUS}\n"
        f"  found:    {static}\n"
        "If a whole file vanished from 'found', its `pytestmark = pytest.mark.model_ci` "
        "line was deleted or renamed and every gate in it silently stopped running — "
        "the exact mutation that took this suite from 40 collected gates to 19 while "
        "still reporting green. If you genuinely added or removed a gate, update the "
        "census in the same commit."
    )
    assert sum(static.values()) == EXPECTED_MODEL_CI_GATES

    # Cross-check the static reader against pytest's own collection, so the census
    # cannot drift into counting something pytest does not run (a parametrised gate,
    # a class-nested test, a conditional skip at import time).
    collected: dict[str, int] = {}
    for nodeid in COLLECTED_MODEL_CI_NODEIDS:
        collected[Path(nodeid.split("::")[0]).name] = (
            collected.get(Path(nodeid.split("::")[0]).name, 0) + 1
        )
    if not collected:
        pytest.skip("collection hook recorded nothing — cannot cross-check the census")
    for name, n in collected.items():
        assert MODEL_CI_GATE_CENSUS.get(name) == n, (
            f"pytest collected {n} model_ci tests from {name} but the census declares "
            f"{MODEL_CI_GATE_CENSUS.get(name)}. The static reader and pytest disagree, so "
            "the census is no longer a reliable count of what actually runs."
        )
    # When the whole suite was collected, the totals must agree exactly.
    if set(collected) == set(MODEL_CI_GATE_CENSUS):
        assert len(COLLECTED_MODEL_CI_NODEIDS) == EXPECTED_MODEL_CI_GATES, (
            f"pytest collected {len(COLLECTED_MODEL_CI_NODEIDS)} model_ci gates; "
            f"{EXPECTED_MODEL_CI_GATES} are declared"
        )


def test_missing_provenance_is_detected_not_assumed():
    """The provenance gate must fail on an artifact that has none."""
    assert model_store.missing_provenance_fields(None) == list(
        model_store.REQUIRED_PROVENANCE_FIELDS
    )
    assert model_store.missing_provenance_fields({}) == list(
        model_store.REQUIRED_PROVENANCE_FIELDS
    )
    partial = {"trained_at": "2026-08-15T00:00:00+00:00", "git_sha": None}
    missing = model_store.missing_provenance_fields(partial)
    assert "trained_at" not in missing
    assert "git_sha" in missing, "a null field must count as missing, not present"


# ─────────────────────────────────────────────────────────────────────────────
# Runtime/train environment parity
#
# Why this gate exists: on 2026-08-18 the live API served
# model_source="none" / cv_r2=null while the *identical commit* worked locally.
# Cause: the artifacts were pickled by scikit-learn 1.8.0, but
# backend/requirements.txt pinned scikit-learn==1.3.2 / numpy==1.26.2, and
# joblib/pickle of sklearn estimators is not portable across those versions —
# GradientBoostingRegressor's Cython loss unpickles via a bare `_loss` module
# that only sklearn >=1.4 registers in sys.modules, so every Render boot raised
# `ModuleNotFoundError: No module named '_loss'`. The startup handler caught it
# and the endpoints reported it as "no models trained", so nothing was red.
#
# Every existing model gate runs against the DEVELOPER's interpreter, where the
# load trivially succeeds — none of them could see the deployed pin. This one
# reads requirements.txt as text, so it fails in any environment.
# ─────────────────────────────────────────────────────────────────────────────
REQUIREMENTS_PATH = BACKEND / "requirements.txt"


def _pinned_version(package: str) -> str | None:
    """The ``==`` pin for ``package`` in requirements.txt, or None if unpinned."""
    pattern = re.compile(
        rf"^{re.escape(package)}\s*==\s*([A-Za-z0-9_.!+-]+)", re.MULTILINE
    )
    match = pattern.search(REQUIREMENTS_PATH.read_text())
    return match.group(1) if match else None


def test_requirements_pin_the_sklearn_that_pickled_the_artifacts(metrics):
    """The deployed scikit-learn pin must equal the one recorded at fit time.

    Not "compatible with" — equal. sklearn makes no cross-version pickle
    compatibility promise, and the failure mode is a silent fallback to
    model_source="none" in production, not a loud crash.
    """
    trained_with = (metrics.get("provenance") or {}).get("sklearn_version")
    if not trained_with:
        pytest.skip("artifact records no sklearn_version — covered by the provenance gate")

    pinned = _pinned_version("scikit-learn")
    assert pinned is not None, (
        "backend/requirements.txt does not pin scikit-learn with '=='. The deployed "
        f"artifacts were pickled by scikit-learn {trained_with}; an unpinned resolver "
        "will eventually install a version that cannot unpickle them, and the API will "
        "silently serve model_source='none'."
    )
    assert pinned == trained_with, (
        f"VERSION SKEW: backend/requirements.txt pins scikit-learn=={pinned}, but "
        f"data/ml_models/*.joblib were pickled by scikit-learn {trained_with}. The "
        "deployed instance will fail to unpickle them and serve model_source='none' "
        f"with null metrics. Fix by pinning scikit-learn=={trained_with}, or retrain "
        "under the pinned version with `python -m seeds.train_ml_models`."
    )


def test_runtime_sklearn_matches_the_artifacts(metrics):
    """The interpreter running this suite must also be able to trust the pickles.

    Guards the reverse mistake: bumping requirements.txt without retraining, or
    retraining in a venv that has drifted from the pin.
    """
    import sklearn

    trained_with = (metrics.get("provenance") or {}).get("sklearn_version")
    if not trained_with:
        pytest.skip("artifact records no sklearn_version — covered by the provenance gate")

    assert sklearn.__version__ == trained_with, (
        f"this environment runs scikit-learn {sklearn.__version__} but the committed "
        f"artifacts were pickled by {trained_with}. Every metric this suite verifies is "
        "therefore being measured on a load sklearn does not guarantee. Align the venv "
        "with backend/requirements.txt, or retrain."
    )


# ── Which INTERPRETER fit the artifact ───────────────────────────────────────
#
# sklearn is pinned and gated above, but nothing recorded the Python version.
# Every local retrain has run 3.13.x while CI pins 3.11, and the standalone
# research scripts under seeds/ already stamp platform.python_version() — so
# their artifacts could be compared across interpreters and the model artifacts
# could not. build_provenance() now stamps it too.
#
# It is deliberately NOT in REQUIRED_PROVENANCE_FIELDS: the committed
# metrics.joblib predates the field, and gating on it would fail the build for an
# artifact nobody is retraining today. The second test below is the one that
# matters — it proves the new field cannot retroactively break an old artifact.


def test_new_provenance_records_the_python_interpreter_version():
    """A fresh provenance block must say which interpreter produced it."""
    import platform

    prov = model_store.build_provenance()

    stamped = prov.get("python_version")
    assert stamped, (
        "build_provenance() records no python_version, so an artifact cannot say "
        "which interpreter pickled it — CI runs 3.11 and local retrains run 3.13."
    )
    assert stamped == platform.python_version()
    assert re.match(r"^\d+\.\d+\.\d+", str(stamped)), f"not a version string: {stamped!r}"


def test_an_artifact_without_python_version_still_loads_and_passes_the_gates(metrics):
    """Adding a provenance field must never invalidate an existing artifact.

    The committed metrics.joblib was trained before python_version existed. If the
    field were added to REQUIRED_PROVENANCE_FIELDS it would fail every provenance
    gate at once, for an artifact that is deliberately not being retrained.
    """
    assert "python_version" not in model_store.REQUIRED_PROVENANCE_FIELDS, (
        "python_version must not be a required field until an artifact trained "
        "with it has actually been committed"
    )

    legacy = {field: "recorded" for field in model_store.REQUIRED_PROVENANCE_FIELDS}
    assert "python_version" not in legacy
    assert model_store.missing_provenance_fields(legacy) == [], (
        "a pre-python_version provenance block must still be complete"
    )

    # ...and the real committed artifact, loaded from disk, must still pass.
    prov = metrics.get("provenance") or {}
    assert prov, "the committed artifact carries no provenance at all"
    assert model_store.missing_provenance_fields(prov) == []
