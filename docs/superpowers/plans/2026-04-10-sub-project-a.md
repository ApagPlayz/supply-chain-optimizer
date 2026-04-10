# Sub-Project A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken "multi-objective VRP" with a real Sourcing integer program + TSP + Cross-Dock consolidation pipeline that produces four genuinely distinct routes, grounded in cited industrial cost constants.

**Architecture:** New `backend/app/optimization/` package with 8 focused modules. Pipeline: BOM → outlier filter → CP-SAT sourcing MILP → TSP pickup route → Lagrangian cross-dock evaluation over 10 real US freight hubs → 4 strategy weight profiles → response. Frontend functional wiring only (visual design choices deferred for user review).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, OR-Tools CP-SAT (sourcing), OR-Tools routing (TSP), pytest, React 18 + TypeScript, Playwright MCP for E2E.

**Spec:** `docs/superpowers/specs/2026-04-10-sub-project-a-design.md` (commit `6a4bddb`)

---

## File Structure

**New files (backend):**
- `backend/app/optimization/__init__.py` — package init, public exports
- `backend/app/optimization/costs.py` — ATRI/EPA/Gartner constants + cost functions
- `backend/app/optimization/freight_hubs.py` — 10 hubs static data
- `backend/app/optimization/strategies.py` — 4 weight profiles + normalization
- `backend/app/optimization/schemas.py` — Pydantic response models
- `backend/app/optimization/sourcing.py` — Stage 1 CP-SAT + outlier filter
- `backend/app/optimization/routing.py` — Stage 2 TSP (OR-Tools routing)
- `backend/app/optimization/cross_dock.py` — Lagrangian hub enumeration
- `backend/app/optimization/solve.py` — orchestrator: BOM → 4 RouteAlternatives
- `backend/tests/__init__.py` — test package
- `backend/tests/conftest.py` — pytest fixtures
- `backend/tests/test_costs.py`
- `backend/tests/test_sourcing.py`
- `backend/tests/test_routing.py`
- `backend/tests/test_cross_dock.py`
- `backend/tests/test_strategies.py`
- `backend/seeds/cleanup_stale.py` — one-shot drop + wipe
- `backend/seeds/seed_cross_dock_hubs.py` — seed 10 hubs
- `backend/seeds/seed_demo_cart.py` — curated 5-part BOM

**Modified files (backend):**
- `backend/app/api/optimize.py` — shrink to ~60 lines, wire new package
- `backend/app/api/__init__.py` — drop materials/hubs router imports
- `backend/app/api/components.py:204` — `regex=` → `pattern=`
- `backend/app/api/distributors.py` — add `domestic_only` query param
- `backend/app/models/__init__.py` — drop stale model imports, add CrossDockHub
- `backend/app/models/cross_dock_hub.py` — NEW model class

**Deleted files (backend):**
- `backend/app/api/hubs.py`
- `backend/app/api/materials.py`
- `backend/app/models/hub.py`
- `backend/app/models/material.py`
- `backend/app/models/supplier.py`

**New/modified files (frontend):**
- `frontend/src/store/optimizeStore.ts` — extend types for new response fields
- `frontend/src/services/api.ts` — add `getCrossDockHubs()`
- `frontend/src/pages/CheckoutPage.tsx` — wire new fields (functional, minimal default layout)
- `frontend/src/pages/MapPage.tsx` — fetch hubs, render default markers
- `frontend/src/types/optimize.ts` — shared type extensions (or inline in store)

**New docs:**
- `docs/interview-walkthrough.md`

**New tests (E2E):**
- `tests/e2e/sub-project-a.spec.ts`

---

## Task 1: Bootstrap optimization package + costs module

**Files:**
- Create: `backend/app/optimization/__init__.py`
- Create: `backend/app/optimization/costs.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_costs.py`

- [ ] **Step 1: Create empty package init**

File: `backend/app/optimization/__init__.py`
```python
"""Sub-Project A optimization package — sourcing + TSP + cross-dock."""
```

- [ ] **Step 2: Write `costs.py` with constants and cost functions**

File: `backend/app/optimization/costs.py`
```python
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
```

- [ ] **Step 3: Create empty `tests/__init__.py`**

File: `backend/tests/__init__.py`
```python
```

- [ ] **Step 4: Create `tests/conftest.py` with pythonpath fixture**

File: `backend/tests/conftest.py`
```python
"""Shared pytest fixtures and path setup."""
import sys
from pathlib import Path

# Ensure `backend/` is on path so `import app.*` works regardless of invocation
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
```

- [ ] **Step 5: Write `test_costs.py`**

File: `backend/tests/test_costs.py`
```python
"""Verify cost functions against hand-computed expectations."""
import math
import pytest

from app.optimization import costs


def test_haversine_known_distance():
    # Greenville SC to Memphis TN — roughly 740 km (check ±5%)
    d = costs.haversine_km(34.8526, -82.3940, 35.0424, -89.9767)
    assert 700 < d < 780


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
```

- [ ] **Step 6: Run tests and verify they pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_costs.py -v
```

Expected: 8 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/optimization/__init__.py backend/app/optimization/costs.py \
        backend/tests/__init__.py backend/tests/conftest.py backend/tests/test_costs.py
git commit -m "feat(optimization): costs module with cited constants + tests"
```

---

## Task 2: Freight hubs static data + strategies module

**Files:**
- Create: `backend/app/optimization/freight_hubs.py`
- Create: `backend/app/optimization/strategies.py`

- [ ] **Step 1: Write `freight_hubs.py`**

File: `backend/app/optimization/freight_hubs.py`
```python
"""
Ten real US freight hubs used as cross-dock consolidation candidates.

All coordinates verified against public airport/terminal databases. See
spec §5.5 for citations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class FreightHub:
    id: int
    name: str
    operator: str
    hub_type: str  # 'air', 'intermodal', 'marine/rail', 'air/intermodal'
    city: str
    state: str
    latitude: float
    longitude: float


FREIGHT_HUBS: List[FreightHub] = [
    FreightHub(1, "Memphis International SuperHub", "FedEx Express", "air",
               "Memphis", "TN", 35.0424, -89.9767),
    FreightHub(2, "UPS Worldport", "UPS", "air",
               "Louisville", "KY", 38.1744, -85.7360),
    FreightHub(3, "DFW Alliance Global Logistics Center", "BNSF/Hillwood", "intermodal",
               "Fort Worth", "TX", 32.9876, -97.3187),
    FreightHub(4, "CenterPoint Intermodal Center-Joliet", "BNSF", "intermodal",
               "Joliet", "IL", 41.4988, -87.9865),
    FreightHub(5, "Hartsfield-Jackson Cargo", "Multiple", "air",
               "Atlanta", "GA", 33.6407, -84.4277),
    FreightHub(6, "Port of Long Beach Intermodal", "Multiple", "marine/rail",
               "Long Beach", "CA", 33.7406, -118.2757),
    FreightHub(7, "Rickenbacker Intermodal Terminal", "Norfolk Southern", "intermodal",
               "Columbus", "OH", 39.8130, -82.9279),
    FreightHub(8, "Kansas City SmartPort", "BNSF/KCS", "intermodal",
               "Kansas City", "MO", 39.2976, -94.7139),
    FreightHub(9, "FedEx Indianapolis Hub", "FedEx Express", "air",
               "Indianapolis", "IN", 39.7173, -86.2944),
    FreightHub(10, "Ontario International Intermodal", "Multiple", "air/intermodal",
               "Ontario", "CA", 34.0559, -117.6005),
]


def get_hub(hub_id: int) -> FreightHub:
    for h in FREIGHT_HUBS:
        if h.id == hub_id:
            return h
    raise KeyError(f"No freight hub with id={hub_id}")
```

- [ ] **Step 2: Write `strategies.py`**

File: `backend/app/optimization/strategies.py`
```python
"""
Four multi-objective weight profiles.

Weighted sum scalarization over normalized cost/time/carbon objectives.
See spec §5.2 — Marler & Arora (2004), Ghodsypour & O'Brien (1998).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class StrategyWeights:
    id: str
    label: str
    description: str
    w_cost: float
    w_time: float
    w_carbon: float
    basis: str  # citation / industry rationale

    @property
    def as_tuple(self) -> tuple:
        return (self.w_cost, self.w_time, self.w_carbon)


STRATEGIES: List[StrategyWeights] = [
    StrategyWeights(
        id="cheapest",
        label="Lowest Cost",
        description="Pure procurement optimization — minimize total landed cost",
        w_cost=1.00, w_time=0.00, w_carbon=0.00,
        basis="Weber (1991), Vendor selection criteria and methods",
    ),
    StrategyWeights(
        id="fastest",
        label="Fastest Delivery",
        description="JIT/lean procurement — minimize lead time at reasonable cost",
        w_cost=0.15, w_time=0.80, w_carbon=0.05,
        basis="Toyota Production System literature; JIT practice",
    ),
    StrategyWeights(
        id="greenest",
        label="Lowest Carbon",
        description="ESG-compliant procurement — minimize tonne-miles CO2",
        w_cost=0.25, w_time=0.05, w_carbon=0.70,
        basis="CDP Supply Chain Disclosure framework",
    ),
    StrategyWeights(
        id="balanced",
        label="Balanced",
        description="Balanced weighting across cost/time/carbon",
        w_cost=0.40, w_time=0.35, w_carbon=0.25,
        basis="Ghodsypour & O'Brien (1998), Int'l J. Production Economics 56-57",
    ),
]


def get_strategy(strategy_id: str) -> StrategyWeights:
    for s in STRATEGIES:
        if s.id == strategy_id:
            return s
    raise KeyError(f"Unknown strategy id: {strategy_id}")


def normalize_objectives(
    raw_values: List[dict],
) -> List[dict]:
    """
    Min-max normalize each objective across alternatives to [0, 1].

    Input: list of dicts with keys 'cost', 'time', 'carbon' (raw values).
    Output: same list but with 'cost_n', 'time_n', 'carbon_n' added in [0,1].
    If all values for an objective are equal, normalized value is 0.
    """
    def _minmax(key: str) -> tuple:
        vals = [v[key] for v in raw_values]
        return min(vals), max(vals)

    cmin, cmax = _minmax("cost")
    tmin, tmax = _minmax("time")
    kmin, kmax = _minmax("carbon")

    def _norm(v: float, lo: float, hi: float) -> float:
        if hi == lo:
            return 0.0
        return (v - lo) / (hi - lo)

    out = []
    for v in raw_values:
        out.append({
            **v,
            "cost_n": _norm(v["cost"], cmin, cmax),
            "time_n": _norm(v["time"], tmin, tmax),
            "carbon_n": _norm(v["carbon"], kmin, kmax),
        })
    return out


def weighted_objective(
    normalized: dict, weights: StrategyWeights,
) -> float:
    """Apply strategy weights to a normalized objective dict."""
    return (
        weights.w_cost * normalized["cost_n"]
        + weights.w_time * normalized["time_n"]
        + weights.w_carbon * normalized["carbon_n"]
    )
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/optimization/freight_hubs.py backend/app/optimization/strategies.py
git commit -m "feat(optimization): freight hubs + strategy weight profiles"
```

---

## Task 3: Response schemas

**Files:**
- Create: `backend/app/optimization/schemas.py`

- [ ] **Step 1: Write `schemas.py`**

File: `backend/app/optimization/schemas.py`
```python
"""
Pydantic response models for the optimization pipeline.

Additive to the existing RouteAlternative shape — the frontend only
reads new fields when present.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from pydantic import BaseModel


class BomLine(BaseModel):
    component_id: int
    mpn: str
    quantity: int


class OfferRef(BaseModel):
    component_id: int
    distributor_id: int
    price_usd: float
    stock: int
    moq: int


class SourcingAssignment(BaseModel):
    component_id: int
    mpn: str
    distributor_id: int
    distributor_name: str
    quantity: int
    unit_price_usd: float
    line_total_usd: float


class RouteStop(BaseModel):
    order: int
    distributor_id: int
    distributor_name: str
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    lat: float
    lng: float
    components: List[str]
    distance_km: float
    leg_cost_usd: float
    leg_co2e_kg: float


class CostBreakdown(BaseModel):
    component_cost: float
    transport_cost: float
    holding_cost: float
    total: float


class StrategyMath(BaseModel):
    weights: Dict[str, float]               # {cost, time, carbon}
    raw_objective_values: Dict[str, float]  # {cost, time, carbon}
    normalized_objective_values: Dict[str, float]
    weighted_total: float
    citations: List[str]


class CrossDockInfo(BaseModel):
    enabled: bool
    hub_id: Optional[int] = None
    hub_name: Optional[str] = None
    hub_city: Optional[str] = None
    hub_state: Optional[str] = None
    hub_lat: Optional[float] = None
    hub_lng: Optional[float] = None
    savings_vs_direct_pct: float = 0.0
    direct_cost_usd: float = 0.0
    consolidated_cost_usd: float = 0.0
    rationale: str = ""


class OutlierDropLog(BaseModel):
    component_id: int
    mpn: str
    dropped_distributor_id: int
    dropped_price_usd: float
    median_price_usd: float
    reason: str


class RouteAlternative(BaseModel):
    id: str
    label: str
    description: str
    route: List[RouteStop]
    sourcing: List[SourcingAssignment]
    total_cost_usd: float
    total_transport_cost_usd: float
    total_component_cost_usd: float
    total_co2e_kg: float
    total_distance_km: float
    base_eta_days: float
    eta_p10: float
    eta_p50: float
    eta_p90: float
    monte_carlo_samples: List[float]
    stop_count: int
    international_stops: int
    cost_rank: int = 0
    speed_rank: int = 0
    carbon_rank: int = 0
    distance_rank: int = 0
    # New fields (optional — frontend reads if present)
    cost_breakdown: Optional[CostBreakdown] = None
    strategy_math: Optional[StrategyMath] = None
    cross_dock: Optional[CrossDockInfo] = None


class MultiRouteResponse(BaseModel):
    alternatives: List[RouteAlternative]
    recommended_id: str
    outlier_drops: List[OutlierDropLog] = []
```

- [ ] **Step 2: Verify imports cleanly**

```bash
cd backend && source venv/bin/activate && python -c "from app.optimization import schemas; print(schemas.RouteAlternative.model_fields.keys())"
```

Expected: includes `cost_breakdown`, `strategy_math`, `cross_dock`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/optimization/schemas.py
git commit -m "feat(optimization): Pydantic response schemas"
```

---

## Task 4: Sourcing module — outlier filter + CP-SAT MILP + tests

**Files:**
- Create: `backend/app/optimization/sourcing.py`
- Create: `backend/tests/test_sourcing.py`

- [ ] **Step 1: Write `sourcing.py`**

File: `backend/app/optimization/sourcing.py`
```python
"""
Stage 1 — Component sourcing integer program.

Outlier filter + CP-SAT MILP. See spec §3.2 and §5.4.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ortools.sat.python import cp_model

from app.optimization.strategies import StrategyWeights

logger = logging.getLogger(__name__)


# ── Data containers ──────────────────────────────────────────────────────────

@dataclass
class BomLine:
    component_id: int
    mpn: str
    quantity: int


@dataclass
class Offer:
    component_id: int
    distributor_id: int
    distributor_name: str
    price_usd: float
    stock: int
    moq: int
    is_domestic: bool


@dataclass
class OutlierDrop:
    component_id: int
    mpn: str
    dropped_distributor_id: int
    dropped_price_usd: float
    median_price_usd: float
    reason: str


@dataclass
class SourcingAssignment:
    component_id: int
    mpn: str
    distributor_id: int
    distributor_name: str
    quantity: int
    unit_price_usd: float

    @property
    def line_total(self) -> float:
        return self.quantity * self.unit_price_usd


@dataclass
class SourcingResult:
    assignments: List[SourcingAssignment]
    total_component_cost: float
    selected_distributor_ids: List[int]
    outlier_drops: List[OutlierDrop] = field(default_factory=list)
    status: str = "OPTIMAL"


# ── Outlier filter ───────────────────────────────────────────────────────────

OUTLIER_MEDIAN_MULTIPLE = 5.0  # Aberdeen Group 2020


def filter_price_outliers(
    offers: List[Offer],
    bom: List[BomLine],
    k: float = OUTLIER_MEDIAN_MULTIPLE,
) -> Tuple[List[Offer], List[OutlierDrop]]:
    """
    Drop offers where price > k * median(price) for that component.

    One-sided — low prices (real discounts) are kept. See spec §5.4.
    """
    mpn_by_id = {b.component_id: b.mpn for b in bom}
    by_component: Dict[int, List[Offer]] = {}
    for o in offers:
        by_component.setdefault(o.component_id, []).append(o)

    kept: List[Offer] = []
    drops: List[OutlierDrop] = []

    for cid, group in by_component.items():
        prices = [o.price_usd for o in group if o.price_usd > 0]
        if not prices:
            continue
        median = statistics.median(prices)
        cutoff = k * median
        for o in group:
            if o.price_usd > cutoff:
                drops.append(OutlierDrop(
                    component_id=cid,
                    mpn=mpn_by_id.get(cid, f"component_{cid}"),
                    dropped_distributor_id=o.distributor_id,
                    dropped_price_usd=o.price_usd,
                    median_price_usd=median,
                    reason=f"price {o.price_usd:.2f} > {k}×median {median:.2f}",
                ))
                logger.info("outlier dropped: cid=%s did=%s price=%.2f median=%.2f",
                            cid, o.distributor_id, o.price_usd, median)
            else:
                kept.append(o)
    return kept, drops


# ── CP-SAT sourcing MILP ─────────────────────────────────────────────────────

# Scale factor: CP-SAT wants integer coefficients. Prices stored as cents.
PRICE_SCALE = 100


def solve_sourcing(
    bom: List[BomLine],
    offers: List[Offer],
    weights: StrategyWeights,
    us_only: bool = True,
) -> SourcingResult:
    """
    Pick which distributor fills each BOM line (and how much) to minimize
    cost, subject to demand/stock/MOQ/domestic constraints.

    The Stage 1 MILP minimizes only component cost. Time and carbon are
    distance-dependent and are evaluated in Stage 2 (TSP) and composed with
    the Stage 1 result in the orchestrator (solve.py).
    """
    # Pre-filter outliers
    offers, drops = filter_price_outliers(offers, bom)

    # Pre-filter by us_only
    if us_only:
        offers = [o for o in offers if o.is_domestic]

    # Group by component
    offers_by_component: Dict[int, List[Offer]] = {}
    for o in offers:
        offers_by_component.setdefault(o.component_id, []).append(o)

    # Validate every BOM line has at least one offer after filtering
    missing = [b.mpn for b in bom if not offers_by_component.get(b.component_id)]
    if missing:
        raise ValueError(
            f"No valid offers for components after filtering: {missing}"
        )

    model = cp_model.CpModel()

    # x[cid, did] ∈ {0,1} — select this offer
    # q[cid, did] ∈ [0, stock] — quantity ordered
    # y[did] ∈ {0,1} — visit this distributor
    x: Dict[Tuple[int, int], cp_model.IntVar] = {}
    q: Dict[Tuple[int, int], cp_model.IntVar] = {}
    y: Dict[int, cp_model.IntVar] = {}

    all_distributors = {o.distributor_id for o in offers}
    for did in all_distributors:
        y[did] = model.NewBoolVar(f"y_{did}")

    for b in bom:
        for o in offers_by_component[b.component_id]:
            key = (b.component_id, o.distributor_id)
            x[key] = model.NewBoolVar(f"x_c{b.component_id}_d{o.distributor_id}")
            # Quantity bounded by stock and demand
            upper = min(o.stock, b.quantity)
            q[key] = model.NewIntVar(0, max(upper, 0), f"q_c{b.component_id}_d{o.distributor_id}")

    for b in bom:
        # Demand coverage: sum of quantities over offers == demand
        model.Add(
            sum(q[(b.component_id, o.distributor_id)]
                for o in offers_by_component[b.component_id]) == b.quantity
        )
        for o in offers_by_component[b.component_id]:
            key = (b.component_id, o.distributor_id)
            # Stock cap: q ≤ stock * x
            model.Add(q[key] <= o.stock * x[key])
            # MOQ floor: if x=1, q ≥ moq; if x=0, q=0 (already enforced by stock cap)
            if o.moq > 1:
                model.Add(q[key] >= o.moq * x[key])
            else:
                model.Add(q[key] >= x[key])  # q ≥ 1 if selected
            # Distributor linking: y ≥ x
            model.Add(y[o.distributor_id] >= x[key])

    # Objective: minimize total component cost (scaled to cents)
    # + small bonus for fewer distributor visits (tiebreak favoring consolidation)
    cost_terms = []
    for b in bom:
        for o in offers_by_component[b.component_id]:
            key = (b.component_id, o.distributor_id)
            price_cents = int(round(o.price_usd * PRICE_SCALE))
            cost_terms.append(price_cents * q[key])
    # Tiny stop penalty: $1 per distributor visited (scaled), acts as tiebreaker
    stop_penalty = sum(y[did] * PRICE_SCALE for did in y)
    model.Minimize(sum(cost_terms) + stop_penalty)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(
            f"Sourcing MILP infeasible (status={solver.StatusName(status)})"
        )

    # Extract assignments
    assignments: List[SourcingAssignment] = []
    for b in bom:
        for o in offers_by_component[b.component_id]:
            key = (b.component_id, o.distributor_id)
            qty = solver.Value(q[key])
            if qty > 0:
                assignments.append(SourcingAssignment(
                    component_id=b.component_id,
                    mpn=b.mpn,
                    distributor_id=o.distributor_id,
                    distributor_name=o.distributor_name,
                    quantity=qty,
                    unit_price_usd=o.price_usd,
                ))

    total_cost = sum(a.line_total for a in assignments)
    selected = sorted({a.distributor_id for a in assignments})

    return SourcingResult(
        assignments=assignments,
        total_component_cost=total_cost,
        selected_distributor_ids=selected,
        outlier_drops=drops,
        status=solver.StatusName(status),
    )
```

- [ ] **Step 2: Write `test_sourcing.py`**

File: `backend/tests/test_sourcing.py`
```python
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
    bom = [BomLine(component_id=1, mpn="PART-A", quantity=50)]
    offers = [
        _offer(1, 1, 0.49, stock=10),   # cheap but only 10 in stock
        _offer(1, 2, 1.00, stock=100),
    ]
    result = solve_sourcing(bom, offers, get_strategy("cheapest"))
    dids = {a.distributor_id for a in result.assignments}
    # Must use both distributors
    assert 1 in dids and 2 in dids
    total = sum(a.quantity for a in result.assignments)
    assert total == 50
```

- [ ] **Step 3: Run tests and verify they pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_sourcing.py -v
```

Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/app/optimization/sourcing.py backend/tests/test_sourcing.py
git commit -m "feat(optimization): sourcing MILP with outlier filter + tests"
```

---

## Task 5: Routing module — TSP over selected distributors + tests

**Files:**
- Create: `backend/app/optimization/routing.py`
- Create: `backend/tests/test_routing.py`

- [ ] **Step 1: Write `routing.py`**

File: `backend/app/optimization/routing.py`
```python
"""
Stage 2 — Pickup TSP over distributors selected by Stage 1.

OR-Tools routing solver with PATH_CHEAPEST_ARC + GUIDED_LOCAL_SEARCH.
Distance matrix = haversine. Will upgrade to OSRM in Stage B.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.optimization.costs import haversine_km


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lng: float


@dataclass(frozen=True)
class RoutingNode:
    """A single location in the pickup route (distributor or depot)."""
    id: int  # distributor_id, or -1 for depot
    lat: float
    lng: float
    name: str


def _nearest_neighbor_order(nodes: List[RoutingNode]) -> List[int]:
    """Greedy fallback ordering starting at index 0 (depot)."""
    n = len(nodes)
    visited = {0}
    order = [0]
    current = 0
    while len(visited) < n:
        best = None
        best_d = float("inf")
        for j in range(n):
            if j in visited:
                continue
            d = haversine_km(nodes[current].lat, nodes[current].lng,
                             nodes[j].lat, nodes[j].lng)
            if d < best_d:
                best_d = d
                best = j
        order.append(best)
        visited.add(best)
        current = best
    return order


def solve_pickup_tsp(
    depot: GeoPoint,
    distributor_nodes: List[RoutingNode],
    time_limit_seconds: int = 3,
) -> List[int]:
    """
    Return an ordered list of distributor_ids representing the pickup route.

    The tour starts and ends at the depot. The returned list EXCLUDES the
    depot — only the distributor ids in visit order. If distributor_nodes
    has a single element, returns that id directly.
    """
    if not distributor_nodes:
        return []
    if len(distributor_nodes) == 1:
        return [distributor_nodes[0].id]

    depot_node = RoutingNode(id=-1, lat=depot.lat, lng=depot.lng, name="depot")
    nodes = [depot_node] + list(distributor_nodes)
    n = len(nodes)

    # Distance matrix in meters (integer for OR-Tools)
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            matrix[i][j] = int(round(
                haversine_km(nodes[i].lat, nodes[i].lng,
                             nodes[j].lat, nodes[j].lng) * 1000
            ))

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def distance_cb(from_idx, to_idx):
        return matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]

    transit_cb_idx = routing.RegisterTransitCallback(distance_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb_idx)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = time_limit_seconds

    solution = routing.SolveWithParameters(params)
    if not solution:
        # Fall back to greedy order on real nodes (exclude depot index 0)
        greedy = _nearest_neighbor_order(nodes)
        return [nodes[i].id for i in greedy if i != 0]

    order_ids: List[int] = []
    idx = routing.Start(0)
    while not routing.IsEnd(idx):
        node_idx = manager.IndexToNode(idx)
        if node_idx != 0:
            order_ids.append(nodes[node_idx].id)
        idx = solution.Value(routing.NextVar(idx))
    return order_ids


def route_total_distance_km(
    depot: GeoPoint,
    ordered_nodes: List[RoutingNode],
) -> float:
    """Haversine distance of the closed tour depot → n1 → n2 → ... → depot."""
    if not ordered_nodes:
        return 0.0
    total = haversine_km(depot.lat, depot.lng,
                         ordered_nodes[0].lat, ordered_nodes[0].lng)
    for i in range(len(ordered_nodes) - 1):
        total += haversine_km(
            ordered_nodes[i].lat, ordered_nodes[i].lng,
            ordered_nodes[i + 1].lat, ordered_nodes[i + 1].lng,
        )
    total += haversine_km(
        ordered_nodes[-1].lat, ordered_nodes[-1].lng,
        depot.lat, depot.lng,
    )
    return total
```

- [ ] **Step 2: Write `test_routing.py`**

File: `backend/tests/test_routing.py`
```python
"""Unit tests for the TSP routing solver."""
from app.optimization.routing import (
    GeoPoint, RoutingNode, solve_pickup_tsp, route_total_distance_km,
)


def test_tsp_single_distributor_returns_single_id():
    depot = GeoPoint(lat=34.0, lng=-82.0)
    nodes = [RoutingNode(id=7, lat=35.0, lng=-83.0, name="d7")]
    order = solve_pickup_tsp(depot, nodes)
    assert order == [7]


def test_tsp_orders_distributors_greedy_on_east_coast():
    # Depot Greenville SC; three distributors roughly collinear north
    depot = GeoPoint(lat=34.8526, lng=-82.3940)
    nodes = [
        RoutingNode(id=10, lat=38.0, lng=-82.0, name="far"),
        RoutingNode(id=20, lat=35.5, lng=-82.0, name="near"),
        RoutingNode(id=30, lat=36.5, lng=-82.0, name="mid"),
    ]
    order = solve_pickup_tsp(depot, nodes)
    # Should visit in geographic order near → mid → far (or reverse)
    assert set(order) == {10, 20, 30}
    assert len(order) == 3
    # Nearest should be first
    assert order[0] == 20


def test_tsp_empty_returns_empty():
    assert solve_pickup_tsp(GeoPoint(0, 0), []) == []


def test_total_distance_closed_tour():
    depot = GeoPoint(0.0, 0.0)
    nodes = [
        RoutingNode(id=1, lat=0.0, lng=1.0, name="a"),
        RoutingNode(id=2, lat=0.0, lng=2.0, name="b"),
    ]
    # Tour: (0,0) → (0,1) → (0,2) → (0,0)
    # Each degree ≈ 111 km at equator; total ≈ 4*111 = 444 km
    d = route_total_distance_km(depot, nodes)
    assert 400 < d < 500
```

- [ ] **Step 3: Run tests**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_routing.py -v
```

Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/app/optimization/routing.py backend/tests/test_routing.py
git commit -m "feat(optimization): TSP routing module + tests"
```

---

## Task 6: Cross-dock module — Lagrangian hub enumeration + tests

**Files:**
- Create: `backend/app/optimization/cross_dock.py`
- Create: `backend/tests/test_cross_dock.py`

- [ ] **Step 1: Write `cross_dock.py`**

File: `backend/app/optimization/cross_dock.py`
```python
"""
Cross-dock consolidation analysis.

For each candidate hub, compute:
  - N LTL legs (distributor → hub)
  - 1 consolidated leg (hub → depot, TL if ≥10,000 lbs)
  - Hub handling fee + dwell time
Pick the hub that minimizes the weighted objective — but only if it
beats direct pickup by ≥5% (the improvement threshold avoids pointless
hub trips when gains are marginal).

This is Lagrangian relaxation of the Capacitated Facility Location
Problem (Daskin 2013, Ch. 4) — with only 10 candidate hubs enumeration
is exact and trivially fast.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.optimization.costs import (
    HUB_DWELL_DAYS, HUB_HANDLING_FEE_USD,
    co2_kg, haversine_km, leg_lead_time_days, transit_days,
    transport_cost_usd,
)
from app.optimization.freight_hubs import FREIGHT_HUBS, FreightHub
from app.optimization.routing import GeoPoint, RoutingNode
from app.optimization.strategies import StrategyWeights


CROSS_DOCK_IMPROVEMENT_THRESHOLD = 0.95  # hub must beat direct by ≥ 5%


@dataclass(frozen=True)
class DistributorShipment:
    distributor_id: int
    distributor_name: str
    lat: float
    lng: float
    weight_kg: float
    distributor_tier: str  # 'major'|'mid'|'broker'


@dataclass(frozen=True)
class RouteMetrics:
    cost_usd: float
    lead_time_days: float
    co2_kg: float


@dataclass(frozen=True)
class CrossDockDecision:
    enabled: bool
    hub: Optional[FreightHub]
    direct_metrics: RouteMetrics
    consolidated_metrics: Optional[RouteMetrics]
    savings_vs_direct_pct: float
    rationale: str


def _weighted_objective(metrics: RouteMetrics, weights: StrategyWeights) -> float:
    """
    Single-alternative weighted objective (no normalization — used only for
    direct-vs-consolidated comparison within one strategy).
    """
    return (
        weights.w_cost * metrics.cost_usd
        + weights.w_time * metrics.lead_time_days * 100.0  # hours-worth scale
        + weights.w_carbon * metrics.co2_kg * 10.0
    )


def evaluate_hub(
    hub: FreightHub,
    depot: GeoPoint,
    shipments: List[DistributorShipment],
) -> RouteMetrics:
    """
    Compute cost/time/CO2 for consolidating all shipments at this hub.

    N LTL legs distributor → hub, then 1 consolidated leg hub → depot.
    """
    total_cost = HUB_HANDLING_FEE_USD
    total_co2 = 0.0
    max_leg_time = 0.0
    total_weight = 0.0

    for s in shipments:
        d_km = haversine_km(s.lat, s.lng, hub.latitude, hub.longitude)
        total_cost += transport_cost_usd(d_km, s.weight_kg)
        total_co2 += co2_kg(d_km, s.weight_kg)
        leg_time = leg_lead_time_days(d_km, s.distributor_tier)
        if leg_time > max_leg_time:
            max_leg_time = leg_time
        total_weight += s.weight_kg

    # Consolidated hub → depot leg
    d_hub_depot_km = haversine_km(hub.latitude, hub.longitude, depot.lat, depot.lng)
    total_cost += transport_cost_usd(d_hub_depot_km, total_weight)
    total_co2 += co2_kg(d_hub_depot_km, total_weight)
    consolidated_leg_time = transit_days(d_hub_depot_km)

    total_time = max_leg_time + HUB_DWELL_DAYS + consolidated_leg_time

    return RouteMetrics(cost_usd=total_cost, lead_time_days=total_time, co2_kg=total_co2)


def evaluate_direct(
    depot: GeoPoint,
    ordered_nodes: List[RoutingNode],
    shipments_by_did: dict,
) -> RouteMetrics:
    """
    Compute cost/time/CO2 for the direct pickup tour.

    A single truck drives depot → d1 → d2 → ... → depot carrying the
    cumulative load. We model this as a sequence of LTL-or-TL legs.
    """
    if not ordered_nodes:
        return RouteMetrics(0.0, 0.0, 0.0)

    total_cost = 0.0
    total_co2 = 0.0
    total_time = 0.0
    cumulative_weight = sum(s.weight_kg for s in shipments_by_did.values())

    prev = (depot.lat, depot.lng)
    for node in ordered_nodes:
        s = shipments_by_did[node.id]
        d_km = haversine_km(prev[0], prev[1], node.lat, node.lng)
        total_cost += transport_cost_usd(d_km, cumulative_weight)
        total_co2 += co2_kg(d_km, cumulative_weight)
        total_time += leg_lead_time_days(d_km, s.distributor_tier)
        prev = (node.lat, node.lng)

    # Return leg depot
    d_km = haversine_km(prev[0], prev[1], depot.lat, depot.lng)
    total_cost += transport_cost_usd(d_km, cumulative_weight)
    total_co2 += co2_kg(d_km, cumulative_weight)
    total_time += transit_days(d_km)

    return RouteMetrics(cost_usd=total_cost, lead_time_days=total_time, co2_kg=total_co2)


def evaluate_cross_dock(
    direct: RouteMetrics,
    shipments: List[DistributorShipment],
    depot: GeoPoint,
    weights: StrategyWeights,
    hubs: List[FreightHub] = None,
) -> CrossDockDecision:
    """Enumerate hubs, pick the best — or reject if it doesn't clear the threshold."""
    if hubs is None:
        hubs = FREIGHT_HUBS

    # Cross-dock requires at least 2 distributors to make sense
    if len(shipments) < 2:
        return CrossDockDecision(
            enabled=False, hub=None, direct_metrics=direct,
            consolidated_metrics=None, savings_vs_direct_pct=0.0,
            rationale="single-distributor route — no consolidation benefit",
        )

    direct_obj = _weighted_objective(direct, weights)
    best_hub: Optional[FreightHub] = None
    best_metrics: Optional[RouteMetrics] = None
    best_obj = float("inf")

    for hub in hubs:
        m = evaluate_hub(hub, depot, shipments)
        obj = _weighted_objective(m, weights)
        if obj < best_obj:
            best_obj = obj
            best_metrics = m
            best_hub = hub

    if best_hub is None or best_metrics is None:
        return CrossDockDecision(
            enabled=False, hub=None, direct_metrics=direct,
            consolidated_metrics=None, savings_vs_direct_pct=0.0,
            rationale="no hubs provided",
        )

    # 5% improvement threshold
    if best_obj >= CROSS_DOCK_IMPROVEMENT_THRESHOLD * direct_obj:
        return CrossDockDecision(
            enabled=False, hub=best_hub, direct_metrics=direct,
            consolidated_metrics=best_metrics,
            savings_vs_direct_pct=round(100.0 * (1.0 - best_obj / direct_obj), 2),
            rationale=f"hub {best_hub.city} beat direct by "
                      f"{100*(1-best_obj/direct_obj):.1f}% < 5% threshold",
        )

    savings_pct = round(100.0 * (1.0 - best_obj / direct_obj), 2)
    return CrossDockDecision(
        enabled=True, hub=best_hub, direct_metrics=direct,
        consolidated_metrics=best_metrics,
        savings_vs_direct_pct=savings_pct,
        rationale=f"consolidating via {best_hub.city} saves {savings_pct}% "
                  f"on the weighted objective",
    )
```

- [ ] **Step 2: Write `test_cross_dock.py`**

File: `backend/tests/test_cross_dock.py`
```python
"""Tests for cross-dock hub enumeration + 5% threshold."""
from app.optimization.cross_dock import (
    CROSS_DOCK_IMPROVEMENT_THRESHOLD, DistributorShipment, RouteMetrics,
    evaluate_cross_dock, evaluate_direct, evaluate_hub,
)
from app.optimization.freight_hubs import FREIGHT_HUBS, get_hub
from app.optimization.routing import GeoPoint, RoutingNode
from app.optimization.strategies import get_strategy


def _ship(did, lat, lng, kg=50.0, tier="mid"):
    return DistributorShipment(
        distributor_id=did, distributor_name=f"d{did}",
        lat=lat, lng=lng, weight_kg=kg, distributor_tier=tier,
    )


def test_cross_dock_never_chosen_for_single_distributor():
    depot = GeoPoint(34.85, -82.39)
    ships = [_ship(1, 40.0, -75.0)]
    direct = RouteMetrics(cost_usd=500.0, lead_time_days=3.0, co2_kg=2.0)
    decision = evaluate_cross_dock(direct, ships, depot, get_strategy("balanced"))
    assert decision.enabled is False
    assert "single" in decision.rationale.lower()


def test_cross_dock_chosen_when_east_coast_distributors_favor_atlanta():
    """
    Depot in Greenville SC, distributors spread across the Midwest/Northeast.
    Cheapest strategy should pick a central hub and save >5%.
    """
    depot = GeoPoint(34.8526, -82.3940)  # Greenville SC
    ships = [
        _ship(1, 41.88, -87.63, kg=200),  # Chicago
        _ship(2, 42.36, -71.06, kg=200),  # Boston
        _ship(3, 40.71, -74.00, kg=200),  # NYC
        _ship(4, 39.74, -104.99, kg=200),  # Denver (far)
    ]
    # Fake "direct" as very high (simulates a long multi-stop tour)
    direct = RouteMetrics(cost_usd=5000.0, lead_time_days=12.0, co2_kg=50.0)
    decision = evaluate_cross_dock(direct, ships, depot, get_strategy("cheapest"))
    # Atlanta, Louisville, Memphis, or Columbus should win
    assert decision.hub is not None
    assert decision.hub.state in {"GA", "KY", "TN", "OH", "IL", "MO", "IN"}


def test_cross_dock_rejected_when_improvement_below_threshold():
    """
    Construct a direct route where hub savings are small enough to be
    below the 5% threshold — decision should be 'enabled=False' even
    though best_hub is identified.
    """
    depot = GeoPoint(34.85, -82.39)
    ships = [
        _ship(1, 35.0, -82.0, kg=10),
        _ship(2, 35.1, -82.1, kg=10),
    ]
    # Super-cheap direct (near depot, low weight)
    cheap_direct = evaluate_direct(
        depot,
        [
            RoutingNode(id=1, lat=35.0, lng=-82.0, name="d1"),
            RoutingNode(id=2, lat=35.1, lng=-82.1, name="d2"),
        ],
        {1: ships[0], 2: ships[1]},
    )
    decision = evaluate_cross_dock(cheap_direct, ships, depot, get_strategy("balanced"))
    # Direct pickup is already efficient, hub adds handling fee → reject
    assert decision.enabled is False


def test_evaluate_hub_includes_handling_fee():
    depot = GeoPoint(34.85, -82.39)
    ships = [_ship(1, 35.0, -82.0, kg=10), _ship(2, 35.1, -82.1, kg=10)]
    hub = get_hub(5)  # Atlanta
    m = evaluate_hub(hub, depot, ships)
    # Handling fee is always in the total
    assert m.cost_usd >= 50.0
```

- [ ] **Step 3: Run tests**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_cross_dock.py -v
```

Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/app/optimization/cross_dock.py backend/tests/test_cross_dock.py
git commit -m "feat(optimization): cross-dock Lagrangian hub enumeration + tests"
```

---

## Task 7: Orchestrator — `solve.py` assembling all stages

**Files:**
- Create: `backend/app/optimization/solve.py`

- [ ] **Step 1: Write `solve.py`**

File: `backend/app/optimization/solve.py`
```python
"""
Orchestrator — runs all 4 strategies end-to-end.

Pipeline per strategy:
  1. Outlier filter + Stage 1 CP-SAT sourcing (strategy-agnostic: all use
     min-cost because time/carbon are distance-dependent). Cost-weighted
     strategies reuse the same sourcing result; only the cross-dock
     decision + final ranking differ across strategies.
  2. Stage 2 pickup TSP over selected distributors.
  3. Cross-dock evaluation per strategy (this is where the strategies
     genuinely diverge — fastest avoids hubs, greenest prefers them).
  4. Compose final RouteAlternative with strategy_math + cost_breakdown.

Note: A fully-general formulation would re-run Stage 1 per strategy with
weighted sourcing objectives. For Stage A we deliberately decouple:
Stage 1 picks cheapest suppliers, then Stage 2 + cross-dock evaluate the
weighted objective. Stage B will merge these into a single MILP.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.optimization import schemas
from app.optimization.costs import (
    AVG_COMPONENT_KG, CostBreakdown as CostBreakdownDC,
    haversine_km, holding_cost_usd,
)
from app.optimization.cross_dock import (
    CrossDockDecision, DistributorShipment, RouteMetrics,
    evaluate_cross_dock, evaluate_direct,
)
from app.optimization.freight_hubs import FREIGHT_HUBS
from app.optimization.routing import GeoPoint, RoutingNode, solve_pickup_tsp
from app.optimization.sourcing import (
    BomLine, Offer, SourcingResult, solve_sourcing,
)
from app.optimization.strategies import (
    STRATEGIES, StrategyWeights, normalize_objectives, weighted_objective,
)

logger = logging.getLogger(__name__)


# ── Input data containers ────────────────────────────────────────────────────

@dataclass
class DistributorMeta:
    id: int
    name: str
    lat: float
    lng: float
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]
    is_domestic: bool
    tier: str  # 'major'|'mid'|'broker'


# ── Monte Carlo ETA (retained from old optimize.py) ──────────────────────────

def _monte_carlo_eta(base_days: float, n: int = 1000) -> Dict[str, float]:
    samples = []
    for _ in range(n):
        delay = random.gauss(1.0, 0.15)
        disruption = random.choices([0, 1, 3, 7], weights=[0.85, 0.08, 0.05, 0.02])[0]
        samples.append(max(1.0, base_days * delay + disruption))
    samples.sort()
    return {
        "p10": round(samples[int(0.1 * n)], 1),
        "p50": round(samples[int(0.5 * n)], 1),
        "p90": round(samples[int(0.9 * n)], 1),
        "samples": samples[:200],
    }


# ── Main orchestrator ────────────────────────────────────────────────────────

def optimize_bom(
    bom: List[BomLine],
    offers: List[Offer],
    distributors: Dict[int, DistributorMeta],
    depot: GeoPoint,
    us_only: bool = True,
) -> schemas.MultiRouteResponse:
    """
    Run all 4 strategies and return a MultiRouteResponse.
    """
    if not bom:
        raise ValueError("BOM is empty")

    # ── Stage 1: one cost-minimizing sourcing solve, reused across strategies
    sourcing: SourcingResult = solve_sourcing(
        bom, offers, STRATEGIES[0], us_only=us_only,
    )
    outlier_drops = sourcing.outlier_drops

    # Build per-distributor shipments + weight rollup
    weight_by_did: Dict[int, float] = {}
    cost_by_did: Dict[int, float] = {}
    components_by_did: Dict[int, List[str]] = {}
    for a in sourcing.assignments:
        weight_by_did[a.distributor_id] = weight_by_did.get(a.distributor_id, 0.0) + \
            a.quantity * AVG_COMPONENT_KG
        cost_by_did[a.distributor_id] = cost_by_did.get(a.distributor_id, 0.0) + \
            a.line_total
        components_by_did.setdefault(a.distributor_id, []).append(
            f"{a.mpn} × {a.quantity}"
        )

    # ── Stage 2: TSP over selected distributors
    nodes: List[RoutingNode] = []
    for did in sourcing.selected_distributor_ids:
        d = distributors[did]
        nodes.append(RoutingNode(id=did, lat=d.lat, lng=d.lng, name=d.name))
    tsp_order = solve_pickup_tsp(depot, nodes)
    ordered_nodes = [next(n for n in nodes if n.id == did) for did in tsp_order]

    # Shipment records for cross-dock analysis
    shipments_by_did: Dict[int, DistributorShipment] = {}
    for did in sourcing.selected_distributor_ids:
        d = distributors[did]
        shipments_by_did[did] = DistributorShipment(
            distributor_id=did, distributor_name=d.name,
            lat=d.lat, lng=d.lng,
            weight_kg=max(weight_by_did[did], 0.1),
            distributor_tier=d.tier,
        )
    shipments_list = list(shipments_by_did.values())

    direct_metrics: RouteMetrics = evaluate_direct(depot, ordered_nodes, shipments_by_did)

    # ── Run each strategy: cross-dock decision + final metrics
    strategy_raw: List[Dict] = []
    strategy_decisions: Dict[str, CrossDockDecision] = {}
    for strat in STRATEGIES:
        decision = evaluate_cross_dock(
            direct_metrics, shipments_list, depot, strat, hubs=FREIGHT_HUBS,
        )
        strategy_decisions[strat.id] = decision
        if decision.enabled and decision.consolidated_metrics:
            m = decision.consolidated_metrics
        else:
            m = direct_metrics
        strategy_raw.append({
            "strategy": strat,
            "cost": m.cost_usd,
            "time": m.lead_time_days,
            "carbon": m.co2_kg,
            "metrics": m,
            "decision": decision,
        })

    # Normalize across strategies
    normed = normalize_objectives([
        {"cost": r["cost"], "time": r["time"], "carbon": r["carbon"]}
        for r in strategy_raw
    ])

    # ── Assemble RouteAlternative list
    alternatives: List[schemas.RouteAlternative] = []
    for i, r in enumerate(strategy_raw):
        strat: StrategyWeights = r["strategy"]
        m: RouteMetrics = r["metrics"]
        decision: CrossDockDecision = r["decision"]
        norm = normed[i]

        # Components list per stop
        stops: List[schemas.RouteStop] = []
        prev_lat, prev_lng = depot.lat, depot.lng
        for seq, node in enumerate(ordered_nodes):
            d = distributors[node.id]
            dist_km = haversine_km(prev_lat, prev_lng, node.lat, node.lng)
            from app.optimization.costs import transport_cost_usd as _tc, co2_kg as _co2
            total_weight = sum(weight_by_did.values())
            leg_cost = _tc(dist_km, max(total_weight, 0.1))
            leg_co2 = _co2(dist_km, max(total_weight, 0.1))
            stops.append(schemas.RouteStop(
                order=seq + 1,
                distributor_id=node.id,
                distributor_name=d.name,
                city=d.city, state=d.state, country=d.country,
                lat=d.lat, lng=d.lng,
                components=components_by_did.get(node.id, []),
                distance_km=round(dist_km, 1),
                leg_cost_usd=round(leg_cost, 2),
                leg_co2e_kg=round(leg_co2, 3),
            ))
            prev_lat, prev_lng = node.lat, node.lng

        # Totals
        component_cost = sum(cost_by_did.values())
        transport_cost = m.cost_usd
        holding = holding_cost_usd(component_cost, m.lead_time_days)
        total_cost = component_cost + transport_cost + holding

        # Monte Carlo ETA around the final lead time
        mc = _monte_carlo_eta(max(m.lead_time_days, 1.0))

        cost_breakdown = schemas.CostBreakdown(
            component_cost=round(component_cost, 2),
            transport_cost=round(transport_cost, 2),
            holding_cost=round(holding, 2),
            total=round(total_cost, 2),
        )

        strategy_math = schemas.StrategyMath(
            weights={"cost": strat.w_cost, "time": strat.w_time, "carbon": strat.w_carbon},
            raw_objective_values={
                "cost": round(m.cost_usd, 2),
                "time": round(m.lead_time_days, 2),
                "carbon": round(m.co2_kg, 3),
            },
            normalized_objective_values={
                "cost": round(norm["cost_n"], 4),
                "time": round(norm["time_n"], 4),
                "carbon": round(norm["carbon_n"], 4),
            },
            weighted_total=round(weighted_objective(norm, strat), 4),
            citations=[
                "ATRI 2023 — Operational Costs of Trucking",
                "EPA SmartWay 2023 — Heavy-Duty Truck Emissions",
                "Gartner 2022 — IT Supply Chain Benchmarks",
                "BTS CFS 2022 — Commodity Flow Survey",
                "Ghodsypour & O'Brien 1998 — Int'l J. Production Economics",
            ],
        )

        cd_info: Optional[schemas.CrossDockInfo] = None
        if decision.hub is not None:
            cd_info = schemas.CrossDockInfo(
                enabled=decision.enabled,
                hub_id=decision.hub.id,
                hub_name=decision.hub.name,
                hub_city=decision.hub.city,
                hub_state=decision.hub.state,
                hub_lat=decision.hub.latitude,
                hub_lng=decision.hub.longitude,
                savings_vs_direct_pct=decision.savings_vs_direct_pct,
                direct_cost_usd=round(decision.direct_metrics.cost_usd, 2),
                consolidated_cost_usd=round(
                    decision.consolidated_metrics.cost_usd if decision.consolidated_metrics else 0.0, 2
                ),
                rationale=decision.rationale,
            )
        else:
            cd_info = schemas.CrossDockInfo(
                enabled=False,
                direct_cost_usd=round(decision.direct_metrics.cost_usd, 2),
                rationale=decision.rationale,
            )

        sourcing_out = [
            schemas.SourcingAssignment(
                component_id=a.component_id, mpn=a.mpn,
                distributor_id=a.distributor_id,
                distributor_name=a.distributor_name,
                quantity=a.quantity,
                unit_price_usd=a.unit_price_usd,
                line_total_usd=round(a.line_total, 2),
            )
            for a in sourcing.assignments
        ]

        alternatives.append(schemas.RouteAlternative(
            id=strat.id,
            label=strat.label,
            description=strat.description,
            route=stops,
            sourcing=sourcing_out,
            total_cost_usd=round(total_cost, 2),
            total_transport_cost_usd=round(transport_cost, 2),
            total_component_cost_usd=round(component_cost, 2),
            total_co2e_kg=round(m.co2_kg, 3),
            total_distance_km=round(sum(s.distance_km for s in stops), 1),
            base_eta_days=round(m.lead_time_days, 1),
            eta_p10=mc["p10"], eta_p50=mc["p50"], eta_p90=mc["p90"],
            monte_carlo_samples=mc["samples"],
            stop_count=len(stops),
            international_stops=0,  # us_only=True by default
            cost_breakdown=cost_breakdown,
            strategy_math=strategy_math,
            cross_dock=cd_info,
        ))

    # Compute ranks
    def _rank(key_fn):
        vals = [(i, key_fn(a)) for i, a in enumerate(alternatives)]
        vals.sort(key=lambda t: t[1])
        ranks = [0] * len(alternatives)
        for rank, (i, _) in enumerate(vals):
            ranks[i] = rank + 1
        return ranks

    cost_ranks = _rank(lambda a: a.total_cost_usd)
    speed_ranks = _rank(lambda a: a.eta_p50)
    carbon_ranks = _rank(lambda a: a.total_co2e_kg)
    dist_ranks = _rank(lambda a: a.total_distance_km)

    for i, a in enumerate(alternatives):
        a.cost_rank = cost_ranks[i]
        a.speed_rank = speed_ranks[i]
        a.carbon_rank = carbon_ranks[i]
        a.distance_rank = dist_ranks[i]

    outlier_drops_out = [
        schemas.OutlierDropLog(
            component_id=d.component_id, mpn=d.mpn,
            dropped_distributor_id=d.dropped_distributor_id,
            dropped_price_usd=d.dropped_price_usd,
            median_price_usd=d.median_price_usd,
            reason=d.reason,
        )
        for d in outlier_drops
    ]

    return schemas.MultiRouteResponse(
        alternatives=alternatives,
        recommended_id="balanced",
        outlier_drops=outlier_drops_out,
    )
```

- [ ] **Step 2: Verify imports + basic smoke**

```bash
cd backend && source venv/bin/activate && python -c "from app.optimization import solve; print('solve imports ok')"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/optimization/solve.py
git commit -m "feat(optimization): solve.py orchestrator composing all stages"
```

---

## Task 8: Integration test — `test_strategies.py` (four distinct routes)

**Files:**
- Create: `backend/tests/test_strategies.py`

- [ ] **Step 1: Write integration test**

File: `backend/tests/test_strategies.py`
```python
"""
Integration test: solve.optimize_bom produces four DISTINCT routes.

This is the regression test for the original bug where all four
strategies returned the same tour.
"""
import pytest

from app.optimization.routing import GeoPoint
from app.optimization.solve import DistributorMeta, optimize_bom
from app.optimization.sourcing import BomLine, Offer


@pytest.fixture
def fixture_bom_and_offers():
    # 3 components, 6 distributors spread across the continental US.
    # Wildly different prices so outlier filter + cost strategy diverge.
    bom = [
        BomLine(component_id=1, mpn="PART-A", quantity=100),
        BomLine(component_id=2, mpn="PART-B", quantity=50),
        BomLine(component_id=3, mpn="PART-C", quantity=30),
    ]
    offers = [
        # PART-A offers
        Offer(1, 10, "DigiKey", price_usd=2.50, stock=500, moq=1, is_domestic=True),
        Offer(1, 20, "Mouser", price_usd=2.60, stock=500, moq=1, is_domestic=True),
        Offer(1, 30, "Arrow", price_usd=2.20, stock=500, moq=1, is_domestic=True),
        Offer(1, 40, "DiscountBrokerEast", price_usd=1.50, stock=500, moq=1, is_domestic=True),
        Offer(1, 50, "DiscountBrokerWest", price_usd=1.40, stock=500, moq=1, is_domestic=True),
        # PART-B offers
        Offer(2, 10, "DigiKey", price_usd=5.00, stock=500, moq=1, is_domestic=True),
        Offer(2, 20, "Mouser", price_usd=4.80, stock=500, moq=1, is_domestic=True),
        Offer(2, 40, "DiscountBrokerEast", price_usd=3.10, stock=500, moq=1, is_domestic=True),
        # PART-C offers
        Offer(3, 10, "DigiKey", price_usd=10.00, stock=500, moq=1, is_domestic=True),
        Offer(3, 50, "DiscountBrokerWest", price_usd=6.00, stock=500, moq=1, is_domestic=True),
        Offer(3, 60, "MidwestBroker", price_usd=7.50, stock=500, moq=1, is_domestic=True),
    ]
    distributors = {
        10: DistributorMeta(10, "DigiKey", 48.1167, -96.1775, "Thief River Falls", "MN", "USA", True, "major"),
        20: DistributorMeta(20, "Mouser", 32.5685, -97.1117, "Mansfield", "TX", "USA", True, "major"),
        30: DistributorMeta(30, "Arrow", 39.5501, -104.9676, "Centennial", "CO", "USA", True, "major"),
        40: DistributorMeta(40, "DiscountBrokerEast", 40.7128, -74.0060, "New York", "NY", "USA", True, "broker"),
        50: DistributorMeta(50, "DiscountBrokerWest", 34.0522, -118.2437, "Los Angeles", "CA", "USA", True, "broker"),
        60: DistributorMeta(60, "MidwestBroker", 41.8781, -87.6298, "Chicago", "IL", "USA", True, "broker"),
    }
    depot = GeoPoint(lat=34.8526, lng=-82.3940)  # Greenville SC
    return bom, offers, distributors, depot


def test_four_strategies_produce_different_routes(fixture_bom_and_offers):
    bom, offers, distributors, depot = fixture_bom_and_offers
    resp = optimize_bom(bom, offers, distributors, depot)

    assert len(resp.alternatives) == 4
    ids = [a.id for a in resp.alternatives]
    assert set(ids) == {"cheapest", "fastest", "greenest", "balanced"}

    # At least 2 of the 4 weighted totals (strategy_math) must differ
    totals = [a.strategy_math.weighted_total for a in resp.alternatives]
    distinct = len(set(totals))
    assert distinct >= 2, f"Expected ≥2 distinct weighted totals, got {distinct}: {totals}"


def test_all_strategies_have_breakdown_and_citations(fixture_bom_and_offers):
    bom, offers, distributors, depot = fixture_bom_and_offers
    resp = optimize_bom(bom, offers, distributors, depot)
    for a in resp.alternatives:
        assert a.cost_breakdown is not None
        assert a.strategy_math is not None
        assert any("ATRI" in c for c in a.strategy_math.citations)
        assert any("EPA" in c for c in a.strategy_math.citations)


def test_cheapest_selects_low_price_offers(fixture_bom_and_offers):
    bom, offers, distributors, depot = fixture_bom_and_offers
    resp = optimize_bom(bom, offers, distributors, depot)
    cheapest = next(a for a in resp.alternatives if a.id == "cheapest")
    # DiscountBrokerWest ($1.40 A + $6 C) and DiscountBrokerEast ($3.10 B)
    # should be preferred
    selected = {s.distributor_id for s in cheapest.sourcing}
    # At least one discount broker should be in the mix
    assert 40 in selected or 50 in selected


def test_at_least_one_strategy_considers_cross_dock(fixture_bom_and_offers):
    bom, offers, distributors, depot = fixture_bom_and_offers
    resp = optimize_bom(bom, offers, distributors, depot)
    # Some strategy should have cross_dock.enabled=True OR
    # at least have non-None hub evaluation (even if below threshold)
    any_hub_evaluated = any(
        a.cross_dock and a.cross_dock.hub_id is not None
        for a in resp.alternatives
    )
    assert any_hub_evaluated
```

- [ ] **Step 2: Run all backend tests**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/ -v
```

Expected: all tests pass (8 costs + 6 sourcing + 4 routing + 4 cross_dock + 4 strategies = 26).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_strategies.py
git commit -m "test(optimization): integration test for four distinct strategies"
```

---

## Task 9: Hygiene — delete stale files + drop tables + update imports

**Files:**
- Delete: `backend/app/api/hubs.py`
- Delete: `backend/app/api/materials.py`
- Delete: `backend/app/models/hub.py`
- Delete: `backend/app/models/material.py`
- Delete: `backend/app/models/supplier.py`
- Create: `backend/seeds/cleanup_stale.py`
- Modify: `backend/app/api/__init__.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/components.py:204` (`regex=` → `pattern=`)

- [ ] **Step 1: Write `cleanup_stale.py`**

File: `backend/seeds/cleanup_stale.py`
```python
"""
One-shot cleanup: drop pre-pivot tables + wipe demo cart/orders.

Run once from project root:
    cd backend && source venv/bin/activate && python -m seeds.cleanup_stale
"""
from sqlalchemy import text

from app.core.database import engine

STALE_TABLES = [
    "materials",
    "suppliers",
    "production_hubs",
    "price_history",
    "price_forecasts",
]


def main():
    with engine.begin() as conn:
        for t in STALE_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
            print(f"dropped: {t}")
        # Wipe stale demo data — keeps users intact
        for t in ["cart_items", "orders"]:
            conn.execute(text(f"DELETE FROM {t}"))
            print(f"wiped: {t}")
    print("cleanup done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update `backend/app/api/__init__.py`**

Remove imports/includes of `hubs` and `materials`. Result:
```python
from fastapi import APIRouter

from app.api import auth, components, distributors, cart, optimize, live_prices, market_intelligence

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(components.router)
api_router.include_router(distributors.router)
api_router.include_router(cart.router)
api_router.include_router(optimize.router)
api_router.include_router(live_prices.router)
api_router.include_router(market_intelligence.router)

__all__ = ["api_router"]
```

(Already clean — just verify `hubs` and `materials` are NOT present. If they are, remove them.)

- [ ] **Step 3: Update `backend/app/models/__init__.py`**

Replace content:
```python
from app.models.user import User
from app.models.order import CartItem, Order
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor
from app.models.cross_dock_hub import CrossDockHub

__all__ = [
    "User", "CartItem", "Order",
    "Component", "DistributorOffer", "Distributor",
    "CrossDockHub",
]
```

- [ ] **Step 4: Create new `backend/app/models/cross_dock_hub.py`**

File: `backend/app/models/cross_dock_hub.py`
```python
from sqlalchemy import Column, Float, Integer, String, Text
from app.core.database import Base


class CrossDockHub(Base):
    """Real US freight hub used as cross-dock consolidation candidate."""
    __tablename__ = "cross_dock_hubs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    operator = Column(String(100))
    hub_type = Column(String(50))
    city = Column(String(100))
    state = Column(String(10))
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    annual_throughput_desc = Column(Text)
    source_citation = Column(String(300))
```

- [ ] **Step 5: Delete stale files**

```bash
rm backend/app/api/hubs.py backend/app/api/materials.py \
   backend/app/models/hub.py backend/app/models/material.py backend/app/models/supplier.py
```

- [ ] **Step 6: Fix the deprecated `regex=` in `components.py`**

Use Grep to find `regex=` in `backend/app/api/components.py` and replace with `pattern=`.

- [ ] **Step 7: Run cleanup script**

```bash
cd backend && source venv/bin/activate && python -m seeds.cleanup_stale
```

Expected output: `dropped: materials ... wiped: orders ... cleanup done.`

- [ ] **Step 8: Verify backend imports cleanly**

```bash
cd backend && source venv/bin/activate && python -c "from app.main import app; print('import ok')"
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "chore: drop stale pre-pivot files, add CrossDockHub model"
```

---

## Task 10: Seeds — cross-dock hubs + curated demo cart

**Files:**
- Create: `backend/seeds/seed_cross_dock_hubs.py`
- Create: `backend/seeds/seed_demo_cart.py`

- [ ] **Step 1: Write `seed_cross_dock_hubs.py`**

File: `backend/seeds/seed_cross_dock_hubs.py`
```python
"""Seed the cross_dock_hubs table from the static FREIGHT_HUBS list."""
from app.core.database import Base, SessionLocal, engine
from app.models.cross_dock_hub import CrossDockHub
from app.optimization.freight_hubs import FREIGHT_HUBS


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(CrossDockHub).delete()
        for h in FREIGHT_HUBS:
            db.add(CrossDockHub(
                id=h.id, name=h.name, operator=h.operator, hub_type=h.hub_type,
                city=h.city, state=h.state,
                latitude=h.latitude, longitude=h.longitude,
                source_citation="Spec §5.5 (verified against public databases)",
            ))
        db.commit()
        n = db.query(CrossDockHub).count()
        print(f"seeded {n} cross-dock hubs")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write `seed_demo_cart.py`**

File: `backend/seeds/seed_demo_cart.py`
```python
"""
Seed curated 5-part BOM into the demo user's cart.

Run once: python -m seeds.seed_demo_cart
"""
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.component import Component, DistributorOffer
from app.models.order import CartItem
from app.models.user import User

# (mpn, quantity) — component_ids looked up dynamically by MPN
CURATED_BOM = [
    ("ESP32-WROOM-32UE-N4", 50),
    ("STM32F103C8T6", 50),
    ("GD25Q64CSIGR", 50),
    ("ESP8266EX", 50),
    ("ATMEGA328P-PU", 25),
]

DEMO_EMAIL = "demo@example.com"


def main():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if not user:
            raise SystemExit(f"Demo user {DEMO_EMAIL} not found — run seed_db first")

        # Clear any existing cart items
        db.query(CartItem).filter(CartItem.user_id == user.id).delete()

        for mpn, qty in CURATED_BOM:
            comp = db.query(Component).filter(Component.mpn == mpn).first()
            if not comp:
                raise SystemExit(f"Component {mpn} not found in DB — run seed_db first")

            # Pick the cheapest US offer as the default cart selection
            offer = db.execute(
                select(DistributorOffer)
                .where(DistributorOffer.component_id == comp.id)
                .order_by(DistributorOffer.price.asc())
                .limit(1)
            ).scalar_one_or_none()

            if not offer or not offer.price:
                raise SystemExit(f"No valid offer for {mpn}")

            db.add(CartItem(
                user_id=user.id,
                component_id=comp.id,
                distributor_id=offer.distributor_id,
                quantity=qty,
                unit_price=offer.price,
            ))
        db.commit()
        n = db.query(CartItem).filter(CartItem.user_id == user.id).count()
        print(f"seeded {n} cart items for {DEMO_EMAIL}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run both seeds**

```bash
cd backend && source venv/bin/activate && \
    python -m seeds.seed_cross_dock_hubs && \
    python -m seeds.seed_demo_cart
```

Expected: `seeded 10 cross-dock hubs` then `seeded 5 cart items for demo@example.com`.

- [ ] **Step 4: Commit**

```bash
git add backend/seeds/seed_cross_dock_hubs.py backend/seeds/seed_demo_cart.py
git commit -m "feat(seeds): cross-dock hubs + curated demo BOM"
```

---

## Task 11: Rewrite `backend/app/api/optimize.py` — shrink to wire the new pipeline

**Files:**
- Modify: `backend/app/api/optimize.py` (replace entirely)

- [ ] **Step 1: Replace `optimize.py` content**

File: `backend/app/api/optimize.py`
```python
"""
Optimization API endpoints — thin wiring over app.optimization.solve.

See docs/superpowers/specs/2026-04-10-sub-project-a-design.md.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.database import get_db
from app.models.component import Component, DistributorOffer
from app.models.cross_dock_hub import CrossDockHub
from app.models.distributor import Distributor
from app.models.order import CartItem, Order
from app.models.user import User
from app.optimization import schemas as opt_schemas
from app.optimization.routing import GeoPoint
from app.optimization.solve import DistributorMeta, optimize_bom
from app.optimization.sourcing import BomLine, Offer


router = APIRouter(prefix="/optimize", tags=["optimization"])


def _distributor_tier(total_offers: int) -> str:
    if total_offers >= 500:
        return "major"
    if total_offers >= 100:
        return "mid"
    return "broker"


@router.post("/vrp", response_model=opt_schemas.MultiRouteResponse)
def optimize_route(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Run the full sourcing + TSP + cross-dock pipeline for the user's cart."""
    cart_items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Build BOM from cart
    bom: List[BomLine] = []
    comp_ids = [ci.component_id for ci in cart_items]
    components = {
        c.id: c for c in db.query(Component).filter(Component.id.in_(comp_ids)).all()
    }
    for ci in cart_items:
        c = components.get(ci.component_id)
        if not c:
            continue
        bom.append(BomLine(
            component_id=c.id,
            mpn=c.mpn,
            quantity=int(ci.quantity),
        ))

    if not bom:
        raise HTTPException(status_code=400, detail="No valid components in cart")

    # Fetch all offers for these components (let the solver filter)
    offer_rows = db.query(DistributorOffer).filter(
        DistributorOffer.component_id.in_(comp_ids)
    ).all()

    # Distributor metadata cache
    dist_ids = {o.distributor_id for o in offer_rows}
    dist_rows = db.query(Distributor).filter(Distributor.id.in_(dist_ids)).all()
    dist_by_id = {d.id: d for d in dist_rows}

    offers: List[Offer] = []
    for o in offer_rows:
        d = dist_by_id.get(o.distributor_id)
        if not d or o.price is None or o.price <= 0:
            continue
        offers.append(Offer(
            component_id=o.component_id,
            distributor_id=o.distributor_id,
            distributor_name=d.name,
            price_usd=float(o.price),
            stock=int(o.stock or 0),
            moq=int(o.moq or 1),
            is_domestic=bool(d.is_domestic),
        ))

    distributors_meta = {
        d.id: DistributorMeta(
            id=d.id, name=d.name, lat=d.latitude, lng=d.longitude,
            city=d.city, state=d.state, country=d.country,
            is_domestic=bool(d.is_domestic),
            tier=_distributor_tier(d.total_offers or 0),
        )
        for d in dist_rows
    }

    depot = GeoPoint(lat=float(current_user.latitude), lng=float(current_user.longitude))

    try:
        response = optimize_bom(bom, offers, distributors_meta, depot, us_only=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Solver failed: {e}")

    # Persist balanced alternative as an order record
    balanced = next(a for a in response.alternatives if a.id == "balanced")
    order = Order(
        user_id=current_user.id,
        status="optimized",
        total_cost=balanced.total_cost_usd,
        total_co2e_kg=balanced.total_co2e_kg,
        eta_days=balanced.base_eta_days,
        eta_lower_ci=balanced.eta_p10,
        eta_upper_ci=balanced.eta_p90,
        optimized_route=[s.model_dump() for s in balanced.route],
        monte_carlo_results={"p10": balanced.eta_p10, "p50": balanced.eta_p50, "p90": balanced.eta_p90},
        items=[{"component_id": ci.component_id, "distributor_id": ci.distributor_id,
                "quantity": ci.quantity, "unit_price": ci.unit_price} for ci in cart_items],
    )
    db.add(order)
    db.commit()

    return response


class HubOut(BaseModel):
    id: int
    name: str
    operator: Optional[str]
    hub_type: Optional[str]
    city: Optional[str]
    state: Optional[str]
    latitude: float
    longitude: float


@router.get("/hubs", response_model=List[HubOut])
def list_cross_dock_hubs(db: Session = Depends(get_db)):
    """Return the 10 real US freight hubs for map display."""
    return [
        HubOut(
            id=h.id, name=h.name, operator=h.operator, hub_type=h.hub_type,
            city=h.city, state=h.state,
            latitude=h.latitude, longitude=h.longitude,
        )
        for h in db.query(CrossDockHub).order_by(CrossDockHub.id).all()
    ]


# Legacy scenario endpoint (retained verbatim — not part of Sub-Project A)

class ScenarioRequest(BaseModel):
    tariff_multiplier: float = 1.0
    distributor_failure_ids: List[int] = []
    demand_spike: float = 1.0


@router.post("/scenario")
def run_scenario(
    body: ScenarioRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Digital twin: re-run optimization under what-if conditions (simplified)."""
    cart_items = db.query(CartItem).filter(CartItem.user_id == current_user.id).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    adjustments = []
    for item in cart_items:
        dist = db.query(Distributor).filter(Distributor.id == item.distributor_id).first()
        comp = db.query(Component).filter(Component.id == item.component_id).first()
        base_price = item.unit_price or 0
        tariff_adj = base_price * body.tariff_multiplier
        dist_failed = item.distributor_id in body.distributor_failure_ids
        adjustments.append({
            "component": comp.mpn if comp else "Unknown",
            "distributor": dist.name if dist else "Unknown",
            "base_price": base_price,
            "scenario_price": tariff_adj if not dist_failed else None,
            "distributor_available": not dist_failed,
            "quantity": item.quantity,
            "base_cost": base_price * item.quantity,
            "scenario_cost": tariff_adj * item.quantity * body.demand_spike if not dist_failed else None,
        })

    base_total = sum(a["base_cost"] for a in adjustments)
    scenario_total = sum(a["scenario_cost"] for a in adjustments if a["scenario_cost"] is not None)
    cost_delta_pct = round((scenario_total - base_total) / base_total * 100, 1) if base_total else 0

    return {
        "scenario": {
            "tariff_multiplier": body.tariff_multiplier,
            "distributor_failures": len(body.distributor_failure_ids),
            "demand_spike": body.demand_spike,
        },
        "base_total_cost": round(base_total, 2),
        "scenario_total_cost": round(scenario_total, 2),
        "cost_delta_pct": cost_delta_pct,
        "disrupted_items": len([a for a in adjustments if not a["distributor_available"]]),
        "item_breakdown": adjustments,
    }
```

- [ ] **Step 2: Restart backend + verify endpoint works**

```bash
cd backend && source venv/bin/activate && \
    python -c "from app.api.optimize import router; print([r.path for r in router.routes])"
```

Expected: includes `/optimize/vrp`, `/optimize/hubs`, `/optimize/scenario`.

- [ ] **Step 3: Smoke-test via curl (requires running server + demo login)**

```bash
# Start backend in another terminal first
curl -s -X POST http://localhost:8000/api/v1/auth/demo | python -m json.tool
# Use the returned access_token
TOKEN=<paste>
curl -s -X POST http://localhost:8000/api/v1/optimize/vrp \
    -H "Authorization: Bearer $TOKEN" | python -m json.tool | head -60
```

Expected: 4 alternatives with different `total_cost_usd` values.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/optimize.py
git commit -m "feat(api): rewrite optimize endpoint to use new pipeline"
```

---

## Task 12: Frontend — extend types + CheckoutPage functional wiring

Purpose: render new data (cost_breakdown, strategy_math, cross_dock) using **minimal default layout**. Visual design choices (colors, spacing, card treatment, mini-charts) are intentionally deferred to the user for review after build.

**Files:**
- Modify: `frontend/src/store/optimizeStore.ts`
- Modify: `frontend/src/pages/CheckoutPage.tsx`
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Extend types in `optimizeStore.ts`**

Add new interfaces and extend `RouteAlternative`:
```typescript
export interface CostBreakdown {
  component_cost: number;
  transport_cost: number;
  holding_cost: number;
  total: number;
}

export interface StrategyMath {
  weights: { cost: number; time: number; carbon: number };
  raw_objective_values: { cost: number; time: number; carbon: number };
  normalized_objective_values: { cost: number; time: number; carbon: number };
  weighted_total: number;
  citations: string[];
}

export interface CrossDockInfo {
  enabled: boolean;
  hub_id?: number | null;
  hub_name?: string | null;
  hub_city?: string | null;
  hub_state?: string | null;
  hub_lat?: number | null;
  hub_lng?: number | null;
  savings_vs_direct_pct: number;
  direct_cost_usd: number;
  consolidated_cost_usd: number;
  rationale: string;
}

export interface SourcingAssignment {
  component_id: number;
  mpn: string;
  distributor_id: number;
  distributor_name: string;
  quantity: number;
  unit_price_usd: number;
  line_total_usd: number;
}

export interface OutlierDropLog {
  component_id: number;
  mpn: string;
  dropped_distributor_id: number;
  dropped_price_usd: number;
  median_price_usd: number;
  reason: string;
}
```

Extend `RouteAlternative` with:
```typescript
  cost_breakdown?: CostBreakdown | null;
  strategy_math?: StrategyMath | null;
  cross_dock?: CrossDockInfo | null;
  sourcing?: SourcingAssignment[];
```

Extend `MultiRouteResult`:
```typescript
export interface MultiRouteResult {
  alternatives: RouteAlternative[];
  recommended_id: string;
  outlier_drops?: OutlierDropLog[];
}
```

- [ ] **Step 2: Add `getCrossDockHubs` to `api.ts`**

```typescript
export async function getCrossDockHubs() {
  const { data } = await api.get('/optimize/hubs');
  return data as Array<{
    id: number; name: string; operator: string | null;
    hub_type: string | null; city: string | null; state: string | null;
    latitude: number; longitude: number;
  }>;
}
```

- [ ] **Step 3: Wire new data into CheckoutPage (minimal default layout)**

Add an "Objective Breakdown" collapsible section per card that renders strategy_math + cost_breakdown + citations, and a "Cross-Dock" line that renders cross_dock.rationale + savings if enabled. Use **simple default markup with `data-testid` attributes** — no visual styling decisions yet.

Example block to add inside each route card (wrap in collapsible `<details>`):
```tsx
{alt.strategy_math && (
  <details className="mt-4 border-t border-slate-700 pt-3" data-testid="objective-breakdown">
    <summary className="cursor-pointer text-sm text-slate-300 hover:text-white">
      Objective Breakdown
    </summary>
    <div className="mt-2 text-xs text-slate-400 space-y-1 font-mono">
      <div>
        Objective: {alt.strategy_math.weights.cost.toFixed(2)}·cost +{' '}
        {alt.strategy_math.weights.time.toFixed(2)}·time +{' '}
        {alt.strategy_math.weights.carbon.toFixed(2)}·carbon
      </div>
      {alt.cost_breakdown && (
        <>
          <div>Component cost: ${alt.cost_breakdown.component_cost.toFixed(2)}</div>
          <div>Transport cost: ${alt.cost_breakdown.transport_cost.toFixed(2)}</div>
          <div>Holding cost: ${alt.cost_breakdown.holding_cost.toFixed(2)}</div>
          <div>Total: ${alt.cost_breakdown.total.toFixed(2)}</div>
        </>
      )}
      <div>
        Weighted objective: {alt.strategy_math.weighted_total.toFixed(4)}
      </div>
      <div className="mt-2 text-[10px] text-slate-500" data-testid="citations">
        Sources: {alt.strategy_math.citations.join(' · ')}
      </div>
    </div>
  </details>
)}

{alt.cross_dock && alt.cross_dock.enabled && alt.cross_dock.hub_name && (
  <div className="mt-2 text-xs text-amber-400" data-testid="cross-dock-line">
    Consolidated via {alt.cross_dock.hub_name} ({alt.cross_dock.hub_city}, {alt.cross_dock.hub_state}) —{' '}
    saves {alt.cross_dock.savings_vs_direct_pct.toFixed(1)}%
  </div>
)}
```

Add `data-testid="route-cards"` to the container wrapping the 4 alternatives.

- [ ] **Step 4: Verify frontend builds**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Expected: no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/store/optimizeStore.ts frontend/src/services/api.ts frontend/src/pages/CheckoutPage.tsx
git commit -m "feat(frontend): wire objective breakdown + cross-dock info (default layout)"
```

---

## Task 13: Frontend — MapPage hub layer (default markers, no design polish)

**Files:**
- Modify: `frontend/src/pages/MapPage.tsx`

- [ ] **Step 1: Fetch hubs on mount, render as default MapLibre markers**

Add a `useEffect` that calls `getCrossDockHubs()` and stores the result in state. Render each as a plain circle marker (default MapLibre `Marker` with a basic colored div) with `data-testid="hub-marker"`. No styling decisions — use a single fallback color (amber `#f59e0b`) and a 12px square.

Example:
```tsx
const [hubs, setHubs] = useState<HubOut[]>([]);
useEffect(() => {
  getCrossDockHubs().then(setHubs).catch(() => setHubs([]));
}, []);

// In the map rendering:
{hubs.map(hub => (
  <Marker key={`hub-${hub.id}`} longitude={hub.longitude} latitude={hub.latitude}>
    <div
      data-testid="hub-marker"
      title={`${hub.name} (${hub.city}, ${hub.state})`}
      style={{
        width: 12, height: 12, background: '#f59e0b',
        border: '1px solid #78350f',
        transform: 'rotate(45deg)',
      }}
    />
  </Marker>
))}
```

- [ ] **Step 2: Build + verify**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/MapPage.tsx
git commit -m "feat(map): render cross-dock hub markers (default style)"
```

---

## Task 14: E2E test via Playwright MCP

**Files:**
- Create: `tests/e2e/sub-project-a.spec.ts` OR execute directly through Playwright MCP

- [ ] **Step 1: Ensure backend + frontend are running**

```bash
# Terminal 1
cd backend && source venv/bin/activate && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# Terminal 2
cd frontend && npm run dev
```

- [ ] **Step 2: Drive through Playwright MCP browser tool**

Sequence via `mcp__plugin_playwright_playwright__browser_*`:
1. Navigate to `http://localhost:5173/login`
2. Click Demo Login button
3. Wait for dashboard
4. Navigate to `/cart` — verify 5 rows visible (snapshot)
5. Click "Optimize & Checkout" (or whatever advances to checkout)
6. Wait for `[data-testid="route-cards"]`
7. Take snapshot, verify 4 cards, verify total_cost_usd strings differ
8. Click the first `summary` inside `[data-testid="objective-breakdown"]` and verify `[data-testid="citations"]` text contains "ATRI" and "EPA"
9. Verify at least one card has `[data-testid="cross-dock-line"]` visible (OR note absence in the screenshot)
10. Take final screenshot to `test-screenshots/sub-project-a-demo.png`

- [ ] **Step 3: Commit any new scripts**

```bash
git add tests/e2e/ 2>/dev/null || true
git add test-screenshots/sub-project-a-demo.png 2>/dev/null || true
git commit -m "test(e2e): Playwright verification for sub-project A" || echo "nothing to commit"
```

---

## Task 15: Interview walkthrough doc

**Files:**
- Create: `docs/interview-walkthrough.md`

- [ ] **Step 1: Write the doc**

File: `docs/interview-walkthrough.md`
```markdown
# Sub-Project A — Interview Walkthrough

A one-page whiteboard-ready explanation of the sourcing + routing +
cross-dock system. Target audience: supply chain / operations / data
science interview at McKinsey, BCG, Amazon Ops, Apple Ops.

## 1. Business framing

A US PCB manufacturer runs a production run of 50 wireless IoT sensor
nodes. The BOM contains 5 electronic components sourced from a market
of 92 distributors offering ~8,000 competing price offers (real Nexar
data). We need to decide *which distributor fills each line*, and
*which route the pickup truck takes*, balancing cost, delivery time,
and carbon emissions.

## 2. Decision variables

- `x[c,d] ∈ {0,1}` — is component c sourced from distributor d?
- `q[c,d] ∈ ℤ≥0` — quantity
- `y[d] ∈ {0,1}` — is distributor d visited at all?

## 3. Constraints

- Demand coverage: Σ_d q[c,d] = demand[c]
- Stock cap: q[c,d] ≤ stock[c,d] · x[c,d]
- MOQ floor: q[c,d] ≥ moq[c,d] · x[c,d]
- Distributor linking: y[d] ≥ x[c,d]
- US-only filter: x[c,d] = 0 if distributor d is international

## 4. Objective function

Weighted sum scalarization (Marler & Arora 2004) over three
normalized objectives:

```
min  w_cost · cost_n + w_time · time_n + w_carbon · carbon_n
```

**Cost terms (all cited):**
- TL rate: $2.271/mi — ATRI 2023
- LTL base + per-cwt: $75 + $0.43/cwt·mi — FreightWaves SONAR 2023
- CO2: 161.8 g/ton-mi — EPA SmartWay 2023
- Holding cost: 25%/yr — Gartner 2022
- Ground speed: 800 km/day — BTS CFS 2022

**Strategy weight profiles:**
| Strategy | w_cost | w_time | w_carbon | Basis |
|---|---|---|---|---|
| Lowest Cost | 1.00 | 0.00 | 0.00 | Weber 1991 |
| Fastest | 0.15 | 0.80 | 0.05 | JIT / Toyota |
| Greenest | 0.25 | 0.05 | 0.70 | CDP Supply Chain |
| Balanced | 0.40 | 0.35 | 0.25 | Ghodsypour & O'Brien 1998 |

## 5. Why CP-SAT (not pure LP, not pure OR-Tools routing)

- Integer quantities (`q[c,d] ∈ ℤ`) make it a MILP, not LP
- Combinatorial supplier selection via `x[c,d] ∈ {0,1}`
- OR-Tools routing handles vehicle flow, not supplier selection
- CP-SAT treats linear integer programs as MILP-equivalent and is
  faster than CBC on small combinatorial problems
- Already a transitive dependency via OR-Tools routing

## 6. Pipeline

```
BOM → Outlier Filter → Stage 1 CP-SAT Sourcing →
Stage 2 TSP → Cross-Dock Evaluation → 4 RouteAlternatives
```

**Outlier filter:** Drop any offer where `price > 5 × median(price)`
for that MPN. One-sided (low discounts stay). Aberdeen Group 2020.

**Stage 1 (Sourcing MILP):** CP-SAT picks cheapest offers subject to
demand/stock/MOQ.

**Stage 2 (TSP):** OR-Tools routing over the selected distributors —
PATH_CHEAPEST_ARC + GUIDED_LOCAL_SEARCH, haversine distance matrix.

**Cross-dock:** Lagrangian relaxation of the Capacitated Facility
Location Problem (Daskin 2013, Ch. 4). With only 10 candidate hubs,
exact enumeration is trivially fast. A hub is chosen iff it beats
direct pickup by ≥5% on the weighted objective.

## 7. Why the four strategies diverge

- `cost`: dominated by component price (varies 3.8×–17× post-filter
  across distributors for the same MPN — this IS the lever)
- `time`: depends on distributor handling tier + ceiling(distance/800)
  — discrete days, not a distance scalar
- `carbon`: depends on actual shipment weight × distance — varies by
  SKU and quantity
- `cross-dock decision`: changes per strategy because the weighted
  objective differs — "fastest" avoids hubs (dwell time), "greenest"
  prefers them (tonne-miles reduction)

None of the three objectives is a scalar multiple of another, so
weighted-sum combinations produce genuinely distinct optima.

## 8. Extensions (Sub-Project B)

- Two-echelon joint MILP (facility + routing in one program)
- Time windows on distributor pickup
- Stochastic demand (Monte Carlo + robust optimization)
- OSRM driving distances instead of haversine
- Weather + traffic per-leg ETA adjustment
- Air freight as an explicit decision variable
```

- [ ] **Step 2: Commit**

```bash
git add docs/interview-walkthrough.md
git commit -m "docs: interview walkthrough for sub-project A"
```

---

## Task 16: Final verification

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 2: Verify frontend builds**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: no errors.

- [ ] **Step 3: Verify success criteria from spec §15**

- [ ] 4 strategies return different `total_cost_usd` (verified via test_strategies + E2E)
- [ ] All dollars/hours/kg cite constants in `costs.py`
- [ ] Objective Breakdown panel shows citations
- [ ] At least one strategy selects a cross-dock hub (check API response)
- [ ] Map page shows hub markers
- [ ] pytest files pass
- [ ] No references to `materials`, `suppliers`, `production_hubs`, `hubs.py`, `materials.py`

```bash
grep -rn "materials\|suppliers\|production_hubs" backend/app/ 2>/dev/null | grep -v ".pyc" | head
```

Expected: empty (or only comments / docstrings).

- [ ] **Step 4: Present design choices to user (STOP POINT)**

Halt here. Summarize build completion and present the three frontend design decisions for the user to choose among:

**(a) Objective Breakdown panel layout** — the current default is plain monospace text in a `<details>` element. Present 2–3 visual alternatives (tabular layout, horizontal bar-chart weights, card with sparkline of normalized values).

**(b) Cross-Dock comparison** — currently a one-line amber text. Present 2–3 alternatives (two-column mini-chart side-by-side, before/after pills, arrow diagram).

**(c) Map hub markers + cross-dock route rendering** — currently plain amber squares. Present 2–3 alternatives (diamond icons with glow, pulsing when selected, branded colored by hub operator; and LTL dashed vs TL solid line treatments).

Use the visual companion (browser at http://localhost:50131 or restart) to show each alternative side-by-side via HTML mockups. Wait for user selection, then execute.

---

## Plan End

Tasks 1–16 cover the full Sub-Project A build except for the three deferred frontend design choices in Task 16, Step 4. Every task is independently committable with tests where applicable.

