"""
Invariants of the two-stage stochastic sourcing program (app/optimization/stochastic.py).

Three families of test here, in descending order of how much they matter:

1. **The probability calibration is not the old broken one.** The repo's existing
   simulator reads min-max normalized betweenness centrality directly as a failure
   probability, which forces the most central distributor to p = 1.0 in every
   scenario. These tests pin the properties that make the new calibration different:
   nothing saturates, the median supplier sits at the cited base rate, and centrality
   can be switched off entirely.

2. **The stochastic model degenerates correctly.** With no uncertainty it must
   reproduce the deterministic landed cost exactly -- scored through `greedy.
   landed_cost_breakdown`, the same anti-rigging helper `test_greedy.py` uses. If the
   stochastic program cannot reproduce the deterministic answer when there is nothing
   to be stochastic about, none of its other numbers mean anything.

3. **The frontier behaves like a frontier.** CVaR dominates both VaR and the mean,
   lambda = 0 attains the lowest expected cost in the sweep, lambda = 1 attains the
   lowest CVaR, risk aversion actually buys a lower tail and is not free, and the
   published statistics for a plan match an independent exact re-evaluation of that
   same plan.
"""
from __future__ import annotations

import math

import pytest

from app.optimization.greedy import landed_cost_breakdown
from app.optimization.sourcing import BomLine, Offer, SourcingAssignment
from app.optimization.stochastic import (
    DEFAULT_ALPHA,
    DEFAULT_BASE_ANNUAL_PROB,
    MAX_ENUMERABLE_DISTRIBUTORS,
    MAX_FAILURE_PROB,
    DisruptionScenario,
    ScenarioSet,
    annual_to_horizon_prob,
    build_failure_probabilities,
    compute_frontier,
    enumerate_scenarios,
    evaluate_plan,
    find_knee,
    saa_optimality_gap,
    sample_scenarios,
    solve_stochastic_sourcing,
    tail_composition,
    weighted_var_cvar,
)
from app.optimization.strategies import get_strategy

BALANCED = get_strategy("balanced")


def _offer(cid: int, did: int, price: float, stock: int = 10_000, moq: int = 1) -> Offer:
    return Offer(
        component_id=cid,
        distributor_id=did,
        distributor_name=f"dist-{did}",
        price_usd=price,
        stock=stock,
        moq=moq,
        is_domestic=True,
        dist_km_from_depot=100.0,
    )


def _two_line_bom(qty: int = 100):
    bom = [
        BomLine(component_id=1, mpn="PART-A", quantity=qty),
        BomLine(component_id=2, mpn="PART-B", quantity=qty),
    ]
    offers = [
        _offer(1, 10, 2.00), _offer(1, 11, 2.40), _offer(1, 12, 3.10),
        _offer(2, 10, 1.00), _offer(2, 11, 1.30), _offer(2, 12, 1.90),
    ]
    return bom, offers


def _wide_bom(qty: int = 200):
    """
    Two lines sourced from a SIX-distributor pool (ids 10..15) on a price ladder.

    Width matters for any test about tail composition: the cost distribution has at
    most 2**|D| atoms, so a three-supplier BOM can only ever produce eight, and its
    5% tail is one atom wide no matter how it is evaluated.
    """
    bom = [
        BomLine(component_id=1, mpn="PART-A", quantity=qty),
        BomLine(component_id=2, mpn="PART-B", quantity=qty),
    ]
    offers = []
    for i, did in enumerate(range(10, 16)):
        offers.append(_offer(1, did, 2.00 + 0.30 * i, stock=qty * 2))
        offers.append(_offer(2, did, 1.00 + 0.22 * i, stock=qty * 2))
    return bom, offers


def _certain_scenarios(n_draws: int = 50) -> ScenarioSet:
    """A scenario set in which nothing ever fails."""
    return ScenarioSet(
        scenarios=[DisruptionScenario(failed=frozenset(), count=n_draws)],
        n_draws=n_draws,
        seed=0,
        failure_probs={},
    )


# ── 1. Probability calibration ───────────────────────────────────────────────

def test_horizon_conversion_shrinks_an_annual_rate():
    """A 60-day exposure window must carry far less risk than a whole year."""
    p_year = annual_to_horizon_prob(0.2374, 365)
    p_60d = annual_to_horizon_prob(0.2374, 60)
    assert p_year == pytest.approx(0.2374, abs=1e-9)
    assert p_60d == pytest.approx(1 - 0.7626 ** (60 / 365), abs=1e-9)
    assert 0.03 < p_60d < 0.06, (
        f"a 23.7%/yr rate over 60 days should be ~4.4%, got {p_60d:.4f} -- the "
        "horizon conversion is the step that stops an ANNUAL rate being charged "
        "against a single purchase order"
    )


def test_horizon_conversion_rejects_nonsense_inputs():
    with pytest.raises(ValueError):
        annual_to_horizon_prob(1.0, 60)
    with pytest.raises(ValueError):
        annual_to_horizon_prob(0.2, 0)


def test_no_supplier_ever_saturates_at_probability_one():
    """
    REGRESSION GUARD for the defect this module exists to fix.

    graph/simulation.py:155-161 uses min-max normalized betweenness AS the failure
    probability. A min-max normalization always attains 1.0 at its maximum, so the
    most central distributor fails in 100% of scenarios. Here the most central
    supplier is handed betweenness exactly 1.0 -- the pathological input -- and must
    still come out with a sane probability.
    """
    betweenness = {1: 1.0, 2: 0.5, 3: 0.05, 4: 0.0, 5: 0.0}
    probs = build_failure_probabilities([1, 2, 3, 4, 5], betweenness)

    assert max(probs.values()) < MAX_FAILURE_PROB + 1e-12
    assert probs[1] < 0.5, (
        f"the most central distributor got p={probs[1]:.3f}; betweenness is being "
        "read as a probability again"
    )
    assert min(probs.values()) > 0.0, "every supplier carries some disruption risk"


def test_median_supplier_sits_on_the_cited_base_rate():
    """Centrality re-shapes risk around the base rate; it must not move the level."""
    betweenness = {i: float(i) for i in range(1, 8)}  # 7 suppliers, distinct ranks
    probs = build_failure_probabilities(
        list(betweenness), betweenness,
        base_annual_prob=DEFAULT_BASE_ANNUAL_PROB, horizon_days=60,
        centrality_spread=3.0,
    )
    p_base = annual_to_horizon_prob(DEFAULT_BASE_ANNUAL_PROB, 60)
    median_did = 4  # the middle of seven distinct ranks -> multiplier 3**0 == 1
    assert probs[median_did] == pytest.approx(p_base, rel=1e-9)


def test_centrality_spread_of_one_gives_a_flat_base_rate():
    """The 'centrality tells us nothing about failure' sensitivity arm."""
    betweenness = {1: 1.0, 2: 0.4, 3: 0.0}
    probs = build_failure_probabilities([1, 2, 3], betweenness, centrality_spread=1.0)
    assert len(set(probs.values())) == 1


def test_probability_is_monotone_in_centrality_and_bounded_by_the_spread():
    betweenness = {1: 0.0, 2: 0.2, 3: 0.9}
    probs = build_failure_probabilities([1, 2, 3], betweenness, centrality_spread=3.0)
    assert probs[1] < probs[2] < probs[3]
    assert probs[3] / probs[1] == pytest.approx(9.0, rel=1e-6), (
        "with spread=3 the extremes must be 3x above and 3x below the base rate, "
        "i.e. a 9x span -- and no wider"
    )


def test_ties_in_centrality_get_identical_probabilities():
    """18 of this network's 92 distributors sit at exactly betweenness 0."""
    betweenness = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.7}
    probs = build_failure_probabilities([1, 2, 3, 4], betweenness)
    assert probs[1] == probs[2] == probs[3]
    assert probs[4] > probs[1]


def test_centrality_spread_below_one_is_rejected():
    with pytest.raises(ValueError):
        build_failure_probabilities([1, 2], {1: 0.0, 2: 1.0}, centrality_spread=0.5)


def test_scenario_sampling_is_reproducible_and_deduplicated():
    probs = {d: 0.1 for d in range(1, 11)}
    a = sample_scenarios(probs, n_draws=300, seed=42)
    b = sample_scenarios(probs, n_draws=300, seed=42)
    assert [s.failed for s in a.scenarios] == [s.failed for s in b.scenarios]
    assert [s.count for s in a.scenarios] == [s.count for s in b.scenarios]

    assert sum(s.count for s in a.scenarios) == 300, "weights must be the draw counts"
    assert a.n_distinct < a.n_draws, "deduplication did nothing"
    # 10 suppliers at p=0.1 -> P(no failure) = 0.9^10 = 0.349
    assert a.p_no_disruption == pytest.approx(0.349, abs=0.06)
    assert a.mean_failures_per_scenario == pytest.approx(1.0, abs=0.25)


# ── 2. Risk statistics ───────────────────────────────────────────────────────

def test_weighted_cvar_matches_a_hand_computation():
    """
    Ten equally weighted outcomes 1..10, alpha = 0.9 -> the tail is exactly one
    sample, the worst one. CVaR = 10, VaR = 10.
    """
    values = list(range(1, 11))
    weights = [1] * 10
    var, cvar = weighted_var_cvar(values, weights, alpha=0.9)
    assert var == 10
    assert cvar == pytest.approx(10.0)


def test_weighted_cvar_splits_the_boundary_atom_fractionally():
    """
    Two outcomes, weights 1 and 99, alpha = 0.95 -> 5% of the mass is 5 units, of
    which 1 comes from the worst value (100) and 4 from the next (10).
    CVaR = (1*100 + 4*10) / 5 = 28.

    `graph/simulation.py` takes "mean of the worst ceil(5%) SAMPLES" instead, which
    on this input returns 100 -- 3.5x too high. Splitting the boundary atom is what
    makes this the true CVaR of the discrete measure.
    """
    var, cvar = weighted_var_cvar([100.0, 10.0], [1, 99], alpha=0.95)
    assert cvar == pytest.approx(28.0)
    assert var == pytest.approx(10.0)


def test_weighted_cvar_ordering_holds():
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
    weights = [1] * 8
    mean = sum(values) / len(values)
    var, cvar = weighted_var_cvar(values, weights, alpha=0.75)
    assert cvar >= var >= mean


def test_weighted_cvar_rejects_bad_input():
    with pytest.raises(ValueError):
        weighted_var_cvar([1.0], [1, 2], alpha=0.95)
    with pytest.raises(ValueError):
        weighted_var_cvar([], [], alpha=0.95)
    with pytest.raises(ValueError):
        weighted_var_cvar([1.0], [1], alpha=1.0)


# ── 3. The stochastic program itself ─────────────────────────────────────────

def test_with_no_uncertainty_it_reproduces_the_deterministic_landed_cost():
    """
    ANTI-RIGGING INVARIANT. Given a scenario set where nothing ever fails, every
    scenario cost must equal the plan's deterministic landed cost as scored by
    `greedy.landed_cost_breakdown` -- the shared helper the MILP benchmark uses.

    If this drifts, the stochastic program is optimizing a different cost model from
    the rest of the repo and no comparison against it is meaningful.
    """
    bom, offers = _two_line_bom(qty=100)
    res = solve_stochastic_sourcing(
        bom, offers, BALANCED, _certain_scenarios(), lam=0.5, us_only=False,
    )
    scored = landed_cost_breakdown(res.assignments, offers, bom, BALANCED)

    assert res.first_stage_cost_usd == pytest.approx(scored["total_cost"], abs=0.02)
    assert res.expected_cost_usd == pytest.approx(scored["total_cost"], abs=0.02)
    assert res.cvar_usd == pytest.approx(scored["total_cost"], abs=0.02)
    assert res.expected_recourse_usd == pytest.approx(0.0, abs=1e-9)


def test_with_no_uncertainty_it_consolidates_onto_the_cheapest_supplier():
    """Sanity: with no risk, fixed-charge economics should still dominate."""
    bom, offers = _two_line_bom(qty=100)
    res = solve_stochastic_sourcing(
        bom, offers, BALANCED, _certain_scenarios(), lam=0.0, us_only=False,
    )
    assert res.n_suppliers == 1
    assert res.selected_distributor_ids == [10]


def test_cvar_dominates_both_var_and_the_mean():
    """
    CVaR >= VaR and CVaR >= E always. VaR >= E does NOT hold in general and is
    deliberately not asserted: this cost distribution is a large point mass at the
    no-disruption cost with a thin, expensive tail, so the mean is pulled above the
    95th percentile. That asymmetry is exactly why CVaR is the right tail measure
    here and VaR is not.
    """
    bom, offers = _two_line_bom(qty=200)
    probs = build_failure_probabilities([10, 11, 12], {10: 1.0, 11: 0.3, 12: 0.0})
    scenarios = sample_scenarios(probs, n_draws=200, seed=7)
    for lam in (0.0, 0.5, 1.0):
        res = solve_stochastic_sourcing(
            bom, offers, BALANCED, scenarios, lam=lam, us_only=False, time_limit_s=30,
        )
        assert res.cvar_usd >= res.var_usd - 1e-6
        assert res.cvar_usd >= res.expected_cost_usd - 1e-6
        assert res.expected_cost_usd >= res.first_stage_cost_usd - 1e-6, (
            "expected cost must sit at or above the committed first-stage spend; a "
            "disruption cannot make the plan cheaper on average"
        )


def test_risk_aversion_moves_the_award_to_a_lower_probability_supplier():
    """
    The behavioural test that the whole module exists for.

    d10 is the cheapest supplier and also the most central, so the calibration gives
    it the highest disruption probability. A risk-neutral buyer takes the cheap,
    fragile supplier. A CVaR-averse buyer should pay up for the safer one -- and the
    difference must be visible in the tail, not just in the objective.
    """
    bom, offers = _two_line_bom(qty=200)
    probs = build_failure_probabilities([10, 11, 12], {10: 1.0, 11: 0.3, 12: 0.0})
    assert probs[10] > probs[11] > probs[12]
    scenarios = sample_scenarios(probs, n_draws=200, seed=7)

    risk_neutral = solve_stochastic_sourcing(
        bom, offers, BALANCED, scenarios, lam=0.0, us_only=False, time_limit_s=30,
    )
    risk_averse = solve_stochastic_sourcing(
        bom, offers, BALANCED, scenarios, lam=1.0, us_only=False, time_limit_s=30,
    )
    assert risk_averse.cvar_usd < risk_neutral.cvar_usd, (
        "buying risk aversion must actually buy a lower tail"
    )
    assert risk_averse.expected_cost_usd >= risk_neutral.expected_cost_usd - 1e-6, (
        "and it must not be free -- expected cost cannot improve as well"
    )


def test_disruption_forces_recourse_that_covers_the_whole_shortfall():
    """
    Single-source the BOM onto d10, then fail d10 in every scenario. Every committed
    unit must be re-procured or explicitly recorded as unmet -- the recourse balance
    constraint is what makes this a two-stage program rather than a cost surcharge.
    """
    bom, offers = _two_line_bom(qty=50)
    plan = [
        SourcingAssignment(1, "PART-A", 10, "dist-10", 50, 2.00),
        SourcingAssignment(2, "PART-B", 10, "dist-10", 50, 1.00),
    ]
    always_down = ScenarioSet(
        scenarios=[DisruptionScenario(failed=frozenset({10}), count=40)],
        n_draws=40, seed=0, failure_probs={10: 1.0},
    )
    profile = evaluate_plan(plan, bom, offers, BALANCED, always_down, us_only=False)

    outcome = profile.outcomes[0]
    assert outcome.emergency_units + outcome.unmet_units == 100
    assert outcome.unmet_units == 0, "d11 and d12 hold plenty of stock"
    assert outcome.recourse_cost_usd > 0.0, "recovering from a total outage is not free"
    assert profile.expected_cost_usd > profile.first_stage_cost_usd


def test_unmet_demand_is_recorded_when_survivors_cannot_cover():
    """No survivor has the stock, so the shortfall must surface as unmet units."""
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=100)]
    offers = [_offer(1, 10, 2.00, stock=100), _offer(1, 11, 2.50, stock=30)]
    plan = [SourcingAssignment(1, "PART-A", 10, "dist-10", 100, 2.00)]
    always_down = ScenarioSet(
        scenarios=[DisruptionScenario(failed=frozenset({10}), count=10)],
        n_draws=10, seed=0, failure_probs={10: 1.0},
    )
    profile = evaluate_plan(plan, bom, offers, BALANCED, always_down, us_only=False)
    outcome = profile.outcomes[0]
    assert outcome.emergency_units == 30, (
        "the 30 units a survivor still holds must be bought, not written off -- if "
        "this is 0 the unmet-demand penalty has fallen below the cost of recourse"
    )
    assert outcome.unmet_units == 70


def test_published_statistics_match_an_independent_re_evaluation():
    """
    The solver's own recourse variables can be left near-optimal when the MIP gap does
    not close, so `solve_stochastic_sourcing` reports statistics from an independent
    exact re-evaluation. This pins that the two agree for the plan returned.
    """
    bom, offers = _two_line_bom(qty=150)
    probs = build_failure_probabilities([10, 11, 12], {10: 1.0, 11: 0.4, 12: 0.0})
    scenarios = sample_scenarios(probs, n_draws=150, seed=11)
    res = solve_stochastic_sourcing(
        bom, offers, BALANCED, scenarios, lam=0.5, us_only=False, time_limit_s=30,
    )
    again = evaluate_plan(res.assignments, bom, offers, BALANCED, scenarios)
    assert again.expected_cost_usd == pytest.approx(res.expected_cost_usd, abs=0.01)
    assert again.cvar_usd == pytest.approx(res.cvar_usd, abs=0.01)
    assert again.first_stage_cost_usd == pytest.approx(res.first_stage_cost_usd, abs=0.01)


def test_lambda_zero_attains_the_lowest_expected_cost_in_the_sweep():
    bom, offers = _two_line_bom(qty=200)
    probs = build_failure_probabilities([10, 11, 12], {10: 1.0, 11: 0.3, 12: 0.0})
    scenarios = sample_scenarios(probs, n_draws=200, seed=3)
    points, _ = compute_frontier(
        bom, offers, BALANCED, scenarios, [0.0, 0.5, 1.0], time_limit_s=30,
    )
    by_lam = {p.lam: p for p in points}
    best_e = min(p.expected_cost_usd for p in points)
    assert by_lam[0.0].expected_cost_usd == pytest.approx(best_e, abs=0.01)


def test_lambda_one_attains_the_lowest_cvar_in_the_sweep():
    bom, offers = _two_line_bom(qty=200)
    probs = build_failure_probabilities([10, 11, 12], {10: 1.0, 11: 0.3, 12: 0.0})
    scenarios = sample_scenarios(probs, n_draws=200, seed=3)
    points, _ = compute_frontier(
        bom, offers, BALANCED, scenarios, [0.0, 0.5, 1.0], time_limit_s=30,
    )
    by_lam = {p.lam: p for p in points}
    best_cvar = min(p.cvar_usd for p in points)
    assert by_lam[1.0].cvar_usd == pytest.approx(best_cvar, abs=0.01)


def test_frontier_is_returned_in_ascending_lambda_order():
    bom, offers = _two_line_bom(qty=100)
    points, _ = compute_frontier(
        bom, offers, BALANCED, _certain_scenarios(), [0.0, 0.25, 1.0], time_limit_s=20,
    )
    assert [p.lam for p in points] == [0.0, 0.25, 1.0]


def test_alpha_that_breaks_integer_coefficients_is_rejected():
    """
    CP-SAT needs integer objective coefficients, so 1/(1-alpha) must be an integer.
    Failing loudly beats silently rounding the tail level the caller asked for.
    """
    bom, offers = _two_line_bom(qty=10)
    with pytest.raises(ValueError, match="integer"):
        solve_stochastic_sourcing(
            bom, offers, BALANCED, _certain_scenarios(), lam=0.5, alpha=0.93,
        )


def test_lambda_outside_the_unit_interval_is_rejected():
    bom, offers = _two_line_bom(qty=10)
    with pytest.raises(ValueError):
        solve_stochastic_sourcing(bom, offers, BALANCED, _certain_scenarios(), lam=1.5)


def test_empty_bom_is_rejected_like_the_deterministic_solver():
    with pytest.raises(ValueError, match="BOM is empty"):
        solve_stochastic_sourcing([], [], BALANCED, _certain_scenarios(), lam=0.0)


def test_default_alpha_is_the_repo_wide_ninety_five():
    """The repo standardized on CVaR-95. Never 'EVaR'."""
    assert DEFAULT_ALPHA == 0.95


def test_default_base_rate_matches_the_cited_mckinsey_figure():
    """
    McKinsey Global Institute 2020: a month-plus disruption every 3.7 years.
    P(>=1 in a year) = 1 - exp(-1/3.7). Pinned so the "cited" number in the docs
    cannot drift away from the number the code uses.
    """
    assert DEFAULT_BASE_ANNUAL_PROB == pytest.approx(1 - math.exp(-1 / 3.7), rel=1e-12)
    assert DEFAULT_BASE_ANNUAL_PROB == pytest.approx(0.2368, abs=5e-4)


# ── Knee detection ───────────────────────────────────────────────────────────

def test_knee_is_none_when_the_frontier_is_too_short_to_have_one():
    points, _ = compute_frontier(
        bom=_two_line_bom(qty=50)[0], offers=_two_line_bom(qty=50)[1],
        weights=BALANCED, scenario_set=_certain_scenarios(), lambdas=[0.0, 1.0],
        time_limit_s=20,
    )
    assert find_knee(points) is None, (
        "a two-point frontier has no knee; inventing one would be dishonest"
    )


def test_knee_finds_the_elbow_of_a_synthetic_frontier():
    """
    A frontier that drops steeply then flattens: the knee is the last point of the
    steep segment. Built synthetically so the expected answer is unambiguous.
    """
    from app.optimization.stochastic import FrontierPoint

    xs_ys = [(100.0, 200.0), (101.0, 150.0), (103.0, 120.0),
             (110.0, 118.0), (130.0, 117.0), (170.0, 116.5)]
    points = [
        FrontierPoint(
            lam=i / 5, expected_cost_usd=x, cvar_usd=y, var_usd=y,
            first_stage_cost_usd=x, expected_recourse_usd=0.0, n_suppliers=1,
            supplier_ids=[1], status="OPTIMAL", gap_pct=0.0, wall_seconds=0.0,
            evaluate_seconds=0.0, n_variables=0,
        )
        for i, (x, y) in enumerate(xs_ys)
    ]
    knee = find_knee(points)
    assert knee is not None
    assert knee.expected_cost_usd == pytest.approx(103.0), (
        f"expected the elbow at E=103, got E={knee.expected_cost_usd}"
    )


# ── 4. Scenario support: enumeration vs sampling ─────────────────────────────

def test_exact_enumeration_covers_the_whole_support():
    """
    Disruption is |D| independent Bernoulli variables, so the distribution has exactly
    2**|D| atoms and they must sum to probability 1.
    """
    probs = {1: 0.10, 2: 0.05, 3: 0.20}
    exact = enumerate_scenarios(probs)

    assert exact.kind == "exact"
    assert exact.n_distinct == 8 == exact.support_size()
    assert sum(s.probability for s in exact.scenarios) == pytest.approx(1.0, abs=1e-12)
    assert exact.residual_mass == pytest.approx(0.0, abs=1e-12)

    by_set = {s.failed: s.probability for s in exact.scenarios}
    assert by_set[frozenset()] == pytest.approx(0.90 * 0.95 * 0.80)
    assert by_set[frozenset({1, 3})] == pytest.approx(0.10 * 0.95 * 0.20)
    assert by_set[frozenset({1, 2, 3})] == pytest.approx(0.10 * 0.05 * 0.20)


def test_enumeration_refuses_a_pool_it_cannot_hold():
    probs = {d: 0.05 for d in range(MAX_ENUMERABLE_DISTRIBUTORS + 2)}
    with pytest.raises(ValueError, match="exact enumeration"):
        enumerate_scenarios(probs)


def test_sampling_converges_to_the_exact_measure():
    """SAA is consistent: more draws, closer to the enumerated truth."""
    probs = {1: 0.10, 2: 0.05, 3: 0.20}
    exact = enumerate_scenarios(probs)
    exact_p_none = exact.p_no_disruption

    err_small = abs(sample_scenarios(probs, 100, 1).p_no_disruption - exact_p_none)
    err_large = abs(sample_scenarios(probs, 20000, 1).p_no_disruption - exact_p_none)
    assert err_large < err_small
    assert err_large < 0.01


def test_exact_evaluation_puts_many_atoms_in_the_tail_where_sampling_puts_few():
    """
    THE REGRESSION GUARD FOR THE 'n_distinct = 10, alpha = 0.95' OBJECTION.

    With a six-supplier pool, 200 Monte Carlo draws recover ~10 of the 64 atoms and the
    5% tail is averaged over a handful of them. Enumerating the support puts an order of
    magnitude more distinct outcomes in the same tail -- and costs nothing, because the
    support was only ever 64 atoms wide.
    """
    probs = {did: 0.04 + 0.02 * (did - 9) for did in range(10, 16)}
    sampled = sample_scenarios(probs, 200, 42)
    exact = enumerate_scenarios(probs)

    bom, offers = _wide_bom(qty=200)
    plan = solve_stochastic_sourcing(
        bom, offers, BALANCED, sampled, lam=0.5, us_only=False, time_limit_s=30,
    ).assignments

    on_sample = evaluate_plan(plan, bom, offers, BALANCED, sampled)
    on_exact = evaluate_plan(plan, bom, offers, BALANCED, exact)

    assert on_exact.evaluation_kind == "exact"
    assert on_exact.tail.n_atoms_in_tail > on_sample.tail.n_atoms_in_tail
    assert not on_exact.tail.degenerate


def test_tail_composition_flags_a_degenerate_tail():
    """One atom holding the whole tail means CVaR has collapsed onto VaR."""
    values = [100.0, 10.0, 5.0]
    weights = [0.20, 0.50, 0.30]
    comp = tail_composition(values, weights, alpha=0.95)
    assert comp.n_atoms_in_tail == 1
    assert comp.degenerate is True
    assert comp.largest_tail_atom_share == pytest.approx(1.0)

    spread = tail_composition([9.0, 8.0, 7.0, 6.0], [0.25] * 4, alpha=0.5)
    assert spread.n_atoms_in_tail == 2
    assert spread.degenerate is False


def test_cvar_is_reported_across_several_alphas_and_is_monotone():
    """A more extreme tail level can never give a smaller CVaR."""
    bom, offers = _two_line_bom(qty=150)
    probs = build_failure_probabilities([10, 11, 12], {10: 1.0, 11: 0.3, 12: 0.0})
    exact = enumerate_scenarios(probs)
    res = evaluate_plan(
        solve_stochastic_sourcing(
            bom, offers, BALANCED, sample_scenarios(probs, 200, 5), lam=0.5,
            us_only=False, time_limit_s=30,
        ).assignments,
        bom, offers, BALANCED, exact,
    )
    alphas = sorted(res.cvar_by_alpha)
    values = [res.cvar_by_alpha[a] for a in alphas]
    assert values == sorted(values), f"CVaR must be non-decreasing in alpha: {res.cvar_by_alpha}"


def test_solver_refuses_an_enumerated_set_because_cpsat_needs_integer_weights():
    bom, offers = _two_line_bom(qty=50)
    exact = enumerate_scenarios({10: 0.1, 11: 0.05, 12: 0.02})
    with pytest.raises(ValueError, match="SAMPLED"):
        solve_stochastic_sourcing(bom, offers, BALANCED, exact, lam=0.5)


# ── 5. SAA solution quality (Mak, Morton & Wood 1999) ────────────────────────

def test_saa_optimality_gap_brackets_the_optimum_and_shrinks_with_sample_size():
    """
    The SAA lower bound is optimistically biased and the candidate plan's true value is
    a valid upper bound, so the gap must be non-negative -- and a larger sample must not
    make it worse.
    """
    bom, offers = _wide_bom(qty=200)
    probs = {did: 0.04 + 0.02 * (did - 9) for did in range(10, 16)}
    reference = enumerate_scenarios(probs)

    small = saa_optimality_gap(
        bom, offers, BALANCED, probs, reference, n_scenarios=25, n_replications=10,
        lam=0.5, time_limit_s=30,
    )
    large = saa_optimality_gap(
        bom, offers, BALANCED, probs, reference, n_scenarios=400, n_replications=10,
        lam=0.5, time_limit_s=30,
    )

    for est in (small, large):
        # E[v_N] <= v* holds IN EXPECTATION. With a finite number of replications the
        # sample mean can land slightly above the candidate plan's true value, which
        # makes the POINT estimate of the gap mildly negative -- that is the signal
        # "the gap is inside Monte Carlo noise", not a broken bound. The statement that
        # must hold is the interval one: the upper bound cannot sit below the lower
        # confidence limit.
        assert est.upper_bound >= est.lower_bound_ci_low
        assert est.gap_ci_high >= 0.0
        assert est.lower_bound_ci_low <= est.lower_bound_mean <= est.lower_bound_ci_high
        assert len(est.replicate_values) == est.n_replications
        assert est.upper_bound_kind.startswith("exact")
        assert abs(est.gap_pct_of_upper) < 25.0

    # More scenarios must not make the bracket worse by a material margin.
    assert large.gap_ci_high <= small.gap_ci_high * 1.5 + 1.0


def test_saa_optimality_gap_needs_enough_replications_for_a_ci():
    bom, offers = _two_line_bom(qty=50)
    probs = {10: 0.1, 11: 0.05, 12: 0.02}
    with pytest.raises(ValueError, match="replications"):
        saa_optimality_gap(
            bom, offers, BALANCED, probs, enumerate_scenarios(probs),
            n_scenarios=20, n_replications=1,
        )
