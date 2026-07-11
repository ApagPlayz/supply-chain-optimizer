"""
Graph ML API endpoints.

GET  /graph/metrics   — Returns supply graph topology metrics (no auth required).
POST /graph/simulate  — Runs Monte Carlo cascade simulation (no auth required).

Both endpoints are public — they expose only aggregate analytics with no prices,
user data, or sensitive offer details (T-02-04 mitigation).
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator

router = APIRouter(prefix="/graph", tags=["graph"])


# ── Request / Response schemas ────────────────────────────────────────────────

class SimulateRequest(BaseModel):
    bom_component_ids: List[int]

    @validator("bom_component_ids")
    def _max_length(cls, v):
        if len(v) > 200:
            raise ValueError("bom_component_ids must not exceed 200 items")
        return v


class SimulateResponse(BaseModel):
    p10: float
    p50: float
    p90: float
    cvar_95: float
    n_scenarios: int
    seed: int


class GraphMetricsResponse(BaseModel):
    n_distributors: int
    n_components: int
    n_edges: int
    fiedler: float
    single_source_count: int
    betweenness: Dict[str, float]   # str keys for JSON serialization (distributor_id)
    pagerank: Dict[str, float]
    k_core_summary: Dict[int, int]  # {core_number: node_count}
    hhi_by_category: Dict[str, float]


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _require_graph_state():
    from app.graph import get_graph_state
    gs = get_graph_state()
    if gs is None:
        raise HTTPException(
            status_code=503,
            detail="Graph not loaded — server starting up or graph build failed",
        )
    return gs


@router.get("/metrics", response_model=GraphMetricsResponse)
def get_graph_metrics():
    """
    Return supply graph topology metrics.

    All metrics are computed from real offer data in the live database.
    Response contains only aggregate analytics — no prices, no user data (T-02-04).
    """
    gs = _require_graph_state()

    # k_core_summary: count of nodes at each core level
    k_core_summary = dict(Counter(gs.k_core.values()))

    return GraphMetricsResponse(
        n_distributors=gs.n_distributors,
        n_components=gs.n_components,
        n_edges=gs.n_edges,
        fiedler=gs.fiedler,
        single_source_count=len(gs.single_source_component_ids),
        betweenness={str(k): round(v, 6) for k, v in gs.betweenness.items()},
        pagerank={str(k): round(v, 6) for k, v in gs.pagerank.items()},
        k_core_summary=k_core_summary,
        hhi_by_category={k: round(v, 2) for k, v in gs.hhi_by_category.items()},
    )


@router.post("/simulate", response_model=SimulateResponse)
def post_graph_simulate(body: SimulateRequest):
    """
    Run Monte Carlo cascade failure simulation.

    N=1,000 scenarios with fixed seed=42 — reproducible output.
    N is not user-configurable (T-02-03 mitigation).
    """
    gs = _require_graph_state()

    from app.graph.simulation import run_monte_carlo, N_SCENARIOS
    result = run_monte_carlo(
        gs,
        bom_component_ids=body.bom_component_ids,
        n_scenarios=N_SCENARIOS,  # always constant, never from request
        seed=42,
    )

    return SimulateResponse(
        p10=result.p10,
        p50=result.p50,
        p90=result.p90,
        cvar_95=result.cvar_95,
        n_scenarios=result.n_scenarios,
        seed=result.seed,
    )
