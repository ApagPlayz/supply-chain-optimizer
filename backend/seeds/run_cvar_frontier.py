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
program (sample-average approximation + Rockafellar-Uryasev CVaR linearization). This
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
  saa_stability Monte Carlo sample size and seed. Shows how much of the published
                frontier is signal and how much is sampling noise.
  calibration   The failure probabilities themselves, per distributor, with the
                betweenness they were derived from -- so a reader can check that no
                supplier is at p = 1.0 the way the existing simulator has them.

THE HONESTY PROBLEM THIS SCRIPT HAD TO SOLVE FIRST
--------------------------------------------------
`graph/simulation.py:155-161` uses min-max normalized betweenness centrality DIRECTLY
as a failure probability. A min-max normalization attains 1.0 at its maximum, so the
most central distributor in this database (betweenness exactly 1.0) fails in 100% of
scenarios, and the least central (18 distributors sit at exactly 0.0) never fails.
There is no base rate, no exposure window, and no unit anywhere in that expression.

A CVaR objective built on those probabilities would be meaningless, so this work does
NOT reuse them. `build_failure_probabilities` anchors the LEVEL on a cited base rate
(McKinsey Global Institute 2020, a month-plus disruption every 3.7 years) converted to
the 60-day exposure window of one purchase order, and uses centrality only as a bounded
RANK transform for relative risk. Both the base rate and the spread are swept in the
`sensitivity` arm, and the "centrality tells us nothing" arm (spread = 1.0) is run
every time. The existing `simulation.py` is left untouched -- this script does not
quietly change a number that other published documents depend on.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.graph.builder import build_graph_state
from app.optimization import stochastic as st
from app.optimization.sourcing import BomLine, Offer, solve_sourcing
from app.optimization.strategies import get_strategy

from seeds.run_benchmark import BOM_CATALOG, DEPOT, _load_offers_for_bom

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

# Per-solve CP-SAT budget. Reported per point alongside the achieved MIP gap; nothing
# in this document is allowed to hide behind a truncated solve.
TIME_LIMIT_PRIMARY_S = 60.0
TIME_LIMIT_BREADTH_S = 15.0

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


def _point_dict(p: st.FrontierPoint) -> dict:
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
        "evaluate_seconds": round(p.evaluate_seconds, 3),
        "n_variables": p.n_variables,
        "dominated": p.dominated,
    }


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


def _knee_dict(points: Sequence[st.FrontierPoint]) -> Optional[dict]:
    """
    The knee, plus the two numbers that turn it into a recommendation: what the last
    dollar of resilience bought before the knee, and what it buys after.
    """
    knee = st.find_knee(points)
    if knee is None:
        return None
    usable = sorted([p for p in points if not p.dominated], key=lambda p: p.expected_cost_usd)
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
        # Plans are CHOSEN on the Monte Carlo sample (CP-SAT needs integer weights) but
        # SCORED on the exact enumerated support when the supplier pool is small enough
        # to enumerate. Every expected cost and CVaR below therefore carries NO sampling
        # error; only the choice of plan does, and `saa_quality` bounds that.
        points, results = st.compute_frontier(
            bom, offers, weights, scenario_set, LAMBDA_GRID,
            us_only=False, time_limit_s=TIME_LIMIT_PRIMARY_S,
            evaluation_set=exact_set,
        )
        sweep_s = time.perf_counter() - t0
        by_lam = {r.lam: r for r in results}

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
        )
        reference = exact_set if exact_set is not None else scenario_set
        eev = st.evaluate_plan(mean_value.assignments, bom, offers, weights, reference)
        baselines.append({
            **_profile_dict("mean_value_deterministic", eev, points),
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
                **_profile_dict(f"shipped_milp_graph_aware={graph_aware}", prof, points),
                "note": "The plan app/optimization/sourcing.py returns TODAY, including "
                        "its heuristic risk surcharges, scored under the same scenarios.",
            })

        # How much did sampling alone move the answer? Same plans, two measures.
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

        rp = min(r.expected_cost_usd for r in results)
        out[f"x{m}"] = {
            "multiplier": m,
            "total_units": sum(b.quantity for b in bom),
            "lines": [{"mpn": b.mpn, "quantity": b.quantity} for b in bom],
            "sweep_wall_seconds": round(sweep_s, 2),
            "frontier": [_point_dict(p) for p in points],
            "knee": _knee_dict(points),
            "tail_decomposition_at_lambda_0": _tail_decomposition(by_lam[0.0], st.DEFAULT_ALPHA),
            "tail_decomposition_at_knee": (
                _tail_decomposition(by_lam[st.find_knee(points).lam], st.DEFAULT_ALPHA)
                if st.find_knee(points) is not None else None
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
        scenarios = st.sample_scenarios(probs, N_DRAWS, SEED)
        # Same rule as the primary arm: enumerate the exact support where the pool is
        # narrow enough, otherwise fall back to the sample and say so per BOM.
        bom_exact = (
            st.enumerate_scenarios(probs)
            if len(pool) <= st.MAX_ENUMERABLE_DISTRIBUTORS else None
        )
        entries: List[dict] = []
        for m in grid:
            bom = _scale(bom0, m)
            t0 = time.perf_counter()
            try:
                points, _res = st.compute_frontier(
                    bom, offers, weights, scenarios, LAMBDA_GRID_COARSE,
                    us_only=False, time_limit_s=TIME_LIMIT_BREADTH_S,
                    evaluation_set=bom_exact,
                )
            except (ValueError, RuntimeError) as exc:
                entries.append({"multiplier": m, "error": f"{type(exc).__name__}: {exc}"})
                continue
            e_lo = min(p.expected_cost_usd for p in points)
            c_lo = min(p.cvar_usd for p in points)
            c_hi = max(p.cvar_usd for p in points)
            e_at_c_lo = min(p.expected_cost_usd for p in points if p.cvar_usd <= c_lo + 1e-9)
            entries.append({
                "multiplier": m,
                "total_units": sum(b.quantity for b in bom),
                "n_distinct_scenarios": scenarios.n_distinct,
                "risk_neutral_expected_cost_usd": round(e_lo, 2),
                "risk_neutral_cvar_usd": round(c_hi, 2),
                "min_cvar_usd": round(c_lo, 2),
                "expected_cost_at_min_cvar_usd": round(e_at_c_lo, 2),
                "cvar_reduction_available_usd": round(c_hi - c_lo, 2),
                "cvar_reduction_available_pct": round(100.0 * (c_hi - c_lo) / c_hi, 4)
                if c_hi else 0.0,
                "price_of_that_reduction_usd": round(e_at_c_lo - e_lo, 2),
                "tradeoff_exists": bool(c_hi - c_lo > 0.01),
                "supplier_counts": sorted({p.n_suppliers for p in points}),
                "scored_on": points[0].evaluation_kind,
                "min_atoms_in_alpha_tail": min(p.n_atoms_in_tail for p in points),
                "worst_mip_gap_pct": round(max(p.gap_pct for p in points), 4),
                "any_point_hit_time_limit": any(p.status != "OPTIMAL" for p in points),
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
                points, _res = st.compute_frontier(
                    bom, offers, weights, scenarios, LAMBDA_GRID_COARSE,
                    us_only=False, time_limit_s=TIME_LIMIT_PRIMARY_S,
                    evaluation_set=exact,
                )
                knee = _knee_dict(points)
                e_lo = min(p.expected_cost_usd for p in points)
                c_hi = max(p.cvar_usd for p in points)
                c_lo = min(p.cvar_usd for p in points)
                rows.append({
                    "base_annual_prob": round(base_rate, 4),
                    "centrality_spread": spread,
                    "horizon_days": horizon,
                    "horizon_prob_min": round(min(probs.values()), 5),
                    "horizon_prob_median": round(
                        sorted(probs.values())[len(probs) // 2], 5),
                    "horizon_prob_max": round(max(probs.values()), 5),
                    "n_distinct_scenarios": scenarios.n_distinct,
                    "p_no_disruption": round(scenarios.p_no_disruption, 4),
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

    So the primary arm stops sampling and enumerates. What remains is that the PLAN is
    still chosen on a sample, and this arm bounds that residual error the standard way:

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
    stability: List[dict] = []
    for n_draws in SAA_DRAW_GRID:
        for seed in SAA_SEED_GRID:
            scenarios = st.sample_scenarios(failure_probs, n_draws, seed)
            points, _res = st.compute_frontier(
                bom, offers, weights, scenarios, [0.0, 1.0],
                us_only=False, time_limit_s=TIME_LIMIT_PRIMARY_S,
                evaluation_set=exact_set,
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
        "optimality_gap": rows,
        "endpoint_stability": stability,
    }


# ── Driver ───────────────────────────────────────────────────────────────────

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true",
                        help="primary + calibration only; skip breadth/sensitivity/stability")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    started = datetime.now(timezone.utc)
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
            "graph/simulation.py:155-161 uses min-max normalized betweenness DIRECTLY "
            "as p_fail. A min-max normalization attains 1.0 at its maximum, so the most "
            "central distributor in this database fails in 100% of scenarios and the 18 "
            "distributors at betweenness 0.0 never fail. There is no base rate, no "
            "exposure window and no unit in that expression. Its cvar_95 consequently "
            "pins at 1.0 + EMERGENCY_COST_PREMIUM = 1.15. That module is deliberately "
            "left unchanged here; this one does not reuse its probabilities."
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
                "The betweenness-as-probability defect makes this WORSE, not better: "
                "with p_fail = normalized betweenness, the most central distributor "
                "fails in 100% of scenarios, which removes it as a source of variation "
                "and mechanically collapses scenario diversity further."
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
    payload = {
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
                "note": "num_search_workers=1 is REQUIRED: CP-SAT hangs at 0% CPU under "
                        "bare-python invocation on macOS with multiple workers. It also "
                        "keeps every solve deterministic.",
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
            ],
        },
        **results,
    }

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "cvar_frontier.json").write_text(json.dumps(payload, indent=2) + "\n")
    logger.info("wrote docs/cvar_frontier.json  (%.1fs total)", elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
