"""Verify cost functions against hand-computed expectations."""
import math
import pytest

from app.optimization import costs


def test_haversine_known_distance():
    # Greenville SC to Memphis TN — roughly 691 km (check ±5%)
    d = costs.haversine_km(34.8526, -82.3940, 35.0424, -89.9767)
    assert 656 < d < 726


def test_transport_cost_ltl_branch():
    # 100 km, 50 kg → LTL path (weight < 4536 kg threshold)
    c = costs.transport_cost_usd(100.0, 50.0)
    # miles = 62.14, cwt = 50*2.20462/100 = 1.1023
    # cost = 75 + 1.1023 * 62.14 * 0.43 = 75 + 29.45 ≈ 104.45
    assert 100 < c < 110
    assert c > costs.LTL_BASE_FEE_USD  # base fee is included


def test_transport_cost_tl_branch():
    # 100 km, 5000 kg → TL path
    c = costs.transport_cost_usd(100.0, 5000.0)
    # miles = 62.14, cost = 62.14 * 2.271 ≈ 141.12
    assert 135 < c < 148


def test_transit_days_discrete():
    # 800 km/day → 1 day for 800 km, 2 days for 801 km
    assert costs.transit_days(800.0) == 1
    assert costs.transit_days(801.0) == 2
    assert costs.transit_days(0.1) == 1  # ceil rounds up


def test_leg_lead_time_includes_handling():
    # 500 km + major distributor (1 day handling) → 1 + 1 = 2
    assert costs.leg_lead_time_days(500.0, "major") == 2
    assert costs.leg_lead_time_days(500.0, "broker") == 4  # 3 handling + 1 transit


def test_co2_smartway_factor():
    # 1000 km, 1000 kg = 1 tonne, ~621.4 miles → 621.4 * 0.1618 ≈ 100.5 kg
    c = costs.co2_kg(1000.0, 1000.0)
    assert 95 < c < 110


def test_holding_cost_annualized():
    # $10000 inventory, 36.5 days → 10000 * 0.25 * (36.5/365) = $250
    h = costs.holding_cost_usd(10000.0, 36.5)
    assert abs(h - 250.0) < 0.01


def test_cost_breakdown_total():
    b = costs.CostBreakdown(component_cost=100.0, transport_cost=20.0, holding_cost=5.0)
    assert b.total == 125.0
