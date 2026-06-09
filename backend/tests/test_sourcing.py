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
