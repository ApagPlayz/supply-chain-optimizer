"""
Benchmark pipeline — proves TWO things with real numbers on the 10 hand-crafted
named portfolio BOMs:

  (1) VALUE OF OPTIMIZATION — the CP-SAT MILP beats naive greedy baselines on
      landed cost. Per BOM we SOLVE 4 sourcing arms (greedy, greedy_add,
      milp-blind, milp-graph-aware) and score EVERY arm's selection through the
      SAME `landed_cost_breakdown(...)` cost function, so no arm is judged on a
      different yardstick.

  (2) VALUE OF RESILIENCE — the graph-aware MILP costs ~nothing extra in the
      nominal world but protects tail-risk under disruption. We take the two
      MILP arms (blind vs graph-aware) and re-EVALUATE each solved plan under 3
      disruption scenarios via cheap Monte-Carlo re-simulation (NO re-solve):
      nominal, broad stress (stress_factor=3), and a targeted outage of the
      single highest-betweenness distributor in the BOM's full offer pool.

Per BOM we persist 8 OptimizationRun rows (append-only, run_id keyed):
  • Cost story:       4 arms × scenario="nominal"                     (4 rows)
  • Resilience story: 2 milp arms × scenarios {stress, targeted}      (4 rows)

Every arm's selection is scored with the balanced StrategyWeights so the cost
comparison is fair. Greedy arms have no route/ETA/CO2 model (they are pure
sourcing baselines) — their eta/co2 columns are written as 0.0 sentinels and
rendered as "—" in the summary; cost + suppliers + tail-risk are their story.

Produces four outputs:
  (a) Rows in optimization_runs table (run_id keyed, append-only)
  (b) Two aggregate summary tables printed to stdout
  (c) docs/BENCHMARK_RESULTS.md — the human artifact. Paths are derived from
      ``REPO_ROOT`` so the file lands in the repo's own docs/ directory no
      matter what the working directory is, and a hand-written CURATED region
      (delimited by ``<!-- CURATED:BEGIN -->`` / ``<!-- CURATED:END -->``) is
      read back out of the existing file and re-emitted verbatim. Regenerating
      therefore refreshes the DATA and never clobbers the disclosure prose.
  (d) docs/benchmark_results.json — the machine-readable artifact the doc's
      headline figures are checked against
      (tests/test_benchmark_docs_match_artifacts.py), carrying a provenance
      block from seeds.provenance.

BOM INCLUSION (BENCH-07): a BOM whose arms cannot all be solved used to vanish
into a single WARNING log line, silently shrinking the benchmark from 10 BOMs
to 9 while the doc's header still said "10". Every catalog BOM now carries an
explicit included/excluded verdict plus the reason, published in both artifacts,
and the header states the true "N of 10" coverage.

HOLDOUT SEMANTICS (BENCH-06): run_benchmark.py uses ALL offers because the
benchmark IS the holdout evaluation. No strategy-tuning happens here, so no
holdout filter is applied.

Invocation: `python -m seeds.run_benchmark` (CLI only, never via HTTP per T-04-01).
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# sys.path boilerplate — mirrors seed_db.py
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# E402 is unavoidable below: `app.*` is only importable AFTER the sys.path insert
# above, so these imports cannot move to the top of the file. Silenced per-import
# rather than repo-wide so the rule still catches accidental late imports.
from sqlalchemy import func  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.graph import get_graph_state  # noqa: E402
from app.graph.builder import build_graph_state  # noqa: E402
from app.graph.simulation import run_monte_carlo  # noqa: E402
from app.models import (  # noqa: E402
    Component,
    Distributor,
    DistributorOffer,
    OptimizationRun,
)
from app.optimization.costs import haversine_km  # noqa: E402
from app.optimization.greedy import (  # noqa: E402
    landed_cost_breakdown,
    solve_sourcing_greedy,
    solve_sourcing_greedy_add,
)
from app.optimization.routing import GeoPoint  # noqa: E402
from app.optimization.solve import DistributorMeta, optimize_bom  # noqa: E402
from app.optimization.sourcing import BomLine, Offer, SourcingAssignment  # noqa: E402
from app.optimization.strategies import get_strategy  # noqa: E402

from seeds.provenance import build_provenance, provenance_markdown  # noqa: E402

logger = logging.getLogger(__name__)

# ── Output paths (repo-root anchored, NOT cwd-relative) ────────────────────
# Previously this module wrote to Path("docs/BENCHMARK-RESULTS.md") — relative
# to the working directory AND hyphenated, while the committed canonical file is
# docs/BENCHMARK_RESULTS.md. Run the documented way (`cd backend && python -m
# seeds.run_benchmark`) that produced a stray backend/docs/BENCHMARK-RESULTS.md
# and left the real doc untouched, so the doc's own "re-run to regenerate"
# instruction was a no-op. Anchor on the repo root like run_forecast_backtest.py.
REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"
MD_PATH = DOCS / "BENCHMARK_RESULTS.md"
JSON_PATH = DOCS / "benchmark_results.json"

# The hand-written region of BENCHMARK_RESULTS.md. _write_markdown() lifts
# whatever sits between these markers out of the existing file and re-emits it
# byte-for-byte, so regenerating the data tables can never destroy the
# retraction/disclosure prose a human put there.
CURATED_BEGIN = "<!-- CURATED:BEGIN -->"
CURATED_END = "<!-- CURATED:END -->"

CURATED_PLACEHOLDER = "\n".join([
    CURATED_BEGIN,
    "<!-- Hand-written region: everything between these two markers is preserved",
    "     verbatim by seeds/run_benchmark.py::_write_markdown(). Put retractions,",
    "     caveats and framing here; the generator only rewrites the sections",
    "     outside the markers. -->",
    CURATED_END,
])

# ── Canonical SF depot (fixed — interview narrative) ───────────────────────
DEPOT = GeoPoint(lat=37.7749, lng=-122.4194)

# ── Named documented assumption (disclosed in summary + API) ───────────────
# We score arms on ONE representative reorder. To annualize the per-BOM MILP
# savings we assume each BOM is re-ordered this many times per year. This is an
# openly-stated modelling assumption, not a measured cadence.
ANNUAL_REORDERS = 12

# ── Test-override hook (populated by tests; None in production) ─────────────
_BOM_CATALOG_OVERRIDE: Optional[Dict[str, List[Tuple[str, int]]]] = None

# ── 10 named portfolio BOMs (D-01, verified against live DB 2026-04-18) ───
BOM_CATALOG: Dict[str, List[Tuple[str, int]]] = {
    "iot_sensor_node": [
        ("ESP32-WROOM-32E-N4", 1),   # Espressif SoC — Chinese-origin via risk_factors
        ("OPA861ID",           2),   # TI op-amp
        ("GD25Q40CTIGR",       1),   # GigaDevice flash
        ("LM317DCY",           1),   # TI linear regulator
    ],
    "drone_flight_controller": [
        ("STM32F103RCT6",      1),   # STMicro MCU
        ("ESP-WROOM-02D-N4",   1),   # Espressif Wi-Fi — Chinese-origin
        ("DRV8303EVM",         4),   # TI motor driver (single-source tendency)
        ("AD7625BCPZ",         1),   # ADI high-speed ADC
    ],
    "pcb_power_supply": [
        ("LM317DCY",           2),
        ("TPS767D325PWP",      1),
        ("UA78M33CDCY",        2),
        ("OPA861ID",           1),
    ],
    "industrial_motor_driver": [
        ("STM32F103VCT6",      1),
        ("DRV8860EVM",         2),
        ("ADG202AKNZ",         2),
        ("INA2128UA",          2),
    ],
    "rf_transceiver_module": [
        ("ESP32-S3-WROOM-1-N16R8", 1),   # Chinese-origin
        ("ESP-07S",                1),   # Chinese-origin
        ("AD7934BRUZ",             1),
        ("GD25Q16ESIGR",           1),
    ],
    "automotive_ecu": [
        ("STM32F103VET6",      1),
        ("ATMEGA328P-AU",      1),
        ("AD835ARZ",           1),
        ("OPA861ID",           4),
    ],
    "medical_monitoring_device": [
        ("STM32F103CBT6",      1),
        ("INA2128U",           4),
        ("PGA206PA",           2),        # single-source tendency
        ("TPS780330220DDCT",   1),
    ],
    "smart_meter": [
        ("STM32F103C8T6",      1),
        ("GD25Q32ESIGR",       1),
        ("LM317DCY",           1),
        ("ADS1256EVM-PDK",     1),
    ],
    "robotics_servo_driver": [
        ("STM32F103R8T6",      1),
        ("DRV10963AEVM",       4),        # TI motor driver
        ("DRV8885EVM",         2),        # TI motor driver
        ("INA2128U",           2),
    ],
    "audio_dsp_board": [
        ("ATMEGA328P-XMINI",   1),
        ("PCM4202DBT",         1),
        ("OPA861ID",           4),
        ("GD25Q127CYIGR",      1),
    ],
}

FEED_KEYS = ("gpr", "acled", "portwatch", "fred_freight")

# Disruption scenarios (evaluated by re-simulation, no re-solve).
STRESS_FACTOR = 3.0   # broad macro/geopolitical stress spike


def _distributor_tier(total_offers: int) -> str:
    if total_offers >= 500:
        return "major"
    if total_offers >= 100:
        return "mid"
    return "broker"


def next_run_id(db: Session) -> int:
    """Monotonic run_id. First run = 1."""
    max_id = db.query(func.max(OptimizationRun.run_id)).scalar()
    return (max_id or 0) + 1


def snapshot_feed_availability() -> Dict[str, bool]:
    """Return {feed_name: bool} — True if the feed has non-None data right now."""
    try:
        from app.feeds import get_live_data_cache
        ldc = get_live_data_cache()
        if ldc is None:
            return {k: False for k in FEED_KEYS}
        return {
            "gpr": getattr(getattr(ldc, "gpr", None), "data", None) is not None,
            "acled": getattr(getattr(ldc, "acled", None), "data", None) is not None,
            "portwatch": getattr(getattr(ldc, "portwatch", None), "data", None) is not None,
            "fred_freight": getattr(getattr(ldc, "fred_freight", None), "data", None) is not None,
        }
    except Exception:
        return {k: False for k in FEED_KEYS}


def _load_offers_for_bom(
    db: Session, bom_items: List[Tuple[str, int]]
) -> Tuple[List[BomLine], List[Offer], Dict[int, DistributorMeta]]:
    """
    Resolve MPN → Component, then load all DistributorOffers for those components.
    Returns (bom, offers, distributors_meta).
    """
    mpns = [m for m, _q in bom_items]
    comps = db.query(Component).filter(Component.mpn.in_(mpns)).all()
    comp_by_mpn = {c.mpn: c for c in comps}

    bom: List[BomLine] = []
    for mpn, qty in bom_items:
        c = comp_by_mpn.get(mpn)
        if not c:
            logger.warning("MPN %s not found in DB — skipping from BOM", mpn)
            continue
        bom.append(BomLine(component_id=c.id, mpn=c.mpn, quantity=int(qty)))

    comp_ids = [b.component_id for b in bom]
    offer_rows = (
        db.query(DistributorOffer)
        .filter(DistributorOffer.component_id.in_(comp_ids))
        .all()
    )
    dist_ids = {o.distributor_id for o in offer_rows}
    dist_rows = (
        db.query(Distributor).filter(Distributor.id.in_(dist_ids)).all()
        if dist_ids else []
    )
    dist_by_id = {d.id: d for d in dist_rows}

    offers: List[Offer] = []
    for o in offer_rows:
        d = dist_by_id.get(o.distributor_id)
        if not d or o.price is None or o.price <= 0:
            continue
        comp = next((c for c in comps if c.id == o.component_id), None)
        is_chinese = any(
            "chinese" in str(f).lower()
            for f in ((comp.risk_factors if comp else None) or [])
        )
        offers.append(Offer(
            component_id=o.component_id,
            distributor_id=o.distributor_id,
            distributor_name=d.name,
            price_usd=float(o.price),
            stock=int(o.stock or 0),
            moq=int(o.moq or 1),
            is_domestic=bool(d.is_domestic),
            dist_km_from_depot=haversine_km(DEPOT.lat, DEPOT.lng, d.latitude, d.longitude),
            risk_score=float(comp.risk_score if comp else 0.5),
            is_chinese_origin=is_chinese,
            distributor_country=str(d.country or "US"),
        ))

    distributors_meta = {
        d.id: DistributorMeta(
            id=d.id, name=d.name, lat=d.latitude, lng=d.longitude,
            city=d.city, state=d.state, country=d.country,
            is_domestic=bool(d.is_domestic),
            tier=_distributor_tier(d.total_offers or 0),
        )
        for d in dist_rows
    }
    return bom, offers, distributors_meta


# ── Arm scoring (fairness: ALL arms scored through landed_cost_breakdown) ───

def _score_assignments(
    assignments: List[SourcingAssignment],
    offers: List[Offer],
    bom: List[BomLine],
    weights,
) -> dict:
    """Score any arm's assignment set with the single shared cost function."""
    bd = landed_cost_breakdown(assignments, offers, bom, weights)
    selected = sorted({a.distributor_id for a in assignments})
    names = sorted({a.distributor_name for a in assignments})
    return {
        "total_cost": round(float(bd["total_cost"]), 2),
        "component_cost": round(float(bd["component_cost"]), 2),
        # transport_fixed  = per-opened-supplier base fee (LTL / air minimum)
        # transport_variable = per-unit freight on what each supplier actually ships
        "transport_fixed": round(float(bd["transport_fixed"]), 2),
        "transport_variable": round(float(bd["transport_variable"]), 2),
        "transport_total": round(float(bd["transport_total"]), 2),
        "n_distinct_suppliers": int(bd["n_distinct_suppliers"]),
        "selected": selected,
        "selected_names": names,
    }


def _milp_assignments(balanced) -> List[SourcingAssignment]:
    """Convert the MILP balanced alternative's pydantic sourcing rows into the
    dataclass SourcingAssignment shape landed_cost_breakdown expects."""
    return [
        SourcingAssignment(
            component_id=s.component_id,
            mpn=s.mpn,
            distributor_id=s.distributor_id,
            distributor_name=s.distributor_name,
            quantity=s.quantity,
            unit_price_usd=s.unit_price_usd,
        )
        for s in balanced.sourcing
    ]


def _solve_arms(
    bom: List[BomLine],
    offers: List[Offer],
    distributors_meta: Dict[int, DistributorMeta],
    weights,
) -> Tuple[Optional[Dict[str, dict]], Optional[str]]:
    """
    Solve the 4 sourcing arms and score each through landed_cost_breakdown.

    Returns ``(arms, failure_reason)``. On success ``arms`` is a dict keyed by
    arm-id ('greedy','greedy_add','milp_blind','milp_graph') where each value
    carries the scored selection plus eta/co2 (real for MILP arms, 0.0 sentinel
    for greedy arms) and ``failure_reason`` is None.

    If ANY arm fails, ``arms`` is None and ``failure_reason`` is a human-readable
    string naming the arm and the underlying exception — so the caller can
    PUBLISH why the BOM dropped out instead of burying it in a log line. The
    all-or-nothing rule stands: the per-BOM 8-row invariant is never partially
    satisfied.
    """
    arms: Dict[str, dict] = {}

    try:
        g = solve_sourcing_greedy(bom, offers, weights, us_only=False)
        gadd = solve_sourcing_greedy_add(bom, offers, weights, us_only=False)
    except Exception as exc:
        logger.warning("greedy baseline failed: %s", exc)
        return None, f"greedy baseline arm raised {type(exc).__name__}: {exc}"

    for arm_id, arm_label, ga_flag, res in (
        ("greedy", "greedy", False, g),
        ("greedy_add", "greedy_add", False, gadd),
    ):
        scored = _score_assignments(res.assignments, offers, bom, weights)
        scored.update({
            "arm": arm_label, "graph_aware": ga_flag,
            "eta_p10": 0.0, "eta_p50": 0.0, "eta_p90": 0.0,
            "co2": 0.0, "mc_samples": [],
        })
        arms[arm_id] = scored

    for arm_id, ga_flag in (("milp_blind", False), ("milp_graph", True)):
        try:
            # The graph-aware/resilient arm = soft graph surcharge + HARD
            # dual-sourcing diversification. The blind arm stays fully
            # unconstrained (may consolidate the whole BOM onto one hub).
            resp = optimize_bom(
                bom=bom, offers=offers, distributors=distributors_meta,
                depot=DEPOT, us_only=False, graph_aware=ga_flag,
                require_dual_source=ga_flag,
            )
        except Exception as exc:
            logger.warning("MILP (graph_aware=%s) solve failed: %s", ga_flag, exc)
            return None, (
                f"MILP arm `{arm_id}` (graph_aware={ga_flag}) raised "
                f"{type(exc).__name__}: {exc}"
            )
        balanced = next((a for a in resp.alternatives if a.id == "balanced"), None)
        if balanced is None:
            logger.warning("MILP (graph_aware=%s): no balanced alternative", ga_flag)
            return None, (
                f"MILP arm `{arm_id}` (graph_aware={ga_flag}) returned no "
                f"'balanced' alternative"
            )
        scored = _score_assignments(_milp_assignments(balanced), offers, bom, weights)
        scored.update({
            "arm": "milp", "graph_aware": ga_flag,
            "eta_p10": float(balanced.eta_p10),
            "eta_p50": float(balanced.eta_p50),
            "eta_p90": float(balanced.eta_p90),
            "co2": float(balanced.total_co2e_kg),
            "mc_samples": list(balanced.monte_carlo_samples or [])[:200],
        })
        arms[arm_id] = scored

    return arms, None


def _make_row(
    run_id: int, run_tag: str, bom_name: str,
    bom_items: List[Tuple[str, int]], feeds: Dict[str, bool],
    arm_data: dict, scenario: str, mc, cascade_risk_score: float,
) -> OptimizationRun:
    """Build one OptimizationRun row for (arm × scenario)."""
    return OptimizationRun(
        run_id=run_id,
        run_tag=run_tag,
        bom_name=bom_name,
        bom_items_json=[{"mpn": m, "quantity": q} for (m, q) in bom_items],
        strategy="balanced",
        arm=arm_data["arm"],
        graph_aware=arm_data["graph_aware"],
        scenario=scenario,
        total_cost_usd=arm_data["total_cost"],
        total_component_cost_usd=arm_data["component_cost"],
        total_transport_cost_usd=arm_data["transport_total"],
        eta_p10_days=arm_data["eta_p10"],
        eta_p50_days=arm_data["eta_p50"],
        eta_p90_days=arm_data["eta_p90"],
        co2_kg=arm_data["co2"],
        cascade_risk_score=cascade_risk_score,
        plan_cascade_risk=round(1.0 - mc.p50, 4),
        n_distinct_suppliers=arm_data["n_distinct_suppliers"],
        n_orders=arm_data["n_distinct_suppliers"],
        monte_carlo_samples=arm_data["mc_samples"],
        mc_cvar_95=round(float(mc.cvar_95), 4),
        feeds_available=feeds,
        selected_distributor_ids=arm_data["selected"],
        selected_distributor_names=arm_data["selected_names"],
    )


def _run_bom(
    db: Session,
    bom_name: str,
    bom_items: List[Tuple[str, int]],
    run_id: int,
    run_tag: str,
    gs,
    feeds_available: Dict[str, bool],
) -> Tuple[int, Dict[str, Any]]:
    """
    Solve 4 arms for one BOM, evaluate tail-risk under 3 scenarios, and persist
    8 rows.

    Returns ``(rows_added, verdict)`` where ``verdict`` is the published
    inclusion record for this BOM::

        {"bom": name, "included": bool, "reason": str|None,
         "n_lines": int, "n_offers": int, "rows": int}

    ``rows_added`` is 0 whenever ``included`` is False. Excluded BOMs are
    reported, not silently dropped (BENCH-07).
    """
    verdict: Dict[str, Any] = {
        "bom": bom_name,
        "included": False,
        "reason": None,
        "n_bom_lines_requested": len(bom_items),
        "n_bom_lines_resolved": 0,
        "n_offers": 0,
        "rows": 0,
    }

    bom, offers, distributors_meta = _load_offers_for_bom(db, bom_items)
    verdict["n_bom_lines_resolved"] = len(bom)
    verdict["n_offers"] = len(offers)
    if not bom or not offers:
        reason = (
            f"no valid BOM lines / offers resolved from the DB "
            f"({len(bom)} of {len(bom_items)} MPNs matched, {len(offers)} offers)"
        )
        logger.warning("BOM %s: %s — EXCLUDED", bom_name, reason)
        verdict["reason"] = reason
        return 0, verdict

    weights = get_strategy("balanced")
    arms, failure_reason = _solve_arms(bom, offers, distributors_meta, weights)
    if arms is None:
        logger.warning(
            "BOM %s: EXCLUDED from the benchmark — %s", bom_name, failure_reason,
        )
        verdict["reason"] = failure_reason or "an arm failed to solve"
        return 0, verdict

    comp_ids = [b.component_id for b in bom]

    # Whole-network cascade risk (context column, same for every row).
    try:
        mc_full = run_monte_carlo(gs, bom_component_ids=comp_ids)
        cascade_risk_score = round(1.0 - mc_full.p50, 4)
    except Exception:
        cascade_risk_score = 0.0

    # Targeted-outage distributor: the single highest-betweenness distributor in
    # THIS BOM's full offer pool (not any arm's selection — identical across arms
    # so the resilience comparison is fair).
    pool_dids: Set[int] = {o.distributor_id for o in offers}
    targeted_did: Optional[int] = None
    if pool_dids:
        targeted_did = max(pool_dids, key=lambda d: gs.betweenness.get(d, 0.0))

    n_added = 0

    # ── Cost story: all 4 arms × scenario="nominal" ──────────────────────────
    for arm_id in ("greedy", "greedy_add", "milp_blind", "milp_graph"):
        ad = arms[arm_id]
        sel = set(ad["selected"])
        mc = run_monte_carlo(
            gs, bom_component_ids=comp_ids,
            allowed_distributor_ids=sel, stress_factor=1.0,
        )
        db.add(_make_row(
            run_id, run_tag, bom_name, bom_items, feeds_available,
            ad, "nominal", mc, cascade_risk_score,
        ))
        n_added += 1

    # ── Resilience story: 2 milp arms × {stress, targeted} ───────────────────
    for arm_id in ("milp_blind", "milp_graph"):
        ad = arms[arm_id]
        sel = set(ad["selected"])
        # Broad stress
        mc_stress = run_monte_carlo(
            gs, bom_component_ids=comp_ids,
            allowed_distributor_ids=sel, stress_factor=STRESS_FACTOR,
        )
        db.add(_make_row(
            run_id, run_tag, bom_name, bom_items, feeds_available,
            ad, "stress", mc_stress, cascade_risk_score,
        ))
        n_added += 1
        # Targeted outage of the highest-betweenness pool distributor
        forced = {targeted_did} if targeted_did is not None else None
        mc_targeted = run_monte_carlo(
            gs, bom_component_ids=comp_ids,
            allowed_distributor_ids=sel, stress_factor=1.0,
            forced_failures=forced,
        )
        db.add(_make_row(
            run_id, run_tag, bom_name, bom_items, feeds_available,
            ad, "targeted", mc_targeted, cascade_risk_score,
        ))
        n_added += 1

    verdict["included"] = True
    verdict["rows"] = n_added
    return n_added, verdict


# ── Summary + markdown (two stories) ───────────────────────────────────────

def _partition(rows) -> Tuple[dict, dict]:
    """
    Return (cost_by_bom, resil_by_bom).

    cost_by_bom[bom] = {'greedy':row,'greedy_add':row,'milp_blind':row,'milp_graph':row}
      (scenario == 'nominal')
    resil_by_bom[bom][scenario] = {'blind':row,'graph':row}
      (scenario in {'stress','targeted'})
    """
    cost_by_bom: Dict[str, dict] = {}
    resil_by_bom: Dict[str, dict] = {}
    for r in rows:
        if r.scenario == "nominal":
            slot = cost_by_bom.setdefault(r.bom_name, {})
            if r.arm == "greedy":
                slot["greedy"] = r
            elif r.arm == "greedy_add":
                slot["greedy_add"] = r
            elif r.arm == "milp":
                slot["milp_graph" if r.graph_aware else "milp_blind"] = r
        elif r.scenario in ("stress", "targeted") and r.arm == "milp":
            scen = resil_by_bom.setdefault(r.bom_name, {})
            pair = scen.setdefault(r.scenario, {})
            pair["graph" if r.graph_aware else "blind"] = r
    return cost_by_bom, resil_by_bom


def _pct(new: float, base: float) -> float:
    if base in (0, 0.0):
        return 0.0
    return (new - base) / abs(base) * 100.0


def _cost_table_rows(cost_by_bom: dict) -> List[dict]:
    """Per-BOM Value-of-optimization figures + a TOTAL aggregate row."""
    out: List[dict] = []
    tot_greedy = tot_gadd = tot_milp = 0.0
    for name in sorted(cost_by_bom):
        s = cost_by_bom[name]
        if not all(k in s for k in ("greedy", "greedy_add", "milp_blind")):
            continue
        g, ga, m = s["greedy"], s["greedy_add"], s["milp_blind"]
        tot_greedy += g.total_cost_usd
        tot_gadd += ga.total_cost_usd
        tot_milp += m.total_cost_usd
        out.append({
            "bom": name,
            "greedy": g.total_cost_usd,
            "greedy_add": ga.total_cost_usd,
            "milp": m.total_cost_usd,
            "save_vs_greedy": _pct(m.total_cost_usd, g.total_cost_usd),
            "save_vs_greedy_add": _pct(m.total_cost_usd, ga.total_cost_usd),
            "sup_greedy": g.n_distinct_suppliers,
            "sup_milp": m.n_distinct_suppliers,
        })
    out.append({
        "bom": "TOTAL",
        "greedy": tot_greedy,
        "greedy_add": tot_gadd,
        "milp": tot_milp,
        "save_vs_greedy": _pct(tot_milp, tot_greedy),
        "save_vs_greedy_add": _pct(tot_milp, tot_gadd),
        "sup_greedy": None,
        "sup_milp": None,
    })
    return out


def _resil_table_rows(cost_by_bom: dict, resil_by_bom: dict) -> List[dict]:
    """Per-BOM per-scenario blind-vs-graph-aware resilience figures."""
    out: List[dict] = []
    for name in sorted(resil_by_bom):
        cost_slot = cost_by_bom.get(name, {})
        blind_nom = cost_slot.get("milp_blind")
        graph_nom = cost_slot.get("milp_graph")
        premium = (
            _pct(graph_nom.total_cost_usd, blind_nom.total_cost_usd)
            if blind_nom and graph_nom else 0.0
        )
        for scen in ("stress", "targeted"):
            pair = resil_by_bom[name].get(scen, {})
            b, gph = pair.get("blind"), pair.get("graph")
            if not (b and gph):
                continue
            out.append({
                "bom": name,
                "scenario": scen,
                "nominal_premium_pct": premium,
                "risk_blind": b.plan_cascade_risk or 0.0,
                "risk_graph": gph.plan_cascade_risk or 0.0,
                "risk_reduction": (b.plan_cascade_risk or 0.0) - (gph.plan_cascade_risk or 0.0),
                "cvar_blind": b.mc_cvar_95 or 0.0,
                "cvar_graph": gph.mc_cvar_95 or 0.0,
                "cvar_reduction": (b.mc_cvar_95 or 0.0) - (gph.mc_cvar_95 or 0.0),
            })
    return out


def _print_summary(db: Session, run_id: int) -> None:
    rows = db.query(OptimizationRun).filter(OptimizationRun.run_id == run_id).all()
    cost_by_bom, resil_by_bom = _partition(rows)
    print(f"\n=== Benchmark run_id={run_id} — {len(rows)} rows ===")

    # Table A — Value of optimization (nominal)
    print("\n[A] VALUE OF OPTIMIZATION  (nominal landed cost, $)")
    print(f"{'BOM':<28}{'greedy':>10}{'grdy_add':>10}{'milp':>10}"
          f"{'save%grd':>10}{'save%add':>10}{'sup g→m':>10}")
    for r in _cost_table_rows(cost_by_bom):
        sup = "—" if r["sup_greedy"] is None else f"{r['sup_greedy']}→{r['sup_milp']}"
        print(f"{r['bom']:<28}{r['greedy']:>10.2f}{r['greedy_add']:>10.2f}"
              f"{r['milp']:>10.2f}{r['save_vs_greedy']:>10.2f}"
              f"{r['save_vs_greedy_add']:>10.2f}{sup:>10}")

    # Table B — Value of resilience (graph-aware)
    print("\n[B] VALUE OF RESILIENCE  (graph-aware milp vs blind milp)")
    print(f"{'BOM':<24}{'scenario':>10}{'nom_prem%':>10}"
          f"{'risk↓':>10}{'cvar↓':>10}")
    for r in _resil_table_rows(cost_by_bom, resil_by_bom):
        print(f"{r['bom']:<24}{r['scenario']:>10}{r['nominal_premium_pct']:>10.2f}"
              f"{r['risk_reduction']:>10.4f}{r['cvar_reduction']:>10.4f}")

    print("\nNote: greedy arms are pure sourcing baselines (no route model); "
          "their ETA/CO2 are shown as '—'. Cost + suppliers + tail-risk are their story.")


def _extract_curated(path: Path) -> str:
    """
    Lift the hand-written CURATED region out of an existing artifact.

    Returns the marker-delimited block **including** both markers, so it can be
    re-emitted byte-for-byte. Falls back to an empty placeholder block when the
    file is absent or has no markers (fresh checkout), and loudly refuses to
    silently drop a half-open region.
    """
    if not path.is_file():
        logger.info("No existing %s — emitting an empty curated region.", path.name)
        return CURATED_PLACEHOLDER

    text = path.read_text()
    # Anchor the markers to whole lines (^...$ with MULTILINE). Without that, a
    # sentence that merely MENTIONS the marker strings — such as the generated
    # "everything outside the markers is overwritten" banner — matches as a
    # zero-content region and shifts the real block. Found the hard way.
    pattern = (
        r"^" + re.escape(CURATED_BEGIN) + r"[ \t]*$"
        r".*?"
        r"^" + re.escape(CURATED_END) + r"[ \t]*$"
    )
    blocks = re.findall(pattern, text, flags=re.DOTALL | re.MULTILINE)
    if blocks:
        if len(blocks) > 1:
            logger.warning(
                "%s has %d CURATED regions; preserving all of them in order.",
                path.name, len(blocks),
            )
        logger.info(
            "Preserving %d hand-written CURATED byte(s) from %s.",
            sum(len(b) for b in blocks), path.name,
        )
        return "\n\n".join(blocks)

    if CURATED_BEGIN in text or CURATED_END in text:
        raise RuntimeError(
            f"{path} contains an UNPAIRED curated marker. Refusing to regenerate "
            f"— fix the markers by hand first, or the hand-written disclosure "
            f"would be destroyed."
        )

    logger.warning(
        "%s exists but has NO %s / %s markers, so nothing hand-written can be "
        "preserved. Its previous contents are being replaced. Wrap any prose you "
        "want to keep in those markers.",
        path.name, CURATED_BEGIN, CURATED_END,
    )
    return CURATED_PLACEHOLDER


def _inclusion_table_lines(verdicts: List[Dict[str, Any]]) -> List[str]:
    """Per-BOM included/excluded verdict table (BENCH-07)."""
    lines = [
        "| BOM | in benchmark? | rows | offers | reason |",
        "|-----|:-------------:|-----:|-------:|--------|",
    ]
    for v in verdicts:
        mark = "✅ included" if v["included"] else "❌ **EXCLUDED**"
        reason = v["reason"] or "all 4 arms solved"
        lines.append(
            f"| {v['bom']} | {mark} | {v['rows']} | {v['n_offers']} | {reason} |"
        )
    return lines


def _write_markdown(
    db: Session,
    run_id: int,
    out_path: Path,
    verdicts: List[Dict[str, Any]],
    prov: Dict[str, Any],
) -> None:
    rows = db.query(OptimizationRun).filter(OptimizationRun.run_id == run_id).all()
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    cost_by_bom, resil_by_bom = _partition(rows)
    n_boms = len(cost_by_bom)
    n_catalog = len(verdicts)
    n_excluded = sum(1 for v in verdicts if not v["included"])

    # Read the hand-written region BEFORE we overwrite the file.
    curated = _extract_curated(out_path)

    lines = [
        f"# Benchmark Results — run_id={run_id}",
        "",
        # NB: deliberately does NOT print the marker strings verbatim — a line
        # containing them would be picked up by the next run's extractor.
        "> **This file is generated** by `python -m seeds.run_benchmark`. Everything "
        "outside the `CURATED:BEGIN` / `CURATED:END` HTML-comment markers is "
        "overwritten on every run; everything inside them is preserved verbatim. "
        "Put prose, retractions and caveats there.",
        "",
        f"**Generated:** {ts}",
        f"**Coverage:** **{n_boms} of {n_catalog} BOMs** "
        + (
            f"— {n_excluded} excluded, see §0 for the reason."
            if n_excluded
            else "— the full catalog solved."
        ),
        f"**Rows:** {len(rows)} ({n_boms} BOMs × 8 rows: 4 arms×nominal + 2 milp×2 disruptions)",
        "**Seed:** 42 · **Strategy:** balanced · **Holdout:** benchmark IS the holdout",
        "",
        "Every arm's selection is scored through the SAME `landed_cost_breakdown` "
        "cost function, so MILP-vs-greedy is a fair comparison. Greedy arms are pure "
        "sourcing baselines with no route model — their ETA/CO2 are omitted; cost, "
        "supplier count and tail-risk are their story.",
        "",
        *(
            []
            if prov.get("database_path_is_repo_canonical", True)
            else [
                "> ⚠️ **This run did NOT read the repo's committed database.** "
                "`DATABASE_URL` pointed at a copy / alternate file (its exact path "
                "and sha-256 are in the Provenance section below). The numbers are "
                "reproducible from those bytes, not necessarily from "
                "`backend/supply_chain.db` as it stands today.",
                "",
            ]
        ),
        curated,
        "",
        f"## 0) BOM inclusion — {n_boms} of {n_catalog} catalog BOMs are in the tables below",
        "",
        "An excluded BOM is one where at least one of the four arms failed to solve. "
        "The 8-row-per-BOM invariant is all-or-nothing, so a BOM that cannot be "
        "scored on every arm is dropped from **all** tables rather than compared "
        "unevenly. Exclusions are published here; they are not just a log line.",
        "",
        *_inclusion_table_lines(verdicts),
        "",
        "## A) Value of optimization — MILP vs greedy baselines (nominal)",
        "",
        "| BOM | greedy $ | greedy_add $ | milp $ | save% vs greedy | save% vs greedy_add | suppliers greedy→milp |",
        "|-----|---------:|-------------:|-------:|----------------:|--------------------:|:---------------------:|",
    ]
    for r in _cost_table_rows(cost_by_bom):
        sup = "—" if r["sup_greedy"] is None else f"{r['sup_greedy']}→{r['sup_milp']}"
        bom_disp = f"**{r['bom']}**" if r["bom"] == "TOTAL" else r["bom"]
        lines.append(
            f"| {bom_disp} | {r['greedy']:.2f} | {r['greedy_add']:.2f} | "
            f"{r['milp']:.2f} | {r['save_vs_greedy']:+.2f}% | "
            f"{r['save_vs_greedy_add']:+.2f}% | {sup} |"
        )

    resil_rows = _resil_table_rows(cost_by_bom, resil_by_bom)

    # Describe §B from the DATA, not from a hopeful constant. The sentence that
    # used to sit here ("graph-aware routes spend ~0 extra nominally") was
    # hard-coded prose that the numbers no longer support.
    premiums = sorted(
        {r["bom"]: r["nominal_premium_pct"] for r in resil_rows}.values()
    )
    prem_txt = "n/a"
    if premiums:
        mid = premiums[len(premiums) // 2] if len(premiums) % 2 else (
            (premiums[len(premiums) // 2 - 1] + premiums[len(premiums) // 2]) / 2
        )
        prem_txt = (
            f"median **{mid:+.1f}%**, range **{premiums[0]:+.1f}% to "
            f"{premiums[-1]:+.1f}%**"
        )
    risk_better = sum(1 for r in resil_rows if r["risk_reduction"] > 1e-9)
    risk_worse = sum(1 for r in resil_rows if r["risk_reduction"] < -1e-9)
    cvar_better = sum(1 for r in resil_rows if r["cvar_reduction"] > 1e-9)
    cvar_worse = sum(1 for r in resil_rows if r["cvar_reduction"] < -1e-9)

    lines += [
        "",
        "*Negative save% = MILP is cheaper (the win). MILP jointly optimizes "
        "component price, per-distributor transport and consolidation, so it "
        "consolidates orders the myopic greedy baseline cannot.*",
        "",
        "## B) Value of resilience — graph-aware MILP vs blind MILP",
        "",
        "`plan_cascade_risk` = 1 − P50 fulfillment of the selected plan; "
        "`cvar_95` = mean emergency-cost multiplier of the worst-5% scenarios. "
        "A **positive** reduction means the graph-aware arm is the safer plan.",
        "",
        f"**What this run actually shows.** Resilience is **not** free here: the "
        f"graph-aware arm's nominal cost premium is {prem_txt} across the "
        f"{len(cost_by_bom)} BOMs — it buys tail-risk protection with real money, "
        f"because `require_dual_source` forbids the single-supplier consolidation "
        f"that makes the blind arm cheap. And it does not win everywhere: of "
        f"{len(resil_rows)} (BOM × scenario) cells, cascade-risk improves in "
        f"**{risk_better}**, is unchanged in "
        f"**{len(resil_rows) - risk_better - risk_worse}**, and gets **worse in "
        f"{risk_worse}**; CVaR-95 improves in **{cvar_better}** and worsens in "
        f"**{cvar_worse}**. Read the per-row signs below rather than the headline.",
        "",
        "| BOM | scenario | nominal cost premium | cascade_risk (blind→graph, ↓) | cvar_95 (blind→graph, ↓) |",
        "|-----|----------|---------------------:|:-----------------------------:|:------------------------:|",
    ]
    for r in resil_rows:
        lines.append(
            f"| {r['bom']} | {r['scenario']} | {r['nominal_premium_pct']:+.2f}% | "
            f"{r['risk_blind']:.4f}→{r['risk_graph']:.4f} ({r['risk_reduction']:+.4f}) | "
            f"{r['cvar_blind']:.4f}→{r['cvar_graph']:.4f} ({r['cvar_reduction']:+.4f}) |"
        )

    lines += [
        "",
        f"*Annualization assumption: each BOM re-ordered ANNUAL_REORDERS="
        f"{ANNUAL_REORDERS}×/yr (a stated modelling assumption, not measured cadence).*",
        "",
        "## Reproduce",
        "",
        "```bash",
        "cd backend && source venv/bin/activate",
        "python -m seeds.run_benchmark      # ~2-3 minutes",
        "```",
        "",
        f"Writes this file and `docs/{JSON_PATH.name}` (the machine-readable twin "
        "these tables are generated from). Both paths are anchored on the repo root, "
        "so the working directory does not matter.",
        provenance_markdown(prov),
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")


def _build_payload(
    db: Session,
    run_id: int,
    run_tag: str,
    feeds_available: Dict[str, bool],
    verdicts: List[Dict[str, Any]],
    prov: Dict[str, Any],
    wall_seconds: float,
) -> Dict[str, Any]:
    """The machine-readable twin of BENCHMARK_RESULTS.md.

    Every headline figure quoted in the markdown is present here, so
    tests/test_benchmark_docs_match_artifacts.py can assert doc == artifact.
    """
    rows = db.query(OptimizationRun).filter(OptimizationRun.run_id == run_id).all()
    cost_by_bom, resil_by_bom = _partition(rows)
    cost_rows = _cost_table_rows(cost_by_bom)
    total = next((r for r in cost_rows if r["bom"] == "TOTAL"), None)
    resil_rows = _resil_table_rows(cost_by_bom, resil_by_bom)
    premiums = sorted({r["bom"]: r["nominal_premium_pct"] for r in resil_rows}.values())

    return {
        "provenance": prov,
        "meta": {
            "run_id": run_id,
            "run_tag": run_tag,
            "strategy": "balanced",
            "annual_reorders_assumption": ANNUAL_REORDERS,
            "stress_factor": STRESS_FACTOR,
            "feeds_available": feeds_available,
            "wall_seconds": round(wall_seconds, 1),
            "n_rows": len(rows),
            "holdout": "benchmark IS the holdout — no strategy tuning happens here",
        },
        "bom_inclusion": {
            "n_catalog": len(verdicts),
            "n_included": sum(1 for v in verdicts if v["included"]),
            "n_excluded": sum(1 for v in verdicts if not v["included"]),
            "included": [v["bom"] for v in verdicts if v["included"]],
            "excluded": [
                {"bom": v["bom"], "reason": v["reason"]}
                for v in verdicts if not v["included"]
            ],
            "verdicts": verdicts,
        },
        "headline": {
            "n_boms_in_tables": len(cost_by_bom),
            "n_boms_in_catalog": len(verdicts),
            "total_greedy_usd": round(total["greedy"], 2) if total else None,
            "total_greedy_add_usd": round(total["greedy_add"], 2) if total else None,
            "total_milp_usd": round(total["milp"], 2) if total else None,
            "total_save_pct_vs_greedy": round(total["save_vs_greedy"], 2) if total else None,
            "total_save_pct_vs_greedy_add": (
                round(total["save_vs_greedy_add"], 2) if total else None
            ),
        },
        "resilience_summary": {
            "n_cells": len(resil_rows),
            "cascade_risk_improved": sum(
                1 for r in resil_rows if r["risk_reduction"] > 1e-9
            ),
            "cascade_risk_worsened": sum(
                1 for r in resil_rows if r["risk_reduction"] < -1e-9
            ),
            "cvar_95_improved": sum(1 for r in resil_rows if r["cvar_reduction"] > 1e-9),
            "cvar_95_worsened": sum(1 for r in resil_rows if r["cvar_reduction"] < -1e-9),
            "nominal_premium_pct_min": round(premiums[0], 2) if premiums else None,
            "nominal_premium_pct_max": round(premiums[-1], 2) if premiums else None,
        },
        "value_of_optimization": [
            {
                "bom": r["bom"],
                "greedy_usd": round(r["greedy"], 2),
                "greedy_add_usd": round(r["greedy_add"], 2),
                "milp_usd": round(r["milp"], 2),
                "save_pct_vs_greedy": round(r["save_vs_greedy"], 2),
                "save_pct_vs_greedy_add": round(r["save_vs_greedy_add"], 2),
                "suppliers_greedy": r["sup_greedy"],
                "suppliers_milp": r["sup_milp"],
            }
            for r in cost_rows
        ],
        "value_of_resilience": [
            {
                "bom": r["bom"],
                "scenario": r["scenario"],
                "nominal_premium_pct": round(r["nominal_premium_pct"], 2),
                "cascade_risk_blind": round(r["risk_blind"], 4),
                "cascade_risk_graph": round(r["risk_graph"], 4),
                "cascade_risk_reduction": round(r["risk_reduction"], 4),
                "cvar_95_blind": round(r["cvar_blind"], 4),
                "cvar_95_graph": round(r["cvar_graph"], 4),
                "cvar_95_reduction": round(r["cvar_reduction"], 4),
            }
            for r in _resil_table_rows(cost_by_bom, resil_by_bom)
        ],
    }


def _sqlite_path() -> Optional[Path]:
    """Filesystem path behind settings.DATABASE_URL, when it is a sqlite file."""
    from app.core.config import settings

    url = str(settings.DATABASE_URL)
    if not url.startswith("sqlite"):
        return None
    raw = url.split("///", 1)[-1]
    p = Path(raw)
    return p if p.is_absolute() else (BACKEND_ROOT / raw).resolve()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    catalog = _BOM_CATALOG_OVERRIDE or BOM_CATALOG
    t_start = time.perf_counter()

    # Hash the input DB BEFORE the run appends its own optimization_runs rows —
    # otherwise the artifact records the post-write state and the "which bytes
    # produced these numbers?" question stays unanswered.
    db_path = _sqlite_path()
    prov = build_provenance(
        generator="seeds.run_benchmark",
        inputs=({"database": db_path} if db_path else {}),
    )

    db = SessionLocal()
    try:
        gs = get_graph_state()
        if gs is None:
            logger.info("GraphState not loaded — building now")
            gs = build_graph_state(db)

        run_id = next_run_id(db)
        feeds_available = snapshot_feed_availability()
        run_tag = "benchmark" if all(feeds_available.values()) else "static_fallback"
        logger.info("run_id=%d run_tag=%s feeds=%s", run_id, run_tag, feeds_available)

        total_rows = 0
        verdicts: List[Dict[str, Any]] = []
        for bom_name, bom_items in catalog.items():
            added, verdict = _run_bom(
                db, bom_name, bom_items, run_id, run_tag, gs, feeds_available,
            )
            total_rows += added
            verdicts.append(verdict)

        db.commit()
        _print_summary(db, run_id)

        # BENCH-07: never let a dropped BOM live only in a WARNING line.
        excluded = [v for v in verdicts if not v["included"]]
        n_incl = len(verdicts) - len(excluded)
        logger.info(
            "BOM COVERAGE: %d of %d catalog BOMs are in the published tables.",
            n_incl, len(verdicts),
        )
        for v in excluded:
            logger.warning("  EXCLUDED %s — %s", v["bom"], v["reason"])

        canonical_db = REPO_ROOT / "backend" / "supply_chain.db"
        prov.update({
            "run_id": run_id,
            "run_tag": run_tag,
            "boms_included": n_incl,
            "boms_in_catalog": len(verdicts),
            # The DB is hashed BEFORE this run appended its rows, so the digest
            # above is the input state. False here means the run read a copy /
            # alternate DATABASE_URL rather than the repo's committed database.
            "database_hashed_before_write": True,
            "database_path_is_repo_canonical": bool(
                db_path is not None and db_path == canonical_db
            ),
        })

        elapsed = time.perf_counter() - t_start
        payload = _build_payload(
            db, run_id, run_tag, feeds_available, verdicts, prov, elapsed,
        )
        DOCS.mkdir(parents=True, exist_ok=True)
        JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n")
        _write_markdown(db, run_id, MD_PATH, verdicts, prov)
        logger.info("wrote %s", MD_PATH.relative_to(REPO_ROOT))
        logger.info("wrote %s", JSON_PATH.relative_to(REPO_ROOT))
        logger.info(
            "Benchmark complete — run_id=%d rows=%d boms=%d/%d wall=%.1fs",
            run_id, total_rows, n_incl, len(verdicts), elapsed,
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
