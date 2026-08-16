"""The served model must actually answer for real production inputs.

Two defects motivated this file, and both were invisible to every other test
because every other test builds its own toy schema:

  1. ``GET /ml/lead-time`` returned 422 for EVERY input. The trained schema
     required ``parameter_count``; the endpoint never declared it as a query
     parameter, so validation failed before the model was ever consulted.

  2. ``supply_risk.model_available`` was false in 6 of 6 sampled optimizer runs.
     ``standard_pack`` / ``packaging`` live on ``DistributorOffer`` and are
     populated for DigiKey offers only — 571 of 8,176 rows, **7.0%** — so every
     non-DigiKey offer hit ``MissingFeatureError``. The old availability check
     asked "does this column exist?" and not "is it ever filled?".

Together those replaced a model that always answered with a constant by a model
that almost never answered. Neither is a working prediction path, so these tests
assert the property that actually matters: **on real rows, the model returns
real, varying predictions most of the time.** A regression to "declines on
everything" fails CI here.

These run against the REAL persisted artifacts and the REAL database, and skip
cleanly when either is absent (fresh checkout, CI without a seeded DB).
"""
from __future__ import annotations

import inspect

import pytest

from app.ml import model_store, set_ml_state
from app.ml.lead_time_model import (
    MIN_SERVE_COVERAGE,
    MissingFeatureError,
    UnknownCategoryError,
    optional_record_keys,
    predict_lead_time,
    required_record_keys,
)
from app.ml.serving import get_serving_model, load_ml_state

#: Every test in this file is a MODEL CI GATE — see docs/MODEL_CI.md and
#: .github/workflows/model-ci.yml. Under MODEL_CI_STRICT=1 the clean skips below
#: become failures, because the artifacts, the panel and supply_chain.db are all
#: committed: in CI there is no legitimate reason for these to not run.
pytestmark = pytest.mark.model_ci

#: The model must answer for at least this share of real (offer, component)
#: pairs. Set well below the measured 94.4% so ordinary data drift does not turn
#: the suite red — this is a floor against COLLAPSE, not a performance target.
MIN_ANSWER_RATE = 0.80


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
def real_rows():
    """Real (offer, component) pairs straight out of the shipped database."""
    import sqlite3
    from pathlib import Path

    db_path = Path(__file__).resolve().parent.parent / "supply_chain.db"
    if not db_path.exists():
        pytest.skip("no seeded database")
    conn = sqlite3.connect(str(db_path))
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
    return rows


def _record(row) -> dict:
    """The same record shape app/optimization/solve.py builds per BOM line."""
    return {
        "dk_category": row["digikey_category"],
        "dk_subcategory": row["digikey_subcategory"],
        "category": row["category"],
        "manufacturer": row["manufacturer"],
        "lifecycle_status": row["lifecycle_status"],
        "is_normally_stocked": row["normally_stocked"],
        "parameter_count": row["parameter_count"],
        "package_case": row["package_case"],
        "htsus_code": row["htsus_code"],
        "rohs_status": row["rohs_status"],
        "max_break_qty": row["max_break_qty"],
        "price_break_count": row["price_break_count"],
        "unit_price": (
            row["digikey_unit_price"] if row["digikey_unit_price"] is not None
            else row["price"]
        ),
        "moq": row["moq"],
        "packaging": row["packaging"],
        "standard_pack": row["standard_pack"],
    }


def _score_all(served, real_rows):
    model = get_serving_model(served)
    cols = served.feature_columns
    answered, declined = [], 0
    for row in real_rows:
        try:
            answered.append(predict_lead_time(model, _record(row), cols))
        except (MissingFeatureError, UnknownCategoryError):
            declined += 1
    return answered, declined


# ── the property that actually matters ──────────────────────────────────────

def test_model_answers_for_most_real_rows(served, real_rows):
    """THE regression test. Was 7%; must never collapse back."""
    answered, declined = _score_all(served, real_rows)
    rate = len(answered) / len(real_rows)
    assert rate >= MIN_ANSWER_RATE, (
        f"served model answered only {rate:.1%} of {len(real_rows)} real "
        f"(offer, component) pairs ({declined} declined). A model that declines on "
        "the primary case is not a working prediction path."
    )


def test_real_predictions_are_not_constant(served, real_rows):
    """The other half of the failure mode: answering, but always the same."""
    answered, _ = _score_all(served, real_rows)
    assert len(answered) > 50
    assert len({round(v, 3) for v in answered}) > 10, (
        "served model returns near-constant predictions on real data"
    )
    assert all(v > 0 for v in answered)


def test_no_required_feature_is_sourced_from_a_sparse_column(served):
    """A required feature backed by a 7%-filled column is the bug, generalised."""
    from app.ml.lead_time_model import (
        NUMERIC_SPECS,
        SERVE_SOURCES,
        measure_serve_coverage,
    )

    coverage = measure_serve_coverage()
    if all(v is None for v in coverage.values()):
        pytest.skip("serve coverage not measurable (no database)")

    for key in required_record_keys(served.feature_columns):
        feature = next(
            (n for n, s in NUMERIC_SPECS.items() if s.record_key == key), None
        )
        if feature is None or feature not in SERVE_SOURCES:
            continue
        frac = coverage.get(feature)
        if frac is None:
            continue
        assert frac >= MIN_SERVE_COVERAGE, (
            f"required feature {feature!r} is backed by "
            f"{'.'.join(SERVE_SOURCES[feature])}, populated on only {frac:.1%} of rows"
        )


# ── the endpoint must be callable ───────────────────────────────────────────

def test_lead_time_endpoint_declares_every_required_input(served):
    """Adding a feature must not silently make the endpoint un-callable.

    This is exactly how ``/ml/lead-time`` came to return 422 for every request:
    the schema grew a ``parameter_count`` requirement and the endpoint signature
    did not follow.
    """
    from app.api.ml import predict_lead_time_endpoint

    params = set(inspect.signature(predict_lead_time_endpoint).parameters)
    schema_keys = set(required_record_keys(served.feature_columns))
    schema_keys |= set(optional_record_keys(served.feature_columns))
    missing = sorted(schema_keys - params)
    assert not missing, (
        f"/ml/lead-time cannot accept {missing} — the served schema needs them, so "
        "every request that relies on them fails validation before reaching the model"
    )


def _seed_component(db_session, real_rows):
    """Insert a real part into whatever database the app is bound to.

    The suite's ``client`` fixture points the app at a temp database, so reading
    component ids out of the shipped ``supply_chain.db`` and calling the API with
    them 404s. Seed the row we are about to ask for instead — this also keeps the
    test honest about which DB it is exercising.
    """
    from app.models.component import Component

    row = next(
        (r for r in real_rows
         if r["digikey_category"] is not None and r["parameter_count"] is not None),
        None,
    )
    if row is None:
        pytest.skip("no component with the DigiKey attributes populated")

    component = Component(
        mpn="TEST-SERVE-COVERAGE",
        manufacturer=row["manufacturer"] or "ACME",
        category=row["category"] or "Unknown",
        digikey_category=row["digikey_category"],
        digikey_subcategory=row["digikey_subcategory"],
        lifecycle_status=row["lifecycle_status"],
        normally_stocked=row["normally_stocked"],
        parameter_count=row["parameter_count"],
        package_case=row["package_case"],
        htsus_code=row["htsus_code"],
        rohs_status=row["rohs_status"],
        digikey_unit_price=row["digikey_unit_price"] or row["price"],
        max_break_qty=row["max_break_qty"],
        price_break_count=row["price_break_count"],
    )
    db_session.add(component)
    db_session.commit()
    db_session.refresh(component)
    return component


def test_lead_time_endpoint_returns_a_prediction_for_a_real_part(
    served, real_rows, client, db_session
):
    """End-to-end: a real part must produce a real number through the API."""
    set_ml_state(served)
    component = _seed_component(db_session, real_rows)

    resp = client.get(f"/api/v1/ml/lead-time?component_id={component.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["predicted_factory_lead_time_days"] > 0
    assert body["resolved_from"] == f"component:{component.id}"
    # Every input must be echoed, so nothing can be quietly assumed.
    assert body["inputs_used"]
    for key in required_record_keys(served.feature_columns):
        assert key in body["inputs_used"], f"{key} was required but not reported"


def test_lead_time_endpoint_names_what_is_missing(served, client):
    """A refusal must be actionable, not just a 422."""
    set_ml_state(served)
    resp = client.get("/api/v1/ml/lead-time")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["missing"], "422 must name the missing inputs"
    assert detail["required_inputs"] == required_record_keys(served.feature_columns)
    assert "component_id" in detail["hint"]


# ── the optimizer's own serving path ────────────────────────────────────────

def test_optimizer_record_satisfies_the_served_schema(served, real_rows):
    """`supply_risk.model_available` was false on 6/6 runs. Prove it is not now.

    This calls the exact function the optimizer calls
    (``app.optimization.costs.ml_factory_lead_time_days``) with the exact record
    shape ``solve.py`` assembles per BOM line, over real database rows. It does
    not go through the solver, so it stays fast and isolates the serving path —
    which is where the defect was.
    """
    from app.optimization.costs import ml_factory_lead_time_days

    set_ml_state(served)
    available = 0
    reasons: dict[str, int] = {}
    sample = real_rows[:400]
    for row in sample:
        result = ml_factory_lead_time_days(_record(row))
        if result.available and result.days and result.days > 0:
            available += 1
        else:
            key = (result.reason or "unknown").split(":")[0][:60]
            reasons[key] = reasons.get(key, 0) + 1

    rate = available / len(sample)
    assert rate >= MIN_ANSWER_RATE, (
        f"optimizer serving path answered only {rate:.1%} of {len(sample)} real rows; "
        f"decline reasons: {reasons}"
    )
