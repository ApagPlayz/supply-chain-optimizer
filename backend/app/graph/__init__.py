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
    pagerank: Dict[int, float]                 # distributor_id -> normalized [0,1] PageRank
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
    n_distributors: int = 0
    n_components: int = 0
    n_edges: int = 0
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
