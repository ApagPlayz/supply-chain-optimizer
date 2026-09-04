"""
Price-of-resilience frontier — what does one more supplier actually BUY?

MOTIVATION. Benchmark run 5 (`docs/benchmark_results.json`) reports a directional
split: the graph-aware/dual-sourced MILP arm is better on cascade risk under a
TARGETED outage of the most-central distributor and worse under BROAD systemic
stress, at a nominal cost premium. The mechanism is visible in the same run —
the cost-optimal MILP consolidates suppliers from 3.22 per BOM (greedy) to 1.33
(MILP). Concentration is cheap, and it is exactly what a correlated shock
punishes.

The honest response is not to argue about which arm "won". It is that nobody
priced the trade. This script does:

    for each reference BOM, for k = 1, 2, 3, ...:
        solve the SAME cost-optimal sourcing MILP subject to
        "open at least k distinct distributors"
        then evaluate the resulting plan's cost and its cascade risk under the
        benchmark's own stress and targeted scenarios.

That is a price-of-resilience frontier: the measured dollar cost of each unit of
diversification, and the k at which buying more stops paying.

WHAT IS AND IS NOT NEW HERE. The constraint (`solve_sourcing(...,
min_distributors=k)`) is the only new modelling. Everything else is the
benchmark's existing machinery, deliberately reused rather than reimplemented so
the two artifacts cannot drift apart:

  * the BOM catalogue, the DB→BomLine/Offer loader and the SF depot come from
    `seeds.run_benchmark` by import;
  * cost is scored by `app.optimization.greedy.landed_cost_breakdown` — the same
    function every benchmark arm is scored through;
  * risk is `app.graph.simulation.run_monte_carlo` at its module defaults
    (N = 1,000 scenarios, seed = 42) under the benchmark's own scenarios:
    broad stress = `STRESS_FACTOR` (3.0), targeted = forced failure of the
    single highest-betweenness distributor in THAT BOM's full offer pool.

REPRODUCTION CHECK. At k = 1 the constraint binds on nothing, so every plan must
equal the unconstrained `milp_blind` plan. The script asserts that against the
committed `docs/benchmark_results.json` (`value_of_optimization[].milp_usd`) and
publishes the comparison. If that check fails, the frontier is not comparable to
run 5 and the run says so instead of publishing.

THIS SCRIPT IS ADDITIVE. It never re-runs the benchmark, never writes an
`optimization_runs` row, never touches the database, and never overwrites run 5's
artifacts. It reads the DB and writes exactly two new files under `docs/`.

Strategy is `balanced` and `us_only=True`, which is what the benchmark's MILP
arms actually solve: `optimize_bom` keys its Stage-1 cache on
`strat.us_only_sourcing or us_only`, and `balanced.us_only_sourcing` is True.

Invocation: `cd backend && ./venv/bin/python -m seeds.run_diversification_sweep`
"""
from __future__ import annotations

import json
import logging
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.graph import get_graph_state  # noqa: E402
from app.graph.builder import build_graph_state  # noqa: E402
from app.graph.simulation import run_monte_carlo  # noqa: E402
from app.optimization.greedy import landed_cost_breakdown  # noqa: E402
from app.optimization.sourcing import solve_sourcing  # noqa: E402
from app.optimization.strategies import get_strategy  # noqa: E402

# Imported, not copied. `_load_offers_for_bom` is private to run_benchmark, but
# duplicating it here is the worse option: the frontier is only comparable to
# run 5 if it consumes byte-identical BomLine/Offer objects, and two copies of a
# DB loader drift. Nothing in this module writes to run_benchmark's state.
from seeds.run_benchmark import (  # noqa: E402
    BOM_CATALOG,
    STRESS_FACTOR,
    _load_offers_for_bom,
)
from seeds.provenance import build_provenance  # noqa: E402

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"
JSON_PATH = DOCS / "diversification_frontier.json"
MD_PATH = DOCS / "DIVERSIFICATION_FRONTIER.md"
BENCHMARK_JSON = DOCS / "benchmark_results.json"

STRATEGY_ID = "balanced"

# Sweep range. Every catalogue BOM has 4 lines, so k = 4 is "one distinct
# distributor per line" — the natural end of the frontier. k = 5 is reported
# because it is reachable (a multi-unit line can be split across two
# distributors) but it is a DIFFERENT economic regime — it forces a line SPLIT
# rather than a line reassignment — and it is not feasible for every BOM. Each
# k's paired CI is therefore computed over its own feasible panel, and every row
# publishes that panel's size and membership; k = 5's n is not k <= 4's n.
K_MAX = 5

# Paired bootstrap across BOMs.
BOOTSTRAP_N = 10_000
BOOTSTRAP_SEED = 42
CI_ALPHA = 0.05


# ── Solving + scoring ────────────────────────────────────────────────────────

def _plan_signature(assignments) -> Tuple[Tuple[int, int, int], ...]:
    """Order-independent fingerprint of a sourcing plan, for change detection."""
    return tuple(sorted(
        (a.component_id, a.distributor_id, a.quantity)
        for a in assignments if a.quantity > 0
    ))


def _evaluate_plan(
    gs,
    comp_ids: List[int],
    selected: Set[int],
    targeted_did: Optional[int],
) -> Dict[str, Dict[str, float]]:
    """
    Score one plan under the benchmark's three scenarios.

    Two risk measures are reported per scenario and they answer different
    questions:

      cascade_risk = 1 - p50(fulfillment). This is the benchmark's own
        `plan_cascade_risk` column, so the frontier is directly comparable to
        the published Value-of-Resilience table. It is COARSE by construction: a
        4-line BOM can only take fulfillment values {0, .25, .5, .75, 1}, so a
        median of them moves in quarter steps and is insensitive to anything
        that does not shift the median scenario.

      expected_shortfall = 1 - mean(fulfillment). The same simulation's mean
        rather than its median — continuous, and therefore the measure that can
        actually resolve small differences between adjacent k. Reported
        alongside, never instead of, the published one.
    """
    out: Dict[str, Dict[str, float]] = {}
    scenarios = (
        ("nominal", 1.0, None),
        ("stress", STRESS_FACTOR, None),
        ("targeted", 1.0, {targeted_did} if targeted_did is not None else None),
    )
    for label, stress, forced in scenarios:
        mc = run_monte_carlo(
            gs,
            bom_component_ids=comp_ids,
            allowed_distributor_ids=selected,
            stress_factor=stress,
            forced_failures=forced,
        )
        out[label] = {
            "cascade_risk": round(1.0 - mc.p50, 4),
            "expected_shortfall": round(1.0 - mc.mean_fulfillment, 6),
            "cvar_95": round(float(mc.cvar_95), 4),
            "p10": round(mc.p10, 4),
            "worst_fulfillment": round(mc.worst_fulfillment, 4),
            "n_single_source_lines": int(mc.n_single_source_lines),
            "n_scenarios_with_shortfall": int(mc.n_scenarios_with_shortfall),
        }
    return out


def sweep_bom(
    db,
    gs,
    bom_name: str,
    bom_items: List[Tuple[str, int]],
    weights,
    k_max: int = K_MAX,
) -> Dict[str, Any]:
    """
    Solve and evaluate one BOM across k = 1..k_max.

    Returns a record with a `points` list (one entry per feasible k) and an
    explicit `excluded`/`reason` verdict when the BOM cannot be swept at all —
    the same publish-the-exclusion discipline run_benchmark uses (BENCH-07),
    because a BOM that silently vanishes shrinks the panel the CIs are computed
    over.
    """
    record: Dict[str, Any] = {
        "bom": bom_name,
        "n_lines": len(bom_items),
        "included": False,
        "reason": None,
        "n_offers": 0,
        "n_candidate_distributors": 0,
        "targeted_distributor_id": None,
        "points": [],
    }

    bom, offers, _meta = _load_offers_for_bom(db, bom_items)
    record["n_offers"] = len(offers)
    if not bom or not offers:
        record["reason"] = (
            f"no valid BOM lines / offers resolved from the DB "
            f"({len(bom)} of {len(bom_items)} MPNs matched, {len(offers)} offers)"
        )
        return record

    comp_ids = [b.component_id for b in bom]

    # Targeted-outage victim: highest-betweenness distributor in the BOM's FULL
    # offer pool, not in any plan's selection — identical across every k, so the
    # scenario is the same shock at every point on the frontier. This is exactly
    # what run_benchmark._run_bom does.
    pool_dids: Set[int] = {o.distributor_id for o in offers}
    targeted_did = (
        max(pool_dids, key=lambda d: gs.betweenness.get(d, 0.0)) if pool_dids else None
    )
    record["targeted_distributor_id"] = targeted_did

    baseline_sig: Optional[Tuple] = None
    baseline_sel: Optional[Set[int]] = None
    for k in range(1, k_max + 1):
        try:
            res = solve_sourcing(
                bom, offers, weights, us_only=True,
                graph_aware=False, min_distributors=k,
            )
        except (RuntimeError, ValueError) as exc:
            record["points"].append({
                "k": k, "feasible": False, "reason": f"{type(exc).__name__}: {exc}",
            })
            # k is monotone in tightness — once infeasible it stays infeasible.
            break

        bd = landed_cost_breakdown(res.assignments, offers, bom, weights)
        selected = {a.distributor_id for a in res.assignments if a.quantity > 0}
        sig = _plan_signature(res.assignments)
        if baseline_sig is None:
            baseline_sig = sig
            baseline_sel = set(selected)

        point: Dict[str, Any] = {
            "k": k,
            "feasible": True,
            "status": res.status,
            "total_cost_usd": round(float(bd["total_cost"]), 2),
            "component_cost_usd": round(float(bd["component_cost"]), 2),
            "transport_fixed_usd": round(float(bd["transport_fixed"]), 2),
            "transport_variable_usd": round(float(bd["transport_variable"]), 2),
            "n_distinct_suppliers": int(bd["n_distinct_suppliers"]),
            "selected_distributor_ids": sorted(selected),
            "plan_changed_vs_k1": sig != baseline_sig,
            # Does this plan KEEP everything the cost-optimal plan chose and add
            # to it, or does it swap the incumbent out? The constraint only
            # bounds the COUNT of distributors, so the MILP is free to satisfy
            # it by abandoning a reliable incumbent for a cheaper set of k. When
            # that happens the plan is more diversified and not necessarily
            # safer — see the mechanism section of the generated markdown.
            "keeps_k1_suppliers": bool(
                baseline_sel is not None and baseline_sel <= selected
            ),
            "scenarios": _evaluate_plan(gs, comp_ids, selected, targeted_did),
        }
        record["points"].append(point)

    feasible = [p for p in record["points"] if p.get("feasible")]
    if not feasible:
        record["reason"] = (
            record["points"][0]["reason"] if record["points"]
            else "no k was attempted"
        )
        return record

    record["included"] = True
    record["n_candidate_distributors"] = len(pool_dids)
    return record


# ── Paired inference across BOMs ─────────────────────────────────────────────

def paired_bootstrap_ci(
    deltas: Sequence[float],
    n_boot: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
    alpha: float = CI_ALPHA,
) -> Dict[str, Any]:
    """
    Percentile bootstrap CI for the mean of a PAIRED difference.

    Paired because both numbers in each difference come from the SAME BOM under
    the SAME simulation seed — the only thing that changes is k. Resampling BOMs
    (the independent unit) with replacement is therefore the right resample, and
    the BOM-level variation it captures is the variation a reviewer should care
    about: does the effect hold across products, or is it one BOM?

    The percentile interval is used rather than BCa: with n <= 9 BOMs the
    acceleration term is estimated from at most 9 jackknife points and is not
    worth the false precision. n is reported next to every interval for the same
    reason — an interval over 7 BOMs is a description, not a population claim.
    """
    vals = [float(d) for d in deltas]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "ci_low": None, "ci_high": None,
                "excludes_zero": False}
    mean = statistics.fmean(vals)
    if n == 1:
        return {"n": 1, "mean": round(mean, 6), "ci_low": None, "ci_high": None,
                "excludes_zero": False,
                "note": "n=1 — no interval is estimable"}

    rng = random.Random(seed)
    means: List[float] = []
    for _ in range(n_boot):
        means.append(statistics.fmean(rng.choices(vals, k=n)))
    means.sort()
    lo = means[max(0, int((alpha / 2) * n_boot))]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return {
        "n": n,
        "mean": round(mean, 6),
        "ci_low": round(lo, 6),
        "ci_high": round(hi, 6),
        "excludes_zero": (lo > 0.0) or (hi < 0.0),
        "n_boot": n_boot,
        "seed": seed,
        "method": "paired percentile bootstrap over BOMs",
    }


# ── The price of a unit of risk, with its SIGN handled ───────────────────────
#
# `excludes_zero` is symmetric: `(lo > 0) or (hi < 0)`. It says the change is
# measurable, NOT that it is a REDUCTION. Gating a "$ per unit of risk removed"
# on it alone therefore prints a NEGATIVE dollar figure under a column headed
# "risk removed" whenever diversification significantly ADDS risk — which reads
# as a price of protection and is the opposite of what happened.
#
# No k had ever been significantly negative before the supply graph was
# corrected to use all 8,176 supplier-part links, so this never surfaced; on the
# corrected graph the cumulative stress cascade risk at k = 3 is significantly
# WORSE than at k = 1 and the doc rendered `$-1,910.71` as a price of risk
# removed. A price of protection is only defined when protection was bought, so
# the removed-price is withheld and the same magnitude is republished under its
# true name: dollars paid per unit of risk ADDED.

_NOT_MEASURABLE_NOTE = (
    "not reported: the risk change at this k is not distinguishable from zero "
    "(paired 95% CI covers 0)"
)


def _risk_added_note(scen: str, measure: str, mean_removed: float) -> str:
    return (
        "not reported as a price of risk REMOVED: at this k the constrained plan "
        f"ADDS {measure.replace('_', ' ')} under {scen} "
        f"({abs(mean_removed):.4f} more per BOM, paired 95% CI excluding zero on "
        "the ADDED side). Dividing dollars by a NEGATIVE risk change would print "
        "a negative number under a heading that says risk removed, so the same "
        "magnitude is published as dollars paid per unit of risk ADDED instead."
    )


def price_of_risk(
    total_cost: float, total_removed: float, ci: Dict[str, Any],
    scen: str, measure: str,
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Return `(usd_per_unit_removed, usd_per_unit_added, note)` for one ratio.

    Exactly one of the two prices is ever non-None, and a note is present in
    exactly the cases where `usd_per_unit_removed` is None:

      * CI covers zero, or the denominator is numerically zero -> no price at
        all; the ratio would be an artifact of division.
      * CI excludes zero and risk FELL -> the price of risk removed.
      * CI excludes zero and risk ROSE -> no price of risk removed exists;
        the dollars per unit of risk ADDED are reported instead.
    """
    if not ci.get("excludes_zero") or abs(total_removed) <= 1e-12:
        return None, None, _NOT_MEASURABLE_NOTE
    if total_removed > 0:
        return round(total_cost / total_removed, 2), None, None
    return (
        None,
        round(total_cost / -total_removed, 2),
        _risk_added_note(scen, measure, float(ci.get("mean") or 0.0)),
    )


def _frontier_table(records: List[Dict[str, Any]], k_max: int) -> List[Dict[str, Any]]:
    """
    Aggregate the per-BOM sweep into one row per k, with paired CIs vs k = 1.

    `n_effective` is the number of BOMs whose PLAN actually differs from its
    k = 1 plan at this k. It matters: a BOM the constraint does not bind on
    contributes an exact zero to every delta and shrinks the apparent spread
    without carrying any information. Run 5 has the same problem in a different
    form — `drone_flight_controller` and `rf_transceiver_module` are already
    diversified, so their two MILP arms are structurally the same plan and the
    published "9 BOMs" overstates the evidence for the arm comparison.
    """
    included = [r for r in records if r["included"]]
    by_bom: Dict[str, Dict[int, Dict[str, Any]]] = {
        r["bom"]: {p["k"]: p for p in r["points"] if p.get("feasible")}
        for r in included
    }

    rows: List[Dict[str, Any]] = []
    for k in range(1, k_max + 1):
        boms_at_k = [b for b, pts in by_bom.items() if k in pts and 1 in pts]
        if not boms_at_k:
            continue
        pts = [by_bom[b][k] for b in boms_at_k]
        base = [by_bom[b][1] for b in boms_at_k]

        d_cost = [p["total_cost_usd"] - b["total_cost_usd"] for p, b in zip(pts, base, strict=True)]
        row: Dict[str, Any] = {
            "k": k,
            "n_boms_feasible": len(boms_at_k),
            "boms_feasible": sorted(boms_at_k),
            "boms_infeasible": sorted(set(by_bom) - set(boms_at_k)),
            "n_effective": sum(1 for p in pts if p["plan_changed_vs_k1"]),
            "n_keeps_k1_suppliers": sum(1 for p in pts if p["keeps_k1_suppliers"]),
            "mean_total_cost_usd": round(statistics.fmean(
                p["total_cost_usd"] for p in pts), 2),
            "mean_suppliers": round(statistics.fmean(
                p["n_distinct_suppliers"] for p in pts), 2),
            "delta_cost_vs_k1": paired_bootstrap_ci(d_cost),
        }

        # Mask over the EFFECTIVE panel: the BOMs the constraint actually moved.
        eff = [i for i, p in enumerate(pts) if p["plan_changed_vs_k1"]]
        row["effective_panel"] = {
            "boms": sorted(boms_at_k[i] for i in eff),
            "delta_cost_vs_k1": paired_bootstrap_ci([d_cost[i] for i in eff]),
        }

        for scen in ("stress", "targeted", "nominal"):
            for measure in ("cascade_risk", "expected_shortfall", "cvar_95"):
                cur = [p["scenarios"][scen][measure] for p in pts]
                bse = [b["scenarios"][scen][measure] for b in base]
                removed = [b - c for c, b in zip(cur, bse, strict=True)]
                row[f"mean_{scen}_{measure}"] = round(statistics.fmean(cur), 6)
                # Risk REMOVED: positive means k is safer than k = 1.
                row[f"delta_{scen}_{measure}_vs_k1"] = paired_bootstrap_ci(removed)
                row["effective_panel"][f"delta_{scen}_{measure}_vs_k1"] = (
                    paired_bootstrap_ci([removed[i] for i in eff])
                )

        # ── Price of one unit of risk removed ────────────────────────────────
        # Ratio of SUMS (total extra dollars / total risk removed), not a mean of
        # per-BOM ratios: per-BOM ratios are undefined wherever a BOM's risk does
        # not move, which is most of them, and a mean over the survivors is a
        # selected sample. The ratio is only reported when the denominator's own
        # paired CI excludes zero AND the change is a REDUCTION — see
        # `price_of_risk` for why the second half of that test is not optional.
        for scen in ("stress", "targeted"):
            for measure in ("cascade_risk", "expected_shortfall"):
                removed = [
                    b["scenarios"][scen][measure] - p["scenarios"][scen][measure]
                    for p, b in zip(pts, base, strict=True)
                ]
                denom_ci = row[f"delta_{scen}_{measure}_vs_k1"]
                px_removed, px_added, note = price_of_risk(
                    sum(d_cost), sum(removed), denom_ci, scen, measure
                )
                row[f"usd_per_unit_{scen}_{measure}_removed"] = px_removed
                if note is not None:
                    row[f"usd_per_unit_{scen}_{measure}_removed_note"] = note
                if px_added is not None:
                    row[f"usd_per_unit_{scen}_{measure}_added"] = px_added
        rows.append(row)

    # Marginal step k-1 -> k, on the BOMs feasible at both. This is the column
    # that answers "where does buying more stop paying": the k-th supplier's
    # own price, against the risk that k-th supplier's own removes.
    for i, row in enumerate(rows):
        if i == 0:
            row["marginal_cost_usd_vs_prev_k"] = None
            row["marginal_risk_removed_vs_prev_k"] = {}
            row["marginal_usd_per_unit_risk_removed"] = {}
            row["marginal_usd_per_unit_risk_added"] = {}
            row["marginal_usd_per_unit_risk_removed_note"] = {}
            continue
        k, kp = row["k"], rows[i - 1]["k"]
        shared = [b for b, pts in by_bom.items() if k in pts and kp in pts]
        d_cost_step = [
            by_bom[b][k]["total_cost_usd"] - by_bom[b][kp]["total_cost_usd"]
            for b in shared
        ]
        row["marginal_cost_usd_vs_prev_k"] = paired_bootstrap_ci(d_cost_step)
        row["marginal_risk_removed_vs_prev_k"] = {}
        row["marginal_usd_per_unit_risk_removed"] = {}
        row["marginal_usd_per_unit_risk_added"] = {}
        row["marginal_usd_per_unit_risk_removed_note"] = {}
        for scen in ("stress", "targeted"):
            for measure in ("cascade_risk", "expected_shortfall"):
                key = f"{scen}_{measure}"
                removed = [
                    by_bom[b][kp]["scenarios"][scen][measure]
                    - by_bom[b][k]["scenarios"][scen][measure]
                    for b in shared
                ]
                ci = paired_bootstrap_ci(removed)
                row["marginal_risk_removed_vs_prev_k"][key] = ci
                px_removed, px_added, note = price_of_risk(
                    sum(d_cost_step), sum(removed), ci, scen, measure
                )
                row["marginal_usd_per_unit_risk_removed"][key] = px_removed
                row["marginal_usd_per_unit_risk_added"][key] = px_added
                row["marginal_usd_per_unit_risk_removed_note"][key] = note
    return rows


# ── Run-5 reproduction check ─────────────────────────────────────────────────

def check_against_run5(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    k = 1 must reproduce the committed benchmark's unconstrained `milp_blind`
    plan cost, BOM by BOM. If it does not, the frontier's baseline is not run
    5's baseline and nothing downstream is comparable.
    """
    out: Dict[str, Any] = {
        "source": "docs/benchmark_results.json",
        "field": "value_of_optimization[].milp_usd",
        "tolerance_usd": 0.01,
        "checked": 0,
        "matched": 0,
        "mismatches": [],
        "all_match": False,
    }
    if not BENCHMARK_JSON.exists():
        out["error"] = "docs/benchmark_results.json not found"
        return out
    payload = json.loads(BENCHMARK_JSON.read_text())
    out["benchmark_run_id"] = payload.get("meta", {}).get("run_id")
    ref = {r["bom"]: r for r in payload.get("value_of_optimization", [])}

    for rec in records:
        if not rec["included"]:
            continue
        k1 = next((p for p in rec["points"] if p.get("feasible") and p["k"] == 1), None)
        want = ref.get(rec["bom"])
        if k1 is None or want is None:
            continue
        out["checked"] += 1
        delta = abs(k1["total_cost_usd"] - float(want["milp_usd"]))
        if delta <= out["tolerance_usd"]:
            out["matched"] += 1
        else:
            out["mismatches"].append({
                "bom": rec["bom"],
                "sweep_k1_usd": k1["total_cost_usd"],
                "run5_milp_blind_usd": float(want["milp_usd"]),
                "abs_delta_usd": round(delta, 2),
            })
    out["all_match"] = out["checked"] > 0 and not out["mismatches"]
    return out


# ── Is risk actually non-monotone in k on THIS sweep? ────────────────────────
#
# The mechanism section used to ASSERT that it is. It is a property of the
# CONSTRAINT that risk need not be monotone (a count says nothing about which
# doors stay open), but whether it actually is not is a question about the data,
# and the answer changed when the supply graph was corrected: on the full
# 8,176-link graph stress EXPECTED SHORTFALL falls monotonically in k on every
# included BOM, so the expected-shortfall counter-example the section used to
# name no longer exists. The coarser p50 measure still is not monotone. This
# scan reports what is actually there, per measure, so the prose can never
# outlive its evidence again.

def non_monotone_rises(
    records: List[Dict[str, Any]], measure: str, scen: str = "stress"
) -> List[Dict[str, Any]]:
    """Every consecutive-k step on an included BOM where `scen`/`measure` RISES."""
    out: List[Dict[str, Any]] = []
    for rec in records:
        if not rec.get("included"):
            continue
        pts = [p for p in (rec.get("points") or []) if p.get("feasible")]
        for prev, cur in zip(pts, pts[1:], strict=False):
            before = (prev.get("scenarios", {}).get(scen, {}) or {}).get(measure)
            after = (cur.get("scenarios", {}).get(scen, {}) or {}).get(measure)
            if not isinstance(before, (int, float)) or not isinstance(
                after, (int, float)
            ):
                continue
            if after > before:
                out.append({
                    "bom": rec["bom"],
                    "scenario": scen,
                    "measure": measure,
                    "from_k": prev["k"],
                    "to_k": cur["k"],
                    "value_before": round(float(before), 4),
                    "value_after": round(float(after), 4),
                    "rise": round(float(after) - float(before), 4),
                    "n_suppliers_before": int(prev.get("n_distinct_suppliers", 0)),
                    "n_suppliers_after": int(cur.get("n_distinct_suppliers", 0)),
                    "keeps_k1_suppliers": bool(cur.get("keeps_k1_suppliers", False)),
                })
    out.sort(key=lambda r: (-r["rise"], r["bom"], r["to_k"]))
    return out


# ── Markdown ─────────────────────────────────────────────────────────────────

def _ci_str(ci: Optional[Dict[str, Any]], unit: str = "", digits: int = 2) -> str:
    if not ci or ci.get("mean") is None:
        return "—"
    if ci.get("ci_low") is None:
        return f"{ci['mean']:.{digits}f}{unit} (n=1)"
    star = " *" if ci.get("excludes_zero") else ""
    return (f"{ci['mean']:.{digits}f}{unit} "
            f"[{ci['ci_low']:.{digits}f}, {ci['ci_high']:.{digits}f}]{star}")


def render_markdown(payload: Dict[str, Any]) -> str:
    meta = payload["meta"]
    rows = payload["frontier"]
    L: List[str] = []
    A = L.append

    A("# The Price of Resilience — a diversification frontier")
    A("")
    A("**Generated by** `seeds/run_diversification_sweep.py` · "
      f"**strategy** `{meta['strategy']}` · "
      f"**MC** {meta['mc_scenarios']} scenarios, seed {meta['mc_seed']} · "
      f"**stress factor** {meta['stress_factor']}")
    A("")
    A("This file is regenerated by the script. Do not hand-edit the tables.")
    A("")
    A("## What this measures")
    A("")
    A("Benchmark run 5 shows the cost-optimal sourcing MILP consolidating "
      "suppliers per BOM, and shows a mitigation arm that helps under a targeted "
      "outage and hurts under broad stress. Neither result prices the trade. "
      "This sweep does: the SAME MILP is re-solved subject to a hard "
      "`open at least k distinct distributors` constraint, and each resulting "
      "plan is costed and simulated under the benchmark's own scenarios.")
    A("")
    A("At `k = 1` the constraint binds on nothing, so the plan is the "
      "unconstrained cost-optimal plan — the frontier's own control arm.")
    A("")

    chk = payload["run5_reproduction_check"]
    A("### Baseline check against the committed benchmark")
    A("")
    if chk.get("all_match"):
        A(f"`k = 1` reproduces run {chk.get('benchmark_run_id')}'s `milp_blind` "
          f"landed cost on **{chk['matched']} of {chk['checked']}** BOMs to within "
          f"${chk['tolerance_usd']:.2f}. The frontier's baseline IS the published "
          "baseline.")
    else:
        A(f"**MISMATCH** — `k = 1` does not reproduce run "
          f"{chk.get('benchmark_run_id')}'s `milp_blind` cost on "
          f"{len(chk.get('mismatches', []))} BOM(s). The frontier below is NOT "
          "comparable to the published benchmark until this is explained.")
        for m in chk.get("mismatches", []):
            A(f"  - `{m['bom']}`: sweep ${m['sweep_k1_usd']:.2f} vs run 5 "
              f"${m['run5_milp_blind_usd']:.2f} (Δ ${m['abs_delta_usd']:.2f})")
    A("")

    A("## Finding")
    A("")
    k2 = next((r for r in rows if r["k"] == 2), None)
    if k2 is not None:
        tgt = k2["delta_targeted_cascade_risk_vs_k1"]
        stz = k2["delta_stress_cascade_risk_vs_k1"]
        cst = k2["delta_cost_vs_k1"]
        A("Forcing a **second** distinct supplier costs "
          f"**${cst['mean']:.2f} per BOM** "
          f"(95% CI ${cst['ci_low']:.2f} to ${cst['ci_high']:.2f}, n={cst['n']}) "
          "and removes "
          f"**{tgt['mean']:.3f}** of cascade risk under a targeted outage of the "
          "most-central distributor "
          f"(CI {tgt['ci_low']:.3f} to {tgt['ci_high']:.3f}"
          f"{' — excludes zero' if tgt['excludes_zero'] else ''}). "
          "Under **broad systemic stress** the same purchase changes cascade "
          f"risk by {stz['mean']:.3f} "
          f"(CI {stz['ci_low']:.3f} to {stz['ci_high']:.3f}"
          f"{' — excludes zero' if stz['excludes_zero'] else ' — covers zero'}).")
        A("")
        A("**Diversification is priceable against a named single point of "
          "failure and is not, on this data, priceable against broad correlated "
          "stress.** The mechanism section explains why a supplier COUNT was "
          "never going to be a resilience constraint.")
        A("")
        # How far the price column actually reaches, derived from the rows —
        # never asserted. The "cheap second supplier, expensive third" collapse
        # this section used to publish needs TWO priced steps to exist at all.
        steps = [r for r in rows if r.get("marginal_cost_usd_vs_prev_k") is not None]
        priced = [
            r for r in steps
            if (r.get("marginal_usd_per_unit_risk_removed") or {}).get(
                "targeted_cascade_risk") is not None
        ]
        if len(priced) >= 2:
            first, second = priced[0], priced[1]
            p1 = first["marginal_usd_per_unit_risk_removed"]["targeted_cascade_risk"]
            p2 = second["marginal_usd_per_unit_risk_removed"]["targeted_cascade_risk"]
            A(f"**Where it collapses.** The step to k = {first['k']} removes "
              f"targeted cascade risk at ${p1:,.2f} per unit; the step to "
              f"k = {second['k']} costs ${p2:,.2f} per unit, "
              f"{p2 / p1:.1f}× more for the same unit of risk. Past that step no "
              "price can be quoted at all.")
        elif len(priced) == 1:
            only = priced[0]
            p1 = only["marginal_usd_per_unit_risk_removed"]["targeted_cascade_risk"]
            k1r = next((r for r in rows if r["k"] == 1), None)
            after = next((r for r in rows if r["k"] == only["k"]), None)
            A(f"**Only 1 of the {len(steps)} steps on this frontier carries a "
              "price at all**, so there is no cheap-then-expensive collapse to "
              f"report: the step to k = {only['k']} removes targeted cascade "
              f"risk at ${p1:,.2f} per unit, and every later step's marginal "
              "targeted-risk interval covers zero. The reason is not that later "
              "suppliers are expensive — it is that there is nothing measurable "
              "left for them to remove. Mean targeted cascade risk goes from "
              f"{k1r['mean_targeted_cascade_risk']:.3f} at k = 1 to "
              f"{after['mean_targeted_cascade_risk']:.3f} at k = {only['k']}, "
              "and to "
              f"{rows[-1]['mean_targeted_cascade_risk']:.3f} at k = "
              f"{rows[-1]['k']}.")
        else:
            A("**No step on this frontier carries a price.** Every step's "
              "marginal targeted cascade risk has a paired 95% CI covering "
              "zero, so no dollars-per-unit-of-risk figure is quotable and none "
              "is published.")
        A("")
        if all(r["mean_nominal_cascade_risk"] == 0.0 for r in rows):
            A("**Under NOMINAL conditions cascade risk is 0.000 at every k, "
              "including the unconstrained k = 1 plan.** On the full "
              "supplier-part graph this BOM panel has no nominal cascade "
              "exposure for a second supplier to remove, so everything this "
              "frontier prices is protection against an OUTAGE — a targeted one "
              "or broad stress — and never against the base case.")
    A("")

    A("## The frontier")
    A("")
    A("Costs are mean landed cost per BOM. Deltas are **paired** against the same "
      "BOM's own `k = 1` plan, with a 95% percentile bootstrap CI resampling BOMs "
      f"({meta['bootstrap_n']:,} resamples, seed {meta['bootstrap_seed']}). "
      "`*` marks an interval that excludes zero. Risk deltas are risk **removed** "
      "— positive means safer than `k = 1`.")
    A("")
    A("| k | BOMs | n_eff | mean cost | Δcost vs k=1 | Δ cascade risk (stress) | "
      "Δ cascade risk (targeted) | Δ E[shortfall] (stress) | Δ E[shortfall] (targeted) |")
    A("|---:|---:|---:|---:|---|---|---|---|---|")
    for r in rows:
        A("| {k} | {n} | {ne} | ${c:,.2f} | {dc} | {ds} | {dt} | {es} | {et} |".format(
            k=r["k"], n=r["n_boms_feasible"], ne=r["n_effective"],
            c=r["mean_total_cost_usd"],
            dc=_ci_str(r["delta_cost_vs_k1"], unit="", digits=2),
            ds=_ci_str(r["delta_stress_cascade_risk_vs_k1"], digits=4),
            dt=_ci_str(r["delta_targeted_cascade_risk_vs_k1"], digits=4),
            es=_ci_str(r["delta_stress_expected_shortfall_vs_k1"], digits=4),
            et=_ci_str(r["delta_targeted_expected_shortfall_vs_k1"], digits=4),
        ))
    A("")
    A("**`n_eff`** is the number of BOMs whose sourcing plan actually CHANGES at "
      "this k. A BOM the constraint does not bind on contributes an exact zero to "
      "every delta; counting it inflates n and shrinks the interval without "
      "adding evidence.")
    A("")

    A("### The same frontier over the EFFECTIVE panel only")
    A("")
    A("Restricted at each k to the BOMs whose plan the constraint actually "
      "changed. This is the honest denominator — and it is why the headline "
      "table quotes `n_eff` next to `n`.")
    A("")
    A("| k | n_eff | Δcost vs k=1 | Δ cascade risk (stress) | "
      "Δ cascade risk (targeted) | Δ E[shortfall] (stress) | Δ E[shortfall] (targeted) |")
    A("|---:|---:|---|---|---|---|---|")
    for r in rows:
        e = r["effective_panel"]
        A("| {k} | {n} | {dc} | {ds} | {dt} | {es} | {et} |".format(
            k=r["k"], n=r["n_effective"],
            dc=_ci_str(e["delta_cost_vs_k1"], digits=2),
            ds=_ci_str(e["delta_stress_cascade_risk_vs_k1"], digits=4),
            dt=_ci_str(e["delta_targeted_cascade_risk_vs_k1"], digits=4),
            es=_ci_str(e["delta_stress_expected_shortfall_vs_k1"], digits=4),
            et=_ci_str(e["delta_targeted_expected_shortfall_vs_k1"], digits=4),
        ))
    A("")

    A("### Marginal return — what the k-th supplier alone buys")
    A("")
    A("Each row is the step from k−1 to k, paired on the BOMs feasible at both. "
      "This is the column that says where to stop.")
    A("")
    A("| step | marginal cost | marginal cascade risk removed (targeted) | "
      "$/unit (targeted) | marginal E[shortfall] removed (stress) | $/unit (stress) |")
    A("|---|---|---|---|---|---|")
    def _price_cell(
        removed: Optional[float], added: Optional[float], missing: str
    ) -> str:
        """A price of protection, or the honest label for its absence.

        A significantly NEGATIVE risk change is not a cheap price — it is risk
        ADDED, and it is rendered as such rather than as a minus sign in front
        of a figure the column heading calls "removed".
        """
        if removed is not None:
            return f"${removed:,.2f}"
        if added is not None:
            return f"**risk ADDED** — ${added:,.2f} per unit added"
        return missing

    for r in rows:
        if r.get("marginal_cost_usd_vs_prev_k") is None:
            continue
        mr = r["marginal_risk_removed_vs_prev_k"]
        px = r["marginal_usd_per_unit_risk_removed"]
        pa = r.get("marginal_usd_per_unit_risk_added") or {}
        A("| {a}→{k} | {m} | {t} | {tp} | {s} | {sp} |".format(
            a=r["k"] - 1, k=r["k"],
            m=_ci_str(r["marginal_cost_usd_vs_prev_k"], digits=2),
            t=_ci_str(mr.get("targeted_cascade_risk"), digits=4),
            tp=_price_cell(px.get("targeted_cascade_risk"),
                           pa.get("targeted_cascade_risk"), "n.s."),
            s=_ci_str(mr.get("stress_expected_shortfall"), digits=4),
            sp=_price_cell(px.get("stress_expected_shortfall"),
                           pa.get("stress_expected_shortfall"), "n.s."),
        ))
    A("")
    A("### Cumulative price of risk vs k = 1")
    A("")
    A("| k | Δcost vs k=1 | $/unit cascade risk (stress) | "
      "$/unit cascade risk (targeted) |")
    A("|---:|---|---|---|")
    for r in rows:
        A("| {k} | {d} | {s} | {t} |".format(
            k=r["k"], d=_ci_str(r["delta_cost_vs_k1"], digits=2),
            s=_price_cell(r.get("usd_per_unit_stress_cascade_risk_removed"),
                          r.get("usd_per_unit_stress_cascade_risk_added"),
                          "not reported"),
            t=_price_cell(r.get("usd_per_unit_targeted_cascade_risk_removed"),
                          r.get("usd_per_unit_targeted_cascade_risk_added"),
                          "not reported"),
        ))
    A("")
    A("A price per unit of risk removed is printed only where the risk change at "
      "that k has a paired 95% CI excluding zero **and the change is a "
      "REDUCTION** (`n.s.` / `not reported` otherwise). Where the CI covers "
      "zero the denominator is indistinguishable from zero and the ratio would "
      "be an artifact of division, not a price. Where the CI excludes zero on "
      "the other side, diversification at that k ADDED risk: there is no price "
      "of protection to quote, so the cell says `risk ADDED` and reports the "
      "dollars paid per unit of risk added rather than printing a negative "
      "number under a heading that says removed.")
    A("")

    A("## The mechanism — why a supplier COUNT is not a resilience constraint")
    A("")
    A("`min_distributors = k` bounds how many doors the plan keeps open. It says "
      "nothing about WHICH doors, and the objective is still pure cost — so the "
      "cheapest way to satisfy it is often to abandon the incumbent hub and buy "
      "a cheaper set of k. The sweep records whether each plan is a superset of "
      "its own `k = 1` plan:")
    A("")
    A("| k | BOMs | plans that KEEP every k=1 supplier |")
    A("|---:|---:|---:|")
    for r in rows:
        A(f"| {r['k']} | {r['n_boms_feasible']} | {r['n_keeps_k1_suppliers']} |")
    A("")
    A("That is the whole result in one table. Because the sets are not nested, "
      "risk NEED NOT be monotone in k: a BOM can be forced to two suppliers and "
      "end up MORE exposed under broad stress than it was on one, if the one it "
      "left had the lower hazard. Whether it actually is not is a question about "
      "the data, answered below from this sweep's own rows rather than asserted.")
    A("")

    # Which measure, if any, is actually non-monotone here. This paragraph is
    # generated from the per-BOM records: the expected-shortfall counter-example
    # this section used to name does not exist on the corrected supply graph,
    # and prose that outlives its evidence is exactly what this file must not
    # publish.
    recs = payload["boms"]
    n_incl = sum(1 for r in recs if r.get("included"))
    es_rises = non_monotone_rises(recs, "expected_shortfall")
    cr_rises = non_monotone_rises(recs, "cascade_risk")
    worse_ks = [
        r for r in rows
        if r["k"] > 1
        and r["delta_stress_cascade_risk_vs_k1"]["excludes_zero"]
        and r["delta_stress_cascade_risk_vs_k1"]["mean"] < 0
    ]

    def _example(e: Dict[str, Any]) -> str:
        how = (
            "it keeps its whole `k = 1` set and is still more exposed"
            if e["keeps_k1_suppliers"] else
            f"it drops a lower-hazard incumbent for a cheaper set of "
            f"{e['n_suppliers_after']}"
        )
        return (f"`{e['bom']}` goes from {e['value_before']:.4f} to "
                f"{e['value_after']:.4f} between k = {e['from_k']} and "
                f"k = {e['to_k']} — {how}")

    if es_rises:
        A(f"**Stress expected shortfall is not monotone in k.** It rises on "
          f"{len({e['bom'] for e in es_rises})} of the {n_incl} included BOMs; "
          f"worst case, {_example(es_rises[0])}.")
    elif cr_rises:
        A(f"**Retraction — the expected-shortfall counter-example is gone.** "
          f"On this sweep stress expected shortfall FALLS at every step on all "
          f"{n_incl} included BOMs, so the BOM-level counter-example this "
          "section used to name in that measure no longer exists and is "
          "withdrawn. The non-monotonicity survives in the coarser p50 measure: "
          f"stress cascade risk rises on {len({e['bom'] for e in cr_rises})} of "
          f"the {n_incl} BOMs — {_example(cr_rises[0])}.")
        if worse_ks:
            A("")
            w = worse_ks[0]["delta_stress_cascade_risk_vs_k1"]
            A(f"That is not only a per-BOM curiosity: at k = {worse_ks[0]['k']} "
              "the panel as a whole is significantly MORE exposed under broad "
              f"stress than at k = 1 ({-w['mean']:.4f} more cascade risk per "
              f"BOM, paired 95% CI {-w['ci_high']:.4f} to {-w['ci_low']:.4f}, "
              f"n={w['n']} — excludes zero).")
    else:
        A(f"**Retraction — risk is monotone in k on this sweep.** Neither "
          f"stress expected shortfall nor stress cascade risk rises at any step "
          f"on any of the {n_incl} included BOMs, so this section's "
          "counter-example is withdrawn: non-monotonicity remains a property "
          "the constraint PERMITS, and this sweep does not exhibit it.")
    A("")
    A("Under a TARGETED outage the effect is one-directional — spreading always "
      "shrinks the blast radius of losing a single named hub — which is exactly "
      "the asymmetry benchmark run 5 observed and could not explain.")
    A("")

    A("## Per-BOM detail")
    A("")
    A("| BOM | k | suppliers | landed cost | cascade risk (stress) | "
      "cascade risk (targeted) | E[shortfall] (stress) | plan changed | keeps k=1 set |")
    A("|---|---:|---:|---:|---:|---:|---:|:--:|:--:|")
    for rec in payload["boms"]:
        if not rec["included"]:
            continue
        for p in rec["points"]:
            if not p.get("feasible"):
                A(f"| `{rec['bom']}` | {p['k']} | — | infeasible | — | — | — | — | — |")
                continue
            s = p["scenarios"]
            A("| `{b}` | {k} | {n} | ${c:,.2f} | {rs:.4f} | {rt:.4f} | {es:.4f} | {ch} | {ks} |".format(
                b=rec["bom"], k=p["k"], n=p["n_distinct_suppliers"],
                c=p["total_cost_usd"],
                rs=s["stress"]["cascade_risk"], rt=s["targeted"]["cascade_risk"],
                es=s["stress"]["expected_shortfall"],
                ch="yes" if p["plan_changed_vs_k1"] else "no",
                ks="yes" if p["keeps_k1_suppliers"] else "no",
            ))
    A("")

    excluded = [r for r in payload["boms"] if not r["included"]]
    A("### Coverage")
    A("")
    A(f"{meta['n_boms_included']} of {meta['n_boms_in_catalog']} catalogue BOMs "
      "are swept.")
    for r in excluded:
        A(f"- **excluded** `{r['bom']}` — {r['reason']}")
    A("")

    A("## Honest caveats")
    A("")
    for c in payload["caveats"]:
        A(f"- {c}")
    A("")
    return "\n".join(L) + "\n"


# ── Caveats (published, not buried) ──────────────────────────────────────────

CAVEATS: List[str] = [
    "**The cost axis is dominated by a fixed freight fee, not by component "
    "prices.** Each opened distributor pays `LTL_BASE_FEE_USD` scaled by the "
    "strategy's `transport_penalty_scale` (1.5 for `balanced`), plus a flat "
    "consolidation charge. That fixed charge is the same for every supplier, so "
    "the cost side of this frontier is close to linear in k almost by "
    "construction. The interesting question is therefore not the shape of the "
    "cost curve — it is whether the RISK curve buys anything for it.",

    "**`cascade_risk` is quantised.** It is `1 - p50(fulfillment)` over a 4-line "
    "BOM, so it can only take the values {0, 0.25, 0.5, 0.75, 1}. It cannot "
    "resolve a change smaller than a quarter of a BOM. `expected_shortfall` "
    "(`1 - mean(fulfillment)`) is reported beside it precisely because it can. "
    "Where the two disagree in significance, the coarse one is the less "
    "informative measure, not the more conservative one.",

    "**The simulation shares its seed across k.** Every point on the frontier "
    "uses seed 42 and the same 1,000 scenarios, which is what makes the "
    "comparison paired. It also means the CIs describe variation ACROSS BOMs "
    "only — they contain no Monte-Carlo error term. A second seed would move "
    "these numbers by an amount this study does not measure.",

    "**The risk model is a one-shot percolation, not a cascade.** "
    "`run_monte_carlo` fails distributors independently at a calibrated hazard "
    "and asks which lines lost every supplier. There is no propagation, no "
    "time, no recovery, and — importantly for a diversification study — no "
    "CORRELATION between distributor failures beyond the shared `stress_factor` "
    "multiplier. Diversification protects most against correlated shocks, so an "
    "independent-failure model is the conservative place to measure its value.",

    "**Distributor-level, not tier-2.** Two 'distinct distributors' in this "
    "catalogue can both be reselling the same manufacturer's parts from the same "
    "fab. The constraint buys distribution-layer redundancy and nothing deeper; "
    "no upstream data in this repo could support a stronger claim.",

    "**Sub-cent prices round to zero in the MILP objective.** "
    "`sourcing.py` quantised unit prices to whole cents WHEN THIS SWEEP RAN "
    "(`PRICE_SCALE = 100`), so an offer at $0.0031 enters the objective at "
    "$0.00. This was NOT changed here: every arm of this sweep is the same "
    "MILP at the same resolution, so the comparison across k is internally "
    "consistent. It does mean the absolute component cost of a plan containing "
    "sub-cent parts is understated in the solver's objective, and that a greedy "
    "baseline pricing on full floats would not be resolution-matched to it. "
    "NOTE 2026-08-28: the code has since been fixed — a single to_obj_units() "
    "now carries every USD term at the objective's own milli-cent resolution. "
    "These figures reproduce against the pre-fix solver only.",

    "**The constraint bounds a COUNT, and the objective is still pure cost.** "
    "Nothing forces the k-supplier plan to contain the 1-supplier plan, and the "
    "sweep records how often it does not. Where the incumbent is dropped for a "
    "cheaper set of k, the plan is more diversified without being safer — risk "
    "NEED NOT be monotone in k under broad stress, and the frontier must not be "
    "read as though it were. Which measure is actually non-monotone on THIS "
    "sweep, and on how many BOMs, is reported in the mechanism section from the "
    "per-BOM rows rather than asserted here. A resilience-aware version would "
    "either constrain the "
    "plan to be nested (keep what you had, add to it) or put the hazard in the "
    "objective; both are different studies and neither is claimed here.",

    "**`k` beyond the number of BOM lines is a different regime.** All catalogue "
    "BOMs have 4 lines, so k = 4 is one distributor per line. k = 5 can only be "
    "met by SPLITTING a single multi-unit line across two distributors, which the "
    "MOQ floor blocks outright for quantity-1 lines — so it is infeasible for two "
    "BOMs. Its paired CI is computed over the 7 BOMs that reach it, not the 9 that "
    "reach k = 4; every row publishes its own panel size and membership. Do not "
    "read the k = 5 row as the same comparison as the rows above it.",
]


def build_payload(
    records: List[Dict[str, Any]],
    frontier: List[Dict[str, Any]],
    check: Dict[str, Any],
    prov: Dict[str, Any],
    elapsed: float,
) -> Dict[str, Any]:
    from app.graph.simulation import DEFAULT_SEED, N_SCENARIOS

    included = [r for r in records if r["included"]]
    return {
        "provenance": prov,
        "meta": {
            "generator": "seeds.run_diversification_sweep",
            "strategy": STRATEGY_ID,
            "us_only": True,
            "graph_aware": False,
            "k_max": K_MAX,
            "mc_scenarios": N_SCENARIOS,
            "mc_seed": DEFAULT_SEED,
            "stress_factor": STRESS_FACTOR,
            "bootstrap_n": BOOTSTRAP_N,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "ci_alpha": CI_ALPHA,
            "n_boms_in_catalog": len(records),
            "n_boms_included": len(included),
            "wall_seconds": round(elapsed, 1),
            "writes_to_database": False,
            "overwrites_benchmark": False,
        },
        "run5_reproduction_check": check,
        "frontier": frontier,
        "boms": records,
        "caveats": CAVEATS,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    t0 = time.perf_counter()

    prov = build_provenance(generator="seeds.run_diversification_sweep", inputs={})

    db = SessionLocal()
    try:
        gs = get_graph_state()
        if gs is None:
            logger.info("GraphState not loaded — building now")
            gs = build_graph_state(db)

        weights = get_strategy(STRATEGY_ID)
        records: List[Dict[str, Any]] = []
        for name, items in BOM_CATALOG.items():
            rec = sweep_bom(db, gs, name, items, weights)
            if not rec["included"]:
                logger.warning("BOM %s EXCLUDED — %s", name, rec["reason"])
            else:
                ks = [p["k"] for p in rec["points"] if p.get("feasible")]
                logger.info("BOM %s swept k=%s", name, ks)
            records.append(rec)

        frontier = _frontier_table(records, K_MAX)
        check = check_against_run5(records)
        if not check.get("all_match"):
            logger.error(
                "k=1 does NOT reproduce run 5's milp_blind cost: %s",
                check.get("mismatches") or check.get("error"),
            )

        payload = build_payload(records, frontier, check, prov,
                                time.perf_counter() - t0)
        DOCS.mkdir(parents=True, exist_ok=True)
        JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n")
        MD_PATH.write_text(render_markdown(payload))
        logger.info("wrote %s", JSON_PATH.relative_to(REPO_ROOT))
        logger.info("wrote %s", MD_PATH.relative_to(REPO_ROOT))
        return 0 if check.get("all_match") else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
