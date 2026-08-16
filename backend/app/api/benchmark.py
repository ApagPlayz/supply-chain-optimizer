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

import json
import logging
from functools import lru_cache
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmark", tags=["benchmark"])

# ── Named, disclosed modelling assumption ─────────────────────────────────────
# The benchmark scores ONE representative reorder per BOM. To annualize the
# per-BOM MILP savings we assume each BOM is re-ordered this many times per
# year. This is an openly-stated assumption surfaced in the API response
# (`annual_reorders`), not a measured procurement cadence.
ANNUAL_REORDERS = 12

# ── The retracted headline ────────────────────────────────────────────────────
# `docs/BENCHMARK_VOLUME_CURVE.md` retracted "the optimizer is 44.7% cheaper" in
# July 2026 and `docs/RESILIENCE_INTERVIEW_GUIDE.md` says verbatim "DO NOT say my
# optimizer is 44.7% cheaper". The retraction landed in every document but never in
# this API, which kept serving `savings_pct: 48.09` as a bare headline off a run of
# 4-line, 5-to-9-unit prototype BOMs. This endpoint now serves the volume curve and
# the decomposition instead, with the prototype-volume figure explicitly labelled as
# an artifact of a per-supplier fixed fee.
RETRACTED_HEADLINE = "the CP-SAT optimizer is ~44.7% cheaper than a greedy baseline"

# Repo root: app/api/benchmark.py -> app -> backend -> <repo>
_REPO_ROOT = Path(__file__).resolve().parents[3]
_VOLUME_SWEEP_PATH = _REPO_ROOT / "docs" / "volume_sweep.json"

# Production volume, for the honest headline range. The sweep's own caveat: the
# high-multiplier rows are a smaller BOM cohort than the low ones (stock ceilings knock
# BOMs out as volume rises), so the trustworthy statement is a RANGE over this band,
# never a single number.
_PRODUCTION_MULTIPLIER_MIN = 500


# ── Pydantic Response Schemas ─────────────────────────────────────────────────

class MonteCarloSummary(BaseModel):
    baseline_p10: float
    baseline_p50: float
    baseline_p90: float
    graph_aware_p10: float
    graph_aware_p50: float
    graph_aware_p90: float
    baseline_cvar_95: Optional[float] = None
    graph_aware_cvar_95: Optional[float] = None


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


class VolumeCurvePoint(BaseModel):
    """One multiplier on the greedy-vs-MILP volume sweep.

    Costs are POOLED — sum(greedy) / sum(MILP) across the BOMs feasible at that
    multiplier — not a mean of per-BOM percentages. Mixing the two aggregations is
    how the original inconsistency happened.

    Several fields carry a short alias as well as the descriptive name (e.g.
    `fixed_fee_usd` beside `saving_from_fixed_fees_usd`). That is deliberate: the
    Benchmark page's curve normalizer reads the short names, and serving both means
    the UI renders THIS endpoint's live numbers rather than a checked-in fallback
    copy of the same artifact that can silently drift.
    """
    multiplier: int
    boms_feasible: int
    # Units per BOM at this multiplier — the "these are toy orders" evidence.
    units_min: int
    units_max: int
    greedy_cost_usd: float
    milp_cost_usd: float
    pooled_savings_pct: float
    savings_pct: float                       # alias of pooled_savings_pct
    saving_from_fixed_fees_usd: float
    fixed_fee_usd: float                     # alias
    saving_from_component_cost_usd: float
    component_usd: float                     # alias
    saving_from_variable_freight_usd: float
    variable_freight_usd: float              # alias
    fixed_fee_share_of_saving_pct: Optional[float] = None
    fee_share_of_saving_pct: Optional[float] = None   # alias
    # Fixed per-supplier fees as a share of the GREEDY baseline's total landed cost.
    # At 1x this is ~80% — i.e. four fifths of the cost being "optimized" is a fee
    # for opening a supplier account, which is the whole retraction in one number.
    greedy_fixed_share_of_cost_pct: Optional[float] = None
    suppliers_greedy: int
    suppliers_milp: int


class VolumeCurve(BaseModel):
    """The savings-vs-volume decay curve, with the caveats that make it readable."""
    available: bool
    source: str
    generated_utc: Optional[str] = None
    aggregate_definition: str
    points: List[VolumeCurvePoint] = []
    cohort_caveat: str = ""
    unavailable_reason: Optional[str] = None
    # The single constant the retracted headline was really measuring: the fixed
    # per-supplier freight fee (LTL base x the strategy's transport penalty scale).
    fixed_fee_per_supplier_usd: Optional[float] = None


class SavingsDecomposition(BaseModel):
    """Where a saving actually comes from, in dollars, at one volume."""
    multiplier: int
    total_saving_usd: float
    from_fixed_supplier_fees_usd: float
    from_component_cost_usd: float
    from_variable_freight_usd: float
    dominant_term: str
    note: str


class Headline(BaseModel):
    """
    The honest answer to 'how much does the optimizer save?', which is a RANGE that
    depends on order volume — not one percentage.
    """
    statement: str
    retracted_claim: str
    retraction_reason: str
    savings_pct_at_prototype_volume: Optional[float] = None
    prototype_volume_units: Optional[int] = None
    savings_pct_at_production_volume_low: Optional[float] = None
    savings_pct_at_production_volume_high: Optional[float] = None
    production_volume_units_low: Optional[int] = None
    production_volume_units_high: Optional[int] = None
    dominant_mechanism_at_prototype_volume: str
    dominant_mechanism_at_production_volume: str
    do_not_quote_a_single_percentage: bool = True


class ResilienceSection(BaseModel):
    """
    Value of resilience: graph-aware MILP vs blind MILP.

    nominal_cost_premium_pct — mean per-BOM (graph_aware - blind) / blind * 100 of
      nominal landed cost. Negative = graph-aware is cheaper; expected ~0 (the
      graph-aware plan buys tail protection at near-zero nominal premium).

    *_cascade_risk_reduction — mean (blind.plan_cascade_risk - graph.plan_cascade_risk)
      under each disruption scenario. Positive = graph-aware LOWERS collapse risk.
    *_cvar95_reduction — mean (blind.mc_cvar_95 - graph.mc_cvar_95). Positive =
      graph-aware LOWERS the worst-5% emergency-cost multiplier.
    """
    nominal_cost_premium_pct: float
    stress_cascade_risk_reduction: float
    stress_cvar95_reduction: float
    targeted_cascade_risk_reduction: float
    targeted_cvar95_reduction: float
    # A reduction of exactly 0.0 means the two arms scored IDENTICALLY on that metric
    # under that scenario — a real measurement, not a missing one. The raw arm values
    # are published beside it so nobody has to take that on trust, and the
    # interpretation names any metric that came out flat.
    measured_values: Dict[str, Optional[float]] = {}
    flat_metrics: List[str] = []
    interpretation: str = ""


class BenchmarkSummaryResponse(BaseModel):
    run_id: int
    run_tag: str
    # `run_tag` is opaque on its own — the deployed instance serves
    # "static_fallback" with no indication of what that implies about the numbers.
    run_tag_meaning: str = ""
    timestamp: str            # ISO-8601 of created_at for the run_id
    n_boms: int
    # ── The honest headline: a volume-dependent range, not a number ───────────
    headline: Headline
    volume_curve: VolumeCurve
    decomposition_at_prototype_volume: Optional[SavingsDecomposition] = None
    decomposition_at_production_volume: Optional[SavingsDecomposition] = None
    caveats: List[str] = []
    # ── Flat scalars the Benchmark page reads directly ────────────────────────
    # Same numbers as `headline` / `volume_curve`, promoted to the top level and to
    # the names the UI already looks for, so the page renders THIS endpoint's live
    # values instead of a checked-in copy of the artifact that can drift from it.
    headline_retracted: bool = True
    retraction_note: str = ""
    realistic_savings_pct_low: Optional[float] = None
    realistic_savings_pct_high: Optional[float] = None
    fixed_fee_share_of_savings_pct: Optional[float] = None
    fixed_fee_share_of_cost_pct: Optional[float] = None
    fixed_fee_per_supplier_usd: Optional[float] = None
    mean_units_per_bom: Optional[int] = None
    # ── Value of optimization: MILP (arm='milp', blind) vs greedy baselines ────
    # savings_pct — mean per-BOM (greedy - milp) / greedy * 100, MEASURED ON THIS RUN
    #   ONLY. This run's BOMs are 4 lines / 5–9 units, so this figure is the
    #   PROTOTYPE-volume number and it is dominated by a $75-per-supplier fixed fee.
    #   It is NOT the optimizer's saving at any volume a buyer would actually order —
    #   read `headline` and `volume_curve` for that. `savings_units` names the unit so
    #   it cannot be confused with the USD fields below (the two have coincidentally
    #   equal values on run_id=4: savings_pct 48.09 % and cost_delta_usd $48.09).
    # savings_usd_per_bom — mean per-BOM (greedy - milp) landed cost, one reorder.
    # savings_usd_annualized — savings_usd_per_bom * annual_reorders (disclosed).
    savings_pct: float
    savings_units: str = "percent"
    savings_pct_is_prototype_volume_only: bool = True
    # Display-ready label for `savings_pct`. A UI that renders the bare number will
    # reproduce the retracted headline; render this string instead.
    savings_pct_display_label: str = ""
    savings_usd_per_bom: float
    savings_usd_annualized: float
    annual_reorders: int
    avg_suppliers_greedy: float
    avg_suppliers_milp: float
    benchmark_volume_note: str = ""
    # ── Value of resilience: graph-aware vs blind MILP (nominal + disruption) ──
    resilience: ResilienceSection
    # ── Legacy graph-aware-vs-blind A/B fields (now filtered to arm='milp',
    #    scenario='nominal'). Negative = graph-aware cheaper/faster/less risky. ──
    cost_delta_pct: float
    # Dollar-denominated framing (P3). cost_delta_usd is the mean absolute USD
    # difference (graph-aware - baseline) in total landed cost per BOM run;
    # negative => graph-aware saves money. baseline_spend_at_risk_usd is the mean
    # CVaR-95 emergency-procurement premium exposed per baseline BOM
    # (= total_cost_usd * (mc_cvar_95 - 1)).
    #
    # ON THE 48.09 COINCIDENCE (2026-08 audit): the audit flagged
    # `cost_delta_usd: 48.09` sitting beside `savings_pct: 48.09` as a percentage in a
    # USD field. It is not — the two are computed from different arms by different
    # formulas and happen to agree to two decimals on run_id=4:
    #   savings_pct    = mean over BOMs of (greedy - blind_milp) / greedy * 100
    #                  = 48.09 PERCENT
    #   cost_delta_usd = mean over BOMs of (graph_aware_milp - blind_milp)
    #                  = 433.64 - 385.54 = 48.09 US DOLLARS
    # `cost_delta_units` and `savings_units` are published so no reader has to take
    # that on trust, and `cost_delta_pct` (23.68) is the percentage partner of
    # cost_delta_usd — it is cost_delta_pct, not savings_pct, that shares its arms.
    cost_delta_usd: float
    cost_delta_units: str = "usd"
    baseline_spend_at_risk_usd: float
    eta_delta_pct: float
    co2_delta_pct: float
    # Sourced from `plan_cascade_risk`, NOT from the dead `cascade_risk_score` column.
    # See `cascade_risk_metric` for why.
    cascade_risk_delta_pct: float
    cascade_risk_metric: str = ""
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
    # A heatmap that renders nothing must say why. Previously this returned
    # `{"points": []}` on a database with 234 perfectly good rows, because the weight
    # column it read was structurally 0.0 and a `normalized_weight > 0` guard then
    # dropped every point.
    metric: str = ""
    run_id: Optional[int] = None
    n_distributors_scored: int = 0
    max_raw_weight: float = 0.0
    note: str = ""


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


def _pct_delta(baseline: Optional[float], graph_aware: Optional[float]) -> float:
    """Compute (graph_aware - baseline) / baseline * 100. Returns 0.0 if baseline is 0."""
    if baseline is None or graph_aware is None or baseline == 0.0:
        return 0.0
    return (graph_aware - baseline) / abs(baseline) * 100.0


# ── The volume curve: the honest replacement for the retracted headline ───────

_CASCADE_RISK_METRIC = (
    "plan_cascade_risk = 1 - median fulfillment of the SELECTED sourcing plan under "
    "the Monte Carlo. The sibling column `cascade_risk_score` is DEAD and is no longer "
    "read by this API: the benchmark seed pipeline computes it as 1 - median "
    "fulfillment over the WHOLE distributor network, and with 97.7% of components "
    "carried by two or more distributors that median is 1.0 in essentially every "
    "trial, so the column is exactly 0.0 in all 234 rows ever written. A metric that "
    "is structurally incapable of being non-zero cannot express a delta, which is why "
    "cascade_risk_delta_pct used to be 0.0 for every BOM and /benchmark/cascade-heatmap "
    "returned an empty points list."
)

_AGGREGATE_DEFINITION = (
    "POOLED: sum(greedy costs) / sum(MILP costs) across the BOMs feasible at that "
    "multiplier — NOT a mean of per-BOM percentages. Mixing the two aggregations is "
    "how the original 44.7% inconsistency arose. Arm = `milp_matched`: greedy and "
    "MILP see the SAME offer pool (us_only=False for both), which the published "
    "benchmark run does not do. Points where greedy's plan orders more units than "
    "exist are excluded — greedy cannot be allowed to win with an unexecutable plan."
)

_COHORT_CAVEAT = (
    "The high-volume rows are a DIFFERENT, SMALLER BOM cohort than the low-volume "
    "ones — stock ceilings knock BOMs out as volume rises (10 BOMs feasible at 1x, "
    "2 at 10,000x). This curve is not a like-for-like cohort and must not be read as "
    "one. The trustworthy statement is the RANGE at production volume, not any single "
    "point on it."
)


@lru_cache(maxsize=1)
def _load_volume_curve() -> VolumeCurve:
    """
    Build the savings-vs-volume curve from `docs/volume_sweep.json`.

    The numbers are POOLED here rather than copied from the markdown, so the API can
    never drift from the published data the way the retracted 44.7% headline did.
    If the sweep artifact is missing the curve is returned as UNAVAILABLE with a
    reason — it is never replaced by a single headline percentage.
    """
    if not _VOLUME_SWEEP_PATH.exists():
        logger.warning("volume_sweep.json not found at %s", _VOLUME_SWEEP_PATH)
        return VolumeCurve(
            available=False,
            source=str(_VOLUME_SWEEP_PATH.relative_to(_REPO_ROOT)),
            aggregate_definition=_AGGREGATE_DEFINITION,
            unavailable_reason=(
                "docs/volume_sweep.json is missing. Regenerate it with "
                "`cd backend && python -m seeds.run_volume_sweep` (~1s). Until then "
                "this API cannot state how the saving varies with order volume, and "
                "no single savings percentage should be quoted."
            ),
        )

    try:
        raw: Dict[str, Any] = json.loads(_VOLUME_SWEEP_PATH.read_text())
    except Exception as exc:  # noqa: BLE001 — a bad artifact must not 500 the endpoint
        logger.warning("volume_sweep.json unreadable: %s", exc)
        return VolumeCurve(
            available=False,
            source=str(_VOLUME_SWEEP_PATH.relative_to(_REPO_ROOT)),
            aggregate_definition=_AGGREGATE_DEFINITION,
            unavailable_reason=f"docs/volume_sweep.json could not be parsed: {exc}",
        )

    meta = raw.get("meta", {})
    boms: Dict[str, Any] = raw.get("boms", {})
    points: List[VolumeCurvePoint] = []

    for multiplier in meta.get("multiplier_grid", []):
        greedy_total = milp_total = 0.0
        greedy_fixed_total = 0.0
        fees = comp = freight = 0.0
        sup_g = sup_m = 0
        n_feasible = 0
        units: List[int] = []
        for bom in boms.values():
            match = [p for p in bom.get("points", []) if p.get("multiplier") == multiplier]
            if not match:
                continue
            point = match[0]
            arms = point.get("arms", {})
            greedy_arm = arms.get("greedy", {})
            milp_arm = arms.get("milp_matched", {})
            if not greedy_arm.get("feasible") or not milp_arm.get("feasible"):
                continue
            # Greedy's fallback can order more units than an offer holds. Such a plan
            # cannot be executed, so it must not be allowed to inflate greedy's cost.
            if greedy_arm.get("stock_violations"):
                continue
            versus = point.get("vs_milp_matched", {})
            greedy_total += greedy_arm.get("total_cost", 0.0)
            greedy_fixed_total += greedy_arm.get("fixed_fee_usd", 0.0)
            milp_total += milp_arm.get("total_cost", 0.0)
            fees += versus.get("saving_from_fixed_fees_usd", 0.0)
            comp += versus.get("saving_from_component_cost_usd", 0.0)
            freight += versus.get("saving_from_variable_freight_usd", 0.0)
            sup_g += versus.get("suppliers_greedy", 0)
            sup_m += versus.get("suppliers_milp", 0)
            units.append(int(point.get("total_units", 0)))
            n_feasible += 1

        if not n_feasible or greedy_total <= 0:
            continue
        saving = greedy_total - milp_total
        pooled_pct = round(saving / greedy_total * 100.0, 2)
        fee_share = round(fees / saving * 100.0, 1) if abs(saving) > 1e-9 else None
        points.append(VolumeCurvePoint(
            multiplier=int(multiplier),
            boms_feasible=n_feasible,
            units_min=min(units) if units else 0,
            units_max=max(units) if units else 0,
            greedy_cost_usd=round(greedy_total, 2),
            milp_cost_usd=round(milp_total, 2),
            pooled_savings_pct=pooled_pct,
            savings_pct=pooled_pct,
            saving_from_fixed_fees_usd=round(fees, 2),
            fixed_fee_usd=round(fees, 2),
            saving_from_component_cost_usd=round(comp, 2),
            component_usd=round(comp, 2),
            saving_from_variable_freight_usd=round(freight, 2),
            variable_freight_usd=round(freight, 2),
            fixed_fee_share_of_saving_pct=fee_share,
            fee_share_of_saving_pct=fee_share,
            greedy_fixed_share_of_cost_pct=round(
                greedy_fixed_total / greedy_total * 100.0, 1
            ),
            suppliers_greedy=sup_g,
            suppliers_milp=sup_m,
        ))

    # The fixed per-supplier fee the cost model actually charges: the domestic LTL
    # base fee scaled by the strategy's transport penalty. This single constant is
    # what the retracted headline was measuring.
    try:
        fee = float(meta["cost_constants"]["LTL_BASE_FEE_USD"]) * float(
            meta["strategy_weights"]["transport_penalty_scale"]
        )
    except Exception:  # noqa: BLE001 — an older artifact simply omits it
        fee = 0.0

    return VolumeCurve(
        available=bool(points),
        source=str(_VOLUME_SWEEP_PATH.relative_to(_REPO_ROOT)),
        generated_utc=meta.get("generated_utc"),
        fixed_fee_per_supplier_usd=round(fee, 2) if fee else None,
        aggregate_definition=_AGGREGATE_DEFINITION,
        points=points,
        cohort_caveat=_COHORT_CAVEAT,
        unavailable_reason=None if points else "The sweep contains no feasible points.",
    )


def _decompose(point: VolumeCurvePoint, label: str) -> SavingsDecomposition:
    """Name the term that actually produced the saving at one volume."""
    terms = {
        "fixed per-supplier fees": point.saving_from_fixed_fees_usd,
        "component cost": point.saving_from_component_cost_usd,
        "variable freight": point.saving_from_variable_freight_usd,
    }
    dominant = max(terms, key=lambda k: abs(terms[k]))
    total = point.greedy_cost_usd - point.milp_cost_usd
    if dominant == "fixed per-supplier fees":
        note = (
            f"At {label} the saving is fee arithmetic, not optimization. The greedy "
            f"baseline picks min(price) per line, so it is the component-cost minimum "
            f"BY CONSTRUCTION — the MILP cannot beat it on parts and here pays "
            f"${abs(point.saving_from_component_cost_usd):,.0f} MORE for them. What it "
            f"avoids is a $75 LTL / $150 air fee charged per opened supplier (x1.5 "
            f"transport_penalty_scale), by consolidating "
            f"{point.suppliers_greedy} suppliers into {point.suppliers_milp}. That fee "
            "is roughly constant in volume while component cost grows linearly, so the "
            "percentage must decay — and it does."
        )
    elif dominant == "variable freight":
        note = (
            f"At {label} the saving is real optimization and it SURVIVES volume: the "
            f"MILP routes each line's units to whichever distributor minimizes price + "
            f"freight, which greedy structurally cannot see. It now opens MORE "
            f"suppliers than greedy ({point.suppliers_greedy} -> "
            f"{point.suppliers_milp}) and pays more in per-visit fees on purpose, to "
            "buy down freight and stay inside stock caps."
        )
    else:
        note = f"At {label} the dominant term is component cost."
    return SavingsDecomposition(
        multiplier=point.multiplier,
        total_saving_usd=round(total, 2),
        from_fixed_supplier_fees_usd=point.saving_from_fixed_fees_usd,
        from_component_cost_usd=point.saving_from_component_cost_usd,
        from_variable_freight_usd=point.saving_from_variable_freight_usd,
        dominant_term=dominant,
        note=note,
    )


def _build_headline(curve: VolumeCurve) -> Headline:
    """The volume-dependent truth, phrased so it cannot be quoted as one number."""
    retraction_reason = (
        "Retracted 2026-07-13 (docs/BENCHMARK_VOLUME_CURVE.md, commit 4b4c5b2). The "
        "benchmark scores 4-line BOMs of 5-9 TOTAL UNITS. At that size a fixed "
        "$75-per-supplier LTL fee (x1.5) is larger than the parts, so consolidating "
        "suppliers dominates everything else. The fee does not grow with volume and "
        "component cost does, so the percentage decays. docs/"
        "RESILIENCE_INTERVIEW_GUIDE.md states it plainly: do not say the optimizer is "
        "44.7% cheaper."
    )
    common = {
        "retracted_claim": RETRACTED_HEADLINE,
        "retraction_reason": retraction_reason,
        "dominant_mechanism_at_prototype_volume":
            "avoided fixed per-supplier onboarding fees (an artifact of toy quantities)",
        "dominant_mechanism_at_production_volume":
            "variable freight — routing units by landed cost rather than unit price "
            "(genuine, volume-scaling optimization)",
    }

    if not curve.available or not curve.points:
        return Headline(
            statement=(
                "No savings figure can be stated: the volume sweep that grounds it is "
                "unavailable. A single savings percentage is not a valid answer for "
                "this optimizer at any volume."
            ),
            **common,
        )

    by_mult = {p.multiplier: p for p in curve.points}
    prototype = by_mult.get(1) or curve.points[0]
    production = [p for p in curve.points if p.multiplier >= _PRODUCTION_MULTIPLIER_MIN]
    if production:
        lows = min(p.pooled_savings_pct for p in production)
        highs = max(p.pooled_savings_pct for p in production)
        lo_mult = min(p.multiplier for p in production)
        hi_mult = max(p.multiplier for p in production)
        statement = (
            f"The MILP's cost edge over a greedy baseline is VOLUME-DEPENDENT: "
            f"{prototype.pooled_savings_pct:.1f}% on the benchmark's "
            f"{prototype.multiplier}x prototype BOMs, decaying to "
            f"{lows:.1f}%-{highs:.1f}% at production volume "
            f"({lo_mult}x-{hi_mult}x). The prototype figure is a fixed per-supplier fee "
            f"(${prototype.saving_from_fixed_fees_usd:,.0f} of a "
            f"${prototype.greedy_cost_usd - prototype.milp_cost_usd:,.0f} saving — the "
            f"MILP actually pays "
            f"${abs(prototype.saving_from_component_cost_usd):,.0f} MORE for the parts). "
            "The production figure is genuine freight optimization. Quote the range, "
            "not a number."
        )
    else:
        lows = highs = None
        lo_mult = hi_mult = None
        statement = (
            f"The sweep only reaches {max(by_mult)}x, below the "
            f"{_PRODUCTION_MULTIPLIER_MIN}x production band, so no production-volume "
            "range can be stated."
        )

    return Headline(
        statement=statement,
        savings_pct_at_prototype_volume=prototype.pooled_savings_pct,
        prototype_volume_units=None,
        savings_pct_at_production_volume_low=lows,
        savings_pct_at_production_volume_high=highs,
        production_volume_units_low=lo_mult,
        production_volume_units_high=hi_mult,
        **common,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=BenchmarkSummaryResponse)
def get_benchmark_summary(
    run_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Return two stories for the latest (or specified) run_id.

    (1) VALUE OF OPTIMIZATION — partitions nominal rows by arm (greedy vs milp)
        and reports savings_pct / savings_usd_* and supplier consolidation.
    (2) VALUE OF RESILIENCE — the two MILP arms (blind vs graph-aware): ~0 nominal
        cost premium, but cascade-risk and CVaR-95 reduction under stress/targeted
        disruption.

    Legacy graph-aware-vs-blind delta fields are retained (now filtered to
    arm='milp', scenario='nominal'). Delta sign convention preserved:
    negative = graph-aware is cheaper/faster/less risky.
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

    # Partition rows by arm/scenario (benchmark 2.0 schema). Legacy rows written
    # before arm/scenario existed (both NULL) are treated as milp/nominal so the
    # graph-aware A/B still works on older run_ids.
    def _arm(r) -> str:
        return r.arm or "milp"

    def _scen(r) -> str:
        return r.scenario or "nominal"

    # Value-of-resilience A/B compares the two MILP arms in the NOMINAL world.
    milp_nominal = [r for r in all_rows if _arm(r) == "milp" and _scen(r) == "nominal"]
    baseline_rows = [r for r in milp_nominal if not r.graph_aware]   # blind MILP
    graph_aware_rows = [r for r in milp_nominal if r.graph_aware]    # graph-aware MILP
    # Value-of-optimization compares greedy baseline vs (blind) MILP, nominal.
    greedy_nominal = [r for r in all_rows if _arm(r) == "greedy" and _scen(r) == "nominal"]

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
            # `plan_cascade_risk`, NOT `cascade_risk_score` — see _CASCADE_RISK_METRIC.
            cascade_risk_delta_pct=_pct_delta(b.plan_cascade_risk, g.plan_cascade_risk),
        ))

    # Aggregate mean deltas
    cost_delta_pct = _safe_mean([d.cost_delta_pct for d in bom_deltas])

    # Absolute dollar deltas (P3): mean USD saved per BOM run, and the mean
    # CVaR-95 emergency-procurement premium exposed on each baseline BOM.
    cost_delta_usd = _safe_mean([
        graph_aware_by_bom[bom].total_cost_usd - baseline_by_bom[bom].total_cost_usd
        for bom in common_boms
    ])
    baseline_spend_at_risk_usd = _safe_mean([
        baseline_by_bom[bom].total_cost_usd * max(0.0, (baseline_by_bom[bom].mc_cvar_95 or 1.0) - 1.0)
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
        baseline_cvar_95=_safe_list_mean(baseline_rows, "mc_cvar_95") or None,
        graph_aware_cvar_95=_safe_list_mean(graph_aware_rows, "mc_cvar_95") or None,
    )

    # ── Value of optimization: greedy baseline vs (blind) MILP, nominal ────────
    greedy_by_bom: Dict[str, object] = {r.bom_name: r for r in greedy_nominal}
    opt_boms = sorted(set(greedy_by_bom.keys()) & set(baseline_by_bom.keys()))

    per_bom_savings_pct: List[float] = []
    per_bom_savings_usd: List[float] = []
    for bom in opt_boms:
        greedy_cost = greedy_by_bom[bom].total_cost_usd
        milp_cost = baseline_by_bom[bom].total_cost_usd
        if greedy_cost:
            per_bom_savings_pct.append((greedy_cost - milp_cost) / abs(greedy_cost) * 100.0)
        per_bom_savings_usd.append(greedy_cost - milp_cost)

    savings_pct = _safe_mean(per_bom_savings_pct)
    savings_usd_per_bom = _safe_mean(per_bom_savings_usd)
    savings_usd_annualized = savings_usd_per_bom * ANNUAL_REORDERS
    avg_suppliers_greedy = _safe_mean([
        greedy_by_bom[b].n_distinct_suppliers for b in opt_boms
        if greedy_by_bom[b].n_distinct_suppliers is not None
    ])
    avg_suppliers_milp = _safe_mean([
        baseline_by_bom[b].n_distinct_suppliers for b in opt_boms
        if baseline_by_bom[b].n_distinct_suppliers is not None
    ])

    # ── Value of resilience: graph-aware vs blind MILP under disruption ────────
    milp_stress = [r for r in all_rows if _arm(r) == "milp" and _scen(r) == "stress"]
    milp_targeted = [r for r in all_rows if _arm(r) == "milp" and _scen(r) == "targeted"]

    def _mean_reduction(rows, attr: str) -> float:
        """mean(blind - graph) per BOM: positive = graph-aware lowers the metric."""
        blind = {r.bom_name: r for r in rows if not r.graph_aware}
        graph = {r.bom_name: r for r in rows if r.graph_aware}
        vals = []
        for b in set(blind) & set(graph):
            bv = getattr(blind[b], attr)
            gv = getattr(graph[b], attr)
            if bv is not None and gv is not None:
                vals.append(bv - gv)
        return _safe_mean(vals)

    def _arm_mean(rows, attr: str, graph_aware: bool) -> Optional[float]:
        vals = [
            getattr(r, attr) for r in rows
            if bool(r.graph_aware) is graph_aware and getattr(r, attr) is not None
        ]
        return round(_safe_mean(vals), 4) if vals else None

    reductions = {
        "stress_cascade_risk_reduction": _mean_reduction(milp_stress, "plan_cascade_risk"),
        "stress_cvar95_reduction": _mean_reduction(milp_stress, "mc_cvar_95"),
        "targeted_cascade_risk_reduction": _mean_reduction(milp_targeted, "plan_cascade_risk"),
        "targeted_cvar95_reduction": _mean_reduction(milp_targeted, "mc_cvar_95"),
    }
    flat = [name for name, value in reductions.items() if abs(value) < 1e-9]
    measured = {
        "stress_blind_plan_cascade_risk": _arm_mean(milp_stress, "plan_cascade_risk", False),
        "stress_graph_plan_cascade_risk": _arm_mean(milp_stress, "plan_cascade_risk", True),
        "stress_blind_mc_cvar_95": _arm_mean(milp_stress, "mc_cvar_95", False),
        "stress_graph_mc_cvar_95": _arm_mean(milp_stress, "mc_cvar_95", True),
        "targeted_blind_plan_cascade_risk": _arm_mean(milp_targeted, "plan_cascade_risk", False),
        "targeted_graph_plan_cascade_risk": _arm_mean(milp_targeted, "plan_cascade_risk", True),
        "targeted_blind_mc_cvar_95": _arm_mean(milp_targeted, "mc_cvar_95", False),
        "targeted_graph_mc_cvar_95": _arm_mean(milp_targeted, "mc_cvar_95", True),
    }
    if flat:
        resil_interpretation = (
            f"{len(flat)} of 4 reductions are exactly 0.0 ({', '.join(flat)}). That is "
            "a MEASUREMENT, not a gap: the graph-aware and blind MILP arms scored "
            "identically on those metrics under that scenario. Check measured_values "
            "for the two arm means that produced it. The CVaR figures in particular "
            "saturate easily — this catalogue is diversified enough that a plan's "
            "emergency-procurement multiplier is often the same either way."
        )
    else:
        resil_interpretation = (
            "All four reductions are non-zero: the graph-aware arm lowered both plan "
            "cascade risk and the CVaR-95 tail under stress and targeted disruption."
        )

    resilience = ResilienceSection(
        # graph-aware vs blind NOMINAL premium — same figure as cost_delta_pct
        nominal_cost_premium_pct=cost_delta_pct,
        **reductions,
        measured_values=measured,
        flat_metrics=flat,
        interpretation=resil_interpretation,
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
             baseline_by_bom[bd.bom_name].plan_cascade_risk or 0.0,
             graph_aware_by_bom[bd.bom_name].plan_cascade_risk or 0.0),
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

    # ── The honest, volume-dependent headline (replaces the retracted number) ──
    curve = _load_volume_curve()
    headline = _build_headline(curve)
    by_mult = {p.multiplier: p for p in curve.points}
    proto_point = by_mult.get(1)
    prod_points = [p for p in curve.points if p.multiplier >= _PRODUCTION_MULTIPLIER_MIN]
    # Pick the deepest production point that still has a real cohort behind it.
    prod_point = max(prod_points, key=lambda p: p.boms_feasible) if prod_points else None

    # Mean units per BOM across this run — the reason its savings_pct is a prototype
    # figure and not a procurement number.
    run_units: Optional[int] = None
    try:
        per_bom_units = []
        seen_boms = set()
        for row in all_rows:
            if row.bom_name in seen_boms:
                continue
            seen_boms.add(row.bom_name)
            items = row.bom_items_json or []
            if isinstance(items, list):
                per_bom_units.append(
                    sum(int(i.get("quantity", 0)) for i in items if isinstance(i, dict))
                )
        run_units = round(_safe_mean(per_bom_units)) if per_bom_units else None
    except Exception:  # noqa: BLE001 — a malformed items blob must not 500 the endpoint
        run_units = None

    run_tag = all_rows[0].run_tag
    run_tag_meaning = {
        "benchmark": (
            "Every live risk feed was available when this run was scored, so the "
            "feed-derived inputs are real."
        ),
        "static_fallback": (
            "At least one live risk feed was UNAVAILABLE when this run was scored, so "
            "its feed-derived inputs fell back to static values. Cost and supplier "
            "consolidation are unaffected (they come from the offer table); the "
            "geopolitical-risk inputs are not live. See feeds_fallback."
        ),
    }.get(run_tag, f"Unrecognised run_tag '{run_tag}'.")

    return BenchmarkSummaryResponse(
        run_id=target_run_id,
        run_tag=run_tag,
        run_tag_meaning=run_tag_meaning,
        timestamp=timestamp_str,
        n_boms=n_boms,
        headline=headline,
        volume_curve=curve,
        decomposition_at_prototype_volume=(
            _decompose(proto_point, "prototype volume (1x)") if proto_point else None
        ),
        decomposition_at_production_volume=(
            _decompose(prod_point, f"production volume ({prod_point.multiplier}x)")
            if prod_point else None
        ),
        headline_retracted=True,
        retraction_note=headline.retraction_reason,
        realistic_savings_pct_low=headline.savings_pct_at_production_volume_low,
        realistic_savings_pct_high=headline.savings_pct_at_production_volume_high,
        fixed_fee_share_of_savings_pct=(
            proto_point.fixed_fee_share_of_saving_pct if proto_point else None
        ),
        fixed_fee_share_of_cost_pct=(
            proto_point.greedy_fixed_share_of_cost_pct if proto_point else None
        ),
        fixed_fee_per_supplier_usd=curve.fixed_fee_per_supplier_usd,
        mean_units_per_bom=run_units,
        caveats=[
            "savings_pct on this response is measured on THIS RUN ONLY, whose BOMs are "
            f"4 lines and {run_units if run_units is not None else '5-9'} total units. "
            "It is a prototype-volume figure dominated by a fixed per-supplier fee. Do "
            "not quote it as the optimizer's saving — quote headline.statement.",
            RETRACTED_HEADLINE.capitalize() + " is RETRACTED and must not be repeated.",
            "The published benchmark run compares a DOMESTIC-ONLY MILP against an "
            "international-inclusive greedy, so the two arms do not see the same offer "
            "pool. volume_curve uses the matched arm (same pool for both), which is the "
            "fair comparison.",
            _CASCADE_RISK_METRIC,
            "The resilience section (graph-aware vs blind MILP under disruption) is a "
            "separate story on a separate axis and is NOT affected by anything in the "
            "volume curve.",
        ],
        savings_pct=round(savings_pct, 2),
        savings_units="percent",
        savings_pct_is_prototype_volume_only=True,
        savings_pct_display_label=(
            f"{savings_pct:.1f}% at "
            f"{f'{run_units}-unit' if run_units is not None else 'prototype'} "
            "prototype volume — a per-supplier fee artifact, not the optimizer's "
            "saving. See headline."
        ),
        savings_usd_per_bom=round(savings_usd_per_bom, 2),
        savings_usd_annualized=round(savings_usd_annualized, 2),
        annual_reorders=ANNUAL_REORDERS,
        avg_suppliers_greedy=round(avg_suppliers_greedy, 2),
        avg_suppliers_milp=round(avg_suppliers_milp, 2),
        benchmark_volume_note=(
            f"This run's BOMs total "
            f"{run_units if run_units is not None else 'a handful of'} units per BOM. "
            "Every percentage below is measured at that volume."
        ),
        resilience=resilience,
        cost_delta_pct=cost_delta_pct,
        cost_delta_usd=round(cost_delta_usd, 2),
        cost_delta_units="usd",
        baseline_spend_at_risk_usd=round(baseline_spend_at_risk_usd, 2),
        eta_delta_pct=eta_delta_pct,
        co2_delta_pct=co2_delta_pct,
        cascade_risk_delta_pct=cascade_risk_delta_pct,
        cascade_risk_metric=_CASCADE_RISK_METRIC,
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
    Weight is the mean `plan_cascade_risk` across the runs in which each distributor
    was selected, normalized to [0, 1] against the most-exposed distributor.

    2026-08 audit fixes:
      * reads `plan_cascade_risk` (populated, 0.0–1.0 with real variance) instead of
        `cascade_risk_score`, which is exactly 0.0 in all 234 rows ever written — see
        _CASCADE_RISK_METRIC;
      * drops the `normalized_weight > 0` filter. A distributor whose plans never
        collapse has weight 0.0, which is a RESULT and belongs on the map; discarding
        it is how a fully-populated database produced `{"points": []}`;
      * when nothing scores above zero, says so in `note` instead of returning a
        structurally-empty success.
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
        return CascadeHeatmapResponse(
            points=[], metric=_CASCADE_RISK_METRIC,
            note=(
                "No optimization_runs rows exist. Run the benchmark seed pipeline "
                "(see backend/seeds/) to populate them."
            ),
        )

    target_run_id = latest[0]
    all_rows = (
        db.query(OptimizationRun)
        .filter(OptimizationRun.run_id == target_run_id)
        .all()
    )

    if not all_rows:
        return CascadeHeatmapResponse(
            points=[], metric=_CASCADE_RISK_METRIC, run_id=target_run_id,
            note=f"run_id={target_run_id} has no rows.",
        )

    # Compute per-distributor mean plan_cascade_risk
    dist_risk_accumulator: Dict[int, List[float]] = {}
    for row in all_rows:
        if row.plan_cascade_risk is None:
            continue
        dist_ids = row.selected_distributor_ids or []
        if isinstance(dist_ids, list):
            for did in dist_ids:
                if isinstance(did, int):
                    dist_risk_accumulator.setdefault(did, []).append(
                        float(row.plan_cascade_risk)
                    )

    if not dist_risk_accumulator:
        return CascadeHeatmapResponse(
            points=[], metric=_CASCADE_RISK_METRIC, run_id=target_run_id,
            note=(
                f"run_id={target_run_id} has {len(all_rows)} rows but none carry both a "
                "plan_cascade_risk value and a selected_distributor_ids list, so no "
                "distributor can be scored. Re-run the benchmark pipeline."
            ),
        )

    # Compute raw weights
    raw_weights: Dict[int, float] = {
        did: _safe_mean(scores)
        for did, scores in dist_risk_accumulator.items()
    }
    max_raw = max(raw_weights.values())
    # Divisor only — a zero max means every distributor scores 0.0, which is reported
    # rather than hidden.
    denom = max_raw if max_raw > 0 else 1.0

    # Fetch distributor details
    dist_ids_list = list(raw_weights.keys())
    distributors = (
        db.query(Distributor)
        .filter(Distributor.id.in_(dist_ids_list))
        .all()
    )
    dist_map = {d.id: d for d in distributors}

    points = []
    missing_geo = 0
    for did, raw_w in raw_weights.items():
        dist = dist_map.get(did)
        if dist is None or dist.latitude is None or dist.longitude is None:
            missing_geo += 1
            continue
        points.append(HeatmapPoint(
            lat=dist.latitude,
            lng=dist.longitude,
            weight=round(raw_w / denom, 4),
            distributor_id=dist.id,
            distributor_name=dist.name,
        ))
    points.sort(key=lambda p: -p.weight)

    if max_raw <= 0:
        note = (
            f"All {len(points)} distributors score 0.0: no selected sourcing plan in "
            f"run_id={target_run_id} collapsed under the Monte Carlo. Points are still "
            "returned (weight 0.0) so the map shows the network rather than nothing."
        )
    else:
        note = (
            f"{sum(1 for p in points if p.weight > 0)} of {len(points)} distributors "
            f"carry non-zero collapse exposure; weights are normalized against the "
            f"most-exposed (raw max {max_raw:.4f})."
        )
    if missing_geo:
        note += f" {missing_geo} distributor(s) omitted for missing coordinates."

    return CascadeHeatmapResponse(
        points=points,
        metric=_CASCADE_RISK_METRIC,
        run_id=target_run_id,
        n_distributors_scored=len(points),
        max_raw_weight=round(max_raw, 4),
        note=note,
    )


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
