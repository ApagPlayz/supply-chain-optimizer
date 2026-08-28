"""
Benchmark API endpoints (04-02).

Four public endpoints for the benchmark dashboard:
  GET /benchmark/summary               — Aggregate A/B delta metrics for latest run_id
  GET /benchmark/fiedler-curve         — Sequential-removal λ₂ curve from GraphState
  GET /benchmark/cascade-heatmap       — Per-distributor unfulfilled-BOM-line exposure for maplibre
  GET /benchmark/single-source-components — Real component MPN+manufacturer+sole-source distributor

All endpoints are unauthenticated — public aggregate analytics, no user data (T-04-02-03/04).
"""
from __future__ import annotations

import json
import logging
import random
from functools import lru_cache
from pathlib import Path
from statistics import fmean, mean
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
_DIVERSIFICATION_FRONTIER_PATH = _REPO_ROOT / "docs" / "diversification_frontier.json"

# Production volume, for the honest headline range. The sweep's own caveat: the
# high-multiplier rows are a smaller BOM cohort than the low ones (stock ceilings knock
# BOMs out as volume rises), so the trustworthy statement is a RANGE over this band,
# never a single number.
_PRODUCTION_MULTIPLIER_MIN = 500

# ── Materiality threshold — an ASSUMPTION, not a measurement ──────────────────
# This used to be served as `noise_floor_pct` and rendered as "this run's 2.0%
# noise floor", which invited the question "how did you establish it?" and had no
# answer: it was never derived from solver tolerance or replicate variance.
#
# It is not derivable here, and that is a property of the benchmark rather than an
# oversight. The run is a single deterministic solve — seed 42, CP-SAT with
# `num_search_workers = 1` and no relative-gap limit — so re-running it reproduces
# every figure bit-for-bit. There are no replicates, so the measured run-to-run
# variance is exactly 0.0%; a "noise floor" derived from it would be 0.0 and would
# declare every difference, however tiny, material.
#
# So it is published as what it actually is: a reporting convention, fixed before
# the run and held constant across runs so it cannot be tuned toward a result.
MATERIALITY_THRESHOLD_PCT = 2.0
_MATERIALITY_BASIS = (
    "ASSUMED THRESHOLD, NOT A MEASURED NOISE FLOOR. 2.0% of landed cost is a "
    "reporting convention chosen a priori and held fixed across runs, so it cannot "
    "be tuned toward a result. Nothing in this pipeline measures it: the benchmark "
    "is a single deterministic solve (seed 42, CP-SAT num_search_workers=1, no "
    "relative-gap limit), so re-running reproduces every figure exactly and there "
    "are no replicates from which run-to-run variance could be estimated. Read it "
    "as 'differences smaller than this are not worth acting on', never as "
    "'differences smaller than this are indistinguishable from noise'."
)


# ── Paired bootstrap over BOM clusters — the ship standard, applied here too ──
# The lead-time model may only ship by beating its baselines with a PAIRED
# BOOTSTRAP CI THAT EXCLUDES ZERO, and the Model Card says so prominently. Until
# 2026-08-28 this endpoint published every resilience delta as a bare
# uninterval'd mean over 9 BOMs — no CI, no standard error, no replicate, one
# fixed seed — while the ML page two clicks away was held to the harder bar. A
# reviewer who reads both pages is entitled to ask why. There is no good answer,
# so the benchmark is now held to the same bar.
#
# NOTHING IS RE-SOLVED. Every per-BOM delta is already stored in
# `optimization_runs`; the bootstrap resamples the BOM CLUSTERS with replacement
# over those stored values. The BOM is the independent unit — both arms of a
# delta come from the SAME BOM under the SAME simulation seed, so the BOM is what
# gets resampled — and resampling it leaves run 5 byte-identical.
#
# Percentile interval, not BCa: with n <= 9 clusters the acceleration term would
# be estimated from at most 9 jackknife points, which is false precision. `n` and
# `n_effective` are published beside every interval for the same reason — an
# interval over 7 BOMs is a description of these BOMs, not a population claim.
BOOTSTRAP_N = 10_000
BOOTSTRAP_SEED = 42
CI_ALPHA = 0.05

_BOOTSTRAP_METHOD = (
    "paired percentile bootstrap over BOM clusters, 10,000 resamples, seed 42, "
    "computed from the per-BOM deltas already stored for this run — no re-solve"
)

# Why a BOM can be "structurally zero". Two of run 5's nine BOMs
# (`drone_flight_controller`, `rf_transceiver_module`) select the SAME plan in
# both arms, so their delta is an exact 0.0 on every metric in every scenario.
# They are not evidence of a null effect; they are BOMs the treatment never
# touched. They drag every mean toward zero AND shrink the apparent spread, which
# is the worst of both. `n_effective` counts only the BOMs whose plan actually
# differs, and both the full-panel and effective-panel intervals are published so
# nobody has to take the distinction on trust.
_N_EFFECTIVE_DEFINITION = (
    "n = BOMs in the paired panel. n_effective = BOMs whose graph-aware plan "
    "actually DIFFERS from the blind plan (different distributor set, or the same "
    "set at a different landed cost). A BOM whose plan is identical in both arms "
    "contributes an exact 0.0 to every delta and carries no information about the "
    "treatment; it is counted, not hidden, and the effective-panel interval is "
    "published beside the full-panel one."
)


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


class PairedBootstrapCI(BaseModel):
    """
    A 95% paired percentile-bootstrap interval around one published delta.

    The resample unit is the BOM CLUSTER, not the row: both arms of every
    per-BOM delta come from the same BOM under the same simulation seed, so the
    BOM is the independent unit. 10,000 resamples, seed 42, computed from the
    per-BOM values already stored for the run — the benchmark is NOT re-solved
    and no published mean moves.

    `significant` is True only when the interval EXCLUDES zero. A delta whose
    interval covers zero is not a result and must not be rendered as one.

    `n_effective` and the `*_effective` fields describe the sub-panel of BOMs
    whose plan actually differs between arms. See `n_effective_definition` on the
    parent section.
    """
    metric: str
    units: str                      # "share_0_1" | "cost_multiplier" | "percent"
    mean: float
    ci95_low: Optional[float] = None
    ci95_high: Optional[float] = None
    significant: bool = False
    n: int = 0
    n_effective: int = 0
    mean_effective: Optional[float] = None
    ci95_low_effective: Optional[float] = None
    ci95_high_effective: Optional[float] = None
    significant_effective: bool = False
    # BOMs that select an identical plan in both arms and therefore contribute an
    # exact 0.0 to this delta. Named, not just counted.
    zero_plan_boms: List[str] = []
    n_boot: int = BOOTSTRAP_N
    seed: int = BOOTSTRAP_SEED
    method: str = ""


class ResilienceSection(BaseModel):
    """
    Value of resilience: graph-aware MILP vs blind MILP.

    nominal_cost_premium_pct — mean per-BOM (graph_aware - blind) / blind * 100 of
      nominal landed cost. Negative = graph-aware is cheaper; expected ~0 (the
      graph-aware plan buys tail protection at near-zero nominal premium).

    *_cascade_risk_reduction — mean (blind.plan_cascade_risk - graph.plan_cascade_risk)
      under each disruption scenario. Positive = graph-aware LOWERS the share of
      BOM lines left unfulfilled. plan_cascade_risk is 1 - the MEDIAN fraction of
      the BOM's lines that stay fulfillable across the Monte Carlo trials — a
      share on 0-1, NOT a probability: it has no base rate and no exposure
      window, and on 4-line BOMs it can only take the values 0, .25, .5, .75, 1.
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
    # ── Paired inference (2026-08-28) ─────────────────────────────────────────
    # Every scalar above is a MEAN OVER 9 BOMs and was published for months with
    # no interval of any kind, while the lead-time model on the ML page may only
    # ship by beating its baselines with a paired bootstrap CI excluding zero.
    # `intervals` closes that gap: one PairedBootstrapCI per published delta,
    # keyed by the exact field name it qualifies, so a reader can map an interval
    # to its number without guessing. The scalars are unchanged — this ADDS an
    # interval around figures that already existed, it does not restate them.
    #
    # Read `significant_metrics` / `non_significant_metrics` before quoting any
    # scalar above. A delta in `non_significant_metrics` has an interval that
    # covers zero and IS NOT A RESULT.
    intervals: Dict[str, PairedBootstrapCI] = {}
    n_boms: int = 0
    n_effective_boms: int = 0
    n_effective_definition: str = ""
    significant_metrics: List[str] = []
    non_significant_metrics: List[str] = []
    inference_note: str = ""


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
    # Renamed from `noise_floor_pct` (2026-08): it was never a noise floor.
    # See MATERIALITY_THRESHOLD_PCT / _MATERIALITY_BASIS above — the basis
    # string is served alongside the number so no reader has to ask where the
    # 2.0 came from.
    materiality_threshold_pct: float
    materiality_threshold_basis: str = ""


class FiedlerPoint(BaseModel):
    step: int
    removed: Optional[int] = None
    removed_name: Optional[str] = None
    lambda2: float
    delta_pct: float
    # Reference BOMs with at least one line that has NO supplier left in the graph
    # once the distributors up to and including this step have been removed.
    # Cumulative, and computed on the same graph λ₂ is computed on. Empty means
    # "checked, none collapsed" — `boms_checked` on the response says how many
    # BOMs stood behind that check, so an empty list is never ambiguous.
    collapsed_boms: List[str] = []


class FiedlerCurveResponse(BaseModel):
    points: List[FiedlerPoint]
    baseline_lambda2: float
    # How many reference BOMs the collapse check covered, and where they came
    # from. `boms_checked == 0` means the check could not run (no benchmarked
    # BOMs in the database) — the UI must then say so rather than rendering
    # "all BOMs remain fulfillable".
    boms_checked: int = 0
    bom_source: str = ""


class HeatmapPoint(BaseModel):
    lat: float
    lng: float
    # Mean `plan_cascade_risk` over the runs that selected this distributor:
    # the median SHARE of BOM lines left unfulfilled, on 0.0-1.0. A share, not
    # a probability — see _CASCADE_RISK_METRIC.
    weight: float
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


# ── Paired inference over BOM clusters ────────────────────────────────────────

def paired_bootstrap_ci(
    deltas: Sequence[float],
    n_boot: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
    alpha: float = CI_ALPHA,
) -> Dict[str, Any]:
    """
    Percentile bootstrap CI for the mean of a PAIRED per-BOM difference.

    Paired because both numbers behind each difference come from the same BOM,
    the same offer pool and the same simulation seed — the only thing that
    changes is the arm. The BOM is therefore the independent unit, and the BOM is
    what gets resampled with replacement.

    Returns ``significant = True`` only when the interval EXCLUDES zero. An
    interval that touches zero on either side is reported as not significant:
    `lo > 0 or hi < 0` is deliberately strict, so an all-zero panel (lo = hi = 0)
    can never be called a result.

    ``mean`` is NOT rounded to display precision here — the caller rounds. The
    served figures for run 5 are unchanged by this function; it only puts an
    interval around numbers that already exist.
    """
    vals = [float(d) for d in deltas]
    n = len(vals)
    if n == 0:
        return {
            "n": 0, "mean": 0.0, "ci95_low": None, "ci95_high": None,
            "significant": False,
            "note": "empty panel — no interval is estimable",
        }
    m = fmean(vals)
    if n == 1:
        return {
            "n": 1, "mean": m, "ci95_low": None, "ci95_high": None,
            "significant": False,
            "note": "n=1 — no interval is estimable from a single cluster",
        }

    rng = random.Random(seed)
    means: List[float] = []
    for _ in range(n_boot):
        means.append(fmean(rng.choices(vals, k=n)))
    means.sort()
    lo = means[max(0, int((alpha / 2) * n_boot))]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return {
        "n": n,
        "mean": m,
        "ci95_low": lo,
        "ci95_high": hi,
        "significant": (lo > 0.0) or (hi < 0.0),
    }


def _plan_differs(blind_row: Any, graph_row: Any) -> bool:
    """
    Did the graph-aware arm actually choose a DIFFERENT plan for this BOM?

    `optimization_runs` stores no line-level assignment snapshot, so plan
    identity is inferred from the two things it does store: the set of selected
    distributors and the landed cost. Same distributor set AND the same landed
    cost to the cent = the same plan, and such a BOM contributes an exact 0.0 to
    every delta. A same-set/different-cost pair means the quantities moved, which
    IS a different plan.
    """
    b_ids = sorted(blind_row.selected_distributor_ids or [])
    g_ids = sorted(graph_row.selected_distributor_ids or [])
    if b_ids != g_ids:
        return True
    b_cost = blind_row.total_cost_usd
    g_cost = graph_row.total_cost_usd
    if b_cost is None or g_cost is None:
        return False
    return abs(b_cost - g_cost) > 1e-9


def _paired_panel(
    rows: List[Any],
    value: Any,
) -> Tuple[List[str], List[float], List[bool]]:
    """
    Build the paired per-BOM panel for one scenario.

    Returns (bom_names, deltas, plan_changed) aligned by index, sorted by BOM
    name so the panel is deterministic. `value(blind_row, graph_row)` returns the
    per-BOM delta, or None when either side is missing the field.
    """
    blind = {r.bom_name: r for r in rows if not r.graph_aware}
    graph = {r.bom_name: r for r in rows if r.graph_aware}
    names: List[str] = []
    deltas: List[float] = []
    changed: List[bool] = []
    for name in sorted(set(blind) & set(graph)):
        b, g = blind[name], graph[name]
        d = value(b, g)
        if d is None:
            continue
        names.append(name)
        deltas.append(float(d))
        changed.append(_plan_differs(b, g))
    return names, deltas, changed


def _interval(
    metric: str,
    units: str,
    names: List[str],
    deltas: List[float],
    changed: List[bool],
    digits: int = 6,
) -> "PairedBootstrapCI":
    """Full-panel and effective-panel intervals for one published delta."""
    full = paired_bootstrap_ci(deltas)
    eff_idx = [i for i, c in enumerate(changed) if c]
    eff = paired_bootstrap_ci([deltas[i] for i in eff_idx])

    def _r(x: Optional[float]) -> Optional[float]:
        return None if x is None else round(x, digits)

    return PairedBootstrapCI(
        metric=metric,
        units=units,
        mean=round(float(full["mean"]), digits),
        ci95_low=_r(full["ci95_low"]),
        ci95_high=_r(full["ci95_high"]),
        significant=bool(full["significant"]),
        n=full["n"],
        n_effective=len(eff_idx),
        mean_effective=_r(eff["mean"]),
        ci95_low_effective=_r(eff["ci95_low"]),
        ci95_high_effective=_r(eff["ci95_high"]),
        significant_effective=bool(eff["significant"]),
        zero_plan_boms=[names[i] for i, c in enumerate(changed) if not c],
        n_boot=BOOTSTRAP_N,
        seed=BOOTSTRAP_SEED,
        method=_BOOTSTRAP_METHOD,
    )


# ── The volume curve: the honest replacement for the retracted headline ───────

_CASCADE_RISK_METRIC = (
    "plan_cascade_risk = 1 - the MEDIAN FRACTION OF THE BOM'S LINES that stay "
    "fulfillable under the Monte Carlo, with the supplying pool restricted to the "
    "distributors the plan actually chose. It is a SHARE on 0-1, not a probability: "
    "there is no base rate and no exposure window behind it, and on the 4-line "
    "reference BOMs it can only take the values 0, 0.25, 0.5, 0.75 and 1.0. "
    "The sibling column `cascade_risk_score` is DEAD and is no longer "
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

    # ── Paired bootstrap CIs over the BOM clusters (item 12) ──────────────────
    # No re-solve: every per-BOM delta below is read straight out of the rows the
    # run already wrote. The BOM is the cluster and the BOM is what is resampled.
    def _risk(b, g) -> Optional[float]:
        bv, gv = b.plan_cascade_risk, g.plan_cascade_risk
        return None if (bv is None or gv is None) else bv - gv

    def _cvar(b, g) -> Optional[float]:
        bv, gv = b.mc_cvar_95, g.mc_cvar_95
        return None if (bv is None or gv is None) else bv - gv

    def _premium(b, g) -> Optional[float]:
        return _pct_delta(b.total_cost_usd, g.total_cost_usd)

    _panels = [
        ("stress_cascade_risk_reduction", "share_0_1", milp_stress, _risk),
        ("stress_cvar95_reduction", "cost_multiplier", milp_stress, _cvar),
        ("targeted_cascade_risk_reduction", "share_0_1", milp_targeted, _risk),
        ("targeted_cvar95_reduction", "cost_multiplier", milp_targeted, _cvar),
        ("nominal_cost_premium_pct", "percent", milp_nominal, _premium),
    ]
    intervals: Dict[str, PairedBootstrapCI] = {}
    for metric, units, panel_rows, fn in _panels:
        names, deltas, changed = _paired_panel(panel_rows, fn)
        intervals[metric] = _interval(metric, units, names, deltas, changed)

    sig = [k for k, v in intervals.items() if v.significant]
    nonsig = [k for k, v in intervals.items() if not v.significant]
    _nominal_ci = intervals["nominal_cost_premium_pct"]
    n_panel = _nominal_ci.n
    n_eff = _nominal_ci.n_effective
    inference_note = (
        f"Every delta above is a mean over {n_panel} BOMs and now carries a 95% "
        f"paired percentile-bootstrap CI ({BOOTSTRAP_N:,} resamples, seed "
        f"{BOOTSTRAP_SEED}) that resamples the BOM CLUSTERS over the per-BOM "
        f"values this run already stored — nothing was re-solved and no published "
        f"mean moved. {n_eff} of {n_panel} BOMs select a different plan in the two "
        f"arms; the rest contribute an exact 0.0 to every delta, so both the "
        f"full-panel and effective-panel intervals are published. "
        + (
            f"{len(sig)} of {len(intervals)} deltas have an interval that excludes "
            f"zero ({', '.join(sig)}). "
            if sig else
            f"NONE of the {len(intervals)} deltas has an interval excluding zero. "
        )
        + (
            f"{len(nonsig)} do not ({', '.join(nonsig)}) and MUST NOT be quoted as "
            f"results: on {n_panel} clusters they are not distinguishable from zero. "
            if nonsig else
            "All of them exclude zero. "
        )
        + "This is the same bar the lead-time model is held to on the ML page, "
        "which is the point: a benchmark published without intervals beside a "
        "model card that requires them is a double standard, not a finding."
    )

    resilience = ResilienceSection(
        # graph-aware vs blind NOMINAL premium — same figure as cost_delta_pct
        nominal_cost_premium_pct=cost_delta_pct,
        **reductions,
        measured_values=measured,
        flat_metrics=flat,
        interpretation=resil_interpretation,
        intervals=intervals,
        n_boms=n_panel,
        n_effective_boms=n_eff,
        n_effective_definition=_N_EFFECTIVE_DEFINITION,
        significant_metrics=sig,
        non_significant_metrics=nonsig,
        inference_note=inference_note,
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
        materiality_threshold_pct=MATERIALITY_THRESHOLD_PCT,
        materiality_threshold_basis=_MATERIALITY_BASIS,
    )


@router.get("/fiedler-curve", response_model=FiedlerCurveResponse)
def get_fiedler_curve():
    """
    Return the sequential-removal Fiedler λ₂ curve from pre-computed GraphState.

    Step 0 is the baseline (no removal). Subsequent steps show λ₂ after removing
    the most-central distributor.

    `collapsed_boms` lists the reference BOMs that have at least one line with no
    remaining supplier once every distributor up to that step is gone. It is
    computed in `main.compute_fiedler_curve` against the SAME graph λ₂ is computed
    on (the 80% training partition of the offer table), so the two columns of the
    chart describe one network, not two. `boms_checked` and `bom_source` disclose
    how many BOMs the check covered and where they came from; when `boms_checked`
    is 0 the check did not run and an empty `collapsed_boms` means nothing.
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

    head = gs.fiedler_curve[0]
    baseline_lambda2 = head["lambda2"]
    return FiedlerCurveResponse(
        points=points,
        baseline_lambda2=baseline_lambda2,
        boms_checked=int(head.get("boms_checked", 0) or 0),
        bom_source=str(head.get("bom_source", "") or ""),
    )


@router.get("/cascade-heatmap", response_model=CascadeHeatmapResponse)
def get_cascade_heatmap(db: Session = Depends(get_db)):
    """
    Return per-distributor unfulfilled-BOM-line exposure for maplibre heatmap-layer
    rendering.

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


# ══════════════════════════════════════════════════════════════════════════════
# THE PRICE OF RESILIENCE — the diversification frontier
# ══════════════════════════════════════════════════════════════════════════════
# `/benchmark/summary` reports that graph-aware sourcing is measurably better
# against a TARGETED outage and shows no measurable effect under broad systemic
# stress. On its own that reads as a shrug. This endpoint serves the sweep that
# explains it and turns it into a number.
#
# The same sourcing MILP is re-solved subject to a hard "open at least k distinct
# distributors" constraint, each plan is costed, and each is simulated under the
# benchmark's OWN scenarios. k = 1 is the frontier's control arm: the constraint
# binds on nothing, so the plan IS the unconstrained cost-optimal plan — and it
# reproduces run 5's published `milp_blind` landed cost on 9 of 9 BOMs to the
# cent, which is what makes the sweep comparable to the published benchmark.
#
# This is a LOADER, exactly like `_load_volume_curve`. It pools and reshapes a
# checked-in artifact so the API can never drift from the published data; it does
# not re-run the sweep, does not touch the database, and cannot move a published
# number. A missing or unparseable artifact returns `available: false` with a
# reason, never a bare headline.

_FRONTIER_AGGREGATE_DEFINITION = (
    "Costs are the MEAN landed cost per BOM at that k. Deltas are PAIRED against "
    "the same BOM's own k=1 plan, then summarised with a 95% percentile bootstrap "
    "that resamples BOMs (10,000 resamples, seed 42). An interval that covers zero "
    "is not a result and is labelled as such. Risk deltas are risk REMOVED: "
    "positive means safer than k=1."
)

# The four caveats a reader needs before they quote anything off this frontier.
# They are served as data, not baked into the page, so the UI cannot soften them.
_FRONTIER_COST_AXIS_CAVEAT = (
    "THE COST AXIS IS LARGELY A FIXED-CHARGE ARTIFACT. Every opened distributor "
    "pays the same fixed freight charge (LTL_BASE_FEE_USD scaled by the balanced "
    "strategy's transport_penalty_scale of 1.5), so the marginal cost of the k-th "
    "supplier settles at $115-120 and the cost side of this frontier is close to "
    "linear in k almost by construction. The interesting axis is RISK, not cost."
)
_FRONTIER_SEED_CAVEAT = (
    "ONE SEED. Every point on the frontier uses the same 1,000 Monte Carlo "
    "scenarios at seed 42 — that is exactly what makes the comparison paired, and "
    "it also means these CIs contain BOM-level variation ONLY, with no "
    "Monte-Carlo error term. A second seed would move these numbers by an amount "
    "this study does not measure."
)
_FRONTIER_QUANTISATION_CAVEAT = (
    "cascade_risk IS QUANTISED. It is 1 - p50(fulfillment) over a 4-line BOM, so "
    "it can only take the values {0, 0.25, 0.5, 0.75, 1} and cannot resolve a "
    "change smaller than a quarter of a BOM. expected_shortfall "
    "(1 - mean(fulfillment)) is reported beside it precisely because it can. Where "
    "the two disagree on significance, the coarse one is the LESS informative "
    "measure, not the more conservative one."
)
_FRONTIER_INDEPENDENCE_CAVEAT = (
    "FAILURES ARE INDEPENDENT beyond a shared stress multiplier. run_monte_carlo "
    "fails distributors independently at a calibrated hazard; there is no "
    "propagation, no recovery, and no correlation between distributor failures "
    "except the common stress_factor. Diversification protects most against "
    "CORRELATED shocks, so an independent-failure model is the conservative place "
    "to measure its value, not a flattering one."
)
_FRONTIER_NESTING_CAVEAT = (
    "THE CONSTRAINT BOUNDS A COUNT AND THE OBJECTIVE IS STILL PURE COST. "
    "min_distributors = k says how many doors stay open, never WHICH doors, so "
    "the cheapest way to satisfy it is often to ABANDON the incumbent and buy a "
    "different, cheaper set. Because the k-supplier plan is not required to "
    "contain the 1-supplier plan, risk is NOT MONOTONE in k under broad stress: a "
    "BOM can be forced onto two suppliers and end up more exposed than it was on "
    "one, if the supplier it left had the lower hazard. Under a TARGETED outage "
    "the effect is one-directional — spreading always shrinks the blast radius of "
    "losing a single named hub — and that asymmetry is exactly the split the "
    "benchmark reports. It is a property of the constraint, not of resilience."
)


class FrontierInterval(BaseModel):
    """One paired percentile-bootstrap interval on the frontier.

    Mirrors `PairedBootstrapCI`'s contract — `significant` is True ONLY when the
    interval EXCLUDES zero — but is a separate model because the resample unit and
    provenance differ: these come from the sweep artifact, not from the run's
    stored per-BOM deltas.
    """
    n: int
    mean: float
    ci95_low: Optional[float] = None
    ci95_high: Optional[float] = None
    significant: bool = False
    n_boot: int = 0
    seed: int = 0
    method: str = ""


class FrontierPoint(BaseModel):
    """One value of k on the price-of-resilience frontier.

    `n_boms_feasible` is how many BOMs the MILP could solve at this k.
    `n_effective` is how many of those had their PLAN ACTUALLY CHANGE. A BOM the
    constraint does not bind on contributes an exact zero to every delta;
    counting it inflates n and shrinks the interval without adding evidence. Both
    are published because quoting only the larger one is the dishonest option.
    """
    k: int
    n_boms_feasible: int
    n_effective: int
    boms_infeasible: List[str] = []
    # How often the k-supplier plan still contains every k=1 supplier. This single
    # column is the mechanism: where it is low, the plan is more diversified
    # without being nested, and risk need not fall.
    n_keeps_k1_suppliers: int = 0
    mean_total_cost_usd: float
    mean_suppliers: float
    mean_stress_cascade_risk: Optional[float] = None
    mean_stress_expected_shortfall: Optional[float] = None
    mean_targeted_cascade_risk: Optional[float] = None
    mean_targeted_expected_shortfall: Optional[float] = None
    # Cumulative, paired against each BOM's own k = 1 plan.
    delta_cost_usd: Optional[FrontierInterval] = None
    delta_stress_cascade_risk: Optional[FrontierInterval] = None
    delta_stress_expected_shortfall: Optional[FrontierInterval] = None
    delta_targeted_cascade_risk: Optional[FrontierInterval] = None
    delta_targeted_expected_shortfall: Optional[FrontierInterval] = None
    # Cumulative price of risk removed vs k = 1, printed ONLY where the risk
    # change has a paired 95% CI excluding zero. Everywhere else the denominator
    # is indistinguishable from zero and the ratio would be an artifact of
    # division, not a price — the `_note` says so in the API's own words.
    usd_per_unit_targeted_cascade_risk: Optional[float] = None
    usd_per_unit_targeted_cascade_risk_note: Optional[str] = None
    usd_per_unit_stress_cascade_risk: Optional[float] = None
    usd_per_unit_stress_cascade_risk_note: Optional[str] = None


class FrontierStep(BaseModel):
    """The step from k-1 to k — what the k-th supplier ALONE buys.

    This is the column that says where to stop. `usd_per_unit_*` is None with a
    `_note` wherever the marginal risk removed at that step has an interval
    covering zero.
    """
    label: str                     # "1 → 2"
    from_k: int
    to_k: int
    marginal_cost_usd: Optional[FrontierInterval] = None
    marginal_targeted_cascade_risk_removed: Optional[FrontierInterval] = None
    marginal_stress_cascade_risk_removed: Optional[FrontierInterval] = None
    marginal_targeted_expected_shortfall_removed: Optional[FrontierInterval] = None
    marginal_stress_expected_shortfall_removed: Optional[FrontierInterval] = None
    usd_per_unit_targeted_cascade_risk: Optional[float] = None
    usd_per_unit_targeted_cascade_risk_note: Optional[str] = None
    usd_per_unit_stress_expected_shortfall: Optional[float] = None
    usd_per_unit_stress_expected_shortfall_note: Optional[str] = None
    # How much more this step costs per unit of TARGETED cascade risk removed than
    # the first step did. This is the collapse, as a multiple: the third supplier
    # is 6.8x the first's price per unit of risk.
    cost_multiple_vs_first_step: Optional[float] = None


class FrontierNonMonotoneExample(BaseModel):
    """The single worst counter-example to "more suppliers is safer".

    Read straight off the artifact — the BOM whose stress expected shortfall
    RISES most when the constraint forces it off one supplier onto two.
    """
    bom: str
    from_k: int
    to_k: int
    expected_shortfall_before: float
    expected_shortfall_after: float
    n_suppliers_before: int
    n_suppliers_after: int
    # The artifact records nesting against the k = 1 plan specifically, so this
    # is named for what it actually is rather than "keeps the previous set".
    keeps_k1_suppliers: bool


class DiversificationFrontierResponse(BaseModel):
    """`GET /benchmark/diversification-frontier`.

    Serves `docs/diversification_frontier.json`, reshaped. Every basis string is
    self-documenting: a client that renders this payload and nothing else still
    tells the reader what the numbers mean and where they break down.
    """
    available: bool
    source: str
    unavailable_reason: Optional[str] = None
    generated_utc: Optional[str] = None
    # ── The one sentence ─────────────────────────────────────────────────────
    finding: str = ""
    verdict: str = ""
    # ── Provenance of the sweep itself ───────────────────────────────────────
    strategy: Optional[str] = None
    mc_scenarios: Optional[int] = None
    mc_seed: Optional[int] = None
    stress_factor: Optional[float] = None
    bootstrap_n: Optional[int] = None
    bootstrap_seed: Optional[int] = None
    n_boms_in_catalog: Optional[int] = None
    n_boms_included: Optional[int] = None
    boms_excluded: Dict[str, str] = {}
    # k = 1 reproduces run 5's blind-MILP landed cost — the sentence that makes
    # this sweep comparable to the published benchmark instead of a parallel
    # universe with its own baseline.
    baseline_check: str = ""
    baseline_check_passed: bool = False
    # ── The frontier ─────────────────────────────────────────────────────────
    aggregate_definition: str = _FRONTIER_AGGREGATE_DEFINITION
    points: List[FrontierPoint] = []
    steps: List[FrontierStep] = []
    # Suppliers per BOM at the unconstrained optimum — the consolidation this
    # sweep prices the reversal of.
    mean_suppliers_at_k1: Optional[float] = None
    # ── The mechanism ────────────────────────────────────────────────────────
    nesting_caveat: str = _FRONTIER_NESTING_CAVEAT
    non_monotone_example: Optional[FrontierNonMonotoneExample] = None
    # ── Honesty ──────────────────────────────────────────────────────────────
    cost_axis_caveat: str = _FRONTIER_COST_AXIS_CAVEAT
    seed_caveat: str = _FRONTIER_SEED_CAVEAT
    quantisation_caveat: str = _FRONTIER_QUANTISATION_CAVEAT
    independence_caveat: str = _FRONTIER_INDEPENDENCE_CAVEAT
    n_effective_definition: str = ""
    caveats: List[str] = []


_FRONTIER_N_EFFECTIVE_DEFINITION = (
    "n = BOMs whose MILP is feasible at this k. n_effective = BOMs whose SOURCING "
    "PLAN actually changes at this k. Two of the nine BOMs are structurally "
    "identical between k=1 and k=2 — the unconstrained optimum already opened two "
    "or more distributors, so the constraint binds on nothing — and they "
    "contribute hard zeros to every delta. That is why the headline quotes "
    "n_effective = 7, not 9."
)

_NOT_REPORTED_NOTE = (
    "not reported: the risk change here has a paired 95% CI covering zero, so the "
    "denominator is indistinguishable from zero and the ratio would be an artifact "
    "of division, not a price"
)


def _frontier_interval(raw: Any) -> Optional[FrontierInterval]:
    """Reshape one bootstrap block from the artifact. Returns None if absent."""
    if not isinstance(raw, dict) or "mean" not in raw:
        return None
    return FrontierInterval(
        n=int(raw.get("n", 0)),
        mean=float(raw.get("mean", 0.0)),
        ci95_low=raw.get("ci_low"),
        ci95_high=raw.get("ci_high"),
        significant=bool(raw.get("excludes_zero", False)),
        n_boot=int(raw.get("n_boot", 0)),
        seed=int(raw.get("seed", 0)),
        method=str(raw.get("method", "")),
    )


def _frontier_source() -> str:
    """Repo-relative path when it is under the repo, absolute otherwise.

    `Path.relative_to` RAISES on a path outside the root, and an artifact path
    pointed somewhere else (a test tmpdir, a mounted volume) must degrade to a
    readable string rather than a 500.
    """
    try:
        return str(_DIVERSIFICATION_FRONTIER_PATH.relative_to(_REPO_ROOT))
    except ValueError:
        return str(_DIVERSIFICATION_FRONTIER_PATH)


def _frontier_unavailable(reason: str) -> DiversificationFrontierResponse:
    return DiversificationFrontierResponse(
        available=False,
        source=_frontier_source(),
        unavailable_reason=reason,
        n_effective_definition=_FRONTIER_N_EFFECTIVE_DEFINITION,
    )


@lru_cache(maxsize=1)
def _load_diversification_frontier() -> DiversificationFrontierResponse:
    """
    Build the price-of-resilience frontier from `docs/diversification_frontier.json`.

    Cached for the process lifetime, like `_load_volume_curve`: the artifact is a
    committed file that only changes on redeploy, and re-reading it per request
    would buy nothing.
    """
    if not _DIVERSIFICATION_FRONTIER_PATH.exists():
        logger.warning(
            "diversification_frontier.json not found at %s",
            _DIVERSIFICATION_FRONTIER_PATH,
        )
        return _frontier_unavailable(
            "docs/diversification_frontier.json is missing. Regenerate it with "
            "`cd backend && python -m seeds.run_diversification_sweep`. Until then "
            "this API cannot price a second supplier, and no cost-per-unit-of-risk "
            "figure should be quoted."
        )

    try:
        raw: Dict[str, Any] = json.loads(_DIVERSIFICATION_FRONTIER_PATH.read_text())
    except Exception as exc:  # noqa: BLE001 — a bad artifact must not 500 the endpoint
        logger.warning("diversification_frontier.json unreadable: %s", exc)
        return _frontier_unavailable(
            f"docs/diversification_frontier.json could not be parsed: {exc}"
        )

    meta: Dict[str, Any] = raw.get("meta", {}) or {}
    provenance: Dict[str, Any] = raw.get("provenance", {}) or {}
    check: Dict[str, Any] = raw.get("run5_reproduction_check", {}) or {}
    rows: List[Dict[str, Any]] = list(raw.get("frontier", []) or [])

    if not rows:
        return _frontier_unavailable(
            "docs/diversification_frontier.json contains no frontier rows."
        )

    points: List[FrontierPoint] = []
    for row in rows:
        d_cost = _frontier_interval(row.get("delta_cost_vs_k1"))
        d_t_casc = _frontier_interval(row.get("delta_targeted_cascade_risk_vs_k1"))
        d_s_casc = _frontier_interval(row.get("delta_stress_cascade_risk_vs_k1"))
        points.append(FrontierPoint(
            k=int(row.get("k", 0)),
            n_boms_feasible=int(row.get("n_boms_feasible", 0)),
            n_effective=int(row.get("n_effective", 0)),
            boms_infeasible=[str(b) for b in (row.get("boms_infeasible") or [])],
            n_keeps_k1_suppliers=int(row.get("n_keeps_k1_suppliers", 0)),
            mean_total_cost_usd=float(row.get("mean_total_cost_usd", 0.0)),
            mean_suppliers=float(row.get("mean_suppliers", 0.0)),
            mean_stress_cascade_risk=row.get("mean_stress_cascade_risk"),
            mean_stress_expected_shortfall=row.get("mean_stress_expected_shortfall"),
            mean_targeted_cascade_risk=row.get("mean_targeted_cascade_risk"),
            mean_targeted_expected_shortfall=row.get(
                "mean_targeted_expected_shortfall"
            ),
            delta_cost_usd=d_cost,
            delta_stress_cascade_risk=d_s_casc,
            delta_stress_expected_shortfall=_frontier_interval(
                row.get("delta_stress_expected_shortfall_vs_k1")
            ),
            delta_targeted_cascade_risk=d_t_casc,
            delta_targeted_expected_shortfall=_frontier_interval(
                row.get("delta_targeted_expected_shortfall_vs_k1")
            ),
            usd_per_unit_targeted_cascade_risk=row.get(
                "usd_per_unit_targeted_cascade_risk_removed"
            ),
            usd_per_unit_targeted_cascade_risk_note=row.get(
                "usd_per_unit_targeted_cascade_risk_removed_note"
            ),
            usd_per_unit_stress_cascade_risk=row.get(
                "usd_per_unit_stress_cascade_risk_removed"
            ),
            usd_per_unit_stress_cascade_risk_note=row.get(
                "usd_per_unit_stress_cascade_risk_removed_note"
            ),
        ))

    # ── Marginal returns: what the k-th supplier ALONE buys ───────────────────
    steps: List[FrontierStep] = []
    first_step_price: Optional[float] = None
    for row in rows:
        marginal_cost = _frontier_interval(row.get("marginal_cost_usd_vs_prev_k"))
        if marginal_cost is None:
            continue                                  # k = 1 has no previous step
        k = int(row.get("k", 0))
        removed: Dict[str, Any] = row.get("marginal_risk_removed_vs_prev_k", {}) or {}
        ratios: Dict[str, Any] = row.get("marginal_usd_per_unit_risk_removed", {}) or {}
        t_casc_price = ratios.get("targeted_cascade_risk")
        s_es_price = ratios.get("stress_expected_shortfall")
        if first_step_price is None and isinstance(t_casc_price, (int, float)):
            first_step_price = float(t_casc_price)
        multiple = (
            round(float(t_casc_price) / first_step_price, 1)
            if isinstance(t_casc_price, (int, float))
            and first_step_price
            and first_step_price > 0
            else None
        )
        steps.append(FrontierStep(
            label=f"{k - 1} → {k}",
            from_k=k - 1,
            to_k=k,
            marginal_cost_usd=marginal_cost,
            marginal_targeted_cascade_risk_removed=_frontier_interval(
                removed.get("targeted_cascade_risk")
            ),
            marginal_stress_cascade_risk_removed=_frontier_interval(
                removed.get("stress_cascade_risk")
            ),
            marginal_targeted_expected_shortfall_removed=_frontier_interval(
                removed.get("targeted_expected_shortfall")
            ),
            marginal_stress_expected_shortfall_removed=_frontier_interval(
                removed.get("stress_expected_shortfall")
            ),
            usd_per_unit_targeted_cascade_risk=t_casc_price,
            usd_per_unit_targeted_cascade_risk_note=(
                None if t_casc_price is not None else _NOT_REPORTED_NOTE
            ),
            usd_per_unit_stress_expected_shortfall=s_es_price,
            usd_per_unit_stress_expected_shortfall_note=(
                None if s_es_price is not None else _NOT_REPORTED_NOTE
            ),
            cost_multiple_vs_first_step=multiple,
        ))

    # ── The mechanism, as the worst single counter-example ────────────────────
    # Not asserted from memory: the artifact is scanned for the BOM whose stress
    # expected shortfall RISES most on the step the headline is about.
    example = _worst_non_monotone_step(raw.get("boms", []) or [])

    # ── The one sentence ──────────────────────────────────────────────────────
    finding, verdict = _frontier_finding(points, steps)

    excluded = {
        str(b.get("bom")): str(b.get("reason") or "excluded, reason not recorded")
        for b in (raw.get("boms") or [])
        if isinstance(b, dict) and not b.get("included", True)
    }

    matched = int(check.get("matched", 0))
    checked = int(check.get("checked", 0))
    baseline_check = (
        f"k = 1 reproduces benchmark run {check.get('benchmark_run_id')}'s "
        f"milp_blind landed cost on {matched} of {checked} BOMs to within "
        f"${float(check.get('tolerance_usd', 0.01)):.2f}. The frontier's baseline "
        f"IS the published baseline, which is what makes this sweep comparable to "
        f"the benchmark rather than a parallel study with its own control arm."
        if checked
        else ""
    )

    return DiversificationFrontierResponse(
        available=True,
        source=_frontier_source(),
        generated_utc=provenance.get("generated_at_utc"),
        finding=finding,
        verdict=verdict,
        strategy=meta.get("strategy"),
        mc_scenarios=meta.get("mc_scenarios"),
        mc_seed=meta.get("mc_seed"),
        stress_factor=meta.get("stress_factor"),
        bootstrap_n=meta.get("bootstrap_n"),
        bootstrap_seed=meta.get("bootstrap_seed"),
        n_boms_in_catalog=meta.get("n_boms_in_catalog"),
        n_boms_included=meta.get("n_boms_included"),
        boms_excluded=excluded,
        baseline_check=baseline_check,
        baseline_check_passed=bool(check.get("all_match", False)),
        points=points,
        steps=steps,
        mean_suppliers_at_k1=points[0].mean_suppliers if points else None,
        non_monotone_example=example,
        n_effective_definition=_FRONTIER_N_EFFECTIVE_DEFINITION,
        caveats=[str(c) for c in (raw.get("caveats") or [])],
    )


def _worst_non_monotone_step(
    boms: Sequence[Any],
) -> Optional[FrontierNonMonotoneExample]:
    """
    Find the BOM that gets WORSE under broad stress when forced to diversify.

    Scans every consecutive (k-1, k) pair on every included BOM for the largest
    INCREASE in stress expected shortfall. If the frontier were monotone in k
    this would return None — that it does not is the mechanism section's evidence.
    """
    worst: Optional[FrontierNonMonotoneExample] = None
    worst_gap = 0.0
    for bom in boms:
        if not isinstance(bom, dict) or not bom.get("included", False):
            continue
        pts = [p for p in (bom.get("points") or []) if p.get("feasible")]
        for prev, cur in zip(pts, pts[1:], strict=False):
            before = (prev.get("scenarios", {}).get("stress", {}) or {}).get(
                "expected_shortfall"
            )
            after = (cur.get("scenarios", {}).get("stress", {}) or {}).get(
                "expected_shortfall"
            )
            if not isinstance(before, (int, float)) or not isinstance(
                after, (int, float)
            ):
                continue
            gap = float(after) - float(before)
            if gap > worst_gap:
                worst_gap = gap
                worst = FrontierNonMonotoneExample(
                    bom=str(bom.get("bom", "?")),
                    from_k=int(prev.get("k", 0)),
                    to_k=int(cur.get("k", 0)),
                    expected_shortfall_before=round(float(before), 4),
                    expected_shortfall_after=round(float(after), 4),
                    n_suppliers_before=int(prev.get("n_distinct_suppliers", 0)),
                    n_suppliers_after=int(cur.get("n_distinct_suppliers", 0)),
                    keeps_k1_suppliers=bool(cur.get("keeps_k1_suppliers", False)),
                )
    return worst


def _frontier_finding(
    points: Sequence[FrontierPoint], steps: Sequence[FrontierStep]
) -> Tuple[str, str]:
    """
    Compose the headline and the verdict FROM THE DATA, never from memory.

    Returns ("", "") rather than a half-sentence if the first step is missing or
    its risk interval covers zero — there is no finding to state in that case.
    """
    first = next((s for s in steps if s.to_k == 2), None)
    if first is None:
        return "", ""
    cost = first.marginal_cost_usd
    risk = first.marginal_targeted_cascade_risk_removed
    if cost is None or risk is None or not risk.significant:
        return "", ""
    k2 = next((p for p in points if p.k == 2), None)
    n_eff = k2.n_effective if k2 else risk.n
    finding = (
        f"The second supplier removes {risk.mean:.2f} of targeted cascade risk for "
        f"${cost.mean:,.2f} per BOM (95% CI {risk.ci95_low:.2f} to "
        f"{risk.ci95_high:.2f}, n={risk.n} BOMs, n_effective={n_eff})."
    )
    third = next((s for s in steps if s.to_k == 3), None)
    if third is not None and third.cost_multiple_vs_first_step:
        finding += (
            f" The third costs {third.cost_multiple_vs_first_step:g}x more per unit "
            f"of risk removed, and past it the interval covers zero."
        )
    verdict = "Buy the second supplier. Do not buy the third."
    return finding, verdict


@router.get(
    "/diversification-frontier",
    response_model=DiversificationFrontierResponse,
)
def get_diversification_frontier() -> DiversificationFrontierResponse:
    """
    The price of resilience: cost and cascade risk against a hard minimum
    supplier count k, with paired bootstrap CIs.

    Serves the checked-in sweep artifact. Nothing is solved or simulated here and
    no database is touched — if the artifact is missing the response is
    `available: false` with a regeneration command, never a bare headline.
    """
    return _load_diversification_frontier()
