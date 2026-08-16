"""
Graph ML Network Risk Engine.

Builds a bipartite NetworkX DiGraph from the live SQLite database (Distributor <-> Component
nodes, offer edges weighted by inverse stock). Computes centrality metrics, k-core
decomposition, HHI per category, Fiedler algebraic connectivity, and Monte Carlo
cascade simulation.

Call get_graph_state() to get the loaded GraphState, or None if graph has not been
built yet (builds automatically at startup via lifespan).
"""
from __future__ import annotations
from typing import Optional, Dict, FrozenSet, List
from dataclasses import dataclass, field

import networkx as nx


@dataclass
class GraphState:
    graph: nx.DiGraph                          # bipartite DiGraph: dist->comp, weight=inv_stock
    dist_nodes: FrozenSet[str]                 # frozenset of 'd_{did}' node names
    betweenness: Dict[int, float]              # distributor_id -> normalized [0,1] betweenness
    # RAW PageRank score on the UNDIRECTED bipartite projection -- NOT min-max
    # normalized. Scores sum to 1.0 across ALL nodes (distributors + components),
    # so the distributor sub-total is < 1.0. Two things were wrong before
    # (2026-08 functionality audit):
    #   1. it was computed on the DiGraph, whose edges all run distributor->component.
    #      Every distributor therefore had in-degree 0 and received only teleport mass,
    #      making all 92 scores identical (0.00105149 each) -- a constant, not a metric.
    #   2. the identical scores were then min-max normalized, and a min-max over a
    #      zero-range vector maps EVERY entry to exactly 0.0. That is how the endpoint
    #      came to publish sum = 0.0 and max = 0.0 for 92 distributors.
    # Min-max normalization is not applied to ANY centrality any more: it is what
    # manufactured the p_fail = 1.0 pathology in the simulator as well.
    pagerank: Dict[int, float]                 # distributor_id -> raw PageRank score
    k_core: Dict[str, int]                     # node_name -> core number
    single_source_component_ids: FrozenSet[int]  # component_ids with only 1 stocked distributor
    hhi_by_category: Dict[str, float]          # category -> HHI (0-10000 scale)
    fiedler: float                             # WHOLE-GRAPH algebraic connectivity (λ₂).
                                                # Mathematically exact 0.0 whenever the graph
                                                # has >1 connected component -- this is NOT a
                                                # computation failure, it's the correct answer
                                                # to "is the whole graph connected?" (no).
    holdout_offer_pairs: FrozenSet[tuple]      # 20% holdout (component_id, distributor_id) tuples
    # Phase 4 (BENCH-05): sequential-removal λ₂ curve for top-k distributors.
    # Entries: [{"step": int, "removed": int|None, "removed_name": str|None,
    #            "lambda2": float, "delta_pct": float}, ...]
    fiedler_curve: List[dict] = field(default_factory=list)
    # Per-distributor probability of a material disruption over the sourcing horizon,
    # from app.optimization.stochastic.build_failure_probabilities (cited McKinsey
    # base rate -> exposure window -> bounded centrality RANK transform). This is the
    # ONE probability model the whole app uses. It replaces the previous practice of
    # feeding min-max normalized betweenness straight into a Bernoulli draw, which had
    # no base rate, no exposure window and no unit, and which by construction failed
    # the single most central distributor in 100% of scenarios.
    p_disruption: Dict[int, float] = field(default_factory=dict)
    # Provenance for p_disruption, published by /graph/metrics so the assumption is
    # inspectable rather than asserted. Keys: base_annual_prob, horizon_days,
    # centrality_spread, base_horizon_prob, max_failure_prob, source.
    p_disruption_calibration: Dict[str, object] = field(default_factory=dict)
    n_distributors: int = 0
    n_components: int = 0
    # TRUE number of edges in `graph` (deduplicated distributor->component pairs, after
    # the holdout carve). Previously this held len(offer_rows) -- the raw offer-table row
    # count, 8,176 -- and was published as the edge count of a graph that has 5,789
    # edges. The offer-row count is still available as n_offer_rows.
    n_edges: int = 0
    n_offer_rows: int = 0                      # raw DistributorOffer rows read from the DB
    n_holdout_offer_rows: int = 0              # rows carved into the 20% holdout partition
    n_duplicate_offer_rows: int = 0            # train rows collapsed onto an existing edge
    # Gap-audit fix (2026-07-01, "43 components / λ₂=0.0 is analytically useless"):
    # the whole-graph λ₂ above is always 0.0 for this supplier graph because it is
    # genuinely disconnected (many components carried by exactly one distributor,
    # isolated dist/comp nodes with no offers). These fields report the SAME metric
    # computed on the giant (largest) connected component instead, which is what
    # actually says something about how tightly the *main* supplier network is knit.
    n_connected_components: int = 1            # count of connected components in the full graph
    giant_component_size: int = 0              # node count (dist + comp) in the largest component
    giant_component_fraction: float = 0.0      # giant_component_size / total graph nodes
    fiedler_giant_component: float = 0.0       # λ₂ of the largest connected component only


_graph_state: Optional[GraphState] = None


def set_graph_state(state: Optional[GraphState]) -> None:
    global _graph_state
    _graph_state = state


def get_graph_state() -> Optional[GraphState]:
    return _graph_state
