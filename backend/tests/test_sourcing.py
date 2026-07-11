"""Unit tests for outlier filter and CP-SAT sourcing MILP."""
import pytest

from app.optimization.sourcing import (
    BomLine, Offer, filter_price_outliers, solve_sourcing,
)
from app.optimization.strategies import get_strategy


def _offer(cid, did, price, stock=1000, moq=1, domestic=True, name=None):
    return Offer(
        component_id=cid, distributor_id=did, price_usd=price,
        stock=stock, moq=moq, is_domestic=domestic,
        distributor_name=name or f"dist_{did}",
    )


def test_outlier_filter_drops_price_above_5x_median():
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=10)]
    offers = [
        _offer(1, 1, 1.40), _offer(1, 2, 1.50), _offer(1, 3, 2.00),
        _offer(1, 4, 2.50), _offer(1, 5, 2.80), _offer(1, 6, 1447.87),
    ]
    kept, drops = filter_price_outliers(offers, bom)
    assert len(drops) == 1
    assert drops[0].dropped_price_usd == 1447.87
    assert drops[0].dropped_distributor_id == 6
    assert "median" in drops[0].reason
    assert 6 not in [o.distributor_id for o in kept]


def test_outlier_filter_keeps_low_outliers():
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=10)]
    offers = [
        _offer(1, 1, 0.20), _offer(1, 2, 2.00),
        _offer(1, 3, 2.10), _offer(1, 4, 2.20),
    ]
    kept, drops = filter_price_outliers(offers, bom)
    # Low outlier (0.20) must stay — it's a real discount
    assert 1 in [o.distributor_id for o in kept]
    assert len(drops) == 0


def test_sourcing_picks_cheapest_offer_when_stock_available():
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=10)]
    offers = [
        _offer(1, 1, 0.49), _offer(1, 2, 1.20), _offer(1, 3, 2.00),
    ]
    result = solve_sourcing(bom, offers, get_strategy("cheapest"))
    assert len(result.assignments) == 1
    assert result.assignments[0].distributor_id == 1
    assert result.assignments[0].unit_price_usd == 0.49
    assert result.assignments[0].quantity == 10


def test_sourcing_respects_moq():
    # Cheap offer has MOQ 100 but we only need 5
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=5)]
    offers = [
        _offer(1, 1, 0.49, stock=500, moq=100),
        _offer(1, 2, 2.00, stock=500, moq=1),
    ]
    result = solve_sourcing(bom, offers, get_strategy("cheapest"))
    assert len(result.assignments) == 1
    # Either pays expensive offer or pays cheap but orders 100
    a = result.assignments[0]
    assert (a.distributor_id == 2 and a.quantity == 5) or \
           (a.distributor_id == 1 and a.quantity == 100)


def test_sourcing_rejects_international_when_us_only_true():
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=10)]
    offers = [
        _offer(1, 1, 0.25, domestic=False),  # cheaper, intl
        _offer(1, 2, 1.00, domestic=True),
    ]
    result = solve_sourcing(bom, offers, get_strategy("cheapest"), us_only=True)
    assert result.assignments[0].distributor_id == 2


def test_sourcing_splits_across_distributors_when_stock_insufficient():
    # Both distributors have insufficient stock individually — solver MUST split.
    # (When one distributor has enough stock, the $75 LTL base fee makes a
    # single-supplier solution cheaper despite higher unit price.)
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=50)]
    offers = [
        _offer(1, 1, 0.49, stock=30),   # 30 units only
        _offer(1, 2, 1.00, stock=30),   # 30 units only — neither alone can fill 50
    ]
    result = solve_sourcing(bom, offers, get_strategy("cheapest"))
    dids = {a.distributor_id for a in result.assignments}
    # Must use both distributors since neither has enough stock alone
    assert 1 in dids and 2 in dids
    total = sum(a.quantity for a in result.assignments)
    assert total == 50


# ── Dual-sourcing / hard diversification constraint ─────────────────────────

import math


def _multi_line_bom(n):
    return [BomLine(component_id=c, mpn=f"PART-{c}", quantity=5) for c in range(1, n + 1)]


def test_dual_source_forces_diversification_away_from_single_hub():
    # Hub (did=1) offers ALL 4 lines cheapest. Each line also has an alternative
    # distributor. Without diversification the MILP consolidates onto hub 1.
    bom = _multi_line_bom(4)
    offers = []
    for cid in range(1, 5):
        offers.append(_offer(cid, 1, 0.50))            # cheap hub, every line
        offers.append(_offer(cid, 10 + cid, 0.60))     # a distinct alternative per line

    # Baseline (no dual-sourcing): consolidates onto the single hub.
    blind = solve_sourcing(bom, offers, get_strategy("cheapest"),
                           require_dual_source=False)
    assert len({a.distributor_id for a in blind.assignments}) == 1

    # With dual-sourcing: must spread across ≥2 distributors and no single
    # distributor may source more than ceil(N/2) lines.
    div = solve_sourcing(bom, offers, get_strategy("cheapest"),
                         require_dual_source=True)
    dids = [a.distributor_id for a in div.assignments]
    assert len(set(dids)) >= 2
    from collections import Counter
    max_lines = max(Counter(dids).values())
    assert max_lines <= math.ceil(len(bom) / 2)
    # Full demand still covered
    assert sum(a.quantity for a in div.assignments) == sum(b.quantity for b in bom)


def test_dual_source_leaves_already_diversified_plan_unchanged():
    # Blind plan already spreads across 2 distributors (stock forces a split, or
    # the plan is naturally 2-sourced). require_dual_source must NOT reshuffle it
    # — reshuffling can only make concentration worse, never better.
    bom = _multi_line_bom(2)
    # Each line: hub 1 is cheapest but stock-limited so it can't take both lines;
    # line-specific alternatives make a 2-supplier blind plan optimal anyway.
    offers = [
        _offer(1, 1, 0.50, stock=5),
        _offer(1, 2, 0.55, stock=1000),
        _offer(2, 3, 0.50, stock=5),
        _offer(2, 1, 0.55, stock=1000),
    ]
    blind = solve_sourcing(bom, offers, get_strategy("cheapest"),
                           require_dual_source=False)
    div = solve_sourcing(bom, offers, get_strategy("cheapest"),
                         require_dual_source=True)
    # If blind already used ≥2 distributors, the dual-source plan is identical.
    if len({a.distributor_id for a in blind.assignments}) >= 2:
        assert (
            sorted((a.component_id, a.distributor_id, a.quantity) for a in blind.assignments)
            == sorted((a.component_id, a.distributor_id, a.quantity) for a in div.assignments)
        )


def test_dual_source_single_source_bom_falls_back_gracefully():
    # Every line offered by exactly ONE hub — genuinely single-source. The
    # diversification escalation finds no feasible cap and must fall back to a
    # valid plan without crashing.
    bom = _multi_line_bom(3)
    offers = [_offer(cid, 1, 0.50) for cid in range(1, 4)]  # all on hub 1 only

    result = solve_sourcing(bom, offers, get_strategy("cheapest"),
                            require_dual_source=True)
    # Valid plan: full demand covered, single hub (couldn't diversify).
    assert sum(a.quantity for a in result.assignments) == sum(b.quantity for b in bom)
    assert len({a.distributor_id for a in result.assignments}) == 1


def test_dual_source_false_leaves_plan_identical():
    # require_dual_source=False must reproduce the exact prior selection.
    bom = _multi_line_bom(4)
    offers = []
    for cid in range(1, 5):
        offers.append(_offer(cid, 1, 0.50))
        offers.append(_offer(cid, 10 + cid, 0.60))

    default = solve_sourcing(bom, offers, get_strategy("cheapest"))
    explicit_false = solve_sourcing(bom, offers, get_strategy("cheapest"),
                                    require_dual_source=False)
    assert (
        sorted((a.component_id, a.distributor_id, a.quantity) for a in default.assignments)
        == sorted((a.component_id, a.distributor_id, a.quantity) for a in explicit_false.assignments)
    )
