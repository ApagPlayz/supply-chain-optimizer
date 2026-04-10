"""
Freight cost + carbon + holding cost model.

All constants are cited from published industry sources. See
docs/superpowers/specs/2026-04-10-sub-project-a-design.md §5.1 for full
references.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# ── Physical / unit constants ────────────────────────────────────────────────
KM_PER_MILE = 1.60934
LBS_PER_KG = 2.20462
CWT_PER_LB = 0.01  # 1 hundredweight = 100 lbs

# ── Freight cost constants (cited) ───────────────────────────────────────────
# ATRI 2023: An Analysis of the Operational Costs of Trucking
TL_RATE_USD_PER_MILE = 2.271

# FreightWaves SONAR Q4 2023 + Old Dominion 2023 published tariff
LTL_BASE_FEE_USD = 75.0
LTL_RATE_USD_PER_CWT_MILE = 0.43

# BTS Commodity Flow Survey 2022
GROUND_KM_PER_DAY = 800.0

# EPA SmartWay 2023 heavy-duty truck factor: 161.8 g CO2e / ton-mile
CO2_G_PER_TON_MILE = 161.8

# Gartner IT Supply Chain Benchmarks 2022 — electronics annual holding cost
ANNUAL_HOLDING_RATE = 0.25

# ATA Cross-Docking Best Practices 2019 — midpoint of $30-$80 range
HUB_HANDLING_FEE_USD = 50.0

# BTS Intermodal Freight Transportation Model
HUB_DWELL_DAYS = 0.5

# FTL threshold: 10,000 lbs industry convention
TL_THRESHOLD_KG = 4536.0  # 10,000 lbs

# Distributor tier → handling days (proxy; data lacks SLAs)
HANDLING_DAYS_BY_TIER = {"major": 1, "mid": 2, "broker": 3}

# Average weight per electronic component unit (rough; used for BOM totals)
AVG_COMPONENT_KG = 0.05


# ── Core functions ───────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two (lat, lon) points in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def km_to_miles(km: float) -> float:
    return km / KM_PER_MILE


def transport_cost_usd(distance_km: float, weight_kg: float) -> float:
    """
    Returns USD cost for a single leg.

    Uses TL rate (ATRI 2023) when weight ≥ 10,000 lbs, otherwise LTL
    (FreightWaves SONAR / Old Dominion tariff). See spec §5.1.
    """
    miles = km_to_miles(distance_km)
    if weight_kg >= TL_THRESHOLD_KG:
        return miles * TL_RATE_USD_PER_MILE
    weight_lbs = weight_kg * LBS_PER_KG
    weight_cwt = weight_lbs * CWT_PER_LB
    return LTL_BASE_FEE_USD + weight_cwt * miles * LTL_RATE_USD_PER_CWT_MILE


def transit_days(distance_km: float) -> float:
    """Ground freight transit time (BTS CFS 2022: 800 km/day effective)."""
    return math.ceil(distance_km / GROUND_KM_PER_DAY)


def leg_lead_time_days(distance_km: float, distributor_tier: str) -> float:
    """Total lead time = distributor handling + ground transit."""
    handling = HANDLING_DAYS_BY_TIER.get(distributor_tier, 2)
    return handling + transit_days(distance_km)


def co2_kg(distance_km: float, weight_kg: float) -> float:
    """Carbon emissions in kg CO2e. EPA SmartWay 2023 factor."""
    miles = km_to_miles(distance_km)
    tons = weight_kg / 1000.0
    return tons * miles * (CO2_G_PER_TON_MILE / 1000.0)


def holding_cost_usd(inventory_value_usd: float, lead_time_days: float) -> float:
    """Gartner 2022: electronics annual holding rate 25%."""
    return inventory_value_usd * ANNUAL_HOLDING_RATE * (lead_time_days / 365.0)


@dataclass(frozen=True)
class CostBreakdown:
    """Structured cost breakdown for a single strategy on a route."""
    component_cost: float
    transport_cost: float
    holding_cost: float

    @property
    def total(self) -> float:
        return self.component_cost + self.transport_cost + self.holding_cost
