"""CVaR-95 saturates at a ceiling; the shortfall frequencies do not.

OUTSTANDING_WORK.md item 13. `cost_inflation = 1 + (n_unfulfillable/n_bom) * premium`
is bounded and quantised, so on an n-line BOM it lives on an (n+1)-point lattice and
CVaR-95 -- a mean over the worst-5% tail of it -- tops out at `1 + premium`. Under
`stress_factor=3.0` most benchmark plans sit ON that ceiling, so CVaR-95 reports the
identical number for plans that are in fact very differently exposed. That is a
CEILING, not a finding of equal risk: the same defect class as the retired
`cascade_risk_score`.

The measures that keep resolving past the ceiling are means over ALL scenarios rather
than over the tail: `p_shortfall`, `p_total_shortfall`, and the pre-existing
`mean_cost_inflation`. These tests pin (a) that the ceiling exists and is flagged,
(b) that the new measures discriminate in a case where CVaR-95 ties at it
bit-identically, (c) that they do NOT manufacture a difference where the tie is
genuine, and (d) that re-basing CVaR onto the shortfall share would not have fixed
anything -- so nobody "fixes" this later by rescaling a published number for nothing.
"""
from __future__ import annotations

import pytest

from app.graph.builder import build_graph_state
from app.graph.simulation import EMERGENCY_COST_PREMIUM, run_monte_carlo

# Verified topology of the conftest `graph_db_session` fixture (component_id ->
# supplying distributor_ids): 1 -> {}, 2..5 -> {1, 2}, 6 -> {}, 7..10 -> {1}.
# Components 1 and 6 carry no offers, so they are unfulfillable in EVERY scenario
# and would pin p_shortfall at 1.0 on their own -- deliberately avoided below.
DUAL_SOURCED = 2      # supplied by {1, 2}
SOLE_SOURCED = 7      # supplied by {1}
DUAL_SOURCED_2 = 3    # supplied by {1, 2}


@pytest.fixture()
def gs_fixed_p(graph_db_session):
    """GraphState with p_disruption pinned, so the lattice arithmetic is exact.

    Overriding the calibrated probabilities is what makes these assertions provable
    rather than incidental: with p(d1) = p(d2) = 0.5 the tail-occupancy of every plan
    below is known in closed form, so "both arms hit the ceiling" is a fact about the
    estimator, not an artefact of this fixture's centrality values.
    """
    gs = build_graph_state(graph_db_session)
    gs.p_disruption = {1: 0.5, 2: 0.5, 3: 0.0}
    return gs


def test_the_cost_inflation_lattice_has_exactly_n_plus_one_points():
    """A 4-line BOM can only ever produce 5 distinct per-trial values."""
    n_bom = 4
    lattice = [1.0 + (k / n_bom) * EMERGENCY_COST_PREMIUM for k in range(n_bom + 1)]
    assert lattice == [1.0, 1.0375, 1.075, 1.1125, 1.15]
    # The top of the lattice is bit-identical to the published 1.15 -- two arms that
    # both saturate are equal in float, not merely equal after rounding to 4 dp.
    assert lattice[-1] == 1.0 + EMERGENCY_COST_PREMIUM
    assert lattice[-1] == 1.15


def test_cvar_95_ties_at_its_ceiling_where_the_shortfall_measures_discriminate(gs_fixed_p):
    """THE test for item 13.

    Two plans over the same 2-line BOM. Both put every tail scenario at a total
    shortfall, so both report cvar_95 at the 1.15 ceiling -- and a reader comparing them
    on CVaR alone would conclude they are equally exposed. They are not: the
    single-sourced plan collapses entirely twice as often.
    """
    bom = [DUAL_SOURCED, SOLE_SOURCED]
    blind = run_monte_carlo(gs_fixed_p, bom, allowed_distributor_ids={1})
    graph = run_monte_carlo(gs_fixed_p, bom, allowed_distributor_ids={1, 2})

    ceiling = 1.0 + EMERGENCY_COST_PREMIUM

    # 1. CVaR-95 is pinned at the ceiling for BOTH arms, bit-identically.
    #    The tie BETWEEN the two arms is exact and is the claim under test. The
    #    comparison to the closed-form ceiling is NOT exact: cvar_95 is a mean over
    #    the tail, so it reaches 1.15 only up to float accumulation order, which
    #    differs by platform (1.149999999999999 on CI, 1.15 locally). The tolerance
    #    here is the same 1e-9 `run_monte_carlo` uses to set `cvar_95_saturated`,
    #    so this test asserts exactly what the served flag asserts.
    assert blind.cvar_95 == pytest.approx(ceiling, abs=1e-9)
    assert graph.cvar_95 == pytest.approx(ceiling, abs=1e-9)
    assert blind.cvar_95 == graph.cvar_95
    assert blind.cvar_95_ceiling == ceiling and graph.cvar_95_ceiling == ceiling
    assert blind.cvar_95_saturated and graph.cvar_95_saturated

    # 2. The plans are NOT equally exposed. P(every line unfulfillable) is the event
    #    that fills the CVaR tail; once the tail is full, CVaR stops counting and this
    #    keeps going. Blind collapses whenever d1 fails (~0.5); graph needs d1 AND d2
    #    (~0.25).
    assert graph.p_total_shortfall < blind.p_total_shortfall
    assert blind.p_total_shortfall == pytest.approx(0.5, abs=0.05)
    assert graph.p_total_shortfall == pytest.approx(0.25, abs=0.05)
    # A material gap, not a rounding wobble -- this is what CVaR-95 reported as zero.
    assert blind.p_total_shortfall - graph.p_total_shortfall > 0.15

    # 3. mean_cost_inflation (a mean over ALL scenarios, not the tail) also resolves it.
    assert graph.mean_cost_inflation < blind.mean_cost_inflation

    # 4. p_shortfall is the persisted form of the count that was previously discarded.
    assert blind.p_shortfall == blind.n_scenarios_with_shortfall / blind.n_scenarios
    assert graph.p_shortfall == graph.n_scenarios_with_shortfall / graph.n_scenarios


def test_p_shortfall_discriminates_where_cvar_95_ties_at_the_ceiling(gs_fixed_p):
    """The measure item 13 names by hand, on a BOM where it is the one that moves.

    Both lines dual-sourceable, so restricting the plan to d1 alone makes ANY d1
    outage a shortfall, while the diversified plan needs both to fail. CVaR-95 cannot
    see the difference; p_shortfall reports it directly.
    """
    bom = [DUAL_SOURCED, DUAL_SOURCED_2]  # both supplied by {1, 2}
    blind = run_monte_carlo(gs_fixed_p, bom, allowed_distributor_ids={1})
    graph = run_monte_carlo(gs_fixed_p, bom, allowed_distributor_ids={1, 2})

    assert blind.cvar_95 == graph.cvar_95  # exact: the tie is the point
    # ...and both sit on the ceiling, to the 1e-9 the saturation flag uses.
    assert blind.cvar_95 == pytest.approx(1.0 + EMERGENCY_COST_PREMIUM, abs=1e-9)
    assert blind.cvar_95_saturated and graph.cvar_95_saturated

    assert graph.p_shortfall < blind.p_shortfall
    assert blind.p_shortfall == pytest.approx(0.5, abs=0.05)
    assert graph.p_shortfall == pytest.approx(0.25, abs=0.05)


def test_the_new_measures_do_not_invent_a_difference_between_identical_plans(gs_fixed_p):
    """Negative control.

    Two published benchmark rows (rf_transceiver_module, both scenarios) tie at the
    ceiling because both arms genuinely selected the SAME single distributor. There
    the tie is the correct answer, and a measure that manufactured a gap would be
    worse than the ceiling it replaced.
    """
    bom = [DUAL_SOURCED, SOLE_SOURCED]
    a = run_monte_carlo(gs_fixed_p, bom, allowed_distributor_ids={1})
    b = run_monte_carlo(gs_fixed_p, bom, allowed_distributor_ids={1})

    assert a.cvar_95 == b.cvar_95
    assert a.p_shortfall == b.p_shortfall
    assert a.p_total_shortfall == b.p_total_shortfall
    assert a.mean_cost_inflation == b.mean_cost_inflation


def test_cvar_95_saturated_is_false_while_the_metric_is_still_measuring(gs_fixed_p):
    """The flag must not be stuck on, or it says nothing."""
    gs_fixed_p.p_disruption = {1: 0.01, 2: 0.01, 3: 0.0}
    result = run_monte_carlo(gs_fixed_p, [DUAL_SOURCED], allowed_distributor_ids={1, 2})
    assert not result.cvar_95_saturated
    assert result.cvar_95 < result.cvar_95_ceiling


def test_total_shortfall_is_a_subset_of_shortfall(gs_fixed_p):
    """Bookkeeping invariant: every total shortfall is a shortfall."""
    result = run_monte_carlo(
        gs_fixed_p, [DUAL_SOURCED, SOLE_SOURCED], allowed_distributor_ids={1, 2}
    )
    assert 0 <= result.n_scenarios_total_shortfall <= result.n_scenarios_with_shortfall
    assert 0.0 <= result.p_total_shortfall <= result.p_shortfall <= 1.0
    assert result.p_total_shortfall == result.n_scenarios_total_shortfall / result.n_scenarios


def test_rebasing_cvar_onto_the_shortfall_share_would_not_break_the_tie(gs_fixed_p):
    """Guards item 13's conclusion (3): do NOT recompute CVaR on the line share.

    `inflation = 1 + share * premium` is an exact affine map of `share`, so
    CVaR(share) == (cvar_95 - 1) / premium carries identical information and merely
    moves the ceiling from 1.15 to 1.0. Two arms that tie on one tie on the other.
    Changing the base would move every published CVaR figure and buy no resolution;
    this test exists so that is not attempted.
    """
    bom = [DUAL_SOURCED, SOLE_SOURCED]
    blind = run_monte_carlo(gs_fixed_p, bom, allowed_distributor_ids={1})
    graph = run_monte_carlo(gs_fixed_p, bom, allowed_distributor_ids={1, 2})

    def cvar_on_share(r):
        return (r.cvar_95 - 1.0) / EMERGENCY_COST_PREMIUM

    assert cvar_on_share(blind) == pytest.approx(1.0)
    assert cvar_on_share(graph) == pytest.approx(1.0)
    # Still a tie -- the saturation is caused by truncating to the tail, not by units.
    assert cvar_on_share(blind) == pytest.approx(cvar_on_share(graph))
