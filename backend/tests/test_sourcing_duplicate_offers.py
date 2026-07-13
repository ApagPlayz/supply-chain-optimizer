"""
Regression tests for the duplicate-offer variable collision in solve_sourcing.

The offer table stores one row per price-break tier, so the same
(component_id, distributor_id) pair legitimately appears more than once. The
CP-SAT model keys its x/q variables on that pair, so before the fix each
duplicate row overwrote the previous row's variable while still being summed
into the demand constraint and priced into the objective. Two failure modes
followed, and both are asserted against here:

  1. demand constraint became k*q == demand  -> spurious INFEASIBLE
  2. objective charged the SUM of the k tier prices as the unit price

Real data: 509 (component_id, distributor_id) pairs are duplicated, and
STM32F103C8T6 at Verical was costed at $30.03/unit against a true $2.86.
"""
import pytest

from app.optimization.sourcing import BomLine, Offer, solve_sourcing
from app.optimization.strategies import get_strategy


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


BALANCED = get_strategy("balanced")


def test_duplicate_tiers_do_not_inflate_unit_price():
    """The cheapest tier is charged -- not the sum of every tier."""
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=10)]
    # One distributor, six price-break tiers. Pre-fix the objective charged
    # 2.86+4.94+5.54+5.54+5.65+5.50 = $30.03/unit.
    offers = [_offer(1, 100, p) for p in (2.86, 4.94, 5.54, 5.54, 5.65, 5.50)]

    result = solve_sourcing(bom, offers, BALANCED)

    assert result.assignments, "solver returned no assignment"
    unit_price = result.assignments[0].unit_price_usd
    assert unit_price == pytest.approx(2.86), (
        f"expected the cheapest tier ($2.86/unit), got ${unit_price:.2f} -- "
        "duplicate tiers are being summed into the objective again"
    )


def test_duplicate_tiers_do_not_cause_spurious_infeasibility():
    """
    demand % n_duplicates != 0 used to make the model INFEASIBLE.

    Three duplicate rows and a demand of 10 gives 3*q == 10, which has no
    integer solution -- the solver reported INFEASIBLE on a BOM that is
    trivially satisfiable.
    """
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=10)]
    offers = [_offer(1, 100, p) for p in (1.00, 1.50, 2.00)]

    result = solve_sourcing(bom, offers, BALANCED)

    assert result.assignments, "spuriously infeasible: 3*q == 10 has no integer solution"
    assert sum(a.quantity for a in result.assignments) == 10


def test_duplicate_tiers_do_not_distort_distributor_choice():
    """
    The bug's real-world harm: a genuinely cheap multi-tier distributor is
    priced as the sum of its tiers, so the solver avoids it and picks a more
    expensive single-tier competitor.
    """
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=10)]
    offers = [
        # Cheapest real price ($2.86), but split across 6 tiers summing to $30.03.
        *[_offer(1, 100, p) for p in (2.86, 4.94, 5.54, 5.54, 5.65, 5.50)],
        # Single-tier competitor, genuinely more expensive.
        _offer(1, 200, 4.00),
    ]

    result = solve_sourcing(bom, offers, BALANCED)

    chosen = {a.distributor_id for a in result.assignments}
    assert chosen == {100}, (
        f"picked distributor(s) {chosen}; expected the genuinely cheapest (100). "
        "The multi-tier distributor is being penalised by summed tier prices again."
    )
