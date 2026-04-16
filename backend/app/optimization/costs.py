"""
Freight cost + carbon + holding cost model.

All constants are cited from published industry sources. See
docs/superpowers/specs/2026-04-10-sub-project-a-design.md §5.1 for full
references.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.optimization.constants import (
    KM_PER_MILE, LBS_PER_KG, CWT_PER_LB,
    TL_RATE_USD_PER_MILE, LTL_BASE_FEE_USD, LTL_RATE_USD_PER_CWT_MILE,
    GROUND_KM_PER_DAY, CO2_G_PER_TON_MILE,
)

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


def transit_days(distance_km: float) -> int:
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


def ml_lead_time_days(
    distance_km: float,
    distributor_tier: str,
    component_category: str,
    is_domestic: bool,
    risk_score: float,
    stock_coverage: float,
    is_chinese_origin: bool,
) -> float:
    """
    ML-powered lead time prediction.

    Uses the best-performing lead time model (Ridge/RF/GBM/MLP) loaded at
    startup. Falls back to the deterministic formula if models are not loaded.

    The ML model accounts for:
    - Component category (Sourceability baseline — MCUs 14wk, passives 3wk)
    - Current macro stress probability from FRED regime model
    - Distributor tier, domestic flag, distance
    - Component risk score and stock coverage ratio

    Returns lead time in fractional days (same unit as leg_lead_time_days).
    """
    try:
        from app.ml import get_ml_state
        from app.ml.lead_time_model import build_feature_row, predict_lead_time
        state = get_ml_state()
        if state is not None and state.lead_time_models and state.feature_columns:
            best = state.best_lead_time_model
            model = state.lead_time_models[best]["model"]
            row = build_feature_row(
                category=component_category,
                is_domestic=is_domestic,
                dist_km=distance_km,
                tier=distributor_tier,
                macro_stress=state.current_stress_prob,
                risk_score=risk_score,
                stock_coverage=stock_coverage,
                is_chinese_origin=is_chinese_origin,
            )
            return predict_lead_time(model, row, state.feature_columns)
    except Exception:
        pass  # fall through to deterministic formula
    # Deterministic fallback
    return leg_lead_time_days(distance_km, distributor_tier)


@dataclass(frozen=True)
class CostBreakdown:
    """Structured cost breakdown for a single strategy on a route."""
    component_cost: float
    transport_cost: float
    holding_cost: float

    @property
    def total(self) -> float:
        return self.component_cost + self.transport_cost + self.holding_cost
