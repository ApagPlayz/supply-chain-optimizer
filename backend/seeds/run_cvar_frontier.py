"""
Cost-vs-CVaR efficient frontier for the two-stage stochastic sourcing program.

WHY THIS EXISTS
---------------
Until now every "resilience" number this repo produced was a deterministic surcharge.
`sourcing.py` prices supply risk as `RISK_PREMIUM_RATE = 0.15` times a hand-weighted
vulnerability score, plus `betweenness x recourse_loss`. `graph/simulation.py` prices a
disruption as a flat 15% cost inflation per unfulfillable BOM share -- which is why its
`cvar_95` pins at 1.15 in nearly every published benchmark row. None of it contains a
recourse decision: nothing re-optimizes after a supplier goes dark.

`app/optimization/stochastic.py` replaces that with an actual two-stage stochastic
program (Rockafellar-Uryasev CVaR linearization, solved on the ENUMERATED support where
the supplier pool is narrow enough to hold it and on a sample-average approximation
where it is not). This
script sweeps the risk-aversion weight lambda and publishes the resulting frontier, so
the resilience claim stops being "I added a 15% surcharge" and becomes "here is the
price of resilience, and here is the knee".

WHAT IT PRODUCES
----------------
Five arms, all written to docs/cvar_frontier.json:

  primary       One BOM at three order volumes, full 9-point lambda sweep, knee, tail
                decomposition, out-of-sample validation on independent scenario draws,
                and the comparison against (a) the mean-value plan and (b) the plan the
                SHIPPED deterministic optimizer actually returns. Yields VSS.
  breadth       All 10 reference BOMs across their feasible volume range on a coarse
                lambda grid. Answers "does a cost-vs-CVaR tradeoff exist at all here?"
                -- and reports honestly where the answer is no.
  sensitivity   The primary instance re-run across the disruption base rate and the
                centrality spread. This is the arm that matters most: the disruption
                probabilities are an ASSUMPTION, and the frontier is only worth
                anything if the recommendation survives flexing it.
  saa_stability Monte Carlo sample size and seed. THE ONLY ARM THAT STILL SAMPLES,
                and deliberately so -- see WHICH MEASURE EACH ARM SOLVES ON below.
  calibration   The failure probabilities themselves, per distributor, with the
                betweenness they were derived from -- so a reader can check that no
                supplier is at p = 1.0 the way the existing simulator has them.

WHICH MEASURE EACH ARM SOLVES ON
--------------------------------
Disruption here is |D| independent Bernoulli variables, so the cost distribution has at
most 2**|D| atoms. Six distributors is 64 atoms -- small enough to hold in full. Until
2026-08-27 the primary, breadth and sensitivity arms CHOSE each plan on 200 Monte Carlo
draws and then SCORED it on all 64 atoms. That asymmetry is not a rounding detail: the
sampled solve resolved 10 of the 64 atoms, so the alpha = 0.95 tail the OPTIMIZER saw
was four atoms wide against an exact 49-54, and the sweep returned a lambda = 1.00 point
that was dominated on both axes by lambda = 0.70 -- a solver artefact published as a
frontier point.

Those three arms now choose and score on the SAME measure, via `fit_scenario_set`, which
takes the exact support when its second stage fits the solver's variable budget and
falls back to the draw ladder when it does not. That is the same function and the same
rule `app/api/stochastic.py` serves the live frontier from, so this artifact and the API
describe one solver rather than two.

`saa_quality` is the exception and must stay the exception. Both of its experiments
MEASURE what sampling costs: the Mak-Morton-Wood lower bound IS the mean optimal value
of M independent SAA replications, and the endpoint-stability table sweeps N and the
seed to show the wobble. Enumerate either and the answer is zero by construction -- a
vacuous zero, which is a deleted experiment rather than a stronger result. What that arm
bounds is the SAA path itself, the fallback wide-pool instances take; it is not a bound
on the choice error of the published headline frontier, which no longer has any.

WHAT "COMPLETE SUPPORT" DOES AND DOES NOT CLAIM
-----------------------------------------------
CP-SAT needs integer objective weights, so the exact probabilities are scaled by a
common denominator chosen per solve from what the int64 objective ceiling can carry.
Atoms whose probability falls below that resolution carry no weight. So "the solve set
is the complete support" is true; "every atom carries weight at every lambda" is not.
That residual is published per point as `solve_residual_mass`. It is a DETERMINISTIC
ROUNDING ARTEFACT of the quantization -- it has no confidence interval, it is not an
estimate of anything, and it does not shrink with more draws. It is not sampling error
and must never be described as such.

THE HONESTY PROBLEM THIS SCRIPT HAD TO SOLVE FIRST
--------------------------------------------------
Until 2026-08-16 `graph/simulation.py` used min-max RESCALED betweenness centrality
DIRECTLY as a failure probability. A min-max rescale attains 1.0 at its maximum, so the
most central distributor in this database failed in 100% of scenarios, and the least
central never failed at all. There was no base rate, no exposure window, and no unit
anywhere in that expression.

A CVaR objective built on those probabilities would be meaningless, so this work does
NOT reuse them. `build_failure_probabilities` anchors the LEVEL on a cited base rate
(McKinsey Global Institute 2020, a month-plus disruption every 3.7 years) converted to
the 60-day exposure window of one purchase order, and uses centrality only as a bounded
RANK transform for relative risk. Both the base rate and the spread are swept in the
`sensitivity` arm, and the "centrality tells us nothing" arm (spread = 1.0) is run
every time. Separate work has since fixed `builder.py` and `simulation.py` at the
source; this script has never reused their probabilities either way. A rank transform
is invariant to monotone rescaling, so that fix does not move any number published here.

Invocation:  python -m seeds.run_cvar_frontier      (from backend/, venv active)
             python -m seeds.run_cvar_frontier --quick   (primary + calibration only)
"""
from __future__ import annotations

import argparse
import json
import logging
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.graph.builder import build_graph_state  # noqa: E402
from app.optimization import stochastic as st  # noqa: E402
from app.optimization.sourcing import BomLine, Offer, solve_sourcing  # noqa: E402
from app.optimization.strategies import get_strategy  # noqa: E402

from seeds.provenance import build_provenance  # noqa: E402
from seeds.run_benchmark import BOM_CATALOG, DEPOT, _load_offers_for_bom  # noqa: E402

logger = logging.getLogger(__name__)

REPO_ROOT = BACKEND_ROOT.parent
DOCS = REPO_ROOT / "docs"

STRATEGY_ID = "balanced"

# Headline instance. pcb_power_supply is the reference BOM with the largest stock
# headroom (ceiling 22,051x per docs/BENCHMARK_VOLUME_CURVE.md), so it can be run at a
# volume a real buyer would actually order without the model degenerating into "there
# is only one feasible plan". Its six distributors also keep the scenario space small
# enough that every lambda solves to proven optimality in hundredths of a second, which
# means the published frontier contains no timeout artefacts.
PRIMARY_BOM = "pcb_power_supply"
PRIMARY_MULTIPLIERS = [100, 1000, 10000]
HEADLINE_MULTIPLIER = 10000

LAMBDA_GRID = [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.85, 1.0]
LAMBDA_GRID_COARSE = [0.0, 0.25, 0.5, 0.75, 1.0]

N_DRAWS = 200
SEED = 42
OUT_OF_SAMPLE_SEEDS = [1337, 2718, 31415]

# Per-solve CP-SAT WALL-CLOCK limit. Since 2026-09-01 this is NOT the budget that
# decides where a solve stops -- it is a RUNAWAY GUARD behind the deterministic budget
# below, sized at `_GUARD_MULTIPLE` x the deterministic limit so that the clock never
# binds. Any solve the clock stopped anyway is counted in
# `solve_quality.n_wall_clock_bound`, which must be 0 for the counters to reproduce.
#
# Overridable from the command line -- `--breadth-time-limit` / `--primary-time-limit`
# -- so the guard can be swept and measured WITHOUT editing this file and without the
# constants and the artifact drifting apart. `main()` rebinds these two module-level
# names before any solve runs, and every call site reads them at call time; the value
# that was actually used is recorded in `meta.solver` of the artifact. Defaults below
# are what the committed artifact was generated with -- changing a default silently
# invalidates the committed counters.
TIME_LIMIT_PRIMARY_S = 1600.0
TIME_LIMIT_BREADTH_S = 300.0

# DETERMINISTIC per-solve budget -- THE BUDGET THAT ACTUALLY BINDS. `None` = off; see
# `st.DEFAULT_DETERMINISTIC_LIMIT` for what this buys.
#
# A wall-clock budget makes every solve-quality counter in this artifact a property of
# the machine and its load rather than of the problem: it fixes the search PATH at one
# worker, but not where the search STOPS. A deterministic budget is a WORK budget: the
# search stops in the same place on a loaded laptop and an idle server, so the counters
# reproduce -- including the counters for solves that never converge.
#
# MEASURED 2026-09-01, on a 15-solve verification sweep (3 instances x 5 lambda, run as
# full compute_frontier sweeps so the warm-start chain was exercised), sha256 over every
# published field, five separate interpreter processes. NOTE these digests are of THAT
# sweep, not of the 387-solve committed artifact -- they cannot be recomputed from it:
#
#   W1  wall clock 15s     load 2.45   8f6eeab5f6e22684...
#   W2  wall clock 15s     load 35.45  421cd46a86848a6d...  DIFFERS from W1
#   D1  deterministic 15   load 2.45   10d34ccfae6868c0...
#   D2  deterministic 15   load 43.47  10d34ccfae6868c0...  identical
#   D3  deterministic 15   load 2.64   10d34ccfae6868c0...  identical
#
# The wall-clock control's damage under load: `smart_meter x10` lost its only converged
# lambda (and with it its row in the doc's breadth table); `rf_transceiver_module x1`
# worst gap 92.690 -> 94.352; `pcb_power_supply x100` identical either way. Root cause,
# measured: at the same 15s clock `smart_meter x10` received 6.7-13.5 units of work idle
# but only 1.8-4.7 saturated. A clock buys time; time buys a variable amount of WORK.
#
# It does NOT make hard instances converge -- it makes their truncation reproducible.
#
# Overridable with --breadth-det-limit / --primary-det-limit. The wall-clock limit above
# stays on as a runaway guard, and any solve that the CLOCK stopped is counted in
# `solve_quality.n_wall_clock_bound`: a nonzero count there means the determinism
# guarantee did NOT hold for that many solves and the budget is too large.
#
# Defaults below are what the committed artifact was generated with.
DET_LIMIT_PRIMARY: Optional[float] = 80.0
DET_LIMIT_BREADTH: Optional[float] = 15.0

# ── Solve-quality gate ───────────────────────────────────────────────────────
# A point is only ON the efficient frontier if its first-stage choice was actually
# proved (near-)optimal. `DEFAULT_RELATIVE_GAP` is 0.0, so CP-SAT returns OPTIMAL only
# when it closes the bound COMPLETELY -- proved, not "within a tolerance and called
# proved". It was 0.001 until 2026-08-27, which is why points in artifacts generated
# before that date carry a 0.04-0.08% gap under an `OPTIMAL` status; a FEASIBLE return
# means the per-solve budget (deterministic work, not the clock) was exhausted with the
# bound still open, and the gap it reports is the honest measure of how far from proven
# the answer is. A previous full run of this script produced points at gaps as wide as
# 93%, and those were plotted and quoted as frontier points. They are not: a plan whose
# objective could be 93% worse than the unknown optimum says nothing about the price of
# resilience. Such points are KEPT in the artifact -- deleting them would hide the cost
# of the compute budget -- but they are flagged `converged: false` with an
# `excluded_reason`, and every knee, spread and headline figure downstream is computed
# on the converged subset only.
CONVERGENCE_GAP_PCT = 5.0

# Stock ceilings from docs/BENCHMARK_VOLUME_CURVE.md, recomputed here rather than
# trusted -- see `_max_feasible_multiplier`.
BREADTH_MULTIPLIER_GRID = [1, 10, 100, 1000, 10000]

SENSITIVITY_BASE_RATES = [0.05, 0.10, st.DEFAULT_BASE_ANNUAL_PROB, 0.40]
SENSITIVITY_SPREADS = [1.0, 3.0, 6.0]
SENSITIVITY_HORIZONS = [30, 60, 120]

SAA_DRAW_GRID = [50, 100, 200, 400, 800]
SAA_SEED_GRID = [42, 1337, 2718]

# Mak-Morton-Wood optimality-gap arm.
SAA_GAP_SAMPLE_SIZES = [25, 50, 100, 200, 400]
SAA_GAP_REPLICATIONS = 12
SAA_GAP_LAMBDAS = [0.0, 0.5, 1.0]
# Reference measure when the pool is too wide to enumerate exactly.
SAA_REFERENCE_DRAWS = 20000


# ── Helpers ──────────────────────────────────────────────────────────────────

def _scale(bom: List[BomLine], multiplier: int) -> List[BomLine]:
    return [
        BomLine(component_id=b.component_id, mpn=b.mpn, quantity=b.quantity * multiplier)
        for b in bom
    ]


def _dedupe(offers: List[Offer]) -> Dict[Tuple[int, int], Offer]:
    best: Dict[Tuple[int, int], Offer] = {}
    for o in offers:
        key = (o.component_id, o.distributor_id)
        cur = best.get(key)
        if cur is None or (o.price_usd, -o.stock) < (cur.price_usd, -cur.stock):
            best[key] = o
    return best


def _max_feasible_multiplier(bom: List[BomLine], offers: List[Offer]) -> int:
    """Largest volume multiplier every BOM line can still be covered from stock."""
    best = _dedupe(offers)
    ceilings = []
    for b in bom:
        stock = sum(o.stock for (cid, _d), o in best.items() if cid == b.component_id)
        ceilings.append(stock // max(b.quantity, 1))
    return max(min(ceilings), 0) if ceilings else 0


# ── Solve quality ────────────────────────────────────────────────────────────
# Every lambda-solve in every arm is logged here so the artifact can carry a run-level
# distribution of statuses and MIP gaps, not just a per-point field a reader has to
# aggregate by hand.
_SOLVE_LOG: List[dict] = []


def _classify(p: st.FrontierPoint, time_limit_s: float) -> Tuple[bool, bool, Optional[str]]:
    """(converged, hit_time_limit, excluded_reason) for one frontier point."""
    hit_limit = p.status != "OPTIMAL"
    converged = (not hit_limit) or p.gap_pct <= CONVERGENCE_GAP_PCT
    if converged:
        return True, hit_limit, None
    # Name the budget that ACTUALLY bound. Under a deterministic budget the wall
    # clock is only a runaway guard, and calling a det-limited stop a "time limit"
    # would tell the reader the number is load-dependent when it is not.
    if p.deterministic_time_limit is not None:
        budget = (
            f"the {p.deterministic_time_limit:g} deterministic-time budget "
            f"(wall clock {p.wall_seconds:.1f}s, guard {time_limit_s:g}s)"
        )
    else:
        budget = f"the {time_limit_s:g}s wall-clock time limit"
    return False, hit_limit, (
        f"CP-SAT returned {p.status} at {budget} with a "
        f"{p.gap_pct:.2f}% optimality gap (threshold {CONVERGENCE_GAP_PCT:g}%). The plan "
        "is feasible but its first-stage choice was never proved near-optimal, so this "
        "is not a point on the efficient frontier. It is reported here and excluded "
        "from the knee, the reported spreads and every headline figure."
    )


def _budget_prose(det_limit_s: Optional[float], time_limit_s: float) -> str:
    """How to name the per-solve budget in text an artifact or a document carries.

    Under a deterministic budget the wall clock is only a runaway guard. Writing
    "the 300s per-solve limit" would tell a reader the clock stopped the search and
    therefore that the number is load-dependent -- the exact misreading the switch
    to `max_deterministic_time` was made to remove. `_classify` already got this
    right; this helper exists so the OTHER call sites cannot get it wrong again.
    """
    if det_limit_s is not None:
        return (f"the {det_limit_s:g}-unit deterministic-time budget "
                f"(a WORK budget, not the clock; {time_limit_s:g}s wall-clock "
                "runaway guard)")
    return f"the {time_limit_s:g}s wall-clock per-solve limit"


def _converged(points: Sequence[st.FrontierPoint], time_limit_s: float
               ) -> List[st.FrontierPoint]:
    return [p for p in points if _classify(p, time_limit_s)[0]]


def _record_solves(
    arm: str,
    instance: str,
    points: Sequence[st.FrontierPoint],
    time_limit_s: float,
) -> None:
    for p in points:
        converged, hit_limit, reason = _classify(p, time_limit_s)
        _SOLVE_LOG.append({
            "arm": arm,
            "instance": instance,
            "lambda": round(p.lam, 4),
            "solver_status": p.status,
            "mip_gap_pct": round(p.gap_pct, 4),
            "solve_seconds": round(p.wall_seconds, 3),
            "deterministic_seconds": round(p.deterministic_seconds, 6),
            "deterministic_time_limit": p.deterministic_time_limit,
            # The falsifiable half of the determinism claim: when a deterministic
            # budget is in force, the WALL clock must never be what stopped the
            # solve. If it did, this solve does not reproduce and says so.
            "wall_clock_bound": bool(
                p.deterministic_time_limit is not None
                and p.wall_seconds >= time_limit_s - 0.05
            ),
            "time_limit_s": time_limit_s,
            "hit_time_limit": hit_limit,
            "converged": converged,
            "excluded_reason": reason,
        })


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile of an already-sorted sequence."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _solve_quality_summary() -> dict:
    """
    Run-level solve-quality report over every lambda-solve in every arm.

    This block exists because the first full run of this script published 153 frontier
    points of which 49 carried an optimality gap above 5% (worst: 93.4%) and 22 came
    back FEASIBLE rather than OPTIMAL -- and nothing in the artifact or the document
    said so. The frontier was presented as if every point were proved.
    """
    rows = _SOLVE_LOG
    if not rows:
        return {"n_solves": 0}

    gaps = sorted(r["mip_gap_pct"] for r in rows)
    by_status: Dict[str, int] = {}
    by_arm: Dict[str, dict] = {}
    for r in rows:
        by_status[r["solver_status"]] = by_status.get(r["solver_status"], 0) + 1
        a = by_arm.setdefault(r["arm"], {
            "n_solves": 0, "n_converged": 0, "n_time_limit_hits": 0, "worst_gap_pct": 0.0,
        })
        a["n_solves"] += 1
        a["n_converged"] += int(r["converged"])
        a["n_time_limit_hits"] += int(r["hit_time_limit"])
        a["worst_gap_pct"] = max(a["worst_gap_pct"], r["mip_gap_pct"])

    not_converged = [r for r in rows if not r["converged"]]
    worst = max(rows, key=lambda r: r["mip_gap_pct"])
    return {
        "convergence_gap_threshold_pct": CONVERGENCE_GAP_PCT,
        "rule": (
            "converged := solver_status == 'OPTIMAL' (CP-SAT closed the bound to "
            f"relative_gap_limit = {st.DEFAULT_RELATIVE_GAP} -- proved outright, not to "
            f"a tolerance) OR mip_gap_pct <= "
            f"{CONVERGENCE_GAP_PCT:g}. Non-converged points are retained in the artifact "
            "with converged=false and an excluded_reason, and are excluded from every "
            "knee, spread and headline figure."
        ),
        "n_solves": len(rows),
        "n_converged": len(rows) - len(not_converged),
        "n_not_converged": len(not_converged),
        "n_time_limit_hits": sum(1 for r in rows if r["hit_time_limit"]),
        # Zero is the only acceptable value when a deterministic budget is in force;
        # a nonzero count means the wall clock, not the work budget, decided where
        # those solves stopped, so THEY DO NOT REPRODUCE.
        "n_wall_clock_bound": sum(1 for r in rows if r.get("wall_clock_bound")),
        "deterministic_budget_in_force": any(
            r.get("deterministic_time_limit") is not None for r in rows),
        "counts_by_status": dict(sorted(by_status.items())),
        "gap_pct_distribution": {
            "min": round(gaps[0], 4),
            "p50": round(_quantile(gaps, 0.5), 4),
            "p90": round(_quantile(gaps, 0.9), 4),
            "p99": round(_quantile(gaps, 0.99), 4),
            "max": round(gaps[-1], 4),
            "n_above_1pct": sum(1 for g in gaps if g > 1.0),
            "n_above_5pct": sum(1 for g in gaps if g > CONVERGENCE_GAP_PCT),
        },
        "worst_solve": worst,
        "by_arm": {k: by_arm[k] for k in sorted(by_arm)},
        "not_converged": not_converged[:200],
        "not_converged_truncated": len(not_converged) > 200,
    }


def _point_dict(p: st.FrontierPoint, time_limit_s: float) -> dict:
    converged, hit_limit, reason = _classify(p, time_limit_s)
    return {
        "lambda": round(p.lam, 4),
        "expected_cost_usd": round(p.expected_cost_usd, 2),
        "cvar_95_usd": round(p.cvar_usd, 2),
        "var_95_usd": round(p.var_usd, 2),
        "cvar_by_alpha_usd": {str(a): round(v, 2) for a, v in sorted(p.cvar_by_alpha.items())},
        "n_atoms_in_alpha_tail": p.n_atoms_in_tail,
        "largest_tail_atom_share": round(p.largest_tail_atom_share, 4),
        "evaluation_kind": p.evaluation_kind,
        "tail_premium_usd": round(p.cvar_usd - p.expected_cost_usd, 2),
        "first_stage_cost_usd": round(p.first_stage_cost_usd, 2),
        "expected_recourse_usd": round(p.expected_recourse_usd, 2),
        "n_suppliers": p.n_suppliers,
        "supplier_ids": p.supplier_ids,
        "solver_status": p.status,
        "mip_gap_pct": round(p.gap_pct, 4),
        "solve_seconds": round(p.wall_seconds, 3),
        "time_limit_s": time_limit_s,
        "hit_time_limit": hit_limit,
        "converged": converged,
        "excluded_reason": reason,
        "evaluate_seconds": round(p.evaluate_seconds, 3),
        # What the OPTIMIZER weighted at THIS lambda, reported separately from what the
        # point was SCORED on -- conflating the two is the defect this arm carried until
        # 2026-08-27. The integer weight denominator is chosen per solve from the
        # objective magnitude the int64 ceiling can carry, so it is not constant across
        # the lambda grid and neither is the mass that falls below its resolution.
        # `solve_residual_mass` is that mass. It is a deterministic rounding artefact of
        # the quantization, NOT sampling error: no confidence interval, and it does not
        # shrink with more draws.
        "solve_kind": p.solve_kind,
        "n_atoms_weighted_in_solve": p.n_scenarios_weighted,
        "solve_weight_denominator": p.solve_weight_total,
        "solve_residual_mass": p.solve_residual_mass,
        "n_variables": p.n_variables,
        "dominated": p.dominated,
    }


def _fit_dict(
    fit: st.ScenarioBudgetFit, points: Sequence[st.FrontierPoint] = ()
) -> dict:
    """
    What the OPTIMIZER actually saw, kept distinct from what the points were SCORED on.

    These two questions used to share one field, and the answer to the first was quietly
    the 200-draw sample while the document advertised the second. They are answered
    separately now so a reader can see the difference rather than infer it.

    The integer weight denominator is chosen per solve, so the WORST point on each axis
    is reported rather than a flattering one.
    """
    out: Dict[str, object] = {
        "kind": fit.kind,
        "exact": fit.exact,
        "n_distinct": fit.n_distinct,
        "n_draws_used": fit.n_draws_used,
        "second_stage_variables": fit.recourse_variables,
        "variable_budget": fit.max_recourse_variables,
        "thinned": fit.thinned,
        "at_floor": fit.at_floor,
        "exact_rejected_reason": fit.exact_rejected_reason,
        "note": fit.note,
    }
    if points:
        out["n_atoms_weighted_worst_point"] = min(
            p.n_scenarios_weighted for p in points)
        out["weight_denominator_worst_point"] = min(
            p.solve_weight_total for p in points)
        out["residual_mass_worst_point"] = max(
            p.solve_residual_mass for p in points)
        out["residual_mass_note"] = (
            "Probability mass on atoms whose exact probability rounds below the "
            "integer objective-weight resolution. A DETERMINISTIC QUANTIZATION "
            "ARTEFACT, not sampling error: it has no confidence interval, it is not an "
            "estimate of anything, and it does not shrink with more draws."
        )
    return out


def _tail_decomposition(result: st.StochasticSourcingResult, alpha: float) -> dict:
    """
    What is actually IN the worst 5%? Emergency purchasing, or demand that simply could
    not be covered? The answer changes the recommendation completely, so it is
    published rather than left implicit in a single CVaR number.

    Weighted by scenario PROBABILITY, not by Monte Carlo draw count: an enumerated
    scenario set has no draws at all, and weighting by `count` there silently produced
    an all-zero decomposition.
    """
    ordered = sorted(result.outcomes, key=lambda o: -o.total_cost_usd)
    total_mass = sum(o.probability for o in ordered)
    tail_mass = (1.0 - alpha) * total_mass
    if tail_mass <= 0.0:
        return {"tail_mass": 0.0, "n_atoms_in_tail": 0, "worst_scenarios": []}

    acc = 0.0
    emerg = 0.0
    unmet = 0.0
    rec = 0.0
    n_atoms = 0
    scenarios: List[dict] = []
    for o in ordered:
        take = min(o.probability, tail_mass - acc)
        if take <= 0:
            break
        acc += take
        n_atoms += 1
        emerg += o.emergency_units * take
        unmet += o.unmet_units * take
        rec += o.recourse_cost_usd * take
        scenarios.append({
            "failed_distributor_ids": sorted(o.failed),
            "probability": round(o.probability, 8),
            "share_of_tail": round(take / tail_mass, 4),
            "total_cost_usd": round(o.total_cost_usd, 2),
            "recourse_cost_usd": round(o.recourse_cost_usd, 2),
            "emergency_units": o.emergency_units,
            "unmet_units": o.unmet_units,
        })
    # Ranked by CONTRIBUTION to the tail, not by cost. The most expensive scenarios are
    # "every supplier fails at once", whose probability is ~1e-8; they are in the tail
    # but they are not what the tail is made of. Sorting by share makes the reported
    # rows the ones that actually move CVaR.
    scenarios.sort(key=lambda r: -r["share_of_tail"])
    scenarios = scenarios[:6]
    return {
        "alpha": alpha,
        "tail_mass": round(tail_mass, 6),
        "n_atoms_in_tail": n_atoms,
        "weighted_by": "probability" if result.evaluation_kind == "exact" else "draw share",
        "mean_emergency_units_in_tail": round(emerg / tail_mass, 1),
        "mean_unmet_units_in_tail": round(unmet / tail_mass, 1),
        "mean_recourse_cost_in_tail_usd": round(rec / tail_mass, 2),
        "worst_scenarios": scenarios,
    }


def _knee_point(
    points: Sequence[st.FrontierPoint],
    time_limit_s: float,
) -> Optional[st.FrontierPoint]:
    """The knee, computed on the CONVERGED subset only -- see `CONVERGENCE_GAP_PCT`."""
    return st.find_knee(_converged(points, time_limit_s))


def _knee_dict(
    points: Sequence[st.FrontierPoint],
    time_limit_s: float,
) -> Optional[dict]:
    """
    The knee, plus the two numbers that turn it into a recommendation: what the last
    dollar of resilience bought before the knee, and what it buys after.

    Computed on converged points only. A point the solver never proved cannot define
    the knee: its (E, CVaR) coordinates describe a plan that may be arbitrarily far
    from the efficient frontier, and letting it anchor the chord would move the
    recommendation to wherever the time limit happened to land.
    """
    ok = _converged(points, time_limit_s)
    n_excluded = len(points) - len(ok)
    knee = st.find_knee(ok)
    if knee is None:
        return None
    usable = sorted([p for p in ok if not p.dominated], key=lambda p: p.expected_cost_usd)
    lo, hi = usable[0], usable[-1]

    d_e_before = knee.expected_cost_usd - lo.expected_cost_usd
    d_c_before = lo.cvar_usd - knee.cvar_usd
    d_e_after = hi.expected_cost_usd - knee.expected_cost_usd
    d_c_after = knee.cvar_usd - hi.cvar_usd

    return {
        "lambda": round(knee.lam, 4),
        "expected_cost_usd": round(knee.expected_cost_usd, 2),
        "cvar_95_usd": round(knee.cvar_usd, 2),
        "n_suppliers": knee.n_suppliers,
        "supplier_ids": knee.supplier_ids,
        "computed_on": "converged points only",
        "n_points_considered": len(ok),
        "n_points_excluded_not_converged": n_excluded,
        "vs_risk_neutral": {
            "extra_expected_cost_usd": round(d_e_before, 2),
            "extra_expected_cost_pct": round(100.0 * d_e_before / lo.expected_cost_usd, 4)
            if lo.expected_cost_usd else 0.0,
            "cvar_reduction_usd": round(d_c_before, 2),
            "cvar_reduction_pct": round(100.0 * d_c_before / lo.cvar_usd, 4)
            if lo.cvar_usd else 0.0,
            "usd_of_cvar_removed_per_usd_of_expected_cost": round(d_c_before / d_e_before, 3)
            if d_e_before > 1e-9 else None,
        },
        "beyond_the_knee": {
            "extra_expected_cost_usd": round(d_e_after, 2),
            "cvar_reduction_usd": round(d_c_after, 2),
            "usd_of_cvar_removed_per_usd_of_expected_cost": round(d_c_after / d_e_after, 3)
            if d_e_after > 1e-9 else None,
        },
    }


def _certain_set(n_draws: int) -> st.ScenarioSet:
    """The mean-value ('expect no disruption') scenario set, for the EEV baseline."""
    return st.ScenarioSet(
        scenarios=[st.DisruptionScenario(failed=frozenset(), count=n_draws)],
        n_draws=n_draws, seed=0, failure_probs={},
    )


def _profile_dict(
    label: str,
    res: st.StochasticSourcingResult,
    frontier: Sequence[st.FrontierPoint] = (),
) -> dict:
    """
    Score a baseline plan and locate it relative to the frontier.

    `dominated_by_lambda` is the decisive field. If a frontier point beats a baseline
    on BOTH expected cost and CVaR, that baseline is strictly worse and the stochastic
    program has bought something real. If nothing dominates it, the baseline already
    sits on (or near) the efficient frontier -- and the honest claim shrinks to "the
    heuristic lands somewhere reasonable, but cannot tell you WHERE, and cannot be
    moved". `nearest_lambda` reports which risk preference it is implicitly expressing.
    """
    out = {
        "plan": label,
        "expected_cost_usd": round(res.expected_cost_usd, 2),
        "cvar_95_usd": round(res.cvar_usd, 2),
        "first_stage_cost_usd": round(res.first_stage_cost_usd, 2),
        "n_suppliers": res.n_suppliers,
        "supplier_ids": res.selected_distributor_ids,
    }
    if not frontier:
        return out

    tol = 1e-6
    dominators = [
        round(p.lam, 4) for p in frontier
        if p.expected_cost_usd < res.expected_cost_usd - tol
        and p.cvar_usd < res.cvar_usd - tol
    ]
    e_span = max(p.expected_cost_usd for p in frontier) - min(
        p.expected_cost_usd for p in frontier) or 1.0
    c_span = max(p.cvar_usd for p in frontier) - min(p.cvar_usd for p in frontier) or 1.0
    nearest = min(
        frontier,
        key=lambda p: ((p.expected_cost_usd - res.expected_cost_usd) / e_span) ** 2
        + ((p.cvar_usd - res.cvar_usd) / c_span) ** 2,
    )
    out["dominated_by_lambda"] = dominators
    out["is_dominated"] = bool(dominators)
    out["nearest_lambda"] = round(nearest.lam, 4)
    return out


# ── Arms ─────────────────────────────────────────────────────────────────────

def _run_primary(
    bom0: List[BomLine],
    offers: List[Offer],
    weights,
    scenario_set: st.ScenarioSet,
    exact_set: Optional[st.ScenarioSet],
) -> dict:
    out: Dict[str, dict] = {}
    for m in PRIMARY_MULTIPLIERS:
        bom = _scale(bom0, m)
        t0 = time.perf_counter()
        # CHOOSE AND SCORE ON THE SAME MEASURE. Until 2026-08-27 this arm chose the
        # plan on the 200-draw sample and then scored it on the enumerated support, so
        # the optimizer minimised one distribution and this document published another.
        # The sampled solve resolved 10 of the 64 atoms, leaving the alpha = 0.95 tail
        # the OPTIMIZER saw four atoms wide against an exact 49-54, and it returned a
        # lambda = 1.00 point dominated on both axes -- a solver artefact, published.
        #
        # `fit_scenario_set` takes the exact support when its second stage fits the
        # variable budget and falls back to the draw ladder when it does not: the same
        # function and the same rule app/api/stochastic.py serves the live frontier
        # from. The budget is a property of the SCALED bom, so it is refitted per volume
        # rather than assumed to carry over from x100 to x10,000.
        fit = st.fit_scenario_set(
            bom, offers, weights, scenario_set.failure_probs,
            n_draws=N_DRAWS, seed=SEED, us_only=False, exact_set=exact_set,
        )
        points, results = st.compute_frontier(
            bom, offers, weights, fit.scenario_set, LAMBDA_GRID,
            us_only=False, time_limit_s=TIME_LIMIT_PRIMARY_S,
            evaluation_set=exact_set,
            deterministic_time_limit=DET_LIMIT_PRIMARY,
        )
        sweep_s = time.perf_counter() - t0
        by_lam = {r.lam: r for r in results}
        _record_solves("primary", f"{PRIMARY_BOM}_x{m}", points, TIME_LIMIT_PRIMARY_S)
        ok_points = _converged(points, TIME_LIMIT_PRIMARY_S)
        ok_lams = {round(p.lam, 6) for p in ok_points}
        knee_pt = st.find_knee(ok_points)

        # ── Out-of-sample validation ────────────────────────────────────────
        # Every plan on the frontier was CHOSEN on the seed-42 scenario set. Scoring it
        # on the same draws is in-sample and flatters it. These are independent draws
        # from the same distribution: if the frontier ordering survives them, it is not
        # fitted to its own Monte Carlo noise.
        # Out-of-sample re-scoring is only informative when the published numbers are
        # themselves sampled. With the exact support in hand it is redundant -- an
        # independent draw cannot be more correct than the true measure -- so it is kept
        # as a cross-check on the SAA numbers rather than as the validation of record.
        oos: List[dict] = []
        for oos_seed in OUT_OF_SAMPLE_SEEDS:
            oos_set = st.sample_scenarios(scenario_set.failure_probs, N_DRAWS, oos_seed)
            entry: Dict[str, object] = {"seed": oos_seed, "points": []}
            pts: List[dict] = []
            for r in results:
                prof = st.evaluate_plan(r.assignments, bom, offers, weights, oos_set)
                pts.append({
                    "lambda": round(r.lam, 4),
                    "expected_cost_usd": round(prof.expected_cost_usd, 2),
                    "cvar_95_usd": round(prof.cvar_usd, 2),
                })
            entry["points"] = pts
            oos.append(entry)

        # ── Baselines: what you would have done without this model ──────────
        baselines: List[dict] = []

        mean_value = st.solve_stochastic_sourcing(
            bom, offers, weights, _certain_set(N_DRAWS), lam=0.0, us_only=False,
            time_limit_s=TIME_LIMIT_PRIMARY_S,
            deterministic_time_limit=DET_LIMIT_PRIMARY,
        )
        reference = exact_set if exact_set is not None else scenario_set
        eev = st.evaluate_plan(mean_value.assignments, bom, offers, weights, reference)
        baselines.append({
            **_profile_dict("mean_value_deterministic", eev, ok_points),
            "note": "Solves the same cost model with disruptions assumed away, then "
                    "scores that plan under the scenarios. This is the textbook EEV.",
        })

        for graph_aware in (False, True):
            try:
                det = solve_sourcing(bom, offers, weights, us_only=False,
                                     graph_aware=graph_aware)
            except (ValueError, RuntimeError) as exc:
                baselines.append({
                    "plan": f"shipped_milp_graph_aware={graph_aware}",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue
            prof = st.evaluate_plan(det.assignments, bom, offers, weights, reference)
            baselines.append({
                **_profile_dict(f"shipped_milp_graph_aware={graph_aware}", prof, ok_points),
                "note": "The plan app/optimization/sourcing.py returns TODAY, including "
                        "its heuristic risk surcharges, scored under the same scenarios.",
            })

        # How much does the MEASURE alone move the answer? Identical plans, scored
        # once on the 200-draw sample and once on the exact support. With the choice now
        # made exactly this isolates measurement error cleanly: any difference below is
        # the sample misreading a plan, with no confounding from a different plan having
        # been chosen.
        saa_vs_exact: List[dict] = []
        if exact_set is not None:
            for r in results:
                in_sample = st.evaluate_plan(
                    r.assignments, bom, offers, weights, scenario_set)
                saa_vs_exact.append({
                    "lambda": round(r.lam, 4),
                    "expected_cost_saa_usd": round(in_sample.expected_cost_usd, 2),
                    "expected_cost_exact_usd": round(r.expected_cost_usd, 2),
                    "cvar_95_saa_usd": round(in_sample.cvar_usd, 2),
                    "cvar_95_exact_usd": round(r.cvar_usd, 2),
                    "cvar_95_sampling_error_pct": round(
                        100.0 * (in_sample.cvar_usd - r.cvar_usd) / r.cvar_usd, 4)
                    if r.cvar_usd else 0.0,
                    "atoms_in_tail_saa": in_sample.tail.n_atoms_in_tail,
                    "atoms_in_tail_exact": r.tail.n_atoms_in_tail,
                })

        # VSS is a claim about the RISK-NEUTRAL optimum, so it may only be built from
        # solves that were actually proved.
        rp_pool = [r.expected_cost_usd for r in results if round(r.lam, 6) in ok_lams]
        rp = min(rp_pool) if rp_pool else min(r.expected_cost_usd for r in results)
        out[f"x{m}"] = {
            "multiplier": m,
            "total_units": sum(b.quantity for b in bom),
            "lines": [{"mpn": b.mpn, "quantity": b.quantity} for b in bom],
            "sweep_wall_seconds": round(sweep_s, 2),
            "solve_set": _fit_dict(fit, points),
            "frontier": [_point_dict(p, TIME_LIMIT_PRIMARY_S) for p in points],
            "solve_quality": {
                "n_points": len(points),
                "n_converged": len(ok_points),
                "n_excluded_not_converged": len(points) - len(ok_points),
                "n_hit_time_limit": sum(1 for p in points if p.status != "OPTIMAL"),
                "statuses": sorted({p.status for p in points}),
                "worst_mip_gap_pct": round(max(p.gap_pct for p in points), 4),
                "worst_converged_mip_gap_pct": (
                    round(max(p.gap_pct for p in ok_points), 4) if ok_points else None),
                "time_limit_s": TIME_LIMIT_PRIMARY_S,
                "all_points_converged": len(ok_points) == len(points),
            },
            "knee": _knee_dict(points, TIME_LIMIT_PRIMARY_S),
            "tail_decomposition_at_lambda_0": _tail_decomposition(by_lam[0.0], st.DEFAULT_ALPHA),
            "tail_decomposition_at_knee": (
                _tail_decomposition(by_lam[knee_pt.lam], st.DEFAULT_ALPHA)
                if knee_pt is not None else None
            ),
            "out_of_sample": oos,
            "saa_vs_exact": saa_vs_exact,
            "baselines": baselines,
            "value_of_the_stochastic_solution": {
                "RP_expected_cost_usd": round(rp, 2),
                "EEV_expected_cost_usd": round(eev.expected_cost_usd, 2),
                "VSS_usd": round(eev.expected_cost_usd - rp, 2),
                "VSS_pct_of_RP": round(100.0 * (eev.expected_cost_usd - rp) / rp, 4) if rp else 0.0,
                "definition": "VSS = EEV - RP. What ignoring uncertainty at plan time "
                              "costs in expectation, on the SAME cost model. VSS >= 0 by "
                              "construction; a VSS near zero means the deterministic plan "
                              "was already the risk-neutral optimum.",
            },
        }
        logger.info("primary x%d done in %.1fs", m, sweep_s)
    return out


def _run_breadth(
    loaded: Dict[str, Tuple[List[BomLine], List[Offer], dict]],
    weights,
    betweenness: Dict[int, float],
) -> dict:
    out: Dict[str, dict] = {}
    for name, (bom0, offers, _meta) in loaded.items():
        ceiling = _max_feasible_multiplier(bom0, offers)
        grid = [m for m in BREADTH_MULTIPLIER_GRID if m <= ceiling] or [1]
        pool = sorted({o.distributor_id for o in offers})
        probs = st.build_failure_probabilities(pool, betweenness)
        # Same rule as the primary arm: enumerate the exact support where the pool is
        # narrow enough, otherwise fall back to the draw ladder and say so per BOM.
        # There is no module-level sampled set here any more: what gets solved is
        # decided per VOLUME by `fit_scenario_set` inside the loop, because the
        # second-stage variable count is a property of the scaled BOM.
        bom_exact = (
            st.enumerate_scenarios(probs)
            if len(pool) <= st.MAX_ENUMERABLE_DISTRIBUTORS else None
        )
        entries: List[dict] = []
        for m in grid:
            bom = _scale(bom0, m)
            t0 = time.perf_counter()
            # Exact-first, same rule as the primary arm, refitted per volume because the
            # second-stage variable count is a property of the SCALED BOM: a pool that
            # enumerates comfortably at x1 can blow the budget at x10,000. Pools too
            # wide to enumerate fall back to the draw ladder and say so per row.
            try:
                fit = st.fit_scenario_set(
                    bom, offers, weights, probs,
                    n_draws=N_DRAWS, seed=SEED, us_only=False, exact_set=bom_exact,
                )
                points, _res = st.compute_frontier(
                    bom, offers, weights, fit.scenario_set, LAMBDA_GRID_COARSE,
                    us_only=False, time_limit_s=TIME_LIMIT_BREADTH_S,
                    evaluation_set=bom_exact,
                    deterministic_time_limit=DET_LIMIT_BREADTH,
                )
            except (ValueError, RuntimeError) as exc:
                entries.append({"multiplier": m, "error": f"{type(exc).__name__}: {exc}"})
                continue
            _record_solves("breadth", f"{name}_x{m}", points, TIME_LIMIT_BREADTH_S)
            ok = _converged(points, TIME_LIMIT_BREADTH_S)
            if not ok:
                entries.append({
                    "multiplier": m,
                    "total_units": sum(b.quantity for b in bom),
                    "n_distinct_scenarios": fit.n_distinct,
                    "solve_set": _fit_dict(fit, points),
                    "excluded_reason": (
                        f"none of the {len(points)} lambda points converged within "
                        f"{_budget_prose(DET_LIMIT_BREADTH, TIME_LIMIT_BREADTH_S)} "
                        f"(worst gap {max(p.gap_pct for p in points):.2f}%); no "
                        "tradeoff can be reported for this instance."
                    ),
                    "worst_mip_gap_pct": round(max(p.gap_pct for p in points), 4),
                    "any_point_hit_time_limit": any(p.status != "OPTIMAL" for p in points),
                    "n_variables_max": max(p.n_variables for p in points),
                    "solve_quality": {
                        "n_points": len(points), "n_converged": 0,
                        "n_excluded_not_converged": len(points),
                        "n_hit_time_limit": sum(
                            1 for p in points if p.status != "OPTIMAL"),
                        "statuses": sorted({p.status for p in points}),
                        "worst_mip_gap_pct": round(max(p.gap_pct for p in points), 4),
                        "time_limit_s": TIME_LIMIT_BREADTH_S,
                        "all_points_converged": False,
                    },
                    "sweep_wall_seconds": round(time.perf_counter() - t0, 2),
                })
                logger.warning("breadth %s x%d: NO converged points", name, m)
                continue
            # Every aggregate below is computed on the CONVERGED subset -- an unproved
            # point's (E, CVaR) is not a statement about the efficient frontier.
            e_lo = min(p.expected_cost_usd for p in ok)
            c_lo = min(p.cvar_usd for p in ok)
            c_hi = max(p.cvar_usd for p in ok)
            e_at_c_lo = min(p.expected_cost_usd for p in ok if p.cvar_usd <= c_lo + 1e-9)
            entries.append({
                "multiplier": m,
                "total_units": sum(b.quantity for b in bom),
                "n_distinct_scenarios": fit.n_distinct,
                "solve_set": _fit_dict(fit, ok),
                "risk_neutral_expected_cost_usd": round(e_lo, 2),
                "risk_neutral_cvar_usd": round(c_hi, 2),
                "min_cvar_usd": round(c_lo, 2),
                "expected_cost_at_min_cvar_usd": round(e_at_c_lo, 2),
                "cvar_reduction_available_usd": round(c_hi - c_lo, 2),
                "cvar_reduction_available_pct": round(100.0 * (c_hi - c_lo) / c_hi, 4)
                if c_hi else 0.0,
                "price_of_that_reduction_usd": round(e_at_c_lo - e_lo, 2),
                "tradeoff_exists": bool(c_hi - c_lo > 0.01),
                "supplier_counts": sorted({p.n_suppliers for p in ok}),
                "scored_on": ok[0].evaluation_kind,
                "min_atoms_in_alpha_tail": min(p.n_atoms_in_tail for p in ok),
                "worst_mip_gap_pct": round(max(p.gap_pct for p in points), 4),
                "any_point_hit_time_limit": any(p.status != "OPTIMAL" for p in points),
                "n_variables_max": max(p.n_variables for p in points),
                "solve_quality": {
                    "n_points": len(points),
                    "n_converged": len(ok),
                    "n_excluded_not_converged": len(points) - len(ok),
                    "n_hit_time_limit": sum(1 for p in points if p.status != "OPTIMAL"),
                    "statuses": sorted({p.status for p in points}),
                    "worst_mip_gap_pct": round(max(p.gap_pct for p in points), 4),
                    "worst_converged_mip_gap_pct": round(max(p.gap_pct for p in ok), 4),
                    "excluded_lambdas": [
                        round(p.lam, 4) for p in points
                        if not _classify(p, TIME_LIMIT_BREADTH_S)[0]
                    ],
                    "time_limit_s": TIME_LIMIT_BREADTH_S,
                    "all_points_converged": len(ok) == len(points),
                },
                "sweep_wall_seconds": round(time.perf_counter() - t0, 2),
            })
            logger.info("breadth %s x%d (%.1fs)", name, m, entries[-1]["sweep_wall_seconds"])
        out[name] = {
            "stock_ceiling_multiplier": ceiling,
            "n_distributors_in_pool": len(pool),
            "support_size_2_pow_D": 2 ** len(pool),
            "enumerated_exactly": bom_exact is not None,
            "points": entries,
        }
    return out


def _run_sensitivity(
    bom0: List[BomLine],
    offers: List[Offer],
    weights,
    betweenness: Dict[int, float],
) -> dict:
    """
    THE ARM THAT DECIDES WHETHER ANY OF THIS IS WORTH BELIEVING.

    The disruption probabilities are not measured. They are a cited firm-level base
    rate, reinterpreted as a per-supplier rate, converted to an exposure window, and
    re-shaped by a centrality rank transform. Every one of those four steps is an
    assumption. So the deliverable is not a point estimate of the knee -- it is the
    range the knee moves over when the assumptions are flexed, including the arm where
    centrality is ignored entirely (spread = 1.0).
    """
    bom = _scale(bom0, HEADLINE_MULTIPLIER)
    dids = sorted({o.distributor_id for o in offers})
    can_enumerate = len(dids) <= st.MAX_ENUMERABLE_DISTRIBUTORS
    rows: List[dict] = []

    for base_rate in SENSITIVITY_BASE_RATES:
        for spread in SENSITIVITY_SPREADS:
            for horizon in SENSITIVITY_HORIZONS:
                probs = st.build_failure_probabilities(
                    dids, betweenness, base_annual_prob=base_rate,
                    horizon_days=horizon, centrality_spread=spread,
                )
                scenarios = st.sample_scenarios(probs, N_DRAWS, SEED)
                exact = st.enumerate_scenarios(probs) if can_enumerate else None
                # Exact-first, same rule as the primary and breadth arms. This arm
                # re-runs the HEADLINE instance under flexed assumptions, so it has to
                # be solved the way the headline is solved or it stops being a
                # sensitivity analysis of the published frontier.
                fit = st.fit_scenario_set(
                    bom, offers, weights, probs,
                    n_draws=N_DRAWS, seed=SEED, us_only=False, exact_set=exact,
                )
                points, _res = st.compute_frontier(
                    bom, offers, weights, fit.scenario_set, LAMBDA_GRID_COARSE,
                    us_only=False, time_limit_s=TIME_LIMIT_PRIMARY_S,
                    evaluation_set=exact,
                    deterministic_time_limit=DET_LIMIT_PRIMARY,
                )
                _record_solves(
                    "sensitivity",
                    f"base={base_rate:g}/spread={spread:g}/horizon={horizon}",
                    points, TIME_LIMIT_PRIMARY_S,
                )
                ok = _converged(points, TIME_LIMIT_PRIMARY_S)
                knee = _knee_dict(points, TIME_LIMIT_PRIMARY_S)
                agg = ok or points  # keep the row readable if nothing converged
                e_lo = min(p.expected_cost_usd for p in agg)
                c_hi = max(p.cvar_usd for p in agg)
                c_lo = min(p.cvar_usd for p in agg)
                rows.append({
                    "base_annual_prob": round(base_rate, 4),
                    "centrality_spread": spread,
                    "horizon_days": horizon,
                    "horizon_prob_min": round(min(probs.values()), 5),
                    "horizon_prob_median": round(
                        sorted(probs.values())[len(probs) // 2], 5),
                    "horizon_prob_max": round(max(probs.values()), 5),
                    # The measure this row was actually solved and scored on, not
                    # whatever sample happened to be drawn alongside it.
                    "solve_kind": fit.kind,
                    "n_distinct_scenarios": fit.n_distinct,
                    "n_distinct_scenarios_sampled": scenarios.n_distinct,
                    "solve_residual_mass": (
                        round(max(p.solve_residual_mass for p in points), 12)
                        if points else None),
                    "p_no_disruption": round(
                        (exact if exact is not None else scenarios).p_no_disruption, 5),
                    "risk_neutral_expected_cost_usd": round(e_lo, 2),
                    "risk_neutral_cvar_usd": round(c_hi, 2),
                    "min_cvar_usd": round(c_lo, 2),
                    "cvar_reduction_available_pct": round(100.0 * (c_hi - c_lo) / c_hi, 4)
                    if c_hi else 0.0,
                    "knee_lambda": knee["lambda"] if knee else None,
                    "knee_n_suppliers": knee["n_suppliers"] if knee else None,
                    "knee_supplier_ids": knee["supplier_ids"] if knee else None,
                    "knee_extra_expected_cost_pct": (
                        knee["vs_risk_neutral"]["extra_expected_cost_pct"] if knee else None),
                    "knee_cvar_reduction_pct": (
                        knee["vs_risk_neutral"]["cvar_reduction_pct"] if knee else None),
                    "n_points": len(points),
                    "n_converged": len(ok),
                    "n_excluded_not_converged": len(points) - len(ok),
                    "statuses": sorted({p.status for p in points}),
                    "worst_mip_gap_pct": round(max(p.gap_pct for p in points), 4),
                    "all_points_converged": len(ok) == len(points),
                    "aggregates_computed_on": "converged points" if ok else "ALL points "
                                              "(none converged -- read with caution)",
                })
    return {
        "instance": {"bom": PRIMARY_BOM, "multiplier": HEADLINE_MULTIPLIER},
        "grid": {
            "base_annual_prob": [round(b, 4) for b in SENSITIVITY_BASE_RATES],
            "centrality_spread": SENSITIVITY_SPREADS,
            "horizon_days": SENSITIVITY_HORIZONS,
        },
        "rows": rows,
    }


def _run_saa_quality(
    bom0: List[BomLine],
    offers: List[Offer],
    weights,
    failure_probs: Dict[int, float],
    exact_set: Optional[st.ScenarioSet],
) -> dict:
    """
    How much is the Monte Carlo sample size actually costing us?

    THE OBJECTION THIS ANSWERS
    --------------------------
    "n_draws = 200 but n_distinct = 10, and alpha = 0.95, so 0.05 x 10 = 0.5 distinct
    scenarios land in the tail. That CVaR is one scenario wide."

    That objection is correct about the SAA numbers, and the diagnosis is more
    interesting than a bigger sample: disruption here is |D| independent Bernoulli
    variables, so the cost distribution has AT MOST 2**|D| atoms. The headline BOM is
    supplied by six distributors, so its entire support is 64 atoms. Sampling 200 draws
    from a 64-atom distribution recovers ~10 of them and adds nothing that enumerating
    all 64 does not already give exactly.

    So the primary arm stops sampling and enumerates -- and since 2026-08-27 it
    enumerates for the CHOICE as well as the score, so on the headline instance there is
    no sampling error left anywhere in the published frontier.

    THIS ARM STILL SAMPLES, AND MUST. Both of its experiments MEASURE what sampling
    costs, so enumerating them does not strengthen them -- it deletes them. The
    Mak-Morton-Wood lower bound IS the mean optimal value of M independent SAA
    replications: enumerate and every replication is the same solve, the variance is
    zero, and the reported gap is zero by construction rather than by measurement. The
    endpoint-stability table sweeps N and the seed precisely to show the wobble;
    enumerate and there is no wobble left to show. A vacuous zero is not a better result
    than a measured one.

    What this arm therefore bounds is the SAA PATH -- the fallback that wide-pool
    instances take, where the support cannot be held. It is NOT a bound on the choice
    error of the published headline frontier, which no longer has any to bound.

    The method, on the sampled path:

      lower bound   Mean optimal value of M independent SAA replications at size N.
                    Optimistically biased (each solve optimizes against its own sample),
                    so E[v_N] <= v* -- Mak, Morton & Wood (1999), Oper. Res. Lett.
                    24(1-2):47-56, doi:10.1016/S0167-6377(98)00054-6. Reported with a
                    one-sided Student-t confidence limit over the M replicates.
      upper bound   The true objective of the best candidate plan on the reference
                    measure. Any feasible plan bounds the optimum from above, and with
                    the exact support as reference this is not an estimate at all.
      gap           upper - lower, swept over N. Where it flattens is the sample size
                    that is actually justified.

    Kleywegt, Shapiro & Homem-de-Mello (2002), SIAM J. Optim. 12(2):479-502 is the
    convergence result for SAA with discrete first-stage decisions, which is this model.
    """
    bom = _scale(bom0, HEADLINE_MULTIPLIER)
    # The measure both bounds are read against. Exact where we have it, and a large
    # independent draw only where we do not.
    reference = exact_set if exact_set is not None else st.sample_scenarios(
        failure_probs, SAA_REFERENCE_DRAWS, 424242,
    )
    rows: List[dict] = []
    for n_scen in SAA_GAP_SAMPLE_SIZES:
        for lam in SAA_GAP_LAMBDAS:
            est = st.saa_optimality_gap(
                bom, offers, weights, failure_probs, reference,
                n_scenarios=n_scen, n_replications=SAA_GAP_REPLICATIONS,
                lam=lam, alpha=st.DEFAULT_ALPHA, us_only=False,
                time_limit_s=TIME_LIMIT_PRIMARY_S,
                deterministic_time_limit=DET_LIMIT_PRIMARY,
            )
            rows.append({
                "n_scenarios": est.n_scenarios,
                "n_replications": est.n_replications,
                "lambda": est.lam,
                "lower_bound_mean_usd": round(est.lower_bound_mean, 2),
                "lower_bound_stderr_usd": round(est.lower_bound_stderr, 2),
                "lower_bound_ci95_low_usd": round(est.lower_bound_ci_low, 2),
                "lower_bound_ci95_high_usd": round(est.lower_bound_ci_high, 2),
                "upper_bound_usd": round(est.upper_bound, 2),
                "upper_bound_kind": est.upper_bound_kind,
                "optimality_gap_usd": round(est.gap_estimate, 2),
                "optimality_gap_ci95_high_usd": round(est.gap_ci_high, 2),
                "optimality_gap_pct": round(est.gap_pct_of_upper, 4),
                "wall_seconds": round(est.wall_seconds, 2),
            })
            logger.info(
                "saa gap N=%d lam=%.2f: gap=$%.2f (%.3f%%), CI high $%.2f, %.1fs",
                n_scen, lam, est.gap_estimate, est.gap_pct_of_upper,
                est.gap_ci_high, est.wall_seconds,
            )

    # The cheap stability table stays: it shows the raw wobble in the two endpoints.
    #
    # DELIBERATELY SOLVED ON THE SAMPLE. This is the one place in this script that still
    # hands CP-SAT draws rather than the enumerated support, and it is not an oversight
    # left behind by the exact-support change -- the draw count IS the independent
    # variable of the experiment. Routing this through `fit_scenario_set` would make
    # every row solve the same 64 atoms, collapse the table to five identical rows, and
    # report "no sampling noise" as a finding when what actually happened is that the
    # measurement was removed. Scoring still uses `exact_set`, so each row reads its
    # sampled plan against the true measure.
    stability: List[dict] = []
    for n_draws in SAA_DRAW_GRID:
        for seed in SAA_SEED_GRID:
            scenarios = st.sample_scenarios(failure_probs, n_draws, seed)
            points, _res = st.compute_frontier(
                bom, offers, weights, scenarios, [0.0, 1.0],
                us_only=False, time_limit_s=TIME_LIMIT_PRIMARY_S,
                evaluation_set=exact_set,
                deterministic_time_limit=DET_LIMIT_PRIMARY,
            )
            _record_solves(
                "saa_endpoint_stability", f"N={n_draws}/seed={seed}",
                points, TIME_LIMIT_PRIMARY_S,
            )
            by_lam = {p.lam: p for p in points}
            stability.append({
                "n_draws": n_draws,
                "seed": seed,
                "n_distinct_scenarios": scenarios.n_distinct,
                "risk_neutral_expected_cost_usd": round(by_lam[0.0].expected_cost_usd, 2),
                "risk_neutral_cvar_usd": round(by_lam[0.0].cvar_usd, 2),
                "min_cvar_usd": round(by_lam[1.0].cvar_usd, 2),
                "min_cvar_expected_cost_usd": round(by_lam[1.0].expected_cost_usd, 2),
                "scored_on": by_lam[0.0].evaluation_kind,
                "statuses": {str(round(p.lam, 2)): p.status for p in points},
                "worst_mip_gap_pct": round(max(p.gap_pct for p in points), 4),
                "all_points_converged": len(
                    _converged(points, TIME_LIMIT_PRIMARY_S)) == len(points),
            })

    return {
        "instance": {"bom": PRIMARY_BOM, "multiplier": HEADLINE_MULTIPLIER},
        "method": {
            "lower_bound": "mean of M independent SAA optimal values at size N; "
                           "optimistically biased, so it estimates a lower bound on the "
                           "true optimum (Mak, Morton & Wood 1999)",
            "upper_bound": "true objective of the best candidate first-stage plan on the "
                           "reference measure; any feasible plan is a valid upper bound",
            "reference_measure": reference.kind,
            "citations": [
                "Mak, Morton & Wood (1999), 'Monte Carlo bounding techniques for "
                "determining solution quality in stochastic programs', Operations "
                "Research Letters 24(1-2):47-56, doi:10.1016/S0167-6377(98)00054-6",
                "Kleywegt, Shapiro & Homem-de-Mello (2002), 'The Sample Average "
                "Approximation Method for Stochastic Discrete Optimization', SIAM "
                "Journal on Optimization 12(2):479-502",
            ],
        },
        "solve_set_note": (
            "This arm is the ONLY one in this artifact whose plans are chosen on Monte "
            "Carlo draws. That is the experiment, not an omission: both tables measure "
            "what sampling costs, and enumerating their support would make the answer "
            "zero by construction. The primary, breadth and sensitivity arms choose on "
            "the enumerated support wherever it fits the solver's variable budget, so "
            "the bounds below describe the SAA fallback path, not the choice error of "
            "the published headline frontier."
        ),
        "solve_quality_note": (
            "The M x N replication solves inside `saa_optimality_gap` are run by "
            "app/optimization/stochastic.py, which does not surface their per-solve "
            "CP-SAT status, so they are NOT represented in the run-level solve_quality "
            "block. The `endpoint_stability` rows below are, and each carries its own "
            "statuses / worst_mip_gap_pct / all_points_converged."
        ),
        "optimality_gap": rows,
        "endpoint_stability": stability,
    }


# ── Rendering the numeric sections of the markdown from the artifact ─────────
#
# WHY THIS EXISTS
# ---------------
# `docs/CVAR_EFFICIENT_FRONTIER.md` used to be hand-transcribed from this artifact, and
# it drifted: sections 6, 7 and 8 said "Populated from docs/cvar_frontier.json ->
# sensitivity / saa_quality / breadth" while the committed artifact was a `--quick` run
# that contained none of those keys, and the section 9 row for `iot_sensor_node x100`
# quoted scenario counts and solve times from a run that no longer existed.
#
# So every NUMERIC block in that document is now generated from the artifact and
# delimited by HTML comments. Prose, caveats, retraction banners and the derivations
# live OUTSIDE the markers and are never touched by this code -- honest hand-written
# disclosure is not something a generator should be able to delete.

DOC_PATH = DOCS / "CVAR_EFFICIENT_FRONTIER.md"

# BOMs always shown in the section 9 solve-time table regardless of where they rank by
# wall time, because the document previously quoted hand-typed figures for them.
SOLVE_TIME_SPOTLIGHT_BOMS = ("iot_sensor_node",)

BEGIN = "<!-- GENERATED:{name}:BEGIN -->"
END = "<!-- GENERATED:{name}:END -->"


def _usd(x: Optional[float]) -> str:
    if x is None:
        return "—"
    sign = "−" if x < 0 else ""
    v = abs(x)
    return f"{sign}${v:,.0f}" if v >= 100 else f"{sign}${v:,.2f}"


def _pct(x: Optional[float], places: int = 2) -> str:
    return "—" if x is None else f"{x:.{places}f}%"


def _num(x: Optional[float], places: int = 0) -> str:
    return "—" if x is None else f"{x:,.{places}f}"


def _flag(converged: Optional[bool]) -> str:
    if converged is None:
        return "—"
    return "yes" if converged else "**NO**"


def _budget_phrase(payload: dict, arm: str) -> str:
    """Name the budget that ACTUALLY bound one arm's solves, read from the ARTIFACT.

    Two rules are load-bearing here:

    * **Never quote the wall clock as the budget when a deterministic budget is in
      force.** The clock is only a runaway guard; writing "inside the 300s budget"
      tells the reader these counters are load-dependent when they are not.
    * **Never read this module's constants.** A renderer that reads module state
      cannot reproduce a committed block from the committed artifact, which is
      exactly how `docs/CVAR_EFFICIENT_FRONTIER.md` came to publish "300s budget"
      while a fresh render of the same artifact produced "15s".
    """
    solver = (payload.get("meta") or {}).get("solver") or {}
    det = solver.get(f"max_deterministic_time_{arm}")
    wall = solver.get(f"max_time_in_seconds_{arm}")
    if det is not None:
        return (f"{det:g}-unit deterministic-time budget"
                + (f" ({wall:g}s wall-clock runaway guard)" if wall else ""))
    if wall:
        return f"{wall:g}s wall-clock budget"
    return "per-solve budget"


def _render_solve_quality(payload: dict) -> str:
    sq = payload.get("solve_quality") or {}
    if not sq.get("n_solves"):
        return "*(no solve-quality data in the artifact)*"
    d = sq["gap_pct_distribution"]
    lines = [
        f"Across the whole run, **{sq['n_solves']} λ-solves** were performed. "
        f"**{sq['n_converged']}** converged; **{sq['n_not_converged']}** did not and are "
        f"excluded from every knee, spread and headline below. "
        f"**{sq['n_time_limit_hits']}** returned a status other than `OPTIMAL` — that "
        "is, they exhausted the per-solve budget with the bound still open. "
        + (
            "That budget is DETERMINISTIC work, not elapsed time, and "
            f"`n_wall_clock_bound = {sq.get('n_wall_clock_bound', 0)}` records that the "
            "runaway guard stopped no solve, so every count in this block reproduces "
            "under any CPU load."
            if sq.get("deterministic_budget_in_force")
            else "That budget is WALL-CLOCK time, so every count in this block is a "
                 "measurement of one machine under one load."
        ),
        "",
        "| | |",
        "|---|---:|",
        f"| Solves | {sq['n_solves']} |",
        f"| Converged (`OPTIMAL`, or gap ≤ {sq['convergence_gap_threshold_pct']:g}%) | "
        f"{sq['n_converged']} |",
        f"| **Not converged — excluded from the frontier** | **{sq['n_not_converged']}** |",
        f"| Non-`OPTIMAL` solver returns | {sq['n_time_limit_hits']} |",
        f"| MIP gap: median | {_pct(d['p50'], 3)} |",
        f"| MIP gap: p90 | {_pct(d['p90'], 3)} |",
        f"| MIP gap: p99 | {_pct(d['p99'], 3)} |",
        f"| **MIP gap: worst** | **{_pct(d['max'], 3)}** |",
        f"| Solves above a 1% gap | {d['n_above_1pct']} |",
        f"| Solves above a {sq['convergence_gap_threshold_pct']:g}% gap | {d['n_above_5pct']} |",
        f"| Deterministic work budget in force | "
        f"{'yes' if sq.get('deterministic_budget_in_force') else 'no'} |",
        f"| **Solves the wall clock stopped — must be 0** | "
        f"**{sq.get('n_wall_clock_bound', 0)}** |",
        "",
        "Per arm:",
        "",
        "| Arm | Solves | Converged | Non-`OPTIMAL` | Worst gap |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm, a in (sq.get("by_arm") or {}).items():
        lines.append(
            f"| `{arm}` | {a['n_solves']} | {a['n_converged']} | "
            f"{a['n_time_limit_hits']} | {_pct(a['worst_gap_pct'], 3)} |"
        )
    worst = sq.get("worst_solve") or {}
    if worst:
        det = worst.get("deterministic_time_limit")
        wall = worst.get("time_limit_s")
        budget = (
            f"{det:g}-unit deterministic-time budget "
            f"(it used {worst.get('solve_seconds')}s of wall clock against a {wall:g}s "
            "runaway guard)"
            if det is not None
            else f"{wall:g}s wall-clock limit"
        )
        lines += [
            "",
            f"Worst single solve: arm `{worst.get('arm')}`, instance "
            f"`{worst.get('instance')}`, λ = {worst.get('lambda')} — status "
            f"`{worst.get('solver_status')}` at a **{_pct(worst.get('mip_gap_pct'), 3)}** "
            f"gap at the {budget}.",
        ]
    return "\n".join(lines)


def _render_frontier_table(payload: dict) -> str:
    inst = ((payload.get("primary") or {}).get(f"x{HEADLINE_MULTIPLIER}")) or {}
    pts = inst.get("frontier") or []
    if not pts:
        return "*(no primary frontier in the artifact)*"
    knee = inst.get("knee") or {}
    knee_lam = knee.get("lambda")

    lines = [
        "| λ | E[cost] | CVaR-95 | Tail premium | Suppliers | Atoms in tail | Status | Gap | Solve | On frontier |",
        "|---:|---:|---:|---:|:---:|---:|:---|---:|---:|:---:|",
    ]
    for p in pts:
        lam = p["lambda"]
        is_knee = knee_lam is not None and abs(lam - knee_lam) < 1e-9
        bold = (lambda s: f"**{s}**") if is_knee else (lambda s: s)
        tags = []
        if is_knee:
            tags.append("← **knee**")
        if p.get("dominated"):
            tags.append("*dominated*")
        if not p.get("converged", True):
            tags.append("⚠️ **excluded — not converged**")
        last = _flag(p.get("converged"))
        if tags:
            last += " " + " ".join(tags)
        lines.append(
            f"| {bold(f'{lam:.2f}')} | {bold(_usd(p['expected_cost_usd']))} | "
            f"{bold(_usd(p['cvar_95_usd']))} | {bold(_usd(p['tail_premium_usd']))} | "
            f"{bold(str(p['n_suppliers']))} | {p['n_atoms_in_alpha_tail']} | "
            f"{p['solver_status']} | {_pct(p['mip_gap_pct'], 3)} | "
            f"{p['solve_seconds']:.3f} s | {last} |"
        )

    alphas = sorted({a for p in pts for a in (p.get("cvar_by_alpha_usd") or {})},
                    key=float)
    if alphas:
        lines += ["", "CVaR is also reported at other tail levels, because a single α is "
                      "not enough to read a tail:", ""]
        lines.append("| λ | " + " | ".join(
            f"CVaR-{float(a) * 100:.0f}" for a in alphas) + " |")
        lines.append("|---:|" + "---:|" * len(alphas))
        keep = {pts[0]["lambda"], pts[-1]["lambda"]}
        if knee_lam is not None:
            keep.add(knee_lam)
        for p in pts:
            if p["lambda"] not in keep:
                continue
            is_knee = knee_lam is not None and abs(p["lambda"] - knee_lam) < 1e-9
            bold = (lambda s: f"**{s}**") if is_knee else (lambda s: s)
            cells = " | ".join(
                bold(_usd((p.get("cvar_by_alpha_usd") or {}).get(a))) for a in alphas)
            lam_s = bold(f"{p['lambda']:.2f}")
            lines.append(f"| {lam_s} | {cells} |")
    sq = inst.get("solve_quality") or {}
    if sq:
        lines += [
            "",
            f"*Solve quality for this sweep: {sq['n_converged']} of {sq['n_points']} λ "
            f"points converged, worst MIP gap {_pct(sq['worst_mip_gap_pct'], 3)}, "
            f"statuses {', '.join('`' + s + '`' for s in sq['statuses'])}, per-solve "
            f"budget {_budget_phrase(payload, 'primary')}.*",
        ]
    ss = inst.get("solve_set") or {}
    if ss.get("exact"):
        lines += [
            "",
            f"*Solved on the **complete {ss.get('n_distinct')}-atom support** with exact "
            "probability weights — the same measure these points are scored on, so "
            "there is no sampling error anywhere in this table and no SAA optimality "
            "gap to bound. CP-SAT's integer objective weights are those probabilities "
            "scaled by a common denominator (smallest on this sweep: "
            f"{ss.get('weight_denominator_worst_point', 0):,}); atoms whose probability "
            "falls below that resolution carry no weight, and that mass is "
            f"{ss.get('residual_mass_worst_point', 0.0):.2e} at the worst point on the "
            "grid. It is a deterministic rounding artefact of the quantization — not "
            "sampling error: it has no confidence interval and does not shrink with "
            "more draws. Published per point as `solve_residual_mass`.*",
        ]
    elif ss:
        lines += ["", f"*Solve set: {ss.get('note')}*"]
    return "\n".join(lines)


def _render_knee_table(payload: dict) -> str:
    inst = ((payload.get("primary") or {}).get(f"x{HEADLINE_MULTIPLIER}")) or {}
    knee = inst.get("knee")
    if not knee:
        return ("*No knee exists on this instance: fewer than three distinct converged "
                "non-dominated points. Inventing one would be dishonest.*")
    before, after = knee["vs_risk_neutral"], knee["beyond_the_knee"]
    ratio_before = before["usd_of_cvar_removed_per_usd_of_expected_cost"]
    ratio_after = after["usd_of_cvar_removed_per_usd_of_expected_cost"]
    sup = ", ".join(str(s) for s in knee["supplier_ids"])
    pts = inst.get("frontier") or []
    lam0 = next((p for p in pts if p["lambda"] == 0.0), None)
    n0 = lam0["n_suppliers"] if lam0 else "—"
    lam_hi = max((p["lambda"] for p in pts), default=1.0)
    lines = [
        f"**Knee: λ = {knee['lambda']:g}**, found by maximum perpendicular distance to the "
        "chord joining the extreme non-dominated points (the Kneedle / L-method "
        "criterion, Satopää et al. 2011), on min-max normalized axes so the answer does "
        "not depend on the currency unit — and computed on the "
        f"**{knee['n_points_considered']} converged points only** "
        f"({knee['n_points_excluded_not_converged']} excluded).",
        "",
        f"| | Before the knee (λ 0 → {knee['lambda']:g}) | Beyond the knee "
        f"(λ {knee['lambda']:g} → {lam_hi:g}) |",
        "|---|---:|---:|",
        f"| Extra expected cost | **+{_usd(before['extra_expected_cost_usd'])}** "
        f"(+{_pct(before['extra_expected_cost_pct'])}) | "
        f"+{_usd(after['extra_expected_cost_usd'])} |",
        f"| CVaR-95 reduction | **−{_usd(before['cvar_reduction_usd'])}** "
        f"(−{_pct(before['cvar_reduction_pct'])}) | "
        f"−{_usd(after['cvar_reduction_usd'])} |",
        f"| **$ of tail removed per $ spent** | **{_num(ratio_before, 2)}** | "
        f"{_num(ratio_after, 2)} |",
        "",
        f"> **Recommendation.** Source this BOM at **λ = {knee['lambda']:g}**: "
        f"{knee['n_suppliers']} suppliers ({sup}) rather than the risk-neutral {n0}. It "
        f"costs **{_usd(before['extra_expected_cost_usd'])} more per "
        f"{_num(inst.get('total_units'))}-unit build in expectation — "
        f"{_pct(before['extra_expected_cost_pct'])} of spend — and removes "
        f"{_usd(before['cvar_reduction_usd'])} of CVaR-95 exposure.** Every dollar of "
        f"that premium buys **${_num(ratio_before, 2)}** of tail reduction. Past the knee "
        f"the same dollar buys **${_num(ratio_after, 2)}**. Stop at the knee.",
    ]
    return "\n".join(lines)


def _render_exact_vs_saa_table(payload: dict) -> str:
    inst = ((payload.get("primary") or {}).get(f"x{HEADLINE_MULTIPLIER}")) or {}
    rows = inst.get("saa_vs_exact") or []
    supp = (payload.get("calibration") or {}).get("scenario_support") or {}
    if not rows:
        return ("*The primary instance was scored on the sampled set — its supplier pool "
                "is too wide to enumerate, so there is no exact column to compare.*")
    lo = min(r["lambda"] for r in rows)
    hi = max(r["lambda"] for r in rows)
    r_lo = next(r for r in rows if r["lambda"] == lo)
    r_hi = next(r for r in rows if r["lambda"] == hi)
    atoms_saa = sorted({r["atoms_in_tail_saa"] for r in rows})
    atoms_ex = sorted({r["atoms_in_tail_exact"] for r in rows})
    errs = sorted(r["cvar_95_sampling_error_pct"] for r in rows)

    def rng(vals: Sequence[int]) -> str:
        return str(vals[0]) if vals[0] == vals[-1] else f"{vals[0]}–{vals[-1]}"

    n_draws = ((payload.get("calibration") or {}).get("scenario_set") or {}).get(
        "n_draws", "?")
    n_atoms = supp.get("n_atoms_enumerated", "?")
    return "\n".join([
        f"| | SAA, {n_draws} draws | **Exact, {n_atoms} atoms** |",
        "|---|---:|---:|",
        f"| Atoms in the α = 0.95 tail | {rng(atoms_saa)} | **{rng(atoms_ex)}** |",
        f"| CVaR-95 at λ = {lo:g} | {_usd(r_lo['cvar_95_saa_usd'])} | "
        f"**{_usd(r_lo['cvar_95_exact_usd'])}** |",
        f"| CVaR-95 at λ = {hi:g} | {_usd(r_hi['cvar_95_saa_usd'])} | "
        f"**{_usd(r_hi['cvar_95_exact_usd'])}** |",
        f"| CVaR-95 sampling error | **{errs[0]:+.2f}% … {errs[-1]:+.2f}%** | — (none) |",
        f"| Residual probability mass | — | "
        f"**{supp.get('enumeration_residual_mass')}** |",
        "",
        f"The sampled tail was not merely thin, it was **biased by up to "
        f"{max(abs(errs[0]), abs(errs[-1])):.2f}%** — in both directions, depending on λ. "
        "That is a real error, it was invisible without the exact computation, and it is "
        "now gone.",
    ])


def _render_calibration_table(payload: dict) -> str:
    cal = payload.get("calibration") or {}
    rows = cal.get("primary_bom_distributors") or []
    if not rows:
        return "*(no calibration block in the artifact)*"
    defaults = cal.get("defaults") or {}
    horizon = defaults.get("horizon_days", "?")
    ordered = sorted(rows, key=lambda r: -r["p_disruption_over_horizon"])
    lines = [
        f"| Distributor | Betweenness | **Calibrated `p_fail`** ({horizon}-day) |",
        "|---:|---:|---:|",
    ]
    for r in ordered:
        lines.append(
            f"| {r['distributor_id']} | {r['betweenness_normalized']:.6f} | "
            f"**{r['p_disruption_over_horizon']:.4f}** |"
        )
    scen = cal.get("scenario_set") or {}
    supp = cal.get("scenario_support") or {}
    lines += [
        "",
        f"Base rate {defaults.get('base_annual_prob')} annual over "
        f"{horizon} days, centrality spread {defaults.get('centrality_spread')}, capped "
        f"at `MAX_FAILURE_PROB` = {defaults.get('max_failure_prob')}. **No supplier is "
        "anywhere near probability 1.0** — which is the whole point. The resulting "
        f"scenario set has P(no disruption) = {scen.get('p_no_disruption')} and "
        f"{scen.get('mean_failures_per_scenario')} expected failures per scenario over "
        f"{supp.get('n_distributors_in_primary_pool')} distributors.",
    ]
    return "\n".join(lines)


def _render_tail_table(payload: dict) -> str:
    inst = ((payload.get("primary") or {}).get(f"x{HEADLINE_MULTIPLIER}")) or {}
    t0 = inst.get("tail_decomposition_at_lambda_0") or {}
    tk = inst.get("tail_decomposition_at_knee") or {}
    scen = t0.get("worst_scenarios") or []
    if not scen:
        return "*(no tail decomposition in the artifact)*"
    by_knee = {
        tuple(s["failed_distributor_ids"]): s for s in (tk.get("worst_scenarios") or [])
    }
    top = scen[0]
    lines = [
        f"The α = {t0.get('alpha', 0.95)} tail is not diffuse. "
        f"**{top['share_of_tail'] * 100:.0f}% of it is one event: distributor "
        f"{', '.join(str(d) for d in top['failed_distributor_ids'])} going dark.**",
        "",
        "| Failed | Probability | Share of tail | Cost at λ=0 | **Cost at knee** | "
        "Emergency units (λ=0 → knee) | Unmet units (λ=0 → knee) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in scen[:4]:
        key = tuple(s["failed_distributor_ids"])
        k = by_knee.get(key)
        failed = "{" + ", ".join(str(d) for d in key) + "}"
        cost_k = _usd(k["total_cost_usd"]) if k else "—"
        em_k = f"{k['emergency_units']:,}" if k else "—"
        un_k = f"{k['unmet_units']:,}" if k else "—"
        lines.append(
            f"| {failed} | {s['probability'] * 100:.2f}% | "
            f"**{s['share_of_tail'] * 100:.1f}%** | {_usd(s['total_cost_usd'])} | "
            f"**{cost_k}** | {s['emergency_units']:,} → **{em_k}** | "
            f"{s['unmet_units']:,} → {un_k} |"
        )
    return "\n".join(lines)


def _render_baselines_table(payload: dict) -> str:
    inst = ((payload.get("primary") or {}).get(f"x{HEADLINE_MULTIPLIER}")) or {}
    pts = inst.get("frontier") or []
    knee = inst.get("knee") or {}
    vss = inst.get("value_of_the_stochastic_solution") or {}
    lam0 = next((p for p in pts if p["lambda"] == 0.0), None)

    labels = {
        "mean_value_deterministic": "Mean-value (disruptions assumed away)",
        "shipped_milp_graph_aware=False":
            "**Shipped MILP** (`sourcing.py`, heuristic surcharges live)",
        "shipped_milp_graph_aware=True":
            "**Shipped MILP**, graph-aware (`sourcing.py`, betweenness term on)",
    }
    lines = [
        "| Plan | E[cost] | CVaR-95 | Suppliers | Dominated by any λ? | Sits at λ ≈ |",
        "|---|---:|---:|:---:|:---:|:---:|",
    ]
    for b in inst.get("baselines") or []:
        if b.get("error"):
            lines.append(
                f"| {labels.get(b['plan'], b['plan'])} | — | — | — | — | "
                f"error: {b['error']} |"
            )
            continue
        dom = "**yes**" if b.get("is_dominated") else "no"
        lines.append(
            f"| {labels.get(b['plan'], b['plan'])} | {_usd(b['expected_cost_usd'])} | "
            f"{_usd(b['cvar_95_usd'])} | {b['n_suppliers']} | {dom} | "
            f"**{b.get('nearest_lambda')}** |"
        )
    if lam0:
        lines.append(
            f"| Stochastic, λ = 0 (risk-neutral) | {_usd(lam0['expected_cost_usd'])} | "
            f"{_usd(lam0['cvar_95_usd'])} | {lam0['n_suppliers']} | — | — |"
        )
    if knee:
        lines.append(
            f"| **Stochastic, λ = {knee['lambda']:g} (knee)** | "
            f"**{_usd(knee['expected_cost_usd'])}** | **{_usd(knee['cvar_95_usd'])}** | "
            f"**{knee['n_suppliers']}** | — | — |"
        )
    if vss:
        mv = next((b for b in (inst.get("baselines") or [])
                   if b.get("plan") == "mean_value_deterministic"), None)
        tail_move = ""
        if mv and knee:
            tail_move = (f", where the same comparison is {_usd(mv['cvar_95_usd'])} → "
                         f"{_usd(knee['cvar_95_usd'])}")
        lines += [
            "",
            f"**Value of the stochastic solution: VSS = EEV − RP = {_usd(vss['VSS_usd'])} "
            f"({_pct(vss['VSS_pct_of_RP'])} of RP).** Ignoring uncertainty at plan time "
            f"costs {_pct(vss['VSS_pct_of_RP'])} *in expectation*; the deterministic plan "
            "is very nearly the risk-neutral optimum. **The value of this model is not in "
            f"expected cost. It is entirely in the tail**{tail_move}.",
        ]
    return "\n".join(lines)


def _render_volume_table(payload: dict) -> str:
    prim = payload.get("primary") or {}
    lines = [
        "| Volume | Units | Knee | VSS | λ points converged |",
        "|---|---:|:---:|---:|:---:|",
    ]
    for m in PRIMARY_MULTIPLIERS:
        inst = prim.get(f"x{m}")
        if not inst:
            continue
        knee = inst.get("knee")
        vss = inst.get("value_of_the_stochastic_solution") or {}
        sq = inst.get("solve_quality") or {}
        knee_s = f"**λ = {knee['lambda']:g}**" if knee else "**none**"
        lines.append(
            f"| {m:,}× | {_num(inst.get('total_units'))} | {knee_s} | "
            f"{_usd(vss.get('VSS_usd'))} ({_pct(vss.get('VSS_pct_of_RP'))}) | "
            f"{sq.get('n_converged', '—')}/{sq.get('n_points', '—')} |"
        )
    return "\n".join(lines)


def _render_sensitivity(payload: dict) -> str:
    sens = payload.get("sensitivity")
    if not sens:
        return ("*Not present in this artifact — it was generated with `--quick`. Run "
                "`python -m seeds.run_cvar_frontier` (no flag) to populate it.*")
    rows = sens.get("rows") or []
    with_knee = [r for r in rows if r.get("knee_lambda") is not None]
    flat_arm = [r for r in rows if r.get("centrality_spread") == 1.0]
    flat_with_knee = [r for r in flat_arm if r.get("knee_lambda") is not None]
    knee_lams = sorted({r["knee_lambda"] for r in with_knee})
    not_all_converged = [r for r in rows if not r.get("all_points_converged", True)]

    lines = [
        f"**{len(rows)} full frontier sweeps** on the headline instance "
        f"(`{sens['instance']['bom']}` ×{sens['instance']['multiplier']:,}), over "
        f"`base_annual_prob` × `centrality_spread` × `horizon_days`.",
        "",
        f"* A knee exists in **{len(with_knee)} of {len(rows)}** cells; the knee λ takes "
        f"the values {', '.join(f'{v:g}' for v in knee_lams) or '—'}.",
        f"* In the **centrality-ignored arm** (`centrality_spread = 1.0`, "
        f"{len(flat_arm)} cells — every supplier on the flat cited base rate), a knee "
        f"exists in **{len(flat_with_knee)}** of them.",
        f"* {len(rows) - len(not_all_converged)} of {len(rows)} sweeps had every λ point "
        f"converge; **{len(not_all_converged)}** did not and their aggregates are built "
        "on the converged subset.",
        "",
        "| base rate | spread | horizon | p_median | atoms solved | knee λ | knee suppliers "
        "| extra E[cost] | CVaR-95 reduction | CVaR reduction available | all λ converged |",
        "|---:|---:|---:|---:|---:|:---:|:---:|---:|---:|---:|:---:|",
    ]
    for r in rows:
        knee_lam = r.get("knee_lambda")
        knee_s = f"{knee_lam:g}" if knee_lam is not None else "**none**"
        lines.append(
            f"| {r['base_annual_prob'] * 100:.2f}% | {r['centrality_spread']:g} | "
            f"{r['horizon_days']} d | {r['horizon_prob_median'] * 100:.2f}% | "
            f"{r['n_distinct_scenarios']} | "
            f"{knee_s} | "
            f"{r.get('knee_n_suppliers') if r.get('knee_n_suppliers') is not None else '—'} | "
            f"{_pct(r.get('knee_extra_expected_cost_pct'))} | "
            f"{_pct(r.get('knee_cvar_reduction_pct'))} | "
            f"{_pct(r.get('cvar_reduction_available_pct'))} | "
            f"{_flag(r.get('all_points_converged'))} |"
        )
    return "\n".join(lines)


def _render_saa_quality(payload: dict) -> str:
    saa = payload.get("saa_quality")
    if not saa:
        return ("*Not present in this artifact — it was generated with `--quick`. Run "
                "`python -m seeds.run_cvar_frontier` (no flag) to populate it.*")
    rows = saa.get("optimality_gap") or []
    lines = [
        f"Reference measure: **{saa.get('method', {}).get('reference_measure', '—')}**.",
        "",
        "| N | λ | Lower bound (mean of M) | LB 95% CI low | Upper bound | Gap | "
        "Gap 95% CI high | Gap % | Wall |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['n_scenarios']} | {r['lambda']:g} | {_usd(r['lower_bound_mean_usd'])} | "
            f"{_usd(r['lower_bound_ci95_low_usd'])} | {_usd(r['upper_bound_usd'])} | "
            f"{_usd(r['optimality_gap_usd'])} | {_usd(r['optimality_gap_ci95_high_usd'])} | "
            f"{_pct(r['optimality_gap_pct'], 3)} | {r['wall_seconds']:.1f} s |"
        )
    bad = [r for r in rows if r["upper_bound_usd"] < r["lower_bound_ci95_low_usd"]]
    lines += [
        "",
        f"The interval statement that must hold — `upper_bound ≥ lower_bound_ci_low` — "
        f"holds in **{len(rows) - len(bad)} of {len(rows)}** cells.",
    ]

    stab = saa.get("endpoint_stability") or []
    if stab:
        e = [s["risk_neutral_expected_cost_usd"] for s in stab]
        c = [s["min_cvar_usd"] for s in stab]
        lines += [
            "",
            f"**Endpoint stability** over N ∈ {sorted({s['n_draws'] for s in stab})} × "
            f"seed ∈ {sorted({s['seed'] for s in stab})} ({len(stab)} sweeps): the "
            f"risk-neutral expected cost spans {_usd(min(e))} – {_usd(max(e))} "
            f"({(max(e) - min(e)) / min(e) * 100:.2f}% of the low), and the minimum CVaR-95 "
            f"spans {_usd(min(c))} – {_usd(max(c))} "
            f"({(max(c) - min(c)) / min(c) * 100:.2f}%).",
            "",
            "| N draws | seed | distinct scenarios | risk-neutral E | risk-neutral CVaR-95 "
            "| min CVaR-95 | E at min CVaR | scored on | all λ converged |",
            "|---:|---:|---:|---:|---:|---:|---:|:---|:---:|",
        ]
        for s in stab:
            lines.append(
                f"| {s['n_draws']} | {s['seed']} | {s['n_distinct_scenarios']} | "
                f"{_usd(s['risk_neutral_expected_cost_usd'])} | "
                f"{_usd(s['risk_neutral_cvar_usd'])} | {_usd(s['min_cvar_usd'])} | "
                f"{_usd(s['min_cvar_expected_cost_usd'])} | `{s['scored_on']}` | "
                f"{_flag(s.get('all_points_converged'))} |"
            )
    if saa.get("solve_quality_note"):
        lines += ["", f"*{saa['solve_quality_note']}*"]
    return "\n".join(lines)


def _render_breadth(payload: dict) -> str:
    breadth = payload.get("breadth")
    if not breadth:
        return ("*Not present in this artifact — it was generated with `--quick`. Run "
                "`python -m seeds.run_cvar_frontier` (no flag) to populate it.*")
    entries = [
        (name, e) for name, blk in breadth.items() for e in (blk.get("points") or [])
    ]
    scored = [e for _n, e in entries if e.get("tradeoff_exists") is not None]
    with_tradeoff = [e for e in scored if e.get("tradeoff_exists")]
    boms_with = sorted({
        n for n, e in entries if e.get("tradeoff_exists")
    })
    n_unreportable = len(entries) - len(scored)
    lines = [
        f"**{len(breadth)} reference BOMs**, {len(entries)} (BOM × volume) instances. On "
        f"**{n_unreportable}** of them no λ point converged inside the "
        f"{_budget_phrase(payload, 'breadth')}, so no frontier can honestly be reported "
        "and the row is marked **excluded**. Of the "
        f"**{len(scored)}** instances that did produce a frontier, a cost-vs-CVaR "
        f"tradeoff exists in **{len(with_tradeoff)}**, spread over "
        f"**{len(boms_with)} of {len(breadth)} BOMs** "
        f"({', '.join('`' + b + '`' for b in boms_with) or 'none'}).",
        "",
        "| BOM | Distributors | Support | ×volume | Units | Atoms solved | Tradeoff? | "
        "CVaR-95 reduction available | Price of it | Worst gap | all λ converged |",
        "|---|---:|:---|---:|---:|---:|:---:|---:|---:|---:|:---:|",
    ]
    for name, blk in breadth.items():
        support = ("exact, {:,} atoms".format(blk["support_size_2_pow_D"])
                   if blk.get("enumerated_exactly")
                   else "sampled (2^{})".format(blk["n_distributors_in_pool"]))
        for e in blk.get("points") or []:
            if e.get("error"):
                lines.append(
                    f"| `{name}` | {blk['n_distributors_in_pool']} | {support} | "
                    f"{e['multiplier']:,}× | — | — | — | — | — | — | "
                    f"error: {e['error']} |"
                )
                continue
            if e.get("excluded_reason"):
                lines.append(
                    f"| `{name}` | {blk['n_distributors_in_pool']} | {support} | "
                    f"{e['multiplier']:,}× | {_num(e.get('total_units'))} | "
                    f"{e.get('n_distinct_scenarios', '—')} | **excluded** | — | — | "
                    f"{_pct((e.get('solve_quality') or {}).get('worst_mip_gap_pct'), 2)} | "
                    f"**NO** |"
                )
                continue
            sq = e.get("solve_quality") or {}
            lines.append(
                f"| `{name}` | {blk['n_distributors_in_pool']} | {support} | "
                f"{e['multiplier']:,}× | {_num(e.get('total_units'))} | "
                f"{e['n_distinct_scenarios']} | "
                f"{'**yes**' if e['tradeoff_exists'] else 'no'} | "
                f"{_usd(e['cvar_reduction_available_usd'])} "
                f"({_pct(e['cvar_reduction_available_pct'])}) | "
                f"{_usd(e['price_of_that_reduction_usd'])} | "
                f"{_pct(e['worst_mip_gap_pct'], 2)} | "
                f"{_flag(sq.get('all_points_converged'))} |"
            )
    return "\n".join(lines)


def _scenario_cell(ss: dict) -> str:
    """
    The scenario-count cell for a solve-time row: what the OPTIMIZER was handed.

    This column used to be hard-coded as "N (SAA, 200 draws)" for every breadth row and
    as "SAA / exact" for every primary row. Both would now be false on any instance that
    enumerates, which is most of them.
    """
    n_distinct = ss.get("n_distinct", "—")
    if ss.get("exact"):
        return f"{n_distinct} (exact support)"
    used = ss.get("n_draws_used")
    if used:
        return f"{n_distinct} (SAA, {used} draws)"
    return f"{n_distinct}"


def _render_solve_times(payload: dict) -> str:
    lines = [
        "| Instance | Distributors | Distinct scenarios | Variables | λ points | "
        "λ-sweep wall time | Worst gap | λ not converged |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    prim = payload.get("primary") or {}
    n_dist = ((payload.get("calibration") or {}).get("scenario_support") or {}).get(
        "n_distributors_in_primary_pool", "—")
    for m in PRIMARY_MULTIPLIERS:
        inst = prim.get(f"x{m}")
        if not inst:
            continue
        pts = inst.get("frontier") or []
        sq = inst.get("solve_quality") or {}
        scen_s = _scenario_cell(inst.get("solve_set") or {})
        lines.append(
            f"| `{PRIMARY_BOM}` ×{m:,} (primary arm) | {n_dist} | {scen_s} | "
            f"{max((p['n_variables'] for p in pts), default='—')} | {len(pts)} | "
            f"**{inst.get('sweep_wall_seconds', 0):.1f} s** | "
            f"{_pct(sq.get('worst_mip_gap_pct'), 3)} | "
            f"{sq.get('n_excluded_not_converged', 0)} |"
        )

    breadth = payload.get("breadth") or {}
    rows = [
        (name, blk, e)
        for name, blk in breadth.items()
        for e in (blk.get("points") or [])
        if e.get("sweep_wall_seconds") is not None
    ]
    rows.sort(key=lambda r: -r[2]["sweep_wall_seconds"])
    # The five slowest, PLUS every volume of the BOM this section historically quoted.
    # The stale hand-written row claimed `iot_sensor_node x100` ran 157 scenarios in
    # ~60 s with "timeouts at lambda=0"; keeping it in the generated table is what stops
    # a figure like that from surviving a run that no longer produces it.
    shown = rows[:5] + [r for r in rows[5:] if r[0] in SOLVE_TIME_SPOTLIGHT_BOMS]
    for name, blk, e in shown:
        sq = e.get("solve_quality") or {}
        gap = e.get("worst_mip_gap_pct", sq.get("worst_mip_gap_pct"))
        lines.append(
            f"| `{name}` ×{e['multiplier']:,} (breadth arm) | "
            f"{blk['n_distributors_in_pool']} | "
            f"{_scenario_cell(e.get('solve_set') or {})} | "
            f"{e.get('n_variables_max', '—')} | {sq.get('n_points', '—')} | "
            f"{e['sweep_wall_seconds']:.1f} s | {_pct(gap, 2)} | "
            f"{sq.get('n_excluded_not_converged', '—')} |"
        )
    lines += [
        "",
        "*The five slowest breadth instances are listed, plus every volume of "
        + ", ".join(f"`{b}`" for b in SOLVE_TIME_SPOTLIGHT_BOMS)
        + " (the instance this section used to quote stale figures for). The full set is "
        "in `docs/cvar_frontier.json` → `breadth`. A `—` in the Variables column is an "
        "instance where no λ point converged at all, so the entry carries its "
        "`excluded_reason` instead of a frontier.*",
    ]
    return "\n".join(lines)


def _render_provenance(payload: dict) -> str:
    prov = payload.get("provenance")
    if not prov:
        return "*(no provenance block in this artifact)*"
    from seeds.provenance import provenance_markdown
    body = provenance_markdown(prov, heading="").strip()
    meta = payload.get("meta") or {}
    extra = (
        f"\n- **Run mode:** {'`--quick` (partial artifact)' if prov.get('quick_mode') else 'full'}"
        f"\n- **Wall clock:** {meta.get('wall_seconds', prov.get('wall_seconds', '—'))} s"
        f"\n- **Hardware:** {meta.get('hardware', '—')}"
    )
    return body + extra


def _render_headline_pitch(payload: dict) -> str:
    inst = ((payload.get("primary") or {}).get(f"x{HEADLINE_MULTIPLIER}")) or {}
    knee = inst.get("knee")
    if not knee:
        return ("> The old pitch: *\"I added a 15% risk surcharge.\"*\n"
                "> The new pitch: *\"On this BOM there is no knee — the frontier is flat, "
                "and saying so is the finding.\"*")
    b = knee["vs_risk_neutral"]
    a = knee["beyond_the_knee"]
    return (
        "> The old pitch: *\"I added a 15% risk surcharge.\"*\n"
        f"> The new pitch: *\"On a {_num(inst.get('total_units'))}-unit BOM, spending "
        f"**{_pct(b['extra_expected_cost_pct'])} more in expectation** removes "
        f"**{_pct(b['cvar_reduction_pct'])} of CVaR-95 exposure** — "
        f"{_usd(b['extra_expected_cost_usd'])} buys {_usd(b['cvar_reduction_usd'])} of "
        f"tail reduction, a "
        f"**{_num(b['usd_of_cvar_removed_per_usd_of_expected_cost'], 2)}:1** return. Past "
        f"that point the same trade returns "
        f"**{_num(a['usd_of_cvar_removed_per_usd_of_expected_cost'], 2)}:1**. The knee is "
        f"at λ = {knee['lambda']:g} and that is my recommendation.\"*"
    )


RENDERERS = {
    "headline_pitch": _render_headline_pitch,
    "solve_quality": _render_solve_quality,
    "calibration_table": _render_calibration_table,
    "exact_vs_saa_table": _render_exact_vs_saa_table,
    "frontier_table": _render_frontier_table,
    "knee_table": _render_knee_table,
    "tail_table": _render_tail_table,
    "baselines_table": _render_baselines_table,
    "volume_table": _render_volume_table,
    "sensitivity": _render_sensitivity,
    "saa_quality": _render_saa_quality,
    "breadth": _render_breadth,
    "solve_times": _render_solve_times,
    "provenance": _render_provenance,
}


def render_doc(payload: dict, path: Path = DOC_PATH) -> int:
    """
    Rewrite every ``<!-- GENERATED:name:BEGIN -->…<!-- GENERATED:name:END -->`` block in
    the markdown from ``payload``. Returns the number of blocks replaced.

    Everything outside the markers is left byte-for-byte alone. A marker with no
    registered renderer, or a renderer that raises, leaves its block untouched and logs
    -- a half-written document is worse than a stale one.
    """
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist")
    text = path.read_text()
    replaced = 0
    for name, fn in RENDERERS.items():
        begin, end = BEGIN.format(name=name), END.format(name=name)
        i = text.find(begin)
        j = text.find(end)
        if i < 0 or j < 0 or j < i:
            logger.warning("marker %r not found in %s; skipped", name, path.name)
            continue
        try:
            body = fn(payload)
        except Exception as exc:  # noqa: BLE001 - one bad block must not corrupt the doc
            logger.error("renderer %r failed (%s: %s); block left unchanged",
                         name, type(exc).__name__, exc)
            continue
        text = text[:i + len(begin)] + "\n\n" + body.rstrip() + "\n\n" + text[j:]
        replaced += 1
    path.write_text(text)
    return replaced


# ── Driver ───────────────────────────────────────────────────────────────────

def main(argv: Optional[Sequence[str]] = None) -> int:
    # Rebound below from --breadth-time-limit / --primary-time-limit, before any solve.
    global TIME_LIMIT_BREADTH_S, TIME_LIMIT_PRIMARY_S
    global DET_LIMIT_BREADTH, DET_LIMIT_PRIMARY

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true",
                        help="primary + calibration only; skip breadth/sensitivity/stability")
    parser.add_argument("--render-only", action="store_true",
                        help="skip every solve; re-render the generated blocks of "
                             "docs/CVAR_EFFICIENT_FRONTIER.md from the existing "
                             "docs/cvar_frontier.json")
    parser.add_argument("--no-render", action="store_true",
                        help="write the JSON artifact but do not touch the markdown")
    parser.add_argument("--breadth-time-limit", type=float, default=None,
                        metavar="SECONDS",
                        help="per-solve CP-SAT wall-clock RUNAWAY GUARD for the "
                             f"breadth arm (default {TIME_LIMIT_BREADTH_S:g}s, which is "
                             "what the committed artifact was generated with). This is "
                             "not the budget that decides where a solve stops -- "
                             "--breadth-det-limit is. Setting it low enough to bind "
                             "makes the solve-quality counters load-dependent again; "
                             "solve_quality.n_wall_clock_bound reports any solve it "
                             "stopped and must be 0. The value used is recorded in "
                             "meta.solver.max_time_in_seconds_breadth.")
    parser.add_argument("--primary-time-limit", type=float, default=None,
                        metavar="SECONDS",
                        help="per-solve CP-SAT wall-clock RUNAWAY GUARD for the "
                             "primary, sensitivity and SAA arms "
                             f"(default {TIME_LIMIT_PRIMARY_S:g}s). See "
                             "--breadth-time-limit.")
    parser.add_argument("--breadth-det-limit", type=float, default=None,
                        metavar="DET_SECONDS",
                        help="per-solve DETERMINISTIC budget for the breadth arm "
                             f"(default {DET_LIMIT_BREADTH:g}, which is what generated "
                             "the committed artifact). A deterministic budget measures "
                             "WORK, not wall-clock, so the solve stops in the same "
                             "place under any CPU load and the solve-quality counters "
                             "reproduce. It does not make hard instances converge -- it "
                             "makes their truncation reproducible.")
    parser.add_argument("--primary-det-limit", type=float, default=None,
                        metavar="DET_SECONDS",
                        help="per-solve DETERMINISTIC budget for the primary, "
                             "sensitivity and SAA arms "
                             f"(default {DET_LIMIT_PRIMARY:g}).")
    args = parser.parse_args(argv)

    # Rebind the module-level budgets BEFORE anything solves. Every call site reads
    # these names at call time, so this is the single place the budget is decided.
    if args.breadth_time_limit is not None:
        if args.breadth_time_limit <= 0:
            parser.error("--breadth-time-limit must be > 0")
        TIME_LIMIT_BREADTH_S = float(args.breadth_time_limit)
    if args.primary_time_limit is not None:
        if args.primary_time_limit <= 0:
            parser.error("--primary-time-limit must be > 0")
        TIME_LIMIT_PRIMARY_S = float(args.primary_time_limit)
    if args.breadth_det_limit is not None:
        if args.breadth_det_limit <= 0:
            parser.error("--breadth-det-limit must be > 0")
        DET_LIMIT_BREADTH = float(args.breadth_det_limit)
    if args.primary_det_limit is not None:
        if args.primary_det_limit <= 0:
            parser.error("--primary-det-limit must be > 0")
        DET_LIMIT_PRIMARY = float(args.primary_det_limit)

    # A deterministic budget only buys reproducibility if the WALL CLOCK never binds.
    # The wall limit stays on as a runaway guard, so when a deterministic budget is
    # set and the wall limit was NOT overridden explicitly, raise the guard well clear
    # of it. (With the defaults above this is already satisfied and the max() is a
    # no-op; it still runs so a hand-set --*-det-limit cannot outgrow the guard.)
    # Leaving the guard at 15s under a 15-unit deterministic budget would
    # silently reinstate exactly the load-dependence this flag exists to remove --
    # measured: a det-15 solve costs 9-38s of wall on an idle machine and up to 75s
    # under saturation. `solve_quality.n_wall_clock_bound` reports any solve the guard
    # stopped anyway, and it must be 0 for the counters to be reproducible.
    _GUARD_MULTIPLE = 20.0
    if DET_LIMIT_BREADTH is not None and args.breadth_time_limit is None:
        TIME_LIMIT_BREADTH_S = max(
            TIME_LIMIT_BREADTH_S, _GUARD_MULTIPLE * DET_LIMIT_BREADTH)
        logger.info("breadth wall clock raised to %.0fs as a runaway guard behind the "
                    "%g deterministic-time budget", TIME_LIMIT_BREADTH_S,
                    DET_LIMIT_BREADTH)
    if DET_LIMIT_PRIMARY is not None and args.primary_time_limit is None:
        TIME_LIMIT_PRIMARY_S = max(
            TIME_LIMIT_PRIMARY_S, _GUARD_MULTIPLE * DET_LIMIT_PRIMARY)
        logger.info("primary wall clock raised to %.0fs as a runaway guard behind the "
                    "%g deterministic-time budget", TIME_LIMIT_PRIMARY_S,
                    DET_LIMIT_PRIMARY)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.render_only:
        payload = json.loads((DOCS / "cvar_frontier.json").read_text())
        n = render_doc(payload)
        logger.info("re-rendered %d generated blocks in %s", n, DOC_PATH.name)
        return 0

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    started = datetime.now(UTC)
    t_start = time.perf_counter()

    weights = get_strategy(STRATEGY_ID)

    # Load the shipped ML state so the `shipped_milp` baseline is scored against the
    # optimizer as it ACTUALLY runs in production (its macro stress premium is live),
    # not against a stripped-down version of it. Recorded in meta either way.
    macro_stress: Optional[float] = None
    try:
        from app.ml import get_ml_state, set_ml_state
        from app.ml.serving import load_ml_state
        _state = load_ml_state()
        if _state is not None:
            set_ml_state(_state)
        _cur = get_ml_state()
        macro_stress = float(_cur.current_stress_prob) if _cur is not None else None
    except Exception as exc:  # noqa: BLE001 - never let a model artifact break the sweep
        logger.warning("ML state unavailable (%s); shipped-MILP baseline runs with "
                       "macro_stress=0.0", exc)

    db = SessionLocal()
    try:
        gs = build_graph_state(db)
        loaded = {n: _load_offers_for_bom(db, items) for n, items in BOM_CATALOG.items()}
    finally:
        db.close()

    betweenness = gs.betweenness
    bom0, offers, _meta = loaded[PRIMARY_BOM]
    primary_dids = sorted({o.distributor_id for o in offers})
    primary_probs = st.build_failure_probabilities(primary_dids, betweenness)
    primary_scenarios = st.sample_scenarios(primary_probs, N_DRAWS, SEED)

    # Enumerate the FULL support when the supplier pool is small enough. Disruption is
    # |D| independent Bernoulli variables, so the cost distribution has at most 2**|D|
    # atoms; below the ceiling we can hold all of them and stop estimating entirely.
    exact_set: Optional[st.ScenarioSet] = None
    if len(primary_dids) <= st.MAX_ENUMERABLE_DISTRIBUTORS:
        exact_set = st.enumerate_scenarios(primary_probs)
        logger.info("primary support enumerated exactly: %d atoms (2**%d)",
                    exact_set.n_distinct, len(primary_dids))

    calibration = {
        "method": (
            "p_d = min(base_horizon_prob * spread**(2*rank_d - 1), MAX_FAILURE_PROB), "
            "where rank_d is the percentile rank of distributor d's betweenness within "
            "this BOM's supplier pool (ties share the mean rank) and base_horizon_prob "
            "= 1 - (1 - base_annual_prob)**(horizon_days/365)."
        ),
        "why_not_the_existing_simulator": (
            "Until 2026-08-16 graph/simulation.py used min-max rescaled betweenness "
            "DIRECTLY as p_fail. A min-max rescale attains 1.0 at its maximum, so the "
            "most central distributor in this database failed in 100% of scenarios and "
            "the distributors at a rescaled 0.0 never failed. There was no base rate, no "
            "exposure window and no unit in that expression, and its cvar_95 "
            "consequently pinned at 1.0 + EMERGENCY_COST_PREMIUM = 1.15. This module has "
            "never reused those probabilities. Separate work has since removed the "
            "min-max rescale from graph/builder.py and pointed graph/simulation.py at "
            "build_failure_probabilities, so the defect no longer ships -- but the "
            "reason this program calibrates its own probabilities rather than inheriting "
            "them is recorded here rather than tidied away."
        ),
        "base_rate_source": {
            "citation": "McKinsey Global Institute, 'Risk, resilience, and rebalancing "
                        "in global value chains', August 2020",
            "url": "https://www.mckinsey.com/capabilities/operations/our-insights/"
                   "risk-resilience-and-rebalancing-in-global-value-chains",
            "quote": "companies can now expect supply chain disruptions lasting a month "
                     "or longer to occur every 3.7 years",
            "derivation": "Poisson rate 1/3.7 per year -> P(>=1 event in a year) = "
                          "1 - exp(-1/3.7) = 0.2368",
            "known_weakness": (
                "This is a FIRM-level frequency (a company sees a disruption somewhere in "
                "its value chain), not a per-supplier failure rate. Using it per supplier "
                "almost certainly OVERSTATES individual supplier risk. No per-supplier "
                "base rate could be verified from a citable public source, so the number "
                "is treated as an assumption and swept from 5% to 40% in the sensitivity "
                "arm rather than published as if it were measured."
            ),
        },
        "centrality_assumption": (
            "That more central distributors are more likely to be disrupted. Nothing in "
            "this repo or in the cited literature establishes it, and the opposite is "
            "arguable (hub distributors are typically better capitalised and more "
            "redundant). Centrality is therefore used ONLY as a bounded rank transform, "
            "never as a magnitude, and centrality_spread = 1.0 -- centrality ignored "
            "entirely, every supplier on the flat base rate -- is run as a sensitivity "
            "arm in every published frontier."
        ),
        "defaults": {
            "base_annual_prob": round(st.DEFAULT_BASE_ANNUAL_PROB, 6),
            "horizon_days": st.DEFAULT_HORIZON_DAYS,
            "centrality_spread": st.DEFAULT_CENTRALITY_SPREAD,
            "max_failure_prob": st.MAX_FAILURE_PROB,
            "alpha": st.DEFAULT_ALPHA,
        },
        "primary_bom_distributors": [
            {
                "distributor_id": d,
                "betweenness_normalized": round(betweenness.get(d, 0.0), 6),
                "p_disruption_over_horizon": round(primary_probs[d], 5),
            }
            for d in primary_dids
        ],
        "scenario_set": {
            "n_draws": primary_scenarios.n_draws,
            "n_distinct": primary_scenarios.n_distinct,
            "seed": primary_scenarios.seed,
            "p_no_disruption": round(primary_scenarios.p_no_disruption, 4),
            "mean_failures_per_scenario": round(
                primary_scenarios.mean_failures_per_scenario, 4),
        },
        "scenario_support": {
            "n_distributors_in_primary_pool": len(primary_dids),
            "support_size_2_pow_D": 2 ** len(primary_dids),
            "enumerated_exactly": exact_set is not None,
            "n_atoms_enumerated": exact_set.n_distinct if exact_set else None,
            "enumeration_residual_mass": (
                round(exact_set.residual_mass, 12) if exact_set else None),
            "largest_single_atom_probability": (
                round(exact_set.max_atom_probability, 6) if exact_set
                else round(primary_scenarios.max_atom_probability, 6)),
            "why_the_sampled_set_has_so_few_distinct_scenarios": (
                f"Disruption is {len(primary_dids)} independent Bernoulli variables, so "
                f"the cost distribution has at most 2**{len(primary_dids)} = "
                f"{2 ** len(primary_dids)} atoms IN TOTAL. Sampling "
                f"{primary_scenarios.n_draws} draws recovered "
                f"{primary_scenarios.n_distinct} of them. That is not undersampling of a "
                "rich distribution -- it is a genuinely small support, and the correct "
                "response is to enumerate it rather than to draw more samples. It is "
                "also why 'n_draws=200, n_distinct=10, alpha=0.95' looked alarming: the "
                "SAA tail averaged over ~4 atoms. On the enumerated support the same "
                "tail averages over dozens. See primary.*.saa_vs_exact and saa_quality."
            ),
            "note_on_the_legacy_simulator": (
                "The betweenness-as-probability defect made this WORSE, not better: "
                "with p_fail = rescaled betweenness, the most central distributor "
                "failed in 100% of scenarios, which removed it as a source of variation "
                "and mechanically collapsed scenario diversity further. Fixed at the "
                "source on 2026-08-16 by separate work; recorded here because the "
                "argument for enumerating the support does not depend on it."
            ),
        },
    }

    results: Dict[str, object] = {"calibration": calibration}
    results["primary"] = _run_primary(
        bom0, offers, weights, primary_scenarios, exact_set)
    if not args.quick:
        results["breadth"] = _run_breadth(loaded, weights, betweenness)
        results["sensitivity"] = _run_sensitivity(bom0, offers, weights, betweenness)
        results["saa_quality"] = _run_saa_quality(
        bom0, offers, weights, primary_probs, exact_set)

    elapsed = time.perf_counter() - t_start
    provenance = build_provenance(
        generator="seeds.run_cvar_frontier",
        inputs={
            "component_database": BACKEND_ROOT / "supply_chain.db",
            "ml_metrics": BACKEND_ROOT / "data" / "ml_models" / "metrics.joblib",
            "ml_regime_model": BACKEND_ROOT / "data" / "ml_models" / "regime.joblib",
            "ml_lead_time_models": BACKEND_ROOT / "data" / "ml_models" / "lead_time.joblib",
        },
        extra={
            "quick_mode": args.quick,
            "primary_bom": PRIMARY_BOM,
            "headline_multiplier": HEADLINE_MULTIPLIER,
            "strategy": STRATEGY_ID,
            "lambda_grid": LAMBDA_GRID,
            "lambda_grid_coarse": LAMBDA_GRID_COARSE,
            "n_draws": N_DRAWS,
            "seed": SEED,
            "wall_seconds": round(elapsed, 1),
            "input_note": (
                "The component database is the only data input. The ML artifacts affect "
                "ONLY the `shipped_milp` baseline arm (they set its macro stress "
                "premium); the stochastic program itself does not read them."
            ),
        },
    )
    payload = {
        "provenance": provenance,
        "solve_quality": _solve_quality_summary(),
        "meta": {
            "generated_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hardware": f"{platform.machine()} / {platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "wall_seconds": round(elapsed, 1),
            "quick_mode": args.quick,
            "strategy": STRATEGY_ID,
            "strategy_weights": {
                "w_cost": weights.w_cost, "w_time": weights.w_time,
                "w_carbon": weights.w_carbon,
                "transport_penalty_scale": weights.transport_penalty_scale,
                "consolidation_bonus_usd": weights.consolidation_bonus_usd,
                "us_only_sourcing_default": weights.us_only_sourcing,
            },
            "us_only": False,
            "solver": {
                "engine": "OR-Tools CP-SAT",
                "num_search_workers": 1,
                "relative_gap_limit": st.DEFAULT_RELATIVE_GAP,
                "max_time_in_seconds_primary": TIME_LIMIT_PRIMARY_S,
                "max_time_in_seconds_breadth": TIME_LIMIT_BREADTH_S,
                "max_deterministic_time_primary": DET_LIMIT_PRIMARY,
                "max_deterministic_time_breadth": DET_LIMIT_BREADTH,
                "budget_kind": (
                    "deterministic (work), with the wall clock kept as a runaway guard"
                    if (DET_LIMIT_PRIMARY is not None or DET_LIMIT_BREADTH is not None)
                    else "wall clock"
                ),
                "convergence_gap_threshold_pct": CONVERGENCE_GAP_PCT,
                "note": "num_search_workers=1 is REQUIRED: CP-SAT hangs at 0% CPU under "
                        "bare-python invocation on macOS with multiple workers. It also "
                        "keeps every solve deterministic. NOTE that a WALL-CLOCK budget "
                        "is still machine- and load-dependent even at one worker: it "
                        "fixes the search PATH, not where the search STOPS. Only a "
                        "max_deterministic_time budget fixes the stopping point -- see "
                        "solve_quality.deterministic_budget_in_force.",
            },
            "formulation": {
                "type": "two-stage stochastic program, sample-average approximation",
                "objective": "min (1-lambda) * E[cost] + lambda * CVaR_alpha[cost]",
                "cvar_linearization": "Rockafellar & Uryasev (2000), applied to the "
                                      "recourse cost (E and CVaR are translation "
                                      "invariant, so the deterministic first-stage cost "
                                      "is added back exactly)",
                "alpha": st.DEFAULT_ALPHA,
                "lambda_grid": LAMBDA_GRID,
                "lambda_grid_coarse": LAMBDA_GRID_COARSE,
                "lambda_discretization": f"1/{st.LAMBDA_DEN}",
                "known_limitation": (
                    "A weighted-sum (lambda) scalarization can only recover Pareto points "
                    "on the CONVEX HULL of the (E, CVaR) image. Integer programs routinely "
                    "have unsupported efficient points that no lambda exposes, so this "
                    "frontier is a subset of the true efficient set, never a superset. An "
                    "epsilon-constraint sweep would find the rest; it is not implemented."
                ),
            },
            "recourse_model": {
                "emergency_unit_cost": "offer price x (1 + EMERGENCY_REPROCURE_PREMIUM) "
                                       "+ AVG_KG_PER_UNIT x AIR_FREIGHT_RATE_USD_PER_KG",
                "emergency_premium": st.EMERGENCY_REPROCURE_PREMIUM,
                "expedite_fixed_usd": st.EXPEDITE_FIXED_USD,
                "expedite_per_unit_usd": round(st.EXPEDITE_PER_UNIT_USD, 4),
                "recovery_rate": st.DEFAULT_RECOVERY_RATE,
                "unmet_unit_cost": f"{st.STOCKOUT_PENALTY_MULTIPLE} x the dearest "
                                   "emergency route for that line",
                "not_modelled": [
                    "partial capacity loss -- outages are binary",
                    "correlated / common-cause failures -- draws are independent across "
                    "suppliers, which UNDERSTATES tail risk",
                    "disruption duration and multi-period recovery",
                    "qualification time and cost for a supplier not opened in stage 1, "
                    "which UNDERSTATES the cost of recourse",
                    "MOQ on emergency buys",
                    "price movement under stress -- emergency prices are catalogue prices "
                    "plus a fixed premium, which UNDERSTATES tail cost",
                ],
            },
            "ml_state": {
                "loaded": macro_stress is not None,
                "macro_stress_used_by_shipped_milp_baseline": macro_stress,
                "note": "Affects ONLY the shipped_milp baseline arm. The stochastic "
                        "program does not apply sourcing.py's heuristic risk surcharges "
                        "-- replacing them is the point.",
            },
            "depot": {"lat": DEPOT.lat, "lng": DEPOT.lng},
            "primary_bom": PRIMARY_BOM,
            "headline_multiplier": HEADLINE_MULTIPLIER,
            "n_draws": N_DRAWS,
            "seed": SEED,
            "out_of_sample_seeds": OUT_OF_SAMPLE_SEEDS,
            "notes": [
                "Every expected cost and CVaR published here is computed by re-solving "
                "each scenario's second stage EXACTLY for the returned plan, not by "
                "reading the joint model's own recourse variables -- those can be left "
                "near-optimal when the MIP gap does not close.",
                "CVaR is the true CVaR of the weighted discrete distribution: the "
                "boundary atom is split fractionally. graph/simulation.py instead takes "
                "the mean of the worst ceil(5%) SAMPLES, which is biased whenever the "
                "tail cut does not land on a sample boundary.",
                "Scenario weights are raw Monte Carlo draw counts, so deduplication "
                "changes model size but not the empirical distribution.",
                "Points flagged `dominated` are dominated on BOTH axes by another point "
                "in the same sweep. They are reported, not deleted; they are the "
                "expected artefact of a weighted-sum sweep with ties at lambda = 1.",
                "Every point carries `solver_status`, `mip_gap_pct`, `hit_time_limit` "
                "and `converged`. A point with `converged: false` did NOT have its "
                "first-stage choice proved near-optimal within its per-solve budget and "
                "is NOT on the efficient frontier; it is retained with an "
                "`excluded_reason` and excluded from every knee, spread and headline. "
                "The run-level distribution is in the top-level `solve_quality` block.",
                "`hit_time_limit` and `solve_quality.n_time_limit_hits` are historical "
                "field names: they count solves that returned a status other than "
                "OPTIMAL, i.e. that exhausted the PER-SOLVE BUDGET with the bound still "
                "open. Since 2026-09-01 that budget is `max_deterministic_time` -- a "
                "WORK budget -- so those counts are NOT clock- or load-dependent. The "
                "field that would report a clock-bound solve is "
                "`solve_quality.n_wall_clock_bound`, and it must be 0.",
            ],
        },
        **results,
    }

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "cvar_frontier.json").write_text(json.dumps(payload, indent=2) + "\n")
    logger.info("wrote docs/cvar_frontier.json  (%.1fs total)", elapsed)

    sq = payload["solve_quality"]
    if isinstance(sq, dict) and sq.get("n_solves"):
        logger.info(
            "solve quality: %d solves, %d converged, %d not converged, %d exhausted "
            "the per-solve %s budget; worst gap %.3f%%",
            sq["n_solves"], sq["n_converged"], sq["n_not_converged"],
            sq["n_time_limit_hits"],
            "DETERMINISTIC work" if sq.get("deterministic_budget_in_force")
            else "wall-clock",
            sq["gap_pct_distribution"]["max"],
        )
        # The falsifiable half of the determinism claim. A nonzero count means the
        # runaway guard -- the CLOCK -- stopped that many solves, so their counters
        # are load-dependent and do NOT reproduce. Say it loudly rather than let a
        # reader infer reproducibility the run did not deliver.
        if sq.get("deterministic_budget_in_force"):
            n_clock = sq.get("n_wall_clock_bound", 0)
            if n_clock:
                logger.warning(
                    "n_wall_clock_bound = %d: the wall-clock runaway guard, not the "
                    "deterministic work budget, decided where %d solve(s) stopped. "
                    "Those counters are load-dependent and this run is NOT "
                    "reproducible. Raise the guard and re-run.", n_clock, n_clock,
                )
            else:
                logger.info(
                    "n_wall_clock_bound = 0: the wall clock stopped no solve, so every "
                    "solve-quality counter above reproduces under any CPU load.")

    if not args.no_render:
        try:
            n = render_doc(payload)
            logger.info("re-rendered %d generated blocks in %s", n, DOC_PATH.name)
        except Exception as exc:  # noqa: BLE001 - never lose the artifact over the doc
            logger.error("doc render failed (%s: %s); the JSON artifact is written and "
                         "`--render-only` can retry", type(exc).__name__, exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
