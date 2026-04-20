"""
Benchmark pipeline — runs 10 hand-crafted named BOMs through the optimizer
under both graph_aware=True and graph_aware=False (balanced strategy only,
D-02). Inserts 20 OptimizationRun rows per invocation.

Produces three outputs (D-08):
  (a) Rows in optimization_runs table (run_id keyed, append-only per D-09)
  (b) Aggregate summary table printed to stdout
  (c) .planning/BENCHMARK-RESULTS.md timestamped portfolio artifact

HOLDOUT SEMANTICS (BENCH-06): run_benchmark.py uses ALL offers because the
benchmark IS the holdout evaluation. The Phase 2 holdout partition existed to
keep strategy-tuning honest; no tuning happens here, so no filter is applied.
If a future phase adds calibration, that phase filters via gs.holdout_offer_pairs.

Invocation: `python -m seeds.run_benchmark` (CLI only, never via HTTP per T-04-01).
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# sys.path boilerplate — mirrors seed_db.py
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.graph import get_graph_state
from app.graph.builder import build_graph_state
from app.graph.simulation import run_monte_carlo
from app.models import Component, Distributor, DistributorOffer, OptimizationRun
from app.optimization.costs import haversine_km
from app.optimization.routing import GeoPoint
from app.optimization.solve import DistributorMeta, optimize_bom
from app.optimization.sourcing import BomLine, Offer

logger = logging.getLogger(__name__)

# ── Canonical SF depot (fixed — interview narrative) ───────────────────────
DEPOT = GeoPoint(lat=37.7749, lng=-122.4194)

# ── Test-override hook (populated by tests; None in production) ────────────
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


def _run_one(
    db: Session,
    bom_name: str,
    bom_items: List[Tuple[str, int]],
    run_id: int,
    run_tag: str,
    graph_aware: bool,
    gs,
    feeds_available: Dict[str, bool],
) -> Optional[OptimizationRun]:
    bom, offers, distributors_meta = _load_offers_for_bom(db, bom_items)
    if not bom or not offers:
        logger.warning("BOM %s: no valid bom/offers — skipping row", bom_name)
        return None
    try:
        response = optimize_bom(
            bom=bom, offers=offers, distributors=distributors_meta,
            depot=DEPOT, us_only=False, graph_aware=graph_aware,
        )
    except Exception as exc:
        logger.warning(
            "BOM %s graph_aware=%s solver failed: %s", bom_name, graph_aware, exc
        )
        return None
    balanced = next((a for a in response.alternatives if a.id == "balanced"), None)
    if balanced is None:
        logger.warning("BOM %s: no balanced alternative", bom_name)
        return None

    comp_ids = [b.component_id for b in bom]
    try:
        mc = run_monte_carlo(gs, bom_component_ids=comp_ids)
        cascade_risk = round(1.0 - mc.p50, 4)
        mc_evar_95 = round(float(mc.evar_95), 4)
    except Exception:
        cascade_risk = 0.0
        mc_evar_95 = 1.0

    row = OptimizationRun(
        run_id=run_id,
        run_tag=run_tag,
        bom_name=bom_name,
        bom_items_json=[{"mpn": m, "quantity": q} for (m, q) in bom_items],
        strategy="balanced",
        graph_aware=graph_aware,
        total_cost_usd=float(balanced.total_cost_usd),
        total_component_cost_usd=float(balanced.total_component_cost_usd),
        total_transport_cost_usd=float(balanced.total_transport_cost_usd),
        eta_p10_days=float(balanced.eta_p10),
        eta_p50_days=float(balanced.eta_p50),
        eta_p90_days=float(balanced.eta_p90),
        co2_kg=float(balanced.total_co2e_kg),
        cascade_risk_score=cascade_risk,
        monte_carlo_samples=list(balanced.monte_carlo_samples or [])[:200],
        mc_evar_95=mc_evar_95,
        feeds_available=feeds_available,
        selected_distributor_ids=sorted({s.distributor_id for s in balanced.sourcing}),
        selected_distributor_names=sorted({s.distributor_name for s in balanced.sourcing}),
    )
    db.add(row)
    return row


def _print_summary(db: Session, run_id: int) -> None:
    rows = db.query(OptimizationRun).filter(OptimizationRun.run_id == run_id).all()
    print(f"\n=== Benchmark run_id={run_id} — {len(rows)} rows ===")
    baseline = {r.bom_name: r for r in rows if not r.graph_aware}
    graph = {r.bom_name: r for r in rows if r.graph_aware}
    print(f"{'BOM':<30}{'COST Δ%':>10}{'RISK Δ%':>10}{'ETA Δd':>10}")
    for name in sorted(baseline):
        b, g = baseline.get(name), graph.get(name)
        if not (b and g):
            continue
        cost_pct = (g.total_cost_usd - b.total_cost_usd) / max(b.total_cost_usd, 1e-9) * 100
        risk_pct = (
            (g.cascade_risk_score - b.cascade_risk_score)
            / max(b.cascade_risk_score, 1e-9) * 100
        )
        eta_d = g.eta_p50_days - b.eta_p50_days
        print(f"{name:<30}{cost_pct:>10.2f}{risk_pct:>10.2f}{eta_d:>10.2f}")


def _write_markdown(db: Session, run_id: int, out_path: Path) -> None:
    rows = db.query(OptimizationRun).filter(OptimizationRun.run_id == run_id).all()
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    baseline = {r.bom_name: r for r in rows if not r.graph_aware}
    graph = {r.bom_name: r for r in rows if r.graph_aware}
    lines = [
        f"# Benchmark Results — run_id={run_id}",
        "",
        f"**Generated:** {ts}",
        f"**Rows:** {len(rows)} (10 BOMs × 2 graph_aware)",
        f"**Seed:** 42 · **Strategy:** balanced (D-02) · **Holdout:** benchmark IS the holdout",
        "",
        "| BOM | Cost Δ% | Risk Δ% | ETA Δdays |",
        "|-----|---------|---------|-----------|",
    ]
    for name in sorted(baseline):
        b, g = baseline.get(name), graph.get(name)
        if not (b and g):
            continue
        cost_pct = (g.total_cost_usd - b.total_cost_usd) / max(b.total_cost_usd, 1e-9) * 100
        risk_pct = (
            (g.cascade_risk_score - b.cascade_risk_score)
            / max(b.cascade_risk_score, 1e-9) * 100
        )
        eta_d = g.eta_p50_days - b.eta_p50_days
        lines.append(f"| {name} | {cost_pct:+.2f} | {risk_pct:+.2f} | {eta_d:+.2f} |")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    catalog = _BOM_CATALOG_OVERRIDE or BOM_CATALOG

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

        for bom_name, bom_items in catalog.items():
            for graph_aware in (False, True):
                _run_one(
                    db, bom_name, bom_items, run_id, run_tag,
                    graph_aware, gs, feeds_available,
                )

        db.commit()
        _print_summary(db, run_id)
        _write_markdown(db, run_id, Path(".planning/BENCHMARK-RESULTS.md"))
        logger.info("Benchmark complete — run_id=%d", run_id)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
