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
itself calls the MILP's own `_freight_model_by_did`. No cost model is
reimplemented here. The only thing this script adds is a *report* of the
already-computed fixed / variable freight split.

FREIGHT MODEL FIX (2026-07-13)
------------------------------
Earlier runs of this sweep were distorted by a bug in the shared freight helper:
it computed ONE representative shipment weight for the whole BOM and charged that
full weight to EVERY opened supplier. Splitting a BOM across 3 suppliers was
therefore billed 3x a full BOM's variable freight instead of one BOM's freight
divided among 3 shipments — a permanent, volume-scaling penalty on splitting that
inflated the consolidating MILP's edge. Freight is now `fixed[d] * opened(d) +
per_unit[d] * units_actually_shipped_from(d)` in BOTH arms.

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
  docs/volume_sweep.json          machine-readable, full per-BOM/per-m results,
                                  stamped with a `provenance` block (git SHA + the
                                  sha256 of the sqlite snapshot it read)
  docs/BENCHMARK_VOLUME_CURVE.md  the human writeup. Mostly hand-written argument,
                                  so only the numeric regions are regenerated — see
                                  "the INVERTED curated-region technique" below.

Invocation:  python -m seeds.run_volume_sweep      (from backend/, venv active)
"""
from __future__ import annotations

import json
import logging
import platform
import re
import sys
import textwrap
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.optimization.constants import (  # noqa: E402
    AIR_FREIGHT_BASE_USD,
    LTL_BASE_FEE_USD,
)
from app.optimization.greedy import landed_cost_breakdown, solve_sourcing_greedy  # noqa: E402
from app.optimization.sourcing import (  # noqa: E402
    BomLine,
    Offer,
    SourcingAssignment,
    SourcingResult,
    filter_price_outliers,
    solve_sourcing,
)
from app.optimization.strategies import get_strategy  # noqa: E402

from seeds.provenance import build_provenance, provenance_markdown  # noqa: E402
from seeds.run_benchmark import BOM_CATALOG, DEPOT, _load_offers_for_bom  # noqa: E402

logger = logging.getLogger(__name__)

REPO_ROOT = BACKEND_ROOT.parent
DOCS = REPO_ROOT / "docs"
DOC_PATH = DOCS / "BENCHMARK_VOLUME_CURVE.md"

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
    Score an assignment set with the shared landed_cost_breakdown and surface its
    two freight components separately:

      fixed_fee_usd    — the per-supplier BASE charge that does NOT scale with
                         volume: penalty_scale x $75 (domestic LTL) or
                         penalty_scale x $150 (international air), per supplier.
                         THIS is the term the MILP's advantage rides on.
      freight_var_usd  — the weight x distance component, charged on the units
                         each supplier ACTUALLY ships. Scales with volume, and is
                         allocated across suppliers rather than replicated per
                         supplier (see the freight-model fix in sourcing.py).

    plus the consolidation_charge (also per-supplier, flat) and component cost.
    The four terms sum exactly to breakdown total_cost — no reimplementation here.
    """
    bd = landed_cost_breakdown(assignments, offers, bom, weights)

    fixed_fee = float(bd["transport_fixed"])
    freight_var = float(bd["transport_variable"])
    transport_total = float(bd["transport_total"])

    used_dids = sorted({a.distributor_id for a in assignments if a.quantity > 0})

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


# NOTE (2026-07-13): this script used to carry a "weight-allocated freight"
# counterfactual here, because the SHIPPED cost model charged every opened
# supplier freight for a representative FULL-BOM shipment regardless of how little
# that supplier actually shipped — replicating variable freight per supplier
# instead of allocating it, which over-penalised splitting and handed the
# consolidating MILP a wedge that never decayed with volume.
#
# That bug is now FIXED in the production model (sourcing.py:_freight_model_by_did
# → fixed per-visit fee + per-unit rate on units actually shipped), so the
# counterfactual would be a byte-for-byte duplicate of the real cost model and has
# been removed. The sweep below now measures the corrected model directly.


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
    return point


# ── Markdown regeneration: the INVERTED curated-region technique ─────────────
#
# docs/BENCHMARK_VOLUME_CURVE.md is mostly hand-written argument — a retraction
# narrative with caveats that no generator should ever be allowed to author. Only
# a handful of interleaved numeric blocks come from this sweep. So the polarity of
# the usual "generated file with a few curated islands" is INVERTED: the *generated*
# regions are the ones marked, and everything outside a marker pair is curated prose
# that must survive byte-for-byte.
#
#     <!-- GENERATED:volume_curve:BEGIN -->
#     ...only this text is rewritten...
#     <!-- GENERATED:volume_curve:END -->
#
# A missing marker pair is a warning, never a crash: a fresh checkout of the doc (or
# a prose edit that dropped a marker) still gets a valid JSON artifact and a loud log
# line naming the block that could not be refreshed.
#
# Aggregate definition used by EVERY number below: POOLED — sum(greedy) / sum(MILP)
# over the BOMs feasible at that multiplier, never a mean of per-BOM percentages, and
# always excluding points where greedy's plan orders more units than exist.

MINUS = "−"  # U+2212 MINUS SIGN — the doc renders negative money with this

# Volume at and above which the sweep is described as "production volume".
PRODUCTION_FLOOR = 500

# Pooled saving % from the PRE-FIX run, when variable freight was replicated per
# supplier instead of allocated across them. Historical: it cannot be regenerated
# from today's (corrected) code, so it is pinned here rather than recomputed, and
# the "what the fix changed" table pairs it against live numbers.
BUGGY_FREIGHT_POOLED_PCT: Dict[int, float] = {
    1: 47.66, 10: 24.75, 50: 8.32, 250: 6.66, 1000: 2.78, 5000: 2.40, 10000: 3.49,
}


def _neg(text: str) -> str:
    """Render a formatted number with the doc's unicode minus instead of a hyphen."""
    return text.replace("-", MINUS)


def _wrap(paragraph: str, width: int = 100) -> str:
    """
    Re-flow one paragraph to the doc's ~100-column hand-wrapped prose style.

    Used for the generated paragraphs whose length moves with the data (a cohort
    gaining a BOM lengthens the sentence); paragraphs with stable length keep their
    hand-placed line breaks so the diff of a re-run stays readable.
    """
    return textwrap.fill(
        " ".join(paragraph.split()),
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )


def _signed_usd(v: float) -> str:
    """`+$3,863` / `−$561` — signed whole dollars, as the decomposition columns use."""
    return f"{'+' if v >= 0 else MINUS}${abs(v):,.0f}"


def _mult(m: int) -> str:
    return f"{m:,}×"


def _pct_or_zero(v: float, places: int = 0) -> str:
    """Percent string that never renders a signed zero (`−0%` is nonsense)."""
    s = f"{v:.{places}f}"
    if float(s) == 0.0:
        s = f"{0.0:.{places}f}"
    return _neg(s) + "%"


def _database_file() -> Optional[Path]:
    """
    Filesystem path of the sqlite file this sweep read, per settings.DATABASE_URL.

    That database IS the input data for every number in the artifact, so it is what
    provenance hashes — two runs with the same sha256 here are comparable, two runs
    with different ones are not, whatever the git SHA says.
    """
    url = settings.DATABASE_URL
    if not url.startswith("sqlite"):
        return None
    raw = url.split("///", 1)[-1]
    p = Path(raw)
    if not p.is_absolute():
        p = (BACKEND_ROOT / raw).resolve()
    return p


# ── Aggregation ──────────────────────────────────────────────────────────────

def _pooled_rows(boms: Dict[str, dict]) -> List[dict]:
    """
    One pooled row per multiplier, over the PRIMARY (deduped) offer pool and the
    PRIMARY (`milp_matched`) arm.

    Excluded from every row: points whose greedy plan has `stock_violations` — greedy
    cannot be allowed to "win" with a plan that orders more units than exist.
    """
    rows: List[dict] = []
    for m in MULTIPLIERS:
        greedy = milp = fee = comp = var = 0.0
        sup_g = sup_m = 0
        members: List[Tuple[str, float]] = []
        units: List[int] = []
        for name, b in boms.items():
            for p in b.get("points") or []:
                if p.get("multiplier") != m:
                    continue
                arms = p.get("arms") or {}
                g = arms.get("greedy") or {}
                mm = arms.get("milp_matched") or {}
                s = p.get("vs_milp_matched")
                if not (g.get("feasible") and mm.get("feasible") and s):
                    continue
                if g.get("stock_violations"):
                    continue
                greedy += float(g["total_cost"])
                milp += float(mm["total_cost"])
                fee += float(s["saving_from_fixed_fees_usd"])
                comp += float(s["saving_from_component_cost_usd"])
                var += float(s["saving_from_variable_freight_usd"])
                sup_g += int(s["suppliers_greedy"])
                sup_m += int(s["suppliers_milp"])
                members.append((name, float(s["saving_pct"])))
                units.append(int(p["total_units"]))
        if not members:
            continue
        rows.append({
            "m": m,
            "n": len(members),
            "greedy": greedy,
            "milp": milp,
            "delta": greedy - milp,
            "pct": (greedy - milp) / greedy * 100.0 if greedy else 0.0,
            "fee": fee,
            "comp": comp,
            "var": var,
            "sup_greedy": sup_g,
            "sup_milp": sup_m,
            "members": sorted(members, key=lambda t: -t[1]),
            "units_min": min(units),
            "units_max": max(units),
        })
    return rows


def _row_at(rows: List[dict], m: int) -> Optional[dict]:
    for r in rows:
        if r["m"] == m:
            return r
    return None


def _points_at(boms: Dict[str, dict], m: int) -> List[dict]:
    """Per-BOM records at one multiplier, same exclusion rule as `_pooled_rows`."""
    out: List[dict] = []
    for name, b in boms.items():
        for p in b.get("points") or []:
            if p.get("multiplier") != m:
                continue
            arms = p.get("arms") or {}
            g = arms.get("greedy") or {}
            mm = arms.get("milp_matched") or {}
            s = p.get("vs_milp_matched")
            if not (g.get("feasible") and mm.get("feasible") and s):
                continue
            if g.get("stock_violations"):
                continue
            out.append({"name": name, "point": p, "greedy": g, "milp": mm, "vs": s})
    return out


def _solver_counts(boms: Dict[str, dict]) -> Dict[str, int]:
    """MILP solve attempts across BOTH offer pools and BOTH MILP arms."""
    counts = {"attempts": 0, "feasible": 0, "optimal": 0, "hit_limit": 0, "infeasible": 0}
    for b in boms.values():
        for key in ("points", "points_raw_pool"):
            for p in b.get(key) or []:
                for arm in ("milp_matched", "milp_bench"):
                    a = (p.get("arms") or {}).get(arm)
                    if a is None:
                        continue
                    counts["attempts"] += 1
                    if not a.get("feasible"):
                        counts["infeasible"] += 1
                        continue
                    counts["feasible"] += 1
                    if a.get("solver_status") == "OPTIMAL":
                        counts["optimal"] += 1
                    if a.get("hit_time_limit"):
                        counts["hit_limit"] += 1
    return counts


# ── Block renderers (one per marked region in the doc) ───────────────────────

def _md_header_meta(meta: dict, prov: Mapping[str, Any], n_boms: int) -> str:
    solver = meta["solver"]
    return "\n".join([
        f"**Generated:** {str(prov.get('generated_at_utc', ''))[:10]} · "
        f"**Script:** `backend/seeds/run_volume_sweep.py` · **Data:** `docs/volume_sweep.json`",
        f"**Hardware:** {meta['hardware']} · **Solver:** {solver['engine']}, "
        f"`num_search_workers={solver['num_search_workers']}`, {solver['max_time_in_seconds']:g}s limit",
        f"**Runtime:** {meta['wall_seconds']}s for the full sweep ({n_boms} BOMs × "
        f"{len(MULTIPLIERS)} multipliers × 3 arms × 2 offer pools)",
    ])


def _md_headline_fee(meta: dict, boms: Dict[str, dict], rows: List[dict]) -> str:
    r1 = _row_at(rows, 1)
    pts = _points_at(boms, 1)
    n_comp_negative = sum(1 for p in pts if p["vs"]["saving_from_component_cost_usd"] < 0)
    scale = float(meta["strategy_weights"]["transport_penalty_scale"])
    ltl = float(meta["cost_constants"]["LTL_BASE_FEE_USD"])
    air = float(meta["cost_constants"]["AIR_FREIGHT_BASE_USD"])

    n_lines = sorted({len(b["base_items"]) for b in boms.values() if "base_items" in b})
    qtys = [i["quantity"] for b in boms.values() for i in b.get("base_items", [])]
    units = [int(b["base_total_units"]) for b in boms.values() if "base_total_units" in b]
    lines_txt = f"{n_lines[0]}" if len(n_lines) == 1 else f"{n_lines[0]}–{n_lines[-1]}"

    iot = next((p for p in pts if p["name"] == "iot_sensor_node"), None)
    n_total = r1["n"] if r1 else 0

    first = (
        "The greedy baseline picks `min(price_usd)` per BOM line, so it is *the component-cost minimum by\n"
        "construction* — the MILP can never beat it on component cost, and in fact loses to it on component\n"
        f"cost in **all {n_comp_negative} of {n_total} BOMs** at 1×. At 1× volume every dollar the MILP "
        '"saves" comes from avoiding\n'
        f"fixed, **per-supplier** charges: `LTL_BASE_FEE_USD = ${ltl:g}` (domestic) and "
        f"`AIR_FREIGHT_BASE_USD = ${air:g}`\n"
        f"(international), each scaled by `transport_penalty_scale = {scale:g}` → "
        f"**${ltl * scale:,.2f} / ${air * scale:,.0f} per supplier**."
    )
    if iot is None:
        return first

    fixed_delta = float(iot["greedy"]["fixed_fee_usd"]) - float(iot["milp"]["fixed_fee_usd"])
    second = (
        f"\n\nAt the benchmark's toy volumes ({lines_txt} BOM lines, quantities {min(qtys)}–{max(qtys)}, "
        f"**{min(units)}–{max(units)} units total**) those fees are\n"
        f"larger than the parts. On `iot_sensor_node` the components cost "
        f"**${float(iot['greedy']['component_cost']):,.2f}**; consolidating "
        f"{iot['vs']['suppliers_greedy']} suppliers\n"
        f"into {iot['vs']['suppliers_milp']} avoids **${fixed_delta:,.2f}** of fees. That is the 71.75%."
    )
    return first + second


def _md_headline_decay(rows: List[dict]) -> str:
    r1 = _row_at(rows, 1)
    prod = [r for r in rows if r["m"] >= PRODUCTION_FLOOR]
    if not (r1 and prod):
        return "The fee saving is roughly **constant in volume**. Component cost grows **linearly**."
    lo = min(r["pct"] for r in prod)
    hi = max(r["pct"] for r in prod)
    return (
        "The fee saving is roughly **constant in volume**. Component cost grows **linearly**. So the savings\n"
        f"*percentage* must decay — and it does, from **{r1['pct']:.1f}% at 1× to ~{lo:.1f}–{hi:.1f}% "
        f"at {_mult(prod[0]['m'])}–{_mult(prod[-1]['m'])}**."
    )


def _md_volume_curve(rows: List[dict]) -> str:
    out = [
        "| Multiplier | BOMs feasible | greedy $ | MILP $ | **Pooled saving** | from fixed fees | "
        "from component cost | from variable freight |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        pct = f"{r['pct']:.2f}%"
        if r["m"] == 1:
            pct = f"**{pct}**"
        fee = _signed_usd(r["fee"])
        if r["fee"] < 0:
            fee = f"**{fee}**"
        out.append(
            f"| {_mult(r['m'])} | {r['n']} | {r['greedy']:,.0f} | {r['milp']:,.0f} | {pct} | "
            f"{fee} | {_signed_usd(r['comp'])} | {_signed_usd(r['var'])} |"
        )
    return "\n".join(out)


def _md_curve_composition(rows: List[dict]) -> str:
    r1 = _row_at(rows, 1)
    if r1 is None:
        return "*(no feasible 1× cohort in this run)*"
    share = r1["fee"] / r1["delta"] * 100.0 if r1["delta"] else 0.0
    first = (
        f"* **At 1×** the entire saving is fixed fees ({_signed_usd(r1['fee'])} out of a "
        f"${r1['delta']:,.0f} total saving — **{share:.0f}% of it**).\n"
        "  The MILP *overpays* for components and funds it from avoided supplier fees. Supplier count\n"
        f"  {r1['sup_greedy']} → {r1['sup_milp']}."
    )

    negatives = [r for r in rows if r["fee"] < 0]
    last = rows[-1]
    if not negatives:
        second = (
            "\n* **At volume** the fixed-fee term stays positive but stops growing, while variable freight\n"
            f"  takes over: greedy pays {_signed_usd(last['var'])} more in freight at {_mult(last['m'])} because it\n"
            "  sources on unit price and is blind to distance × quantity."
        )
        return first + second

    examples = ", ".join(
        f"{r['sup_greedy']} → {r['sup_milp']} at {_mult(r['m'])}" for r in negatives[:2]
    )
    second = (
        f"\n* **At ≥{_mult(negatives[0]['m'])}** the fixed-fee term goes **negative**: the MILP now opens "
        "**MORE** suppliers than greedy\n"
        f"  ({examples}) and pays *more* in per-visit fees on purpose — because it is\n"
        "  buying down variable freight and staying inside stock caps. Essentially 100% of the win is now\n"
        f"  **variable freight**: greedy pays ${last['var'] / 1000:,.0f}k more in freight at {_mult(last['m'])} "
        "because it sources on unit price\n"
        "  and is blind to distance × quantity."
    )
    return first + second


def _md_old_vs_new(rows: List[dict]) -> str:
    out = [
        "| Multiplier | Old (buggy freight) | **Corrected** |",
        "|---:|---:|---:|",
    ]
    for m, old in BUGGY_FREIGHT_POOLED_PCT.items():
        r = _row_at(rows, m)
        new = f"**{r['pct']:.2f}%**" if r else "*(no feasible cohort)*"
        out.append(f"| {_mult(m)} | {old:.2f}% | {new} |")
    return "\n".join(out)


def _md_high_volume_caveat(rows: List[dict]) -> str:
    r1 = _row_at(rows, 1)
    prod = [r for r in rows if r["m"] >= PRODUCTION_FLOOR]
    if not (r1 and prod):
        return "*(no production-volume cohort survived the stock ceilings in this run)*"
    last = rows[-1]
    named = " and ".join(f"`{name}` ({pct:.2f}%)" for name, pct in last["members"])
    lo = min(r["pct"] for r in prod)
    hi = max(r["pct"] for r in prod)
    return _wrap(
        f"The high-volume rows are a *different, smaller* BOM set than the low-volume ones "
        f"({r1['n']} BOMs at 1×, {last['n']} at {_mult(last['m'])}) — stock ceilings knock BOMs out as "
        f"volume rises. The {_mult(last['m'])} row is {named} only. It is **not a like-for-like cohort** "
        "and must not be read as one. The trustworthy statement is the *range*: at production volume "
        f"({_mult(prod[0]['m'])}–{_mult(prod[-1]['m'])}, i.e. "
        f"{min(r['units_min'] for r in prod):,}–{max(r['units_max'] for r in prod):,} units) "
        f"the MILP's pooled cost edge is **~{lo:.1f}%–{hi:.1f}%**, dominated by variable freight."
    )


def _md_decomposition_1x(meta: dict, rows: List[dict]) -> str:
    r = _row_at(rows, 1)
    if r is None:
        return "*(no feasible 1× cohort in this run)*"
    scale = float(meta["strategy_weights"]["transport_penalty_scale"])
    ltl = float(meta["cost_constants"]["LTL_BASE_FEE_USD"])
    air = float(meta["cost_constants"]["AIR_FREIGHT_BASE_USD"])
    table = "\n".join([
        "| Component of the saving | Amount |",
        "|---|---:|",
        f"| Avoided fixed per-supplier fees (${ltl:g} LTL / ${air:g} air, ×{scale:g}) | "
        f"**{_signed_usd(r['fee'])}** |",
        f"| Variable freight (weight × distance) | {_signed_usd(r['var'])} |",
        f"| **Component cost** | **{_signed_usd(r['comp'])}** ← *the MILP pays MORE for parts* |",
        f"| **Total saving** | **${r['delta']:,.0f} ({r['pct']:.2f}%)** |",
    ])
    avoided = r["sup_greedy"] - r["sup_milp"]
    prose = (
        f"\n\nSupplier count across the {r['n']} BOMs drops from "
        f"**{r['sup_greedy']} (greedy) → {r['sup_milp']} (MILP)**. {avoided} suppliers avoided ×\n"
        f"${ltl * scale:,.2f}–${air * scale:,.0f} per supplier ≈ the entire \"win\". This is not the optimizer "
        "finding cheaper parts. It is\nthe optimizer noticing that the cost model charges "
        f"${ltl * scale:,.2f} every time you talk to a new distributor."
    )
    return table + prose


def _md_per_bom_1x(boms: Dict[str, dict]) -> str:
    out = [
        "| BOM | greedy $ | MILP $ | save % | suppliers | fee saving $ | component saving $ |",
        "|---|---:|---:|---:|:---:|---:|---:|",
    ]
    pts = sorted(_points_at(boms, 1), key=lambda p: -p["vs"]["saving_pct"])
    for p in pts:
        vs = p["vs"]
        pct = f"{vs['saving_pct']:.1f}%"
        if p["name"] == "iot_sensor_node":
            pct = f"**{pct}**"
        fee = _neg(f"{float(vs['saving_from_fixed_fees_usd']):,.0f}")
        comp = _neg(f"{float(vs['saving_from_component_cost_usd']):,.0f}")
        out.append(
            f"| {p['name']} | {float(p['greedy']['total_cost']):.2f} | {float(p['milp']['total_cost']):.2f} | "
            f"{pct} | {vs['suppliers_greedy']}→{vs['suppliers_milp']} | {fee} | {comp} |"
        )
    return "\n".join(out)


def _iot_rows(boms: Dict[str, dict]) -> List[dict]:
    out: List[dict] = []
    for p in (boms.get("iot_sensor_node") or {}).get("points") or []:
        arms = p.get("arms") or {}
        g = arms.get("greedy") or {}
        mm = arms.get("milp_matched") or {}
        s = p.get("vs_milp_matched")
        if not (g.get("feasible") and mm.get("feasible") and s):
            continue
        if g.get("stock_violations"):
            continue
        out.append({"p": p, "g": g, "m": mm, "vs": s})
    return out


def _md_iot_retraction(boms: Dict[str, dict]) -> str:
    rows = _iot_rows(boms)
    out = [
        "| Multiplier | Units | greedy $ | MILP $ | **Savings %** | Fee share of saving | Suppliers |",
        "|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for i, r in enumerate(rows):
        vs = r["vs"]
        pct = f"{vs['saving_pct']:.1f}%"
        if i in (0, len(rows) - 1):
            pct = f"**{pct}**"
        share = vs.get("fixed_fee_share_of_saving")
        share_txt = "n/a" if share is None else _pct_or_zero(float(share) * 100.0)
        out.append(
            f"| {_mult(int(r['p']['multiplier']))} | {int(r['p']['total_units']):,} | "
            f"{float(r['g']['total_cost']):,.2f} | {float(r['m']['total_cost']):,.2f} | {pct} | "
            f"{share_txt} | {vs['suppliers_greedy']}→{vs['suppliers_milp']} |"
        )
    return "\n".join(out)


def _md_iot_prose(boms: Dict[str, dict]) -> str:
    rows = _iot_rows(boms)
    if len(rows) < 2:
        return "*(iot_sensor_node produced too few feasible points to retract anything this run)*"
    first, last = rows[0], rows[-1]
    f_share = first["vs"].get("fixed_fee_share_of_saving")
    l_share = last["vs"].get("fixed_fee_share_of_saving")
    tail = [r for r in rows if int(r["p"]["multiplier"]) >= PRODUCTION_FLOOR] or rows[-1:]
    lo = min(r["vs"]["saving_pct"] for r in tail)
    hi = max(r["vs"]["saving_pct"] for r in tail)
    fixed_delta = float(first["g"]["fixed_fee_usd"]) - float(first["m"]["fixed_fee_usd"])
    return (
        f"**{first['vs']['saving_pct']:.1f}% → {last['vs']['saving_pct']:.1f}%.** We are still retracting "
        '"71.75% cheaper" as a headline: at 1× it *is* the fee, and\n'
        "the fee doesn't care how many units you buy. But watch the **fee share** column collapse from "
        f"{_pct_or_zero(float(f_share or 0.0) * 100.0)} to\n"
        f"{_pct_or_zero(float(l_share or 0.0) * 100.0)} while the saving stays in double digits: past ~250× "
        "the MILP is winning on something else\n"
        f"entirely. It opens *more* suppliers than greedy ({last['vs']['suppliers_greedy']}→"
        f"{last['vs']['suppliers_milp']}) and still comes out {lo:.0f}–{hi:.0f}% cheaper, because it\n"
        "routes each line's volume to whichever distributor minimizes **price + freight**, and greedy only looks\n"
        "at price.\n\n"
        f"The defensible statement is: *on a {int(first['p']['total_units'])}-unit prototype BOM the MILP avoids "
        f"${fixed_delta:,.2f} of supplier onboarding\n"
        f"fees — that is fee arithmetic. At {int(last['p']['total_units']):,} units it is "
        f"{last['vs']['saving_pct']:.1f}% cheaper on landed cost, and that part is real\n"
        "freight optimization.*"
    )


def _ceiling_rows(boms: Dict[str, dict]) -> List[dict]:
    out = []
    for name, b in boms.items():
        if "stock_ceiling_multiplier_all_offers" not in b:
            continue
        ceil_ = int(b["stock_ceiling_multiplier_all_offers"])
        base = int(b["base_total_units"])
        out.append({
            "name": name,
            "base": base,
            "ceiling": ceil_,
            "max_units": ceil_ * base,
            "dups": int(b.get("n_duplicate_cid_did_pairs", 0)),
            "dom_ceiling": int(b.get("stock_ceiling_multiplier_domestic_only", 0)),
        })
    return sorted(out, key=lambda r: -r["ceiling"])


def _md_feasibility_ceilings(boms: Dict[str, dict]) -> str:
    rows = _ceiling_rows(boms)
    out = [
        "| BOM | Base units | Max multiplier | Max total units | Duplicated offer pairs |",
        "|---|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(rows):
        ceil_txt = f"{r['ceiling']:,}"
        units_txt = f"{r['max_units']:,}"
        if i == len(rows) - 1:  # the binding BOM — the one that caps out first
            ceil_txt, units_txt = f"**{ceil_txt}**", f"**{units_txt}**"
        out.append(f"| {r['name']} | {r['base']} | {ceil_txt} | {units_txt} | {r['dups']} |")
    return "\n".join(out)


def _md_ceiling_summary(boms: Dict[str, dict], rows: List[dict]) -> str:
    ceilings = _ceiling_rows(boms)
    below = sum(1 for r in ceilings if r["ceiling"] < 100)
    worst = ceilings[-1] if ceilings else None

    # Run-length compress "n BOMs feasible" across the grid: 5 at 50×–1,000×.
    segments: List[Tuple[int, int, int]] = []
    for r in rows:
        if segments and segments[-1][0] == r["n"]:
            segments[-1] = (segments[-1][0], segments[-1][1], r["m"])
        else:
            segments.append((r["n"], r["m"], r["m"]))
    surviving = ", ".join(
        f"{n} at {_mult(lo)}" if lo == hi else f"{n} at {_mult(lo)}–{_mult(hi)}"
        for n, lo, hi in segments
    )

    if worst is None:
        return _wrap(f"BOMs surviving at each multiplier: **{surviving}.**")
    times = "twice" if worst["ceiling"] == 2 else f"{worst['ceiling']:,} times"
    return _wrap(
        f"{below} of the {len(ceilings)} BOMs cap out below 100× volume. `{worst['name']}` cannot be built "
        f"more than **{times}** from this data. BOMs surviving at each multiplier: **{surviving}.**"
    )


def _md_solver_hygiene(meta: dict, boms: Dict[str, dict]) -> str:
    c = _solver_counts(boms)
    limit = float(meta["solver"]["max_time_in_seconds"])
    if c["hit_limit"] == 0 and c["optimal"] == c["feasible"]:
        return (
            f"**Solver hygiene:** of {c['attempts']} MILP solve attempts, {c['feasible']} were feasible and "
            f"**all {c['optimal']} returned `OPTIMAL`** —\n"
            f"none hit the {limit:g}s time limit. The {c['infeasible']} infeasible attempts are the genuine "
            "stock/MOQ ceilings documented\nabove. No result in this document is a timeout artifact."
        )
    return (
        f"**Solver hygiene:** of {c['attempts']} MILP solve attempts, {c['feasible']} were feasible; "
        f"{c['optimal']} returned `OPTIMAL` and\n"
        f"**{c['hit_limit']} hit the {limit:g}s time limit** — those are the solver's best incumbent, NOT a proven "
        "optimum, and\nany row resting on them must be read with that caveat. The "
        f"{c['infeasible']} infeasible attempts are the genuine\nstock/MOQ ceilings documented above."
    )


# ── Marker rewriting ─────────────────────────────────────────────────────────

def _apply_blocks(text: str, blocks: Dict[str, str]) -> Tuple[str, List[str]]:
    """
    Replace the body of each `<!-- GENERATED:<id>:BEGIN -->…:END -->` pair.

    Everything outside a marker pair is curated prose and is not touched. Idempotent:
    the replacement is exactly `BEGIN\\n<body>\\nEND`, so re-running with the same data
    reproduces the file byte-for-byte. Returns (new_text, ids_whose_markers_are_missing).
    """
    missing: List[str] = []
    for block_id, body in blocks.items():
        pattern = re.compile(
            r"(<!-- GENERATED:" + re.escape(block_id) + r":BEGIN -->)"
            r"(.*?)"
            r"(<!-- GENERATED:" + re.escape(block_id) + r":END -->)",
            re.DOTALL,
        )
        if not pattern.search(text):
            missing.append(block_id)
            continue
        rendered = body.strip("\n")
        text = pattern.sub(
            lambda mo, r=rendered: f"{mo.group(1)}\n{r}\n{mo.group(3)}", text, count=1
        )
    return text, missing


def _write_markdown(payload: dict, prov: Mapping[str, Any]) -> None:
    """Refresh only the GENERATED regions of docs/BENCHMARK_VOLUME_CURVE.md."""
    if not DOC_PATH.is_file():
        logger.warning(
            "%s missing — skipping doc refresh (the JSON artifact is still written)",
            DOC_PATH,
        )
        return

    meta = payload["meta"]
    boms = payload["boms"]
    rows = _pooled_rows(boms)

    blocks = {
        "header_meta": _md_header_meta(meta, prov, len(boms)),
        "headline_fee_arithmetic": _md_headline_fee(meta, boms, rows),
        "headline_decay": _md_headline_decay(rows),
        "volume_curve": _md_volume_curve(rows),
        "curve_composition": _md_curve_composition(rows),
        "old_vs_new": _md_old_vs_new(rows),
        "high_volume_caveat": _md_high_volume_caveat(rows),
        "decomposition_1x": _md_decomposition_1x(meta, rows),
        "per_bom_1x": _md_per_bom_1x(boms),
        "iot_retraction": _md_iot_retraction(boms),
        "iot_retraction_prose": _md_iot_prose(boms),
        "feasibility_ceilings": _md_feasibility_ceilings(boms),
        "ceiling_summary": _md_ceiling_summary(boms, rows),
        "solver_hygiene": _md_solver_hygiene(meta, boms),
        "provenance": provenance_markdown(prov).strip("\n"),
    }

    original = DOC_PATH.read_text(encoding="utf-8")
    updated, missing = _apply_blocks(original, blocks)
    if missing:
        logger.warning(
            "BENCHMARK_VOLUME_CURVE.md has no GENERATED markers for: %s — those sections "
            "were left as-is and may now be STALE. Re-add the markers "
            "(<!-- GENERATED:<id>:BEGIN --> / :END -->) to bring them back under the generator.",
            ", ".join(missing),
        )
    if updated == original:
        logger.info("docs/BENCHMARK_VOLUME_CURVE.md already current (no byte changed)")
        return
    DOC_PATH.write_text(updated, encoding="utf-8")
    logger.info(
        "refreshed %d generated block(s) in docs/BENCHMARK_VOLUME_CURVE.md",
        len(blocks) - len(missing),
    )


# ── Driver ───────────────────────────────────────────────────────────────────

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    started = datetime.now(UTC)
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

    # The sqlite snapshot IS the input data for every number in this artifact, so it
    # is what provenance hashes: two sweeps with the same DB sha256 are comparable,
    # two with different ones are not — whatever the git SHA says.
    db_file = _database_file()
    prov = build_provenance(
        generator="seeds.run_volume_sweep",
        inputs={"supply_chain_db": db_file} if db_file else {},
        extra={
            "strategy": STRATEGY_ID,
            "primary_offer_pool": "deduped",
            "primary_arm": "milp_matched",
            "wall_seconds": round(elapsed, 1),
        },
    )

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
                "raw": "CONTROL. The pool exactly as it comes out of the offer "
                       "table, one row per price-break tier. solve_sourcing dedupes "
                       "(component_id, distributor_id) internally since 6988530, so "
                       "this arm AGREES with the deduplicated one on every point — "
                       "which is what makes it a control rather than a bug report. "
                       "Results live in boms.<name>.points_raw_pool.",
            },
            # The `known_bug` block that used to live here declared the shipped
            # optimizer broken: CP-SAT variables keyed on (component_id,
            # distributor_id) while the offer table carried duplicated pairs, so
            # price-break tiers were summed. That was real — and it was FIXED in
            # commit 6988530 on 2026-07-13, before this sweep was ever generated.
            # The block outlived the defect and kept telling readers of
            # docs/volume_sweep.json that the optimizer they were looking at was
            # corrupt. Removed from the artifact 2026-08-28 and from this generator
            # so a regeneration cannot bring it back.
            # `test_volume_sweep_declares_no_stale_known_bug` fails if it returns.
            "notes": [
                "All arms scored through the same landed_cost_breakdown().",
                "The cost model has NO holding-cost term; decomposition is "
                "component / fixed per-supplier fee / variable freight / consolidation charge.",
                "greedy's fallback can order above an offer's stock; such plans are "
                "flagged in arms.greedy.stock_violations and are physically infeasible. "
                "Points so flagged must NOT be counted as greedy wins.",
            ],
        },
        "provenance": prov,
        "boms": results,
    }

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "volume_sweep.json").write_text(json.dumps(payload, indent=2) + "\n")
    logger.info("wrote docs/volume_sweep.json  (%.1fs total)", elapsed)
    _write_markdown(payload, prov)
    return 0


if __name__ == "__main__":
    sys.exit(main())
