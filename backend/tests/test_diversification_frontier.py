"""
Tests for the minimum-supplier constraint and the price-of-resilience sweep.

Four things are proved here, in order of how much they matter:

  1. THE UNCONSTRAINED PATH IS UNCHANGED. `min_distributors=None` must add zero
     variables and zero constraints to the CP-SAT model, and the default-argument
     solve must still reproduce the committed benchmark's `milp_blind` landed
     cost on every BOM run 5 published. Nine other agents share this tree and the
     live page copy is written against those numbers; a silent shift in the
     baseline is the failure mode this file exists to prevent.
  2. The constraint is respected at every feasible k.
  3. k = 1 reproduces the unconstrained solution exactly.
  4. Cost is monotone non-decreasing in k.

Plus the statistics the frontier is reported with: the paired bootstrap CI is
tested against cases where the answer is known by construction.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from app.optimization.greedy import landed_cost_breakdown
from app.optimization.sourcing import BomLine, Offer, solve_sourcing
from app.optimization.strategies import get_strategy

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_JSON = REPO_ROOT / "docs" / "benchmark_results.json"


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _offer(cid, did, price, stock=1000, moq=1, domestic=True):
    return Offer(
        component_id=cid, distributor_id=did, price_usd=price,
        stock=stock, moq=moq, is_domestic=domestic,
        distributor_name=f"dist_{did}",
    )


@pytest.fixture
def four_line_bom():
    """
    Four lines, six distributors, everyone offers everything.

    Distributor 1 is cheapest on every line, so the unconstrained optimum
    consolidates onto it and the min-supplier constraint has real work to do at
    every k from 2 to 6.
    """
    bom = [
        BomLine(component_id=c, mpn=f"PART-{c}", quantity=4)
        for c in (1, 2, 3, 4)
    ]
    offers = [
        _offer(cid, did, price=1.00 + 0.10 * did + 0.01 * cid)
        for cid in (1, 2, 3, 4)
        for did in (1, 2, 3, 4, 5, 6)
    ]
    return bom, offers


@pytest.fixture
def weights():
    return get_strategy("balanced")


# ── (1) The unconstrained path is unchanged ──────────────────────────────────

def _capture_model(monkeypatch):
    """Intercept the CpModel handed to CpSolver.Solve and return the protos."""
    seen = []
    original = cp_model.CpSolver.Solve

    def spy(self, model, *args, **kwargs):
        seen.append(model.Proto())
        return original(self, model, *args, **kwargs)

    monkeypatch.setattr(cp_model.CpSolver, "Solve", spy)
    return seen


def test_min_distributors_none_adds_nothing_to_the_model(
    four_line_bom, weights, monkeypatch
):
    """
    The default path must build exactly the model it built before the parameter
    existed. Proved structurally: turning the constraint on adds exactly
    (one bound per distributor + one count bound) constraints and nothing else,
    so the None path demonstrably contributed zero of them.
    """
    bom, offers = four_line_bom
    n_dists = len({o.distributor_id for o in offers})

    seen = _capture_model(monkeypatch)
    solve_sourcing(bom, offers, weights, us_only=True)
    solve_sourcing(bom, offers, weights, us_only=True, min_distributors=1)
    assert len(seen) == 2

    none_proto, k1_proto = seen
    assert len(k1_proto.constraints) == len(none_proto.constraints) + n_dists + 1
    # Same decision variables — the constraint introduces no new ones.
    assert len(k1_proto.variables) == len(none_proto.variables)
    # Same objective, term for term. (The proto wrappers have no value equality,
    # so compare the fields that define the objective.)
    def _obj(p):
        return (
            list(p.objective.vars), list(p.objective.coeffs),
            p.objective.offset, p.objective.scaling_factor,
        )

    assert _obj(none_proto) == _obj(k1_proto)


def test_default_call_signature_still_omits_the_parameter(four_line_bom, weights):
    """A positional-only caller from before the change must still work."""
    bom, offers = four_line_bom
    res = solve_sourcing(bom, offers, weights, True, False, False)
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert res.objective_usd is not None


@pytest.mark.skipif(
    not BENCHMARK_JSON.exists(), reason="docs/benchmark_results.json not present"
)
def test_unconstrained_solve_still_reproduces_published_run5_costs():
    """
    The regression guard that actually protects the published page: the
    default-argument MILP must still land on run 5's `milp_blind` cost, BOM by
    BOM, to the cent.

    Skips (rather than fails) without a seeded database, in line with every
    other DB-backed test in this suite.
    """
    pytest.importorskip("sqlalchemy")
    db_path = REPO_ROOT / "backend" / "supply_chain.db"
    if not db_path.exists():
        pytest.skip("backend/supply_chain.db not present")

    from app.core.database import SessionLocal
    from seeds.run_benchmark import BOM_CATALOG, _load_offers_for_bom

    published = {
        r["bom"]: float(r["milp_usd"])
        for r in json.loads(BENCHMARK_JSON.read_text())["value_of_optimization"]
    }
    w = get_strategy("balanced")

    db = SessionLocal()
    try:
        checked = 0
        for name, items in BOM_CATALOG.items():
            if name not in published:
                continue
            bom, offers, _ = _load_offers_for_bom(db, items)
            if not bom or not offers:
                continue
            try:
                res = solve_sourcing(bom, offers, w, us_only=True)
            except RuntimeError:
                continue  # excluded from run 5 for the same reason
            bd = landed_cost_breakdown(res.assignments, offers, bom, w)
            assert round(float(bd["total_cost"]), 2) == pytest.approx(
                published[name], abs=0.01
            ), f"{name}: unconstrained MILP no longer reproduces run 5"
            checked += 1
    finally:
        db.close()

    assert checked >= 8, (
        f"only {checked} BOMs were checked against run 5 — the guard has gone "
        "quiet, which is how a published number silently drifts"
    )


# ── (2) The constraint is respected ──────────────────────────────────────────

@pytest.mark.parametrize("k", [1, 2, 3, 4, 5, 6])
def test_constraint_is_respected_at_every_k(four_line_bom, weights, k):
    bom, offers = four_line_bom
    res = solve_sourcing(bom, offers, weights, us_only=True, min_distributors=k)
    used = {a.distributor_id for a in res.assignments if a.quantity > 0}
    assert len(used) >= k
    assert len(res.selected_distributor_ids) >= k


def test_every_opened_distributor_actually_ships(four_line_bom, weights):
    """
    The bound is on distributors that GENUINELY supply the BOM. Without the
    reverse link `y[d] <= sum_c x[c,d]`, CP-SAT could satisfy `sum y >= k` by
    flipping empty distributors on, and the plan would be no more diversified.
    """
    bom, offers = four_line_bom
    for k in (2, 4, 6):
        res = solve_sourcing(bom, offers, weights, us_only=True, min_distributors=k)
        shipping = {a.distributor_id for a in res.assignments if a.quantity > 0}
        assert set(res.selected_distributor_ids) == shipping
        assert len(shipping) >= k


def test_infeasible_k_raises_with_a_readable_reason(four_line_bom, weights):
    """k above the number of candidate distributors has no plan; say so."""
    bom, offers = four_line_bom
    with pytest.raises(RuntimeError) as exc:
        solve_sourcing(bom, offers, weights, us_only=True, min_distributors=99)
    assert "min_distributors=99" in str(exc.value)


# ── (3) k = 1 reproduces the unconstrained solution ──────────────────────────

def _plan(res):
    return sorted(
        (a.component_id, a.distributor_id, a.quantity)
        for a in res.assignments if a.quantity > 0
    )


def test_k1_reproduces_the_unconstrained_plan(four_line_bom, weights):
    bom, offers = four_line_bom
    base = solve_sourcing(bom, offers, weights, us_only=True)
    k1 = solve_sourcing(bom, offers, weights, us_only=True, min_distributors=1)
    assert _plan(k1) == _plan(base)
    assert k1.total_component_cost == pytest.approx(base.total_component_cost)
    assert k1.objective_usd == pytest.approx(base.objective_usd)


def test_k1_reproduces_the_unconstrained_plan_across_strategies(four_line_bom):
    """The claim must not depend on `balanced`'s particular fixed charges."""
    bom, offers = four_line_bom
    for sid in ("cheapest", "fastest", "greenest", "balanced"):
        w = get_strategy(sid)
        base = solve_sourcing(bom, offers, w, us_only=True)
        k1 = solve_sourcing(bom, offers, w, us_only=True, min_distributors=1)
        assert _plan(k1) == _plan(base), sid
        assert k1.objective_usd == pytest.approx(base.objective_usd), sid


# ── (4) Cost is monotone non-decreasing in k ─────────────────────────────────

def test_solver_objective_is_monotone_non_decreasing_in_k(four_line_bom, weights):
    """
    Tightening a feasible region can never lower a minimum. Asserted on the
    SOLVER's own objective, which is the quantity the constraint acts on —
    `landed_cost_breakdown` is a re-score of the plan and is checked separately.
    """
    bom, offers = four_line_bom
    objectives = []
    for k in range(1, 7):
        res = solve_sourcing(bom, offers, weights, us_only=True, min_distributors=k)
        objectives.append(res.objective_usd)
    for a, b in zip(objectives, objectives[1:], strict=False):
        assert b >= a - 1e-6, f"objective fell from {a} to {b} as k tightened"


def test_landed_cost_is_monotone_non_decreasing_in_k(four_line_bom, weights):
    bom, offers = four_line_bom
    costs = []
    for k in range(1, 7):
        res = solve_sourcing(bom, offers, weights, us_only=True, min_distributors=k)
        costs.append(landed_cost_breakdown(res.assignments, offers, bom, weights)
                     ["total_cost"])
    for a, b in zip(costs, costs[1:], strict=False):
        assert b >= a - 1e-6, f"landed cost fell from {a:.4f} to {b:.4f}"


def test_supplier_count_is_non_decreasing_in_k(four_line_bom, weights):
    bom, offers = four_line_bom
    counts = [
        len({a.distributor_id for a in
             solve_sourcing(bom, offers, weights, us_only=True,
                            min_distributors=k).assignments})
        for k in range(1, 7)
    ]
    assert counts == sorted(counts)


def test_min_distributors_composes_with_require_dual_source(four_line_bom, weights):
    """
    `require_dual_source` escalates a per-distributor line cap. The two
    diversification levers must not cancel each other: the min-supplier bound
    still has to hold when both are on.
    """
    bom, offers = four_line_bom
    res = solve_sourcing(
        bom, offers, weights, us_only=True,
        require_dual_source=True, min_distributors=3,
    )
    used = {a.distributor_id for a in res.assignments if a.quantity > 0}
    assert len(used) >= 3


# ── The frontier's statistics ────────────────────────────────────────────────

def test_paired_bootstrap_ci_recovers_a_known_constant():
    from seeds.run_diversification_sweep import paired_bootstrap_ci

    ci = paired_bootstrap_ci([5.0] * 9)
    assert ci["n"] == 9
    assert ci["mean"] == pytest.approx(5.0)
    # Every resample of a constant is the constant, so the interval is degenerate
    # AND excludes zero.
    assert ci["ci_low"] == pytest.approx(5.0)
    assert ci["ci_high"] == pytest.approx(5.0)
    assert ci["excludes_zero"] is True


def test_paired_bootstrap_ci_covers_zero_for_a_symmetric_sample():
    from seeds.run_diversification_sweep import paired_bootstrap_ci

    ci = paired_bootstrap_ci([-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0])
    assert ci["mean"] == pytest.approx(0.0)
    assert ci["ci_low"] < 0.0 < ci["ci_high"]
    assert ci["excludes_zero"] is False


def test_paired_bootstrap_ci_is_deterministic():
    from seeds.run_diversification_sweep import paired_bootstrap_ci

    vals = [1.0, -0.5, 4.0, 2.25, 0.0, -1.75, 3.5]
    assert paired_bootstrap_ci(vals) == paired_bootstrap_ci(vals)


def test_paired_bootstrap_ci_refuses_to_invent_an_interval_from_one_point():
    from seeds.run_diversification_sweep import paired_bootstrap_ci

    ci = paired_bootstrap_ci([2.0])
    assert ci["n"] == 1
    assert ci["ci_low"] is None and ci["ci_high"] is None
    assert ci["excludes_zero"] is False


# ── The published artifact ───────────────────────────────────────────────────

FRONTIER_JSON = REPO_ROOT / "docs" / "diversification_frontier.json"


@pytest.mark.skipif(
    not FRONTIER_JSON.exists(), reason="docs/diversification_frontier.json not generated"
)
def test_published_frontier_is_internally_consistent():
    """
    Guards the artifact against the two ways this kind of doc goes wrong:
    a baseline that no longer matches the benchmark, and a price-per-unit-risk
    printed over a denominator the CI says is zero.
    """
    payload = json.loads(FRONTIER_JSON.read_text())

    assert payload["run5_reproduction_check"]["all_match"] is True, (
        "k = 1 no longer reproduces run 5's milp_blind cost — the frontier's "
        "baseline has drifted from the published benchmark"
    )
    assert payload["meta"]["writes_to_database"] is False
    assert payload["meta"]["overwrites_benchmark"] is False

    for row in payload["frontier"]:
        assert row["n_effective"] <= row["n_boms_feasible"]
        for scen in ("stress", "targeted"):
            for measure in ("cascade_risk", "expected_shortfall"):
                price = row.get(f"usd_per_unit_{scen}_{measure}_removed")
                ci = row[f"delta_{scen}_{measure}_vs_k1"]
                if price is not None:
                    assert ci["excludes_zero"], (
                        f"k={row['k']} {scen}/{measure}: a price is published "
                        "over a risk change whose CI covers zero"
                    )

    # Cost must be monotone in k on every BOM the sweep swept.
    for rec in payload["boms"]:
        if not rec["included"]:
            continue
        costs = [p["total_cost_usd"] for p in rec["points"] if p.get("feasible")]
        assert costs == sorted(costs), f"{rec['bom']}: cost falls as k tightens"
