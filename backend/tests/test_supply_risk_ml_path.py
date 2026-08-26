"""The ML lead-time model must actually be exercised by the optimizer.

Background (docs/archive/ML_API_PUSH_PLAN.md item 2). `solve.py` used to swap the ML
prediction in for the route ETA when::

    abs(ml_eta - route_eta) / route_eta > 0.10  and  ml_eta < route_eta * 2

The served model was a constant 62.1 days and `route_eta` never exceeded 16.4 d
across all 234 recorded `optimization_runs`, so the second clause required
`route_eta > 31.05 d` and the branch fired **0 / 234 times**. The model was
wired in but structurally unreachable.

Raising the threshold would not have made it correct. The model predicts FACTORY
(replenishment) lead time; `route_eta` is distributor handling + ground transit
for units shipping off the shelf, and the sourcing MILP hard-constrains
`ordered_qty <= offer.stock`, so the plan's delivery ETA genuinely IS
route-derived. The two are different quantities.

So the model now answers the question it was trained on, per BOM line, and is
reported as its own quantity (`RouteAlternative.supply_risk`). These tests pin
that it is reached on realistic input — on every strategy, with no threshold to
clear — and that its refusals stay honest.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.ml import MLState, set_ml_state
from app.ml.lead_time_model import build_design_matrix, build_feature_row, train_all_models
from app.optimization.routing import GeoPoint
from app.optimization.solve import DistributorMeta, optimize_bom
from app.optimization.sourcing import BomLine, Offer

TRAINED_CATEGORIES = ["Integrated Circuits (ICs)", "Memory", "Sensors"]


@pytest.fixture
def ml_state():
    """A REAL fitted model on a schema built by the real feature builder.

    Deliberately not a mock: the bug being guarded against lived in the seam
    between the training encoder and the serving encoder, so a mocked predictor
    would test nothing.
    """
    rng = np.random.default_rng(0)
    records, targets = [], []
    for i in range(180):
        cat = TRAINED_CATEGORIES[i % len(TRAINED_CATEGORIES)]
        price = float(rng.uniform(0.5, 90))
        records.append(build_feature_row(dk_category=cat, unit_price=price))
        base = {"Integrated Circuits (ICs)": 210.0, "Memory": 84.0, "Sensors": 42.0}[cat]
        targets.append(base + 0.05 * price)

    X, cols = build_design_matrix(records)
    results = train_all_models(X, np.asarray(targets, dtype=float), n_cv_splits=2)
    state = MLState(
        regime_model=None,
        regime_features=None,
        lead_time_models=results,
        best_lead_time_model="random_forest",
        current_stress_prob=0.0,
        feature_columns=cols,
        serving_model=results["random_forest"]["model"],
        provenance={"model_source": "local_joblib", "feature_schema_ok": True},
        regime_status={"available": False, "source": "unavailable_no_artifact"},
    )
    set_ml_state(state)          # restored by the autouse conftest fixture
    return state


def _scenario(
    categories=("Integrated Circuits (ICs)", "Memory"),
    stocks=(500, 500),
    quantities=(100, 50),
):
    bom = [
        BomLine(component_id=i + 1, mpn=f"PART-{i}", quantity=quantities[i],
                category=categories[i], dk_category=categories[i],
                manufacturer="STMicroelectronics", lifecycle_status="Active")
        for i in range(len(categories))
    ]
    offers = []
    for i in range(len(categories)):
        offers.append(Offer(i + 1, 10, "EastCoastPrime", price_usd=1.20 + i,
                            stock=stocks[i], moq=1, is_domestic=True))
        offers.append(Offer(i + 1, 20, "SoutheastMid", price_usd=2.50 + i,
                            stock=stocks[i], moq=1, is_domestic=True))
    distributors = {
        10: DistributorMeta(10, "EastCoastPrime", 35.7796, -78.6382,
                            "Raleigh", "NC", "USA", True, "major"),
        20: DistributorMeta(20, "SoutheastMid", 33.7490, -84.3880,
                            "Atlanta", "GA", "USA", True, "mid"),
    }
    return bom, offers, distributors, GeoPoint(lat=34.8526, lng=-82.3940)


# ── the ML path is reached ───────────────────────────────────────────────────

def test_ml_model_is_exercised_on_every_strategy(ml_state):
    """Was 0/234 runs. Must now be every strategy of every run."""
    bom, offers, distributors, depot = _scenario()
    resp = optimize_bom(bom, offers, distributors, depot)

    assert len(resp.alternatives) == 4
    for alt in resp.alternatives:
        risk = alt.supply_risk
        assert risk is not None, f"{alt.id} produced no supply-risk read-out"
        assert risk.model_available is True, f"{alt.id}: {risk.declined_reason}"
        assert risk.lines_scored > 0, f"{alt.id} scored no BOM lines"
        assert risk.max_factory_lead_time_days is not None
        assert risk.max_factory_lead_time_days > 0
        assert risk.driver_mpn
        assert risk.rationale


def test_prediction_uses_the_real_per_line_category_not_a_hardcoded_one():
    """solve.py used to pass component_category="Microcontrollers" for the whole BOM."""
    import inspect

    from app.optimization import solve
    source = inspect.getsource(solve)
    assert '"Microcontrollers",  # dominant category default' not in source
    assert "line.dk_category" in source


def test_supply_risk_reflects_the_slowest_part_in_the_plan(ml_state):
    """The BOM is ready when its longest-lead line is ready — max, not mean."""
    bom, offers, distributors, depot = _scenario(
        categories=("Sensors", "Integrated Circuits (ICs)"),
        stocks=(500, 500), quantities=(10, 10),
    )
    resp = optimize_bom(bom, offers, distributors, depot)
    fast_only, _, _, _ = _scenario(
        categories=("Sensors",), stocks=(500,), quantities=(10,)
    )
    resp_fast = optimize_bom(
        fast_only, [o for o in offers if o.component_id == 1], distributors, depot
    )

    mixed = resp.alternatives[0].supply_risk.max_factory_lead_time_days
    fast = resp_fast.alternatives[0].supply_risk.max_factory_lead_time_days
    assert mixed > fast, (
        "adding a long-lead part did not raise the plan's supply-risk lead time "
        f"({mixed} vs {fast})"
    )


# ── the delivery ETA stays honest ────────────────────────────────────────────

def test_factory_lead_time_does_not_silently_overwrite_the_delivery_eta(ml_state):
    """Every line ships from stock here, so the ETA must stay route-derived."""
    bom, offers, distributors, depot = _scenario(stocks=(10_000, 10_000))
    resp = optimize_bom(bom, offers, distributors, depot)

    for alt in resp.alternatives:
        risk = alt.supply_risk
        assert risk.zero_buffer_lines == 0
        assert risk.risk_adjusted_eta_days == pytest.approx(risk.route_eta_days)
        # The 200-day factory lead time must NOT have leaked into the ETA.
        assert alt.base_eta_days < 60
        assert risk.max_factory_lead_time_days > alt.base_eta_days


def test_zero_buffer_line_raises_the_risk_adjusted_eta(ml_state):
    """A line that consumes a distributor's whole shelf has no buffer left."""
    # Demand 120 against two shelves of 60: the MILP must take 100% of both.
    bom, offers, distributors, depot = _scenario(
        categories=("Integrated Circuits (ICs)",), stocks=(60,), quantities=(120,)
    )
    resp = optimize_bom(bom, offers, distributors, depot)

    alt = resp.alternatives[0]
    risk = alt.supply_risk
    assert risk.lines_scored > 0
    assert risk.zero_buffer_lines > 0, "expected a zero-buffer line on a fully-drawn shelf"
    assert risk.risk_adjusted_eta_days > risk.route_eta_days
    # ...and the headline ETA is still the ships-from-stock number.
    assert alt.base_eta_days == pytest.approx(risk.route_eta_days, rel=0.5)


# ── refusals stay honest ─────────────────────────────────────────────────────

def test_untrained_category_is_declined_not_guessed(ml_state):
    """~half the catalogue is outside the panel's vocabulary. Say so."""
    bom, offers, distributors, depot = _scenario(
        categories=("Unobtanium Widgets",), stocks=(500,), quantities=(10,)
    )
    resp = optimize_bom(bom, offers, distributors, depot)

    risk = resp.alternatives[0].supply_risk
    assert risk.lines_declined > 0
    assert risk.model_available is False
    assert risk.max_factory_lead_time_days is None
    assert risk.declined_reason
    assert "declined" in risk.rationale.lower() or "no bom line" in risk.rationale.lower()
    # A refusal must never move the ETA.
    assert risk.risk_adjusted_eta_days == pytest.approx(risk.route_eta_days)


def test_no_ml_state_degrades_to_an_honest_refusal():
    """No model loaded is a stated outcome, not a fabricated number."""
    set_ml_state(None)  # type: ignore[arg-type]
    bom, offers, distributors, depot = _scenario()
    resp = optimize_bom(bom, offers, distributors, depot)

    for alt in resp.alternatives:
        risk = alt.supply_risk
        assert risk.model_available is False
        assert risk.max_factory_lead_time_days is None
        assert risk.risk_adjusted_eta_days == pytest.approx(risk.route_eta_days)
        assert alt.base_eta_days > 0      # the route ETA still works


def test_the_old_unreachable_gate_is_gone():
    """Pin the specific expression that made the ML path dead code."""
    import inspect

    from app.optimization import solve
    source = inspect.getsource(solve)
    assert "ml_eta < route_eta * 2" not in source
    assert "effective_eta = ml_eta" not in source
