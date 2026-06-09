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
    us_only_sourcing: bool = False  # if True, filter to domestic (US) distributors only
    # Scales transport-cost penalty in the sourcing MILP objective.
    # Higher values push the solver toward nearby distributors.
    # cheapest=1.0 (landed cost), fastest=0.0 (us_only handles it),
    # greenest=2.5 (tonne-mile minimisation), balanced=1.2 (moderate).
    transport_penalty_scale: float = 1.0
    # USD bonus subtracted per distributor used — rewards consolidation.
    # Positive = fewer stops; set lower for strategies that accept more stops.
    consolidation_bonus_usd: float = 1.0

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
        us_only_sourcing=False,
        transport_penalty_scale=1.0,   # full landed cost (components + freight)
        consolidation_bonus_usd=0.5,   # weak consolidation incentive — split is OK if cheaper
    ),
    StrategyWeights(
        id="fastest",
        label="Fastest Delivery",
        description="JIT/lean procurement — minimize lead time at reasonable cost",
        w_cost=0.15, w_time=0.80, w_carbon=0.05,
        basis="Toyota Production System literature; JIT practice",
        us_only_sourcing=True,
        transport_penalty_scale=0.0,   # us_only filter handles proximity; no extra distance penalty
        consolidation_bonus_usd=3.0,   # strong consolidation to reduce handling/transit hops
    ),
    StrategyWeights(
        id="greenest",
        label="Lowest Carbon",
        description="ESG-compliant — eliminates international air freight (30-40× CO2 penalty vs domestic truck for electronics)",
        w_cost=0.25, w_time=0.05, w_carbon=0.70,
        basis="CDP Supply Chain Disclosure framework; ICAO 2023 cargo emissions factor",
        us_only_sourcing=True,   # US-only: air freight emits 30-40× more CO2/kg than domestic truck for lightweight electronics
        transport_penalty_scale=2.5,   # prefer nearby domestic distributors to cut tonne-miles; unlike fastest which picks cheapest regardless of distance
        consolidation_bonus_usd=2.5,   # strong consolidation: fewer truck legs = lower CO2
    ),
    StrategyWeights(
        id="balanced",
        label="Balanced",
        description="Balanced weighting across cost/time/carbon — avoids international air freight CO2 penalty",
        w_cost=0.40, w_time=0.35, w_carbon=0.25,
        basis="Ghodsypour & O'Brien (1998), Int'l J. Production Economics 56-57",
        us_only_sourcing=True,   # domestic-only: air freight CO2 penalty (30-40×) outweighs component price savings in the weighted objective
        transport_penalty_scale=1.5,   # moderate distance penalty: balance cost vs tonne-miles
        consolidation_bonus_usd=2.0,   # moderate consolidation incentive
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
