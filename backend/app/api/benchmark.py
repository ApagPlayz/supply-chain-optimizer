"""
Benchmark API endpoints (04-02).

Four public endpoints for the benchmark dashboard:
  GET /benchmark/summary               — Aggregate A/B delta metrics for latest run_id
  GET /benchmark/fiedler-curve         — Sequential-removal λ₂ curve from GraphState
  GET /benchmark/cascade-heatmap       — Per-distributor BOM-collapse probability for maplibre
  GET /benchmark/single-source-components — Real component MPN+manufacturer+sole-source distributor

All endpoints are unauthenticated — public aggregate analytics, no user data (T-04-02-03/04).
"""
from __future__ import annotations

from statistics import mean
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


# ── Pydantic Response Schemas ─────────────────────────────────────────────────

class MonteCarloSummary(BaseModel):
    baseline_p10: float
    baseline_p50: float
    baseline_p90: float
    graph_aware_p10: float
    graph_aware_p50: float
    graph_aware_p90: float
    baseline_evar_95: Optional[float] = None
    graph_aware_evar_95: Optional[float] = None


class TradeoffEntry(BaseModel):
    bom_name: str
    losing_axis: str          # "cost" | "eta" | "risk"
    baseline_value: float
    graph_aware_value: float
    delta_pct: float
    narrative: str            # pre-formatted string for UI tradeoff card body


class BomDelta(BaseModel):
    bom_name: str
    cost_delta_pct: float
    eta_delta_pct: float
    co2_delta_pct: float
    cascade_risk_delta_pct: float


class BenchmarkSummaryResponse(BaseModel):
    run_id: int
    run_tag: str
    timestamp: str            # ISO-8601 of created_at for the run_id
    n_boms: int
    cost_delta_pct: float
    # Dollar-denominated framing (P3). cost_delta_usd is the mean absolute USD
    # difference (graph-aware - baseline) in total landed cost per BOM run;
    # negative => graph-aware saves money. baseline_spend_at_risk_usd is the mean
    # EVaR-95 emergency-procurement premium exposed per baseline BOM
    # (= total_cost_usd * (mc_evar_95 - 1)).
    cost_delta_usd: float
    baseline_spend_at_risk_usd: float
    eta_delta_pct: float
    co2_delta_pct: float
    cascade_risk_delta_pct: float
    monte_carlo: MonteCarloSummary
    tradeoff: TradeoffEntry   # BOM with the worst graph-aware axis
    bom_deltas: List[BomDelta]
    feeds_fallback: bool
    noise_floor_pct: float    # hardcoded 2.0


class FiedlerPoint(BaseModel):
    step: int
    removed: Optional[int] = None
    removed_name: Optional[str] = None
    lambda2: float
    delta_pct: float
    collapsed_boms: List[str] = []


class FiedlerCurveResponse(BaseModel):
    points: List[FiedlerPoint]
    baseline_lambda2: float


class HeatmapPoint(BaseModel):
    lat: float
    lng: float
    weight: float             # mean BOM-collapse probability [0.0, 1.0]
    distributor_id: int
    distributor_name: str


class CascadeHeatmapResponse(BaseModel):
    points: List[HeatmapPoint]


class SingleSourceComponent(BaseModel):
    component_id: int
    mpn: str
    manufacturer: str
    distributor_id: int
    distributor_name: str


class SingleSourceComponentsResponse(BaseModel):
    components: List[SingleSourceComponent]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_graph_state():
    from app.graph import get_graph_state
    gs = get_graph_state()
    if gs is None:
        raise HTTPException(
            status_code=503,
            detail="Graph not loaded — server starting up or graph build failed",
        )
    return gs


def _safe_mean(values: list) -> float:
    """Return mean of a list, or 0.0 if empty."""
    if not values:
        return 0.0
    return mean(values)


def _pct_delta(baseline: float, graph_aware: float) -> float:
    """Compute (graph_aware - baseline) / baseline * 100. Returns 0.0 if baseline is 0."""
    if baseline == 0.0:
        return 0.0
    return (graph_aware - baseline) / abs(baseline) * 100.0


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=BenchmarkSummaryResponse)
def get_benchmark_summary(
    run_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Return aggregated A/B delta metrics for the latest (or specified) run_id.

    Partitions rows into graph_aware=False (baseline) and graph_aware=True groups.
    Computes per-BOM deltas, then aggregates means across all BOMs.
    Delta sign convention: negative = graph-aware is better (cheaper/faster/less risky).
    """
    from app.models.optimization_run import OptimizationRun

    # Determine target run_id
    if run_id is None:
        latest = (
            db.query(OptimizationRun.run_id)
            .order_by(OptimizationRun.run_id.desc())
            .first()
        )
        if latest is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No benchmark rows found. "
                    "Run the benchmark pipeline: python -m seeds.benchmark_pipeline"
                ),
            )
        target_run_id = latest[0]
    else:
        target_run_id = run_id

    # Load all rows for this run_id
    all_rows = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.run_id == target_run_id)
        .all()
    )
    if not all_rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No benchmark rows found for run_id={target_run_id}. "
                "Run the benchmark pipeline: python -m seeds.benchmark_pipeline"
            ),
        )

    baseline_rows = [r for r in all_rows if not r.graph_aware]
    graph_aware_rows = [r for r in all_rows if r.graph_aware]

    if not baseline_rows or not graph_aware_rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Incomplete benchmark data for run_id={target_run_id}. "
                "Run the benchmark pipeline: python -m seeds.benchmark_pipeline"
            ),
        )

    # Gather timestamp from first row
    timestamp_str = (
        all_rows[0].created_at.isoformat()
        if all_rows[0].created_at is not None
        else ""
    )

    # Build per-BOM lookup
    baseline_by_bom: Dict[str, object] = {r.bom_name: r for r in baseline_rows}
    graph_aware_by_bom: Dict[str, object] = {r.bom_name: r for r in graph_aware_rows}

    # Compute per-BOM deltas
    bom_deltas: List[BomDelta] = []
    common_boms = sorted(set(baseline_by_bom.keys()) & set(graph_aware_by_bom.keys()))
    n_boms = len(common_boms)

    for bom in common_boms:
        b = baseline_by_bom[bom]
        g = graph_aware_by_bom[bom]
        bom_deltas.append(BomDelta(
            bom_name=bom,
            cost_delta_pct=_pct_delta(b.total_cost_usd, g.total_cost_usd),
            eta_delta_pct=_pct_delta(b.eta_p50_days, g.eta_p50_days),
            co2_delta_pct=_pct_delta(b.co2_kg, g.co2_kg),
            cascade_risk_delta_pct=_pct_delta(b.cascade_risk_score, g.cascade_risk_score),
        ))

    # Aggregate mean deltas
    cost_delta_pct = _safe_mean([d.cost_delta_pct for d in bom_deltas])

    # Absolute dollar deltas (P3): mean USD saved per BOM run, and the mean
    # EVaR-95 emergency-procurement premium exposed on each baseline BOM.
    cost_delta_usd = _safe_mean([
        graph_aware_by_bom[bom].total_cost_usd - baseline_by_bom[bom].total_cost_usd
        for bom in common_boms
    ])
    baseline_spend_at_risk_usd = _safe_mean([
        baseline_by_bom[bom].total_cost_usd * max(0.0, (baseline_by_bom[bom].mc_evar_95 or 1.0) - 1.0)
        for bom in common_boms
        if baseline_by_bom[bom].total_cost_usd is not None
    ])

    eta_delta_pct = _safe_mean([d.eta_delta_pct for d in bom_deltas])
    co2_delta_pct = _safe_mean([d.co2_delta_pct for d in bom_deltas])
    cascade_risk_delta_pct = _safe_mean([d.cascade_risk_delta_pct for d in bom_deltas])

    # Monte Carlo summary
    def _safe_list_mean(rows, attr: str) -> float:
        vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
        return _safe_mean(vals)

    monte_carlo = MonteCarloSummary(
        baseline_p10=_safe_list_mean(baseline_rows, "eta_p10_days"),
        baseline_p50=_safe_list_mean(baseline_rows, "eta_p50_days"),
        baseline_p90=_safe_list_mean(baseline_rows, "eta_p90_days"),
        graph_aware_p10=_safe_list_mean(graph_aware_rows, "eta_p10_days"),
        graph_aware_p50=_safe_list_mean(graph_aware_rows, "eta_p50_days"),
        graph_aware_p90=_safe_list_mean(graph_aware_rows, "eta_p90_days"),
        baseline_evar_95=_safe_list_mean(baseline_rows, "mc_evar_95") or None,
        graph_aware_evar_95=_safe_list_mean(graph_aware_rows, "mc_evar_95") or None,
    )

    # Tradeoff: find BOM where graph-aware is WORST (highest positive delta on any axis)
    # If all negative, pick closest-to-neutral (smallest absolute negative delta)
    best_bom = bom_deltas[0] if bom_deltas else None
    best_axis = "cost"
    best_delta: Optional[float] = None
    best_baseline = 0.0
    best_ga = 0.0

    for bd in bom_deltas:
        axis_vals = [
            ("cost", bd.cost_delta_pct,
             baseline_by_bom[bd.bom_name].total_cost_usd,
             graph_aware_by_bom[bd.bom_name].total_cost_usd),
            ("eta", bd.eta_delta_pct,
             baseline_by_bom[bd.bom_name].eta_p50_days,
             graph_aware_by_bom[bd.bom_name].eta_p50_days),
            ("risk", bd.cascade_risk_delta_pct,
             baseline_by_bom[bd.bom_name].cascade_risk_score,
             graph_aware_by_bom[bd.bom_name].cascade_risk_score),
        ]
        for axis, delta, b_val, g_val in axis_vals:
            if best_delta is None:
                best_bom = bd
                best_axis = axis
                best_delta = delta
                best_baseline = b_val
                best_ga = g_val
            else:
                # Prefer highest positive delta (worst outcome for graph-aware)
                if delta > best_delta:
                    best_bom = bd
                    best_axis = axis
                    best_delta = delta
                    best_baseline = b_val
                    best_ga = g_val

    tradeoff = TradeoffEntry(
        bom_name=best_bom.bom_name if best_bom else "unknown",
        losing_axis=best_axis,
        baseline_value=best_baseline,
        graph_aware_value=best_ga,
        delta_pct=best_delta if best_delta is not None else 0.0,
        narrative=(
            f"{best_bom.bom_name if best_bom else 'unknown'}: graph-aware is "
            f"+{best_delta:.1f}% {best_axis} because the cheapest distributor carries "
            "a high-centrality component and graph-aware routes around it."
        ),
    )

    # feeds_fallback: True if any row has a False feed value
    feeds_fallback = False
    for row in all_rows:
        if row.feeds_available:
            if isinstance(row.feeds_available, dict):
                if any(v is False for v in row.feeds_available.values()):
                    feeds_fallback = True
                    break

    return BenchmarkSummaryResponse(
        run_id=target_run_id,
        run_tag=all_rows[0].run_tag,
        timestamp=timestamp_str,
        n_boms=n_boms,
        cost_delta_pct=cost_delta_pct,
        cost_delta_usd=round(cost_delta_usd, 2),
        baseline_spend_at_risk_usd=round(baseline_spend_at_risk_usd, 2),
        eta_delta_pct=eta_delta_pct,
        co2_delta_pct=co2_delta_pct,
        cascade_risk_delta_pct=cascade_risk_delta_pct,
        monte_carlo=monte_carlo,
        tradeoff=tradeoff,
        bom_deltas=bom_deltas,
        feeds_fallback=feeds_fallback,
        noise_floor_pct=2.0,
    )


@router.get("/fiedler-curve", response_model=FiedlerCurveResponse)
def get_fiedler_curve():
    """
    Return the sequential-removal Fiedler λ₂ curve from pre-computed GraphState.

    Step 0 is the baseline (no removal). Subsequent steps show λ₂ after removing
    the most-central distributor. collapsed_boms lists BOM names that become
    unfulfillable at each step.
    """
    gs = _require_graph_state()

    if not gs.fiedler_curve:
        raise HTTPException(
            status_code=503,
            detail="Fiedler curve not computed — check server startup logs",
        )

    points = []
    for entry in gs.fiedler_curve:
        points.append(FiedlerPoint(
            step=entry["step"],
            removed=entry.get("removed"),
            removed_name=entry.get("removed_name"),
            lambda2=entry["lambda2"],
            delta_pct=entry["delta_pct"],
            collapsed_boms=entry.get("collapsed_boms", []),
        ))

    baseline_lambda2 = gs.fiedler_curve[0]["lambda2"]
    return FiedlerCurveResponse(points=points, baseline_lambda2=baseline_lambda2)


@router.get("/cascade-heatmap", response_model=CascadeHeatmapResponse)
def get_cascade_heatmap(db: Session = Depends(get_db)):
    """
    Return per-distributor BOM-collapse probability for maplibre heatmap-layer rendering.

    If no optimization_runs rows exist, returns an empty points list (not 404).
    Weight is derived from mean cascade_risk_score across runs where each distributor
    was selected, normalized to [0, 1].
    """
    _require_graph_state()

    from app.models.optimization_run import OptimizationRun
    from app.models.distributor import Distributor

    # Find latest run_id
    latest = (
        db.query(OptimizationRun.run_id)
        .order_by(OptimizationRun.run_id.desc())
        .first()
    )
    if latest is None:
        return CascadeHeatmapResponse(points=[])

    target_run_id = latest[0]
    all_rows = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.run_id == target_run_id)
        .all()
    )

    if not all_rows:
        return CascadeHeatmapResponse(points=[])

    # Compute per-distributor mean cascade_risk_score
    dist_risk_accumulator: Dict[int, List[float]] = {}
    for row in all_rows:
        dist_ids = row.selected_distributor_ids or []
        if isinstance(dist_ids, list):
            for did in dist_ids:
                if isinstance(did, int):
                    dist_risk_accumulator.setdefault(did, []).append(
                        row.cascade_risk_score
                    )

    if not dist_risk_accumulator:
        return CascadeHeatmapResponse(points=[])

    # Compute raw weights
    raw_weights: Dict[int, float] = {
        did: _safe_mean(scores)
        for did, scores in dist_risk_accumulator.items()
    }
    max_weight = max(raw_weights.values()) if raw_weights else 1.0
    if max_weight == 0.0:
        max_weight = 1.0

    # Fetch distributor details
    dist_ids_list = list(raw_weights.keys())
    distributors = (
        db.query(Distributor)
        .filter(Distributor.id.in_(dist_ids_list))
        .all()
    )
    dist_map = {d.id: d for d in distributors}

    points = []
    for did, raw_w in raw_weights.items():
        dist = dist_map.get(did)
        if dist is None:
            continue
        normalized_weight = raw_w / max_weight
        if normalized_weight > 0:
            points.append(HeatmapPoint(
                lat=dist.latitude,
                lng=dist.longitude,
                weight=round(normalized_weight, 4),
                distributor_id=dist.id,
                distributor_name=dist.name,
            ))

    return CascadeHeatmapResponse(points=points)


@router.get("/single-source-components", response_model=SingleSourceComponentsResponse)
def get_single_source_components(db: Session = Depends(get_db)):
    """
    Return real component MPN + manufacturer + sole-source distributor from ORM joins.

    Reads GraphState.single_source_component_ids (frozenset[int]) then joins to
    Component and DistributorOffer tables to return authoritative catalog data.

    CRITICAL: mpn and manufacturer come ONLY from the Component ORM row — no fabricated
    strings, no distributor fields used as manufacturer values (VIZ-02, D-05).
    """
    gs = _require_graph_state()

    component_ids = list(gs.single_source_component_ids)
    if not component_ids:
        return SingleSourceComponentsResponse(components=[])

    from app.models.component import Component, DistributorOffer
    from app.models.distributor import Distributor

    components = (
        db.query(Component)
        .filter(Component.id.in_(component_ids))
        .all()
    )

    results = []
    for comp in components:
        # Find stocked offers for this component
        offers = (
            db.query(DistributorOffer)
            .filter(
                DistributorOffer.component_id == comp.id,
                DistributorOffer.stock > 0,
            )
            .all()
        )
        if not offers:
            # Fallback: any offer
            offers = (
                db.query(DistributorOffer)
                .filter(DistributorOffer.component_id == comp.id)
                .limit(1)
                .all()
            )
        if not offers:
            continue

        offer = offers[0]
        dist = (
            db.query(Distributor)
            .filter(Distributor.id == offer.distributor_id)
            .first()
        )
        if not dist:
            continue

        results.append(SingleSourceComponent(
            component_id=comp.id,
            mpn=comp.mpn,                              # REAL catalog MPN
            manufacturer=comp.manufacturer or "Unknown",   # REAL manufacturer name
            distributor_id=dist.id,
            distributor_name=dist.name,
        ))

    return SingleSourceComponentsResponse(components=results)
