"""
Monte Carlo cascade failure simulation.

Runs N=1,000 SIR-style scenarios over the bipartite supply graph.
Each scenario probabilistically fails distributors weighted by normalized betweenness
centrality, then checks which BOM components become unfulfillable.
Fixed seed=42 ensures reproducible output.
N is a module constant -- never controlled by user input.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Set

if TYPE_CHECKING:
    from app.graph import GraphState

# Fixed -- not user-configurable per T-02-03 (DoS mitigation)
N_SCENARIOS: int = 1000

# Reproducibility: all runs on the same DB produce identical numbers
DEFAULT_SEED: int = 42

# Phase 3 will inject live stress multiplier; default = full betweenness
STRESS_FACTOR: float = 1.0

# 15% cost inflation per unfulfillable component
EMERGENCY_COST_PREMIUM: float = 0.15


@dataclass
class SimulationResult:
    """Output of a Monte Carlo cascade failure simulation run."""
    p10: float       # 10th percentile fulfillment rate (worst scenarios)
    p50: float       # Median fulfillment rate
    p90: float       # 90th percentile fulfillment rate (best scenarios)
    evar_95: float   # Mean cost inflation of worst-5% scenarios (>= 1.0)
    n_scenarios: int # Number of scenarios run (always N_SCENARIOS)
    seed: int        # RNG seed used (always DEFAULT_SEED via API)


def _get_comp_to_dists(gs: "GraphState", bom_component_ids: List[int]) -> Dict[int, Set[int]]:
    """
    For each BOM component cid, find all distributor IDs that have an edge to c_{cid}
    in the DiGraph (predecessors of the component node).

    Returns Dict[int, Set[int]]: component_id -> set of distributor_ids supplying it.
    """
    comp_to_dists: Dict[int, Set[int]] = {}
    graph = gs.graph
    for cid in bom_component_ids:
        node_name = f"c_{cid}"
        dist_ids: Set[int] = set()
        if graph.has_node(node_name):
            for pred in graph.predecessors(node_name):
                # Predecessor nodes are distributor nodes named "d_{did}"
                if pred.startswith("d_"):
                    try:
                        dist_ids.add(int(pred[2:]))
                    except ValueError:
                        pass
        comp_to_dists[cid] = dist_ids
    return comp_to_dists


def run_monte_carlo(
    gs: "GraphState",
    bom_component_ids: List[int],
    n_scenarios: int = N_SCENARIOS,
    seed: int = DEFAULT_SEED,
) -> SimulationResult:
    """
    Run N=1,000 SIR-style cascade failure scenarios over the bipartite supply graph.

    Algorithm (per scenario):
      1. Sample distributor failures: each distributor fails with probability =
         min(normalized_betweenness * STRESS_FACTOR, 1.0)
      2. A component is unfulfillable if ALL its supplying distributors failed,
         or it has no suppliers in the graph.
      3. fulfillment_rate = n_fulfillable / n_bom
      4. cost_inflation = 1.0 + (n_unfulfillable / n_bom) * EMERGENCY_COST_PREMIUM

    Output aggregation:
      - P10 = 10th percentile of fulfillment_rates (worst outcomes)
      - P50 = median fulfillment rate
      - P90 = 90th percentile (best outcomes)
      - EVaR_95 = mean cost_inflation of the worst-5% scenarios by fulfillment rate

    The n_scenarios parameter is not exposed to API callers (T-02-03 threat mitigation).
    API endpoint always passes N_SCENARIOS directly and ignores any user-supplied n value.
    """
    # Empty BOM: trivially all components fulfillable
    if not bom_component_ids:
        return SimulationResult(
            p10=1.0,
            p50=1.0,
            p90=1.0,
            evar_95=1.0,
            n_scenarios=n_scenarios,
            seed=seed,
        )

    n_bom = len(bom_component_ids)

    # Build component -> supplying distributors mapping
    comp_to_dists = _get_comp_to_dists(gs, bom_component_ids)

    # Build failure probability dict for each distributor that appears in the graph
    # betweenness is already normalized to [0, 1] by the builder
    betweenness: Dict[int, float] = gs.betweenness
    all_dist_ids: Set[int] = set()
    for dist_ids in comp_to_dists.values():
        all_dist_ids.update(dist_ids)

    failure_probs: Dict[int, float] = {
        did: min(betweenness.get(did, 0.0) * STRESS_FACTOR, 1.0)
        for did in all_dist_ids
    }

    # Isolated RNG -- does not affect any other module's random state
    rng = random.Random(seed)

    fulfillment_rates: List[float] = []
    cost_inflations: List[float] = []

    for _ in range(n_scenarios):
        # Step 1: determine which distributors fail this scenario
        failed_dists: Set[int] = {
            did
            for did, prob in failure_probs.items()
            if rng.random() < prob
        }

        # Step 2: count unfulfillable components
        n_unfulfillable = 0
        for cid in bom_component_ids:
            supplying_dists = comp_to_dists[cid]
            # Unfulfillable if no suppliers OR all suppliers failed
            if not supplying_dists or supplying_dists.issubset(failed_dists):
                n_unfulfillable += 1

        # Step 3: fulfillment rate
        n_fulfillable = n_bom - n_unfulfillable
        fulfillment_rate = n_fulfillable / n_bom

        # Step 4: cost inflation
        inflation = 1.0 + (n_unfulfillable / n_bom) * EMERGENCY_COST_PREMIUM

        fulfillment_rates.append(fulfillment_rate)
        cost_inflations.append(inflation)

    # Sort fulfillment rates ascending for percentile computation
    fulfillment_rates.sort()

    # Percentile indices (clamped to valid range)
    def _percentile_idx(p: float) -> int:
        idx = int(p * n_scenarios)
        return max(0, min(idx, n_scenarios - 1))

    p10 = fulfillment_rates[_percentile_idx(0.10)]
    p50 = fulfillment_rates[_percentile_idx(0.50)]
    p90 = fulfillment_rates[_percentile_idx(0.90)]

    # EVaR: pair rates with inflations, sort ascending by rate, take worst 5%
    paired = sorted(zip(fulfillment_rates, cost_inflations), key=lambda x: x[0])
    n_tail = max(1, int(0.05 * n_scenarios))
    worst_inflations = [inf for _, inf in paired[:n_tail]]
    evar_95 = sum(worst_inflations) / len(worst_inflations)

    return SimulationResult(
        p10=p10,
        p50=p50,
        p90=p90,
        evar_95=evar_95,
        n_scenarios=n_scenarios,
        seed=seed,
    )
