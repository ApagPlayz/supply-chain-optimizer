"""
Volume sweep — does the MILP's cost advantage over greedy survive at production scale?

WHY THIS EXISTS
---------------
The portfolio benchmark (`seeds/run_benchmark.py`) reports the CP-SAT MILP as
~44.7% cheaper than a naive greedy baseline on 10 hand-crafted BOMs. That number
is suspicious by construction:

  * The greedy baseline picks min(price_usd) per BOM line, so it is the
    component-cost minimum. The MILP can never beat it on component cost.
  * Therefore 100% of the MILP's "win" comes from FIXED, per-supplier charges —
    dominated by LTL_BASE_FEE_USD = $75 (constants.py) and AIR_FREIGHT_BASE_USD
    = $150, each multiplied by the strategy's transport_penalty_scale.
  * The benchmark BOMs are toys: 4 lines, quantities 1-4 (5-8 total units). On a
    BOM whose components cost tens of dollars, consolidating 3 suppliers into 1
    "saves" a few hundred dollars of fees. That is fee arithmetic, not
    optimization.

This script measures savings as a FUNCTION OF VOLUME, decomposes the cost delta
by source, and writes the result out honestly — whatever it says.

WHAT IT DOES
------------
For each reference BOM in run_benchmark.BOM_CATALOG, for each volume multiplier
m, it scales every line quantity by m and solves three arms:

  greedy        — solve_sourcing_greedy, us_only=False   (the published baseline)
  milp_matched  — solve_sourcing,        us_only=False   (PRIMARY, fair comparison)
  milp_bench    — solve_sourcing,        us_only=True    (reproduces the published
                                                          benchmark's MILP arm, which
                                                          is domestic-only because
                                                          balanced.us_only_sourcing=True
                                                          while greedy is called with
                                                          us_only=False)

ANTI-RIGGING
------------
Every arm is scored through the SAME `landed_cost_breakdown` from greedy.py, which
itself calls the MILP's own `_transport_cost_by_did`. No cost model is
reimplemented here. Greedy and the MILP are not modified. The only thing this
script adds is a *decomposition* of the already-computed transport term into its
fixed-base and weight/distance-variable parts, using the same constants the cost
model uses.

The primary comparison (greedy vs milp_matched) deliberately gives BOTH arms the
same offer pool (us_only=False), which the published benchmark does NOT do.

THE DUPLICATE-OFFER BUG (found while building this)
---------------------------------------------------
`solve_sourcing` keys its CP-SAT decision variables on (component_id,
distributor_id). The offer table has 509 duplicated (component, distributor)
pairs — price-break tiers from the same distributor. When a distributor has k
offers for one component, the same q[key] variable is created k times (the last
wins) and then:

  * summed k times in the demand constraint  ->  k*q == demand, which is
    INFEASIBLE whenever demand % k != 0 (spurious MILP infeasibility), and
  * priced k times in the objective          ->  the distributor's unit price is
    charged as the SUM of its k tier prices (e.g. PCM4202DBT at distributor 28
    costs $11.35+$11.35+$7.28 = $29.98/unit in the model instead of $7.28).

The greedy baseline is NOT affected — it scans a flat offer list and takes
min(price). So on any BOM touching a duplicated pair, the MILP is competing with
a corrupted model and can LOSE to greedy. That is a bug artifact, not a finding,
and it must not be reported as one.

This script therefore sweeps TWO offer pools and reports both:

  deduped (PRIMARY) — one offer per (component, distributor): the cheapest, which
                      is all the MILP's variable keying can represent. Applied
                      IDENTICALLY to both arms, so it cannot rig the comparison.
  raw               — the pool exactly as the shipped code sees it, bug active.

We do NOT patch sourcing.py here: fixing the solver to make the MILP look better
is exactly the kind of thing this exercise exists to catch. The bug is reported,
not quietly repaired.

FEASIBILITY
-----------
Stock is a hard cap in the MILP (q <= stock). We compute each BOM's maximum
feasible multiplier from total available stock per line and only sweep within it.
The greedy baseline has a fallback that lets it "buy" more than an offer's stock;
we detect and flag that (`greedy_stock_violation`) rather than letting greedy win
on a physically impossible plan.

OUTPUTS
-------
  docs/volume_sweep.json          machine-readable, full per-BOM/per-m results
  docs/BENCHMARK_VOLUME_CURVE.md  the human writeup

Invocation:  python -m seeds.run_volume_sweep      (from backend/, venv active)
"""
from __future__ import annotations

import json
import logging
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.optimization.constants import (
    AIR_FREIGHT_BASE_USD,
    AIR_FREIGHT_RATE_USD_PER_KG,
    CWT_PER_LB,
    KM_PER_MILE,
    LBS_PER_KG,
    LTL_BASE_FEE_USD,
    LTL_RATE_USD_PER_CWT_MILE,
)
from app.optimization.greedy import landed_cost_breakdown, solve_sourcing_greedy
from app.optimization.sourcing import (
    BomLine,
    Offer,
    SourcingAssignment,
    SourcingResult,
    filter_price_outliers,
    solve_sourcing,
)
from app.optimization.strategies import get_strategy

from seeds.run_benchmark import BOM_CATALOG, DEPOT, _load_offers_for_bom

logger = logging.getLogger(__name__)

REPO_ROOT = BACKEND_ROOT.parent
DOCS = REPO_ROOT / "docs"

# Log-spaced volume grid. Trimmed per-BOM to that BOM's feasibility ceiling.
MULTIPLIERS: List[int] = [1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]

STRATEGY_ID = "balanced"

# The MILP's own CP-SAT time limit (sourcing.py sets max_time_in_seconds=5.0,
# num_search_workers=1). We do not change it; we only record whether a solve
# came back OPTIMAL or merely FEASIBLE (i.e. it hit the limit).
SOLVER_TIME_LIMIT_S = 5.0


# ── Decomposition ────────────────────────────────────────────────────────────

def _decompose(
    assignments: List[SourcingAssignment],
    offers: List[Offer],
    bom: List[BomLine],
    weights,
) -> dict:
    """
    Score an assignment set with the shared landed_cost_breakdown, then split the
    already-computed `transport_fixed` term into:

      fixed_fee_usd    — the per-supplier BASE charge that does NOT scale with
                         volume: penalty_scale x $75 (domestic LTL) or
                         penalty_scale x $150 (international air), per supplier.
                         THIS is the term the MILP's whole advantage rides on.
      freight_var_usd  — the remainder of the transport term: the weight x
                         distance component, which DOES scale with volume.

    plus the consolidation_charge (also per-supplier, flat) and component cost.
    The three fee-ish terms + component cost sum exactly to breakdown total_cost.
    """
    bd = landed_cost_breakdown(assignments, offers, bom, weights)
    penalty = getattr(weights, "transport_penalty_scale", 1.0)

    domestic_by_did = {o.distributor_id: o.is_domestic for o in offers}
    used_dids = sorted({a.distributor_id for a in assignments if a.quantity > 0})

    fixed_fee = 0.0
    for did in used_dids:
        base = LTL_BASE_FEE_USD if domestic_by_did.get(did, True) else AIR_FREIGHT_BASE_USD
        fixed_fee += base * penalty

    transport_total = float(bd["transport_fixed"])
    freight_var = transport_total - fixed_fee

    # Physical-feasibility check: did any assignment order more than the chosen
    # offer actually has in stock? The MILP cannot do this (q <= stock is hard);
    # greedy's fallback can.
    stock_by = {(o.component_id, o.distributor_id): o.stock for o in offers}
    violations = [
        {
            "mpn": a.mpn,
            "distributor_id": a.distributor_id,
            "quantity": a.quantity,
            "stock": stock_by.get((a.component_id, a.distributor_id), 0),
        }
        for a in assignments
        if a.quantity > stock_by.get((a.component_id, a.distributor_id), 0)
    ]

    return {
        "total_cost": round(float(bd["total_cost"]), 2),
        "component_cost": round(float(bd["component_cost"]), 2),
        "transport_total": round(transport_total, 2),
        "fixed_fee_usd": round(fixed_fee, 2),
        "freight_var_usd": round(freight_var, 2),
        "consolidation_charge": round(float(bd["consolidation_charge"]), 2),
        "n_distinct_suppliers": int(bd["n_distinct_suppliers"]),
        "n_lines_split": sum(
            1 for cid in {a.component_id for a in assignments}
            if len([a for a in assignments if a.component_id == cid]) > 1
        ),
        "stock_violations": violations,
        "selected_distributor_ids": used_dids,
    }


# ── Counterfactual: freight allocated by ACTUAL shipped weight ──────────────
# DIAGNOSTIC ONLY. This does not change the production cost model and is not used
# to score the primary comparison — it exists to answer one question honestly:
# "once the per-supplier charging artifacts are removed, does the MILP have ANY
# cost edge left at scale?"
#
# The shipped model (_transport_cost_by_did) charges every opened supplier freight
# for a REPRESENTATIVE FULL-BOM shipment (avg BOM line demand x kg/unit), no matter
# how little that supplier actually ships. Splitting a BOM across 3 suppliers
# therefore TRIPLES the variable freight instead of dividing it among them, which
# hands the consolidating MILP a wedge that never decays with volume.
#
# Here we instead allocate freight by what each supplier actually ships:
#   freight_d = penalty x (base_fee_d + rate x actual_weight_shipped_from_d x distance_d)
# The per-stop base fee is KEPT (that part is real — every shipment has a minimum
# charge). Applied identically to both arms, so it cannot bias the comparison.

AVG_KG_PER_UNIT = 0.05  # same value _transport_cost_by_did uses


def _weight_allocated_total(
    assignments: List[SourcingAssignment],
    offers: List[Offer],
    weights,
) -> dict:
    """Total landed cost under weight-allocated (rather than per-supplier-replicated)
    variable freight. Diagnostic counterfactual — see comment above."""
    penalty = getattr(weights, "transport_penalty_scale", 1.0)
    consolidation_bonus = getattr(weights, "consolidation_bonus_usd", 1.0)

    km_by_did = {o.distributor_id: o.dist_km_from_depot for o in offers}
    dom_by_did = {o.distributor_id: o.is_domestic for o in offers}

    component_cost = sum(a.quantity * a.unit_price_usd for a in assignments)

    kg_by_did: Dict[int, float] = {}
    for a in assignments:
        if a.quantity > 0:
            kg_by_did[a.distributor_id] = (
                kg_by_did.get(a.distributor_id, 0.0) + a.quantity * AVG_KG_PER_UNIT
            )

    base_total = 0.0
    var_total = 0.0
    for did, kg in kg_by_did.items():
        km = km_by_did.get(did, 0.0)
        if dom_by_did.get(did, True):
            base = LTL_BASE_FEE_USD
            var = (kg * LBS_PER_KG * CWT_PER_LB) * (km / KM_PER_MILE) * LTL_RATE_USD_PER_CWT_MILE
        else:
            base = AIR_FREIGHT_BASE_USD
            var = kg * AIR_FREIGHT_RATE_USD_PER_KG
        base_total += base * penalty
        var_total += var * penalty

    consolidation = consolidation_bonus * len(kg_by_did)
    return {
        "total_cost": round(component_cost + base_total + var_total + consolidation, 2),
        "component_cost": round(component_cost, 2),
        "fixed_fee_usd": round(base_total, 2),
        "freight_var_usd": round(var_total, 2),
        "consolidation_charge": round(consolidation, 2),
    }


# ── Offer-pool de-duplication (see module docstring) ────────────────────────

def _dedupe_offers(offers: List[Offer]) -> Tuple[List[Offer], int]:
    """
    Collapse the offer pool to one offer per (component_id, distributor_id) —
    keeping the CHEAPEST, which is both what greedy would pick anyway and the
    only thing solve_sourcing's variable keying can actually represent.

    Applied identically to every arm, so it cannot bias the MILP-vs-greedy
    comparison. Returns (deduped_offers, n_pairs_that_had_duplicates).
    """
    best: Dict[Tuple[int, int], Offer] = {}
    dup_pairs = set()
    for o in offers:
        key = (o.component_id, o.distributor_id)
        if key in best:
            dup_pairs.add(key)
            if o.price_usd < best[key].price_usd:
                best[key] = o
        else:
            best[key] = o
    return list(best.values()), len(dup_pairs)


# ── Feasibility ceiling ──────────────────────────────────────────────────────

def _max_feasible_multiplier(
    bom: List[BomLine], offers: List[Offer], us_only: bool
) -> int:
    """
    Upper bound on m from stock alone: for each BOM line, total stock across all
    surviving offers for that component / line quantity. The binding line sets
    the ceiling. (MOQ can still make a particular m infeasible; the solver tells
    us that at solve time and we record it.)
    """
    kept, _drops = filter_price_outliers(offers, bom)
    if us_only:
        kept = [o for o in kept if o.is_domestic]

    ceiling = None
    for b in bom:
        total_stock = sum(o.stock for o in kept if o.component_id == b.component_id)
        if b.quantity <= 0:
            continue
        line_max = total_stock // b.quantity
        ceiling = line_max if ceiling is None else min(ceiling, line_max)
    return int(ceiling or 0)


# ── One (BOM, m) point ───────────────────────────────────────────────────────

def _solve_arm(
    kind: str,
    bom: List[BomLine],
    offers: List[Offer],
    weights,
    us_only: bool,
) -> Tuple[Optional[SourcingResult], float, Optional[str]]:
    t0 = time.perf_counter()
    try:
        if kind == "greedy":
            res = solve_sourcing_greedy(bom, offers, weights, us_only=us_only)
        else:
            res = solve_sourcing(
                bom, offers, weights,
                us_only=us_only, graph_aware=False, require_dual_source=False,
            )
    except Exception as exc:  # infeasible / no offers after filtering
        return None, time.perf_counter() - t0, f"{type(exc).__name__}: {exc}"
    return res, time.perf_counter() - t0, None


def _run_point(
    bom_name: str,
    base_items: List[Tuple[str, int]],
    bom: List[BomLine],
    offers: List[Offer],
    weights,
    m: int,
) -> dict:
    scaled = [BomLine(b.component_id, b.mpn, b.quantity * m) for b in bom]
    total_units = sum(b.quantity for b in scaled)

    point: dict = {"multiplier": m, "total_units": total_units, "arms": {}}

    specs = (
        ("greedy", "greedy", False),
        ("milp_matched", "milp", False),
        ("milp_bench", "milp", True),
    )
    for arm_id, kind, us_only in specs:
        res, secs, err = _solve_arm(kind, scaled, offers, weights, us_only)
        if res is None:
            point["arms"][arm_id] = {
                "feasible": False, "error": err, "solve_seconds": round(secs, 3),
            }
            continue
        dec = _decompose(res.assignments, offers, scaled, weights)
        dec.update({
            "feasible": True,
            "solver_status": res.status,          # OPTIMAL / FEASIBLE / GREEDY
            "hit_time_limit": res.status == "FEASIBLE",
            "solve_seconds": round(secs, 3),
            "us_only": us_only,
            # Diagnostic counterfactual — NOT the production cost model.
            "weight_allocated_freight": _weight_allocated_total(
                res.assignments, offers, weights,
            ),
        })
        point["arms"][arm_id] = dec

    g = point["arms"]["greedy"]
    for milp_id in ("milp_matched", "milp_bench"):
        mm = point["arms"][milp_id]
        if not (g.get("feasible") and mm.get("feasible")):
            continue
        delta = g["total_cost"] - mm["total_cost"]
        fee_delta = (
            (g["fixed_fee_usd"] + g["consolidation_charge"])
            - (mm["fixed_fee_usd"] + mm["consolidation_charge"])
        )
        comp_delta = g["component_cost"] - mm["component_cost"]
        var_delta = g["freight_var_usd"] - mm["freight_var_usd"]
        point[f"vs_{milp_id}"] = {
            "abs_saving_usd": round(delta, 2),
            "saving_pct": round(delta / g["total_cost"] * 100.0, 3) if g["total_cost"] else 0.0,
            "saving_from_fixed_fees_usd": round(fee_delta, 2),
            "saving_from_component_cost_usd": round(comp_delta, 2),
            "saving_from_variable_freight_usd": round(var_delta, 2),
            "fixed_fee_share_of_saving": (
                round(fee_delta / delta, 4) if abs(delta) > 1e-9 else None
            ),
            "suppliers_greedy": g["n_distinct_suppliers"],
            "suppliers_milp": mm["n_distinct_suppliers"],
        }
        # Diagnostic counterfactual: same comparison, but with variable freight
        # allocated by actual shipped weight instead of replicated per supplier.
        gw = g["weight_allocated_freight"]["total_cost"]
        mw = mm["weight_allocated_freight"]["total_cost"]
        point[f"vs_{milp_id}"]["weight_allocated_saving_pct"] = (
            round((gw - mw) / gw * 100.0, 3) if gw else 0.0
        )
    return point


# ── Driver ───────────────────────────────────────────────────────────────────

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    started = datetime.now(timezone.utc)
    t_start = time.perf_counter()

    weights = get_strategy(STRATEGY_ID)
    db = SessionLocal()
    results: Dict[str, dict] = {}
    try:
        for bom_name, items in BOM_CATALOG.items():
            bom, raw_offers, _meta = _load_offers_for_bom(db, items)
            if not bom or not raw_offers:
                logger.warning("%s: no bom/offers — skipping", bom_name)
                results[bom_name] = {"skipped": "no offers"}
                continue

            deduped, n_dup_pairs = _dedupe_offers(raw_offers)

            entry: dict = {
                "base_items": [{"mpn": m_, "quantity": q} for m_, q in items],
                "base_total_units": sum(b.quantity for b in bom),
                "n_offers_raw": len(raw_offers),
                "n_offers_deduped": len(deduped),
                "n_duplicate_cid_did_pairs": n_dup_pairs,
            }

            for pool_name, pool in (("deduped", deduped), ("raw", raw_offers)):
                ceil_all = _max_feasible_multiplier(bom, pool, us_only=False)
                ceil_dom = _max_feasible_multiplier(bom, pool, us_only=True)
                grid = [m for m in MULTIPLIERS if m <= ceil_all] or [1]

                if pool_name == "deduped":
                    logger.info(
                        "%s: base units=%d  dup_pairs=%d  stock ceiling m<=%d "
                        "(domestic-only m<=%d)  grid=%s",
                        bom_name, sum(b.quantity for b in bom), n_dup_pairs,
                        ceil_all, ceil_dom, grid,
                    )

                points = []
                for m in grid:
                    p = _run_point(bom_name, items, bom, pool, weights, m)
                    points.append(p)
                    if pool_name == "deduped":
                        s = p.get("vs_milp_matched")
                        logger.info(
                            "  %s m=%-5d units=%-6d greedy=$%-12s milp=$%-12s save=%s%s",
                            bom_name, m, p["total_units"],
                            p["arms"]["greedy"].get("total_cost", "INFEAS"),
                            p["arms"]["milp_matched"].get("total_cost", "INFEAS"),
                            f"{s['saving_pct']:+.2f}%" if s else "n/a",
                            "  [greedy plan exceeds stock — not physically realizable]"
                            if p["arms"]["greedy"].get("stock_violations") else "",
                        )

                suffix = "" if pool_name == "deduped" else "_raw_pool"
                entry[f"stock_ceiling_multiplier_all_offers{suffix}"] = ceil_all
                entry[f"stock_ceiling_multiplier_domestic_only{suffix}"] = ceil_dom
                entry[f"points{suffix}"] = points

            results[bom_name] = entry
    finally:
        db.close()

    elapsed = time.perf_counter() - t_start

    payload = {
        "meta": {
            "generated_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hardware": f"{platform.machine()} / {platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "wall_seconds": round(elapsed, 1),
            "strategy": STRATEGY_ID,
            "strategy_weights": {
                "w_cost": weights.w_cost, "w_time": weights.w_time,
                "w_carbon": weights.w_carbon,
                "transport_penalty_scale": weights.transport_penalty_scale,
                "consolidation_bonus_usd": weights.consolidation_bonus_usd,
                "us_only_sourcing_default": weights.us_only_sourcing,
            },
            "solver": {
                "engine": "OR-Tools CP-SAT",
                "max_time_in_seconds": SOLVER_TIME_LIMIT_S,
                "num_search_workers": 1,
            },
            "cost_constants": {
                "LTL_BASE_FEE_USD": LTL_BASE_FEE_USD,
                "AIR_FREIGHT_BASE_USD": AIR_FREIGHT_BASE_USD,
            },
            "depot": {"lat": DEPOT.lat, "lng": DEPOT.lng},
            "multiplier_grid": MULTIPLIERS,
            "arms": {
                "greedy": "solve_sourcing_greedy, us_only=False (as published benchmark)",
                "milp_matched": "solve_sourcing, us_only=False — PRIMARY fair comparison",
                "milp_bench": "solve_sourcing, us_only=True — reproduces published benchmark MILP arm",
            },
            "offer_pools": {
                "deduped": "PRIMARY. One offer per (component_id, distributor_id) — the "
                           "cheapest. This is all solve_sourcing's variable keying can "
                           "represent. Applied identically to every arm. Results live in "
                           "boms.<name>.points.",
                "raw": "The pool exactly as the shipped code sees it, with the "
                       "duplicate-offer bug active. Results live in "
                       "boms.<name>.points_raw_pool.",
            },
            "known_bug": {
                "where": "backend/app/optimization/sourcing.py, _build_and_solve()",
                "what": "CP-SAT decision variables x/q are keyed on (component_id, "
                        "distributor_id), but the offer table has duplicated pairs "
                        "(price-break tiers). Duplicates overwrite the variable, are "
                        "summed k times in the demand constraint (k*q == demand -> "
                        "spurious INFEASIBLE when demand % k != 0), and are priced k "
                        "times in the objective (unit price charged as the SUM of the "
                        "k tier prices).",
                "impact": "The MILP competes with a corrupted model and can lose to "
                          "greedy. Greedy is unaffected. NOT patched here by design — "
                          "this sweep reports the bug rather than quietly repairing it.",
            },
            "notes": [
                "All arms scored through the same landed_cost_breakdown().",
                "The cost model has NO holding-cost term; decomposition is "
                "component / fixed per-supplier fee / variable freight / consolidation charge.",
                "greedy's fallback can order above an offer's stock; such plans are "
                "flagged in arms.greedy.stock_violations and are physically infeasible. "
                "Points so flagged must NOT be counted as greedy wins.",
            ],
        },
        "boms": results,
    }

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "volume_sweep.json").write_text(json.dumps(payload, indent=2) + "\n")
    logger.info("wrote docs/volume_sweep.json  (%.1fs total)", elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
