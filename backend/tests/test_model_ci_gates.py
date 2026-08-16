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

These run against the COMMITTED artifacts (``backend/data/ml_models/*.joblib``),
the COMMITTED observed panel and the COMMITTED ``supply_chain.db`` — the same
three things the deployed instance serves from. They skip cleanly on a checkout
that lacks them; under ``MODEL_CI_STRICT=1`` (set by the ``model-ci`` workflow)
a skip is promoted to a failure, because a gate that no-ops is not a gate.
"""
from __future__ import annotations

import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pytest

from app.ml import model_store
from app.ml.lead_time_model import (
    FEATURE_SCHEMA_VERSION,
    MissingFeatureError,
    UnknownCategoryError,
    predict_lead_time,
)
from app.ml.serving import get_serving_model, load_ml_state

pytestmark = pytest.mark.model_ci

BACKEND = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND / "supply_chain.db"

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
    """
    blob = model_store.load("metrics")
    if not blob:
        pytest.skip("no metrics.joblib")
    gate = (blob or {}).get("regime_ship_gate") or {}
    on_disk = model_store.path("regime").exists()
    if not gate:
        assert not on_disk, (
            "regime.joblib is committed but metrics.joblib records no regime_ship_gate — "
            "an ungated model is serving the macro stress probability the optimizer "
            "prices risk off"
        )
        return
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
