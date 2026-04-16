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
from typing import Optional, Dict, FrozenSet
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
    fiedler: float                             # algebraic connectivity; 0.0 if disconnected
    holdout_offer_pairs: FrozenSet[tuple]      # 20% holdout (component_id, distributor_id) tuples
    n_distributors: int
    n_components: int
    n_edges: int


_graph_state: Optional[GraphState] = None


def set_graph_state(state: Optional[GraphState]) -> None:
    global _graph_state
    _graph_state = state


def get_graph_state() -> Optional[GraphState]:
    return _graph_state
