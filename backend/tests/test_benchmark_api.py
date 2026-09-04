"""
Benchmark API endpoint tests (04-02).

Covers:
  - GET /benchmark/summary — response shape, delta math, error states
  - GET /benchmark/fiedler-curve — shape, baseline step, 503 when no graph
  - GET /benchmark/cascade-heatmap — shape, empty-DB returns empty list
  - GET /benchmark/single-source-components — real ORM data, no fabricated strings

Tests: 14+ covering BENCH-02, BENCH-05, BENCH-06, VIZ-02.

NOTE: Each test that needs specific DB state uses a fresh in-memory SQLite engine
and its own TestClient to avoid cross-test contamination. The lifespan graph build
runs against the real DB during startup but is isolated per-fixture via monkeypatching
of app.graph.get_graph_state where needed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure backend root on path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-characters-long-for-testing")
os.environ.setdefault("DEBUG", "true")

import pytest
from dataclasses import dataclass, field
from typing import FrozenSet, Dict, List, Optional
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.models.optimization_run import OptimizationRun
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor


# ── Mock GraphState ────────────────────────────────────────────────────────────

@dataclass
class _MockGraphState:
    """Minimal GraphState mock sufficient for benchmark endpoint tests."""
    graph: object = None
    dist_nodes: FrozenSet[str] = field(default_factory=frozenset)
    betweenness: Dict[int, float] = field(default_factory=dict)
    pagerank: Dict[int, float] = field(default_factory=dict)
    k_core: Dict[str, int] = field(default_factory=dict)
    single_source_component_ids: FrozenSet[int] = field(default_factory=frozenset)
    hhi_by_category: Dict[str, float] = field(default_factory=dict)
    fiedler: float = 0.25
    fiedler_curve: List[dict] = field(default_factory=list)
    n_distributors: int = 3
    n_components: int = 10
    n_edges: int = 15


def _make_fiedler_curve():
    """6-entry Fiedler curve for mock GraphState.

    Step 0 carries the collapse check's provenance (`boms_checked` / `bom_source`),
    exactly as `app.main.compute_fiedler_curve` writes it.
    """
    return [
        {"step": 0, "removed": None, "removed_name": None, "lambda2": 0.25, "delta_pct": 0.0,
         "collapsed_boms": [], "boms_checked": 4,
         "bom_source": "benchmark run_id=7 (4 BOMs), checked against the offer graph"},
        {"step": 1, "removed": 1, "removed_name": "DigiKey", "lambda2": 0.20, "delta_pct": -20.0, "collapsed_boms": []},
        {"step": 2, "removed": 2, "removed_name": "Mouser", "lambda2": 0.15, "delta_pct": -40.0, "collapsed_boms": ["bom_01"]},
        {"step": 3, "removed": 3, "removed_name": "Arrow", "lambda2": 0.10, "delta_pct": -60.0, "collapsed_boms": ["bom_01", "bom_02"]},
        {"step": 4, "removed": 4, "removed_name": "Avnet", "lambda2": 0.05, "delta_pct": -80.0, "collapsed_boms": ["bom_01", "bom_02", "bom_03"]},
        {"step": 5, "removed": 5, "removed_name": "Newark", "lambda2": 0.01, "delta_pct": -96.0, "collapsed_boms": ["bom_01", "bom_02", "bom_03", "bom_04"]},
    ]


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _make_test_db():
    """Return (engine, SessionClass) for a fresh in-memory SQLite DB.

    Uses StaticPool so all connections share a single in-memory database
    instance — without this, each SQLite :memory: connection gets an
    empty independent DB and 'no such table' errors occur.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return engine, Session


def _make_client_with_db(session):
    """
    Return a TestClient with the given session injected as the DB dependency.
    The graph state is always set to a real-looking mock to avoid the lifespan
    blocking on the real DB build. We do NOT override get_graph_state globally —
    individual tests patch it as needed.
    """
    def _override():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    client = TestClient(app, raise_server_exceptions=False)
    return client


def _make_benchmark_rows(
    session, run_id=1, baseline_cost=100.0, graph_aware_cost=90.0,
    greedy_cost=120.0, greedy_add_cost=110.0,
    greedy_dom_cost=None, greedy_add_dom_cost=None,
    with_matched_pool_arms=True,
    per_bom_costs=None,
    greedy_distributors=None,
    graph_distributors=None,
    dom_distributors=None,
):
    """
    Insert the benchmark 2.0 schema: 10 BOMs × 10 rows = 100 rows for run_id.

    Per BOM:
      • Cost story (scenario='nominal'): greedy, greedy_add, greedy_dom,
        greedy_add_dom, milp-blind, milp-graph.
        `baseline_cost`/`graph_aware_cost` are the two MILP nominal costs so the
        graph-aware A/B still reads cleanly; greedy costs are higher (MILP wins).
        The two `_dom` arms are the POOL-MATCHED baselines — the same heuristics
        re-solved on the MILP's domestic-only catalogue — and they default to
        costs BETWEEN the global-pool baselines and the MILP, which is the real
        ordering: matching the pool shrinks the apparent saving without erasing
        it. `with_matched_pool_arms=False` reproduces a pre-run_id=8 run that
        carries no matched arms at all, so the "we did not measure this" path is
        exercised rather than assumed.
      • Resilience story: milp blind+graph under scenario in {stress, targeted},
        with graph-aware showing lower plan_cascade_risk / mc_cvar_95.

    `per_bom_costs` — optional list of (greedy, greedy_add, milp_blind, milp_graph)
    tuples, one per BOM. WITHOUT it every BOM gets identical costs, which makes the
    pooled aggregation and the mean of per-BOM percentages numerically EQUAL — a
    fixture that cannot tell the two apart and therefore cannot catch the defect
    where the endpoint serves one while labelling it the other. Pass it whenever a
    test's subject is the aggregation itself.

    `greedy_distributors` / `graph_distributors` — optional (ids, names) pairs used
    for the greedy arm and the graph-aware MILP arm, so a test can express "the
    graph-aware plan kept the blind distributor and added one" or "it replaced it",
    and so international-supplier counting has something to count.
    """
    bom_names = [f"bom_{i:02d}" for i in range(1, 11)]
    blind_ids, blind_names = [1, 2], ["DigiKey", "Mouser"]
    g_ids, g_names = greedy_distributors or (blind_ids, blind_names)
    ga_ids, ga_names = graph_distributors or (blind_ids, blind_names)
    # The matched arms shop the domestic pool, so by default they open the blind
    # MILP's (domestic) distributors rather than greedy's possibly-foreign ones.
    dom_ids, dom_names = dom_distributors or (blind_ids, blind_names)
    if greedy_dom_cost is None:
        greedy_dom_cost = (greedy_cost + baseline_cost) / 2.0
    if greedy_add_dom_cost is None:
        greedy_add_dom_cost = (greedy_add_cost + baseline_cost) / 2.0

    def _row(bom, arm, graph_aware, scenario, cost, suppliers,
             plan_risk, cvar, has_eta=True, dist_ids=None, dist_names=None):
        return OptimizationRun(
            run_id=run_id,
            run_tag="benchmark",
            bom_name=bom,
            bom_items_json=[{"component_id": 1, "quantity": 1}],
            strategy="balanced",
            arm=arm,
            graph_aware=graph_aware,
            scenario=scenario,
            total_cost_usd=cost,
            total_component_cost_usd=cost * 0.9,
            total_transport_cost_usd=cost * 0.1,
            eta_p10_days=4.0 if has_eta else 0.0,
            eta_p50_days=(5.0 if not graph_aware else 5.5) if has_eta else 0.0,
            eta_p90_days=6.0 if has_eta else 0.0,
            co2_kg=(2.5 if not graph_aware else 2.3) if has_eta else 0.0,
            cascade_risk_score=0.4,
            plan_cascade_risk=plan_risk,
            n_distinct_suppliers=suppliers,
            n_orders=suppliers,
            monte_carlo_samples=[float(i) for i in range(10)] if has_eta else [],
            mc_cvar_95=cvar,
            feeds_available={"gpr": True, "acled": True},
            selected_distributor_ids=list(dist_ids if dist_ids is not None else blind_ids),
            selected_distributor_names=list(
                dist_names if dist_names is not None else blind_names
            ),
        )

    for i, bom in enumerate(bom_names):
        if per_bom_costs is not None:
            g_cost, ga_add_cost, b_cost, gr_cost = per_bom_costs[i % len(per_bom_costs)]
        else:
            g_cost, ga_add_cost, b_cost, gr_cost = (
                greedy_cost, greedy_add_cost, baseline_cost, graph_aware_cost
            )
        # Cost story (nominal)
        session.add(_row(bom, "greedy", False, "nominal", g_cost, 4, 0.30, 6.8,
                         has_eta=False, dist_ids=g_ids, dist_names=g_names))
        session.add(_row(bom, "greedy_add", False, "nominal", ga_add_cost, 3, 0.28, 6.7,
                         has_eta=False, dist_ids=g_ids, dist_names=g_names))
        if with_matched_pool_arms:
            session.add(_row(
                bom, "greedy_dom", False, "nominal", greedy_dom_cost, 4, 0.30, 6.8,
                has_eta=False, dist_ids=dom_ids, dist_names=dom_names,
            ))
            session.add(_row(
                bom, "greedy_add_dom", False, "nominal", greedy_add_dom_cost, 3,
                0.28, 6.7, has_eta=False, dist_ids=dom_ids, dist_names=dom_names,
            ))
        session.add(_row(bom, "milp", False, "nominal", b_cost, 2, 0.20, 6.5))
        session.add(_row(bom, "milp", True, "nominal", gr_cost, 2, 0.18, 6.0,
                         dist_ids=ga_ids, dist_names=ga_names))
        # Resilience story (disruption)
        session.add(_row(bom, "milp", False, "stress", b_cost, 2, 0.50, 7.2))
        session.add(_row(bom, "milp", True, "stress", gr_cost, 2, 0.32, 6.4,
                         dist_ids=ga_ids, dist_names=ga_names))
        session.add(_row(bom, "milp", False, "targeted", b_cost, 2, 0.60, 7.6))
        session.add(_row(bom, "milp", True, "targeted", gr_cost, 2, 0.36, 6.5,
                         dist_ids=ga_ids, dist_names=ga_names))
    session.commit()


# ── Tests: /benchmark/summary ─────────────────────────────────────────────────

def test_summary_returns_required_keys():
    """GET /benchmark/summary with 20 rows → 200 with all required keys."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        required_keys = {
            "run_id", "n_boms", "cost_delta_pct", "eta_delta_pct",
            "co2_delta_pct", "cascade_risk_delta_pct", "monte_carlo",
            "tradeoff", "bom_deltas", "feeds_fallback",
            # Renamed from `noise_floor_pct` — it was a hardcoded 2.0 rendered
            # as "this run's 2.0% noise floor" and derived from nothing.
            "materiality_threshold_pct", "materiality_threshold_basis",
            # benchmark 2.0 — value of optimization
            "savings_pct", "savings_usd_per_bom", "savings_usd_annualized",
            "annual_reorders", "avg_suppliers_greedy", "avg_suppliers_milp",
            # 2026-09-03: the aggregation is named, the other one is published
            # under its own name, every baseline arm in the DB is served, and the
            # offer-pool asymmetry travels with the number.
            "savings_pct_aggregation", "savings_pct_mean_of_boms",
            "savings_pct_mean_of_boms_note", "baselines", "pool_asymmetry",
            # benchmark 2.0 — value of resilience
            "resilience",
        }
        for key in required_keys:
            assert key in data, f"Missing key: {key}"

        resil_keys = {
            "nominal_cost_premium_pct",
            "stress_cascade_risk_reduction", "stress_cvar95_reduction",
            "targeted_cascade_risk_reduction", "targeted_cvar95_reduction",
        }
        for key in resil_keys:
            assert key in data["resilience"], f"Missing resilience key: {key}"
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_savings_partition_greedy_vs_milp():
    """greedy=$120, milp=$100 → savings_pct=+16.67%, savings_usd_per_bom=$20,
    annualized = $20 × ANNUAL_REORDERS, and suppliers consolidate 4 → 2.

    NOTE: every BOM in this fixture has the same cost pair, so pooled and
    mean-of-BOMs agree here BY CONSTRUCTION and this test cannot tell them apart.
    `test_savings_pct_is_pooled_not_a_mean_of_bom_percentages` is the one that can.
    """
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, baseline_cost=100.0, greedy_cost=120.0)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # (120 - 100) / 120 * 100 = 16.666...
        assert abs(data["savings_pct"] - 16.67) < 0.05, data["savings_pct"]
        assert abs(data["savings_usd_per_bom"] - 20.0) < 0.01
        assert abs(
            data["savings_usd_annualized"] - 20.0 * data["annual_reorders"]
        ) < 0.01
        assert data["avg_suppliers_greedy"] == 4.0
        assert data["avg_suppliers_milp"] == 2.0
    finally:
        app.dependency_overrides.clear()
        session.close()


# ── Tests: the two averages, the second baseline, and the offer pool ─────────
# (2026-09-03 audit — three defects that all rendered on the live site)

def test_savings_pct_is_pooled_not_a_mean_of_bom_percentages():
    """
    The endpoint served `savings_pct` as the unweighted MEAN of per-BOM
    percentages while `volume_curve` beside it served the POOLED figure — two
    different statistics of the same quantity in one response, neither labelled.

    This fixture makes the two numerically different so the test can actually
    fail: half the BOMs save 50% on $100, half save 20% on $1,000.
      mean of BOM percentages = (50 + 20) / 2      = 35.00%
      pooled                  = (5500 - 4250)/5500 = 22.73%
    """
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, per_bom_costs=[
        # (greedy, greedy_add, milp_blind, milp_graph)
        (100.0, 90.0, 50.0, 55.0),
        (1000.0, 950.0, 800.0, 850.0),
    ])
    client = _make_client_with_db(session)

    try:
        data = client.get("/api/v1/benchmark/summary").json()
        assert abs(data["savings_pct"] - 22.73) < 0.05, (
            f"savings_pct is {data['savings_pct']} — the mean of per-BOM "
            "percentages is 35.00 and the pooled figure is 22.73; the headline "
            "must be the pooled one"
        )
        assert abs(data["savings_pct_mean_of_boms"] - 35.0) < 0.05
        # Both must be named where they are served, not left to the reader.
        assert "POOLED" in data["savings_pct_aggregation"]
        assert "MEAN OF PER-BOM PERCENTAGES" in data["savings_pct_mean_of_boms_note"]
        # And the headline must use the same aggregation as the curve beside it.
        assert "POOLED" in data["volume_curve"]["aggregate_definition"]
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_serves_the_greedy_add_baseline_beside_greedy():
    """
    `greedy_add` (the ADD heuristic) has been written to every benchmark run since
    the 2.0 schema and the API served only `greedy`, so the published percentage
    was the optimizer's edge over the WEAKEST baseline available. Both arms must
    now appear, pooled, with the ADD heuristic showing the smaller saving.
    """
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(
        session, baseline_cost=100.0, greedy_cost=200.0, greedy_add_cost=125.0,
    )
    client = _make_client_with_db(session)

    try:
        data = client.get("/api/v1/benchmark/summary").json()
        by_arm = {b["arm"]: b for b in data["baselines"]}
        assert set(by_arm) == {
            "greedy", "greedy_add", "greedy_dom", "greedy_add_dom",
        }, by_arm.keys()
        # (200-100)/200 = 50%;  (125-100)/125 = 20%
        assert abs(by_arm["greedy"]["pooled_savings_pct"] - 50.0) < 0.05
        assert abs(by_arm["greedy_add"]["pooled_savings_pct"] - 20.0) < 0.05
        assert (
            by_arm["greedy_add"]["pooled_savings_pct"]
            < by_arm["greedy"]["pooled_savings_pct"]
        ), "the fairer baseline must not be hidden behind the weaker one"
        for b in by_arm.values():
            assert b["label"] and b["description"] and b["pool"]
            assert b["milp_total_cost_usd"] > 0
        # Exactly one baseline is the claim, and it is the pool-matched ADD arm.
        primary = [b["arm"] for b in data["baselines"] if b["is_primary"]]
        assert primary == ["greedy_add_dom"], primary
        assert by_arm["greedy_dom"]["matched_pool"] is True
        assert by_arm["greedy_add_dom"]["matched_pool"] is True
        assert by_arm["greedy"]["matched_pool"] is False
        assert by_arm["greedy_add"]["matched_pool"] is False
        # The like-for-like figure is served under its own name and is the
        # SMALLEST of the four — the whole point of publishing all of them.
        assert data["savings_pct_matched_pool_arm"] == "greedy_add_dom"
        assert abs(
            data["savings_pct_matched_pool"]
            - by_arm["greedy_add_dom"]["pooled_savings_pct"]
        ) < 1e-9
        assert data["savings_pct_matched_pool"] == min(
            b["pooled_savings_pct"] for b in data["baselines"]
        )
        assert data["primary_claim"]
        # And a reader who only reads `caveats` is told the same thing.
        assert any("greedy_add" in c for c in data["caveats"])
        assert any("LIKE-FOR-LIKE FIGURE" in c for c in data["caveats"])
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_serves_no_matched_pool_number_when_the_run_has_no_matched_arms():
    """A run written before 2026-09-03 carries no `_dom` arms.

    "We did not measure this" must be served as null and said in words — never
    as a zero, and never by quietly falling back to the unmatched figure, which
    would restore the exact overclaim the matched arms exist to remove.
    """
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, with_matched_pool_arms=False)
    client = _make_client_with_db(session)

    try:
        data = client.get("/api/v1/benchmark/summary").json()
        assert {b["arm"] for b in data["baselines"]} == {"greedy", "greedy_add"}
        assert data["savings_pct_matched_pool"] is None
        assert data["savings_pct_matched_pool_arm"] is None
        assert not any(b["is_primary"] for b in data["baselines"])
        assert data["pool_asymmetry"]["matched"] is False
        assert data["pool_asymmetry"]["matched_finding"] is None
        assert data["pool_asymmetry"]["points_from_optimizer"] is None
        assert "NOT computed" in data["pool_asymmetry"]["unmatched_side"]
        assert "run_id=8" in data["savings_pct_matched_pool_note"]
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_discloses_the_offer_pool_asymmetry_with_counts():
    """
    The greedy arm shops the full international pool; the MILP arm is
    domestic-only. That was disclosed nowhere the reader could see it. The
    disclosure must now ship WITH the number, and it must be counted off the
    stored plans rather than asserted.
    """
    _, Session = _make_test_db()
    session = Session()
    # Two distributors the greedy arm opens: one US, one Chinese.
    session.add(Distributor(
        id=1, name="DigiKey", country="USA", city="Thief River Falls",
        latitude=48.1, longitude=-96.2, is_domestic=True,
    ))
    session.add(Distributor(
        id=2, name="Worldway Electronics", country="China", city="Shenzhen",
        latitude=22.5, longitude=114.1, is_domestic=False,
    ))
    session.commit()
    _make_benchmark_rows(
        session,
        greedy_distributors=([1, 2], ["DigiKey", "Worldway Electronics"]),
    )
    client = _make_client_with_db(session)

    try:
        data = client.get("/api/v1/benchmark/summary").json()
        pa = data["pool_asymmetry"]
        # The fixture carries the matched arms, so the greedy side of the match
        # is measured on this run and the flag says so.
        assert pa["matched"] is True
        assert "us_only=False" in pa["greedy_pool"]
        assert "domestic" in pa["milp_pool"].lower()
        # 10 BOMs x 2 greedy distributors, one of them foreign.
        assert pa["greedy_suppliers_opened"] == 20
        assert pa["greedy_international_suppliers_opened"] == 10
        # The blind MILP rows use distributor 1 (US) and 2 — but only the greedy
        # arm was given the Chinese one, so the MILP side must count what it holds.
        assert pa["milp_suppliers_opened"] == 20
        # The disclosure sentence carries the counts and the fee gap.
        assert "NOT A LIKE-FOR-LIKE" in pa["statement"]
        assert "10 international" in pa["statement"]
        # It must also ride along with the bare number a UI might render.
        assert "supplier pool" in data["savings_pct_display_label"].lower()
        assert any("LIKE-FOR-LIKE" in c for c in data["caveats"])
        # And the matched-pool control comes from the committed sweep artifact.
        assert pa["control_source"] == "docs/volume_sweep.json"
        assert pa["control_finding"]
        assert pa["control_savings_pct_domestic_pool"] is not None
        assert pa["control_savings_pct_full_pool"] is not None
        # The greedy side of the match IS computed now, from this run's own
        # `greedy_dom` / `greedy_add_dom` rows — and the three handicap terms it
        # publishes must add up to the unmatched headline, or the disclosure is
        # just a fourth inconsistent number.
        assert pa["matched_baseline_arm"] == "greedy_add_dom"
        assert pa["matched_finding"]
        assert pa["matched_savings_pct_vs_greedy_add"] is not None
        assert abs(
            pa["points_from_weaker_heuristic"]
            + pa["points_from_wider_baseline_catalogue"]
            + pa["points_from_optimizer"]
            - data["savings_pct"]
        ) < 0.011, (
            "the handicap decomposition must reconcile to the published "
            "savings_pct"
        )
        assert "RESOLVED" in pa["unmatched_side"]
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_tradeoff_narrative_is_derived_from_the_plans_not_templated():
    """
    The tradeoff card printed a HARDCODED sentence — "the cheapest distributor
    carries a high-centrality component and graph-aware routes around it" — under
    a heading that says HONEST TRADEOFF. On the served run it was false: the
    graph-aware plan KEPT the blind plan's distributor and ADDED a second.

    Here the graph-aware arm keeps DigiKey/Mouser and adds Arrow, so the sentence
    must say a supplier was added and must NOT claim anything was routed around.
    """
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(
        session,
        baseline_cost=100.0, graph_aware_cost=180.0,   # graph-aware LOSES on cost
        graph_distributors=([1, 2, 3], ["Arrow", "DigiKey", "Mouser"]),
    )
    client = _make_client_with_db(session)

    try:
        data = client.get("/api/v1/benchmark/summary").json()
        t = data["tradeoff"]
        assert t["blind_distributors"] == ["DigiKey", "Mouser"]
        assert t["graph_aware_distributors"] == ["Arrow", "DigiKey", "Mouser"]
        assert t["distributors_added"] == ["Arrow"]
        assert t["distributors_dropped"] == []
        assert t["distributors_kept"] == ["DigiKey", "Mouser"]
        assert "routes around" not in t["narrative"].lower()
        assert "NOTHING WAS ROUTED AROUND" in t["narrative"]
        assert "Arrow" in t["narrative"], (
            "the sentence must name what actually changed in the plan"
        )
        # And the panel-wide attribution must name the mechanism it can support.
        assert t["mechanism"]
        assert "ATTRIBUTION" in t["mechanism"]
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_tradeoff_narrative_says_replaced_when_the_plan_is_actually_replaced():
    """
    The counterpart: when the graph-aware arm genuinely drops the blind plan's
    distributors, the sentence must say so. A narrative that always reports the
    same story is not derived from anything — this is the case that proves the
    previous test's assertion could go the other way.
    """
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(
        session,
        baseline_cost=100.0, graph_aware_cost=180.0,
        graph_distributors=([3, 4], ["Arrow", "Avnet"]),   # nothing kept
    )
    client = _make_client_with_db(session)

    try:
        t = client.get("/api/v1/benchmark/summary").json()["tradeoff"]
        assert t["distributors_dropped"] == ["DigiKey", "Mouser"]
        assert t["distributors_kept"] == []
        assert "REPLACED" in t["narrative"]
        assert "genuine re-route" in t["narrative"]
        assert "NOTHING WAS ROUTED AROUND" not in t["narrative"]
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_resilience_reductions_positive_under_disruption():
    """graph-aware lowers cascade risk + cvar under stress and targeted outage,
    while nominal cost premium stays negative (graph-aware slightly cheaper)."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, baseline_cost=100.0, graph_aware_cost=90.0)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200, resp.text
        r = resp.json()["resilience"]
        # blind 0.50 vs graph 0.32 under stress → reduction +0.18
        assert abs(r["stress_cascade_risk_reduction"] - 0.18) < 1e-6
        # blind 7.2 vs graph 6.4 → +0.8
        assert abs(r["stress_cvar95_reduction"] - 0.8) < 1e-6
        # blind 0.60 vs graph 0.36 under targeted → +0.24
        assert abs(r["targeted_cascade_risk_reduction"] - 0.24) < 1e-6
        # nominal premium = (90 - 100)/100 = -10% (graph-aware cheaper)
        assert abs(r["nominal_cost_premium_pct"] - (-10.0)) < 0.01
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_empty_db_returns_404():
    """GET /benchmark/summary with empty DB → 404 with benchmark pipeline hint."""
    _, Session = _make_test_db()
    session = Session()
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 404
        # Detail must guide user to run the benchmark pipeline
        # (string "run_benchmark" is forbidden in app/ per T-04-01 security guard)
        detail = resp.json()["detail"]
        assert "benchmark" in detail.lower(), f"Expected benchmark hint in 404 detail, got: {detail!r}"
        assert "pipeline" in detail.lower() or "python" in detail.lower(), (
            f"Expected execution hint in 404 detail, got: {detail!r}"
        )
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_cost_delta_pct_sign_convention():
    """Baseline cost=$100, graph-aware cost=$90 → cost_delta_pct = -10.0."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, baseline_cost=100.0, graph_aware_cost=90.0)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200
        delta = resp.json()["cost_delta_pct"]
        # (90 - 100) / 100 * 100 = -10.0
        assert abs(delta - (-10.0)) < 0.01, f"Expected -10.0, got {delta}"
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_run_id_param():
    """?run_id=1 returns run 1 data when two run groups exist."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, run_id=1, baseline_cost=100.0, graph_aware_cost=90.0)
    _make_benchmark_rows(session, run_id=2, baseline_cost=200.0, graph_aware_cost=180.0)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary?run_id=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == 1
        # run 1 cost delta should be -10%
        assert abs(data["cost_delta_pct"] - (-10.0)) < 0.01
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_missing_run_id_returns_404():
    """?run_id=999 with no such rows → 404."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, run_id=1)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary?run_id=999")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
        session.close()


# ── Tests: /benchmark/fiedler-curve ──────────────────────────────────────────

def test_fiedler_curve_requires_graph_state():
    """No graph state → 503."""
    _, Session = _make_test_db()
    session = Session()
    client = _make_client_with_db(session)

    try:
        with patch("app.graph.get_graph_state", return_value=None):
            resp = client.get("/api/v1/benchmark/fiedler-curve")
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_fiedler_curve_shape():
    """Mock GraphState with 6-entry fiedler_curve → 200, len(points)==6."""
    _, Session = _make_test_db()
    session = Session()
    client = _make_client_with_db(session)
    gs = _MockGraphState(fiedler_curve=_make_fiedler_curve())

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/fiedler-curve")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "points" in data
        assert len(data["points"]) == 6
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_fiedler_curve_baseline_is_step_zero():
    """points[0].step == 0 and points[0].removed is None."""
    _, Session = _make_test_db()
    session = Session()
    client = _make_client_with_db(session)
    gs = _MockGraphState(fiedler_curve=_make_fiedler_curve())

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/fiedler-curve")
        assert resp.status_code == 200
        pt0 = resp.json()["points"][0]
        assert pt0["step"] == 0
        assert pt0["removed"] is None
        assert pt0["removed_name"] is None
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_fiedler_curve_publishes_collapse_provenance():
    """boms_checked / bom_source are served, so an empty collapsed_boms list is
    never ambiguous.

    Regression guard for the affordance that could not fire: `collapsed_boms` was
    documented on the schema and read by the endpoint while nothing ever wrote it,
    so all 6 served points returned [] and the page still invited "Click a point to
    see which BOMs collapse".
    """
    _, Session = _make_test_db()
    session = Session()
    client = _make_client_with_db(session)
    gs = _MockGraphState(fiedler_curve=_make_fiedler_curve())

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/fiedler-curve")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["boms_checked"] == 4
        assert "run_id=7" in data["bom_source"]
        # And the per-step lists survive serialization rather than being flattened.
        assert data["points"][2]["collapsed_boms"] == ["bom_01"]
        assert data["points"][5]["collapsed_boms"] == [
            "bom_01", "bom_02", "bom_03", "bom_04",
        ]
        assert any(p["collapsed_boms"] for p in data["points"]), (
            "every point returned an empty collapse list — the key is not being "
            "carried through the endpoint"
        )
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_materiality_threshold_is_labelled_as_an_assumption():
    """The 2.0% cut must ship with its own provenance and must NOT be called noise.

    It was served as `noise_floor_pct` and rendered as "well above this run's 2.0%
    noise floor" while being a literal constant derived from neither solver
    tolerance nor replicate variance.
    """
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert "noise_floor_pct" not in data, (
            "the field is still published under a name that claims a measurement"
        )
        assert data["materiality_threshold_pct"] == 2.0
        basis = data["materiality_threshold_basis"].lower()
        assert "assumed" in basis
        assert "not a measured noise floor" in basis
        # It must say WHY there is nothing to measure, not just that there isn't.
        assert "replicates" in basis
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_cascade_risk_metric_is_not_called_a_probability():
    """`cascade_risk_metric` is the string the UI quotes for this quantity.

    plan_cascade_risk is 1 - the median fraction of a BOM's LINES that stay
    fulfillable. No base rate, no exposure window, quantised to quarters on 4-line
    BOMs — a share, not a probability.
    """
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200, resp.text
        metric = resp.json()["cascade_risk_metric"]
        assert "SHARE on 0-1, not a probability" in metric, metric
        assert "LINES" in metric
    finally:
        app.dependency_overrides.clear()
        session.close()


# ── Tests: /benchmark/cascade-heatmap ────────────────────────────────────────

def test_cascade_heatmap_empty_db_returns_empty_list():
    """No rows → 200 with empty points list (not 404)."""
    _, Session = _make_test_db()
    session = Session()
    client = _make_client_with_db(session)
    gs = _MockGraphState()

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/cascade-heatmap")
        assert resp.status_code == 200
        assert resp.json()["points"] == []
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_cascade_heatmap_has_lat_lng_weight():
    """With rows and distributor data → returns dicts with lat, lng, weight."""
    _, Session = _make_test_db()
    session = Session()

    # Seed distributor
    dist = Distributor(
        id=1, name="DigiKey", latitude=48.1, longitude=-96.2,
        city="Thief River Falls", state="MN", country="USA", is_domestic=True,
    )
    session.add(dist)
    session.commit()

    # Seed benchmark rows referencing distributor id=1
    _make_benchmark_rows(session)

    client = _make_client_with_db(session)
    gs = _MockGraphState()

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/cascade-heatmap")
        assert resp.status_code == 200
        data = resp.json()
        assert "points" in data
        # Should have at least one point for distributor 1
        if data["points"]:
            pt = data["points"][0]
            assert "lat" in pt
            assert "lng" in pt
            assert "weight" in pt
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_cascade_heatmap_is_not_structurally_empty():
    """2026-08 audit item 2. The heatmap returned `{"points": []}` against a fully
    populated database because it scored on `cascade_risk_score` — a column that is
    exactly 0.0 in all 234 rows ever written — and then dropped every point with a
    `normalized_weight > 0` guard. It now scores on `plan_cascade_risk` and keeps
    zero-weight points, which are a result rather than an absence."""
    _, Session = _make_test_db()
    session = Session()
    session.add_all([
        Distributor(id=1, name="DigiKey", latitude=48.1, longitude=-96.2,
                    city="Thief River Falls", state="MN", country="USA", is_domestic=True),
        Distributor(id=2, name="Mouser", latitude=32.2, longitude=-97.1,
                    city="Mansfield", state="TX", country="USA", is_domestic=True),
    ])
    session.commit()
    _make_benchmark_rows(session)

    client = _make_client_with_db(session)
    try:
        with patch("app.graph.get_graph_state", return_value=_MockGraphState()):
            resp = client.get("/api/v1/benchmark/cascade-heatmap")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["points"], (
            "the heatmap returned no points despite 80 benchmark rows and 2 "
            "distributors with coordinates — the audited failure"
        )
        assert data["n_distributors_scored"] == 2
        assert data["max_raw_weight"] > 0.0
        assert data["note"], "an empty-looking heatmap must explain itself"
        assert "plan_cascade_risk" in data["metric"]
        assert "cascade_risk_score" in data["metric"]  # named as the DEAD column
    finally:
        app.dependency_overrides.clear()
        session.close()


# ── Tests: the retracted headline (2026-08 audit item 1) ─────────────────────

def test_summary_serves_the_volume_curve_not_a_headline_percentage():
    """`savings_pct` alone is the retracted 44.7%-style claim. The endpoint must
    serve the volume-dependent truth and the decomposition instead."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        head = data["headline"]
        assert head["do_not_quote_a_single_percentage"] is True
        assert head["retracted_claim"]
        assert head["retraction_reason"]
        assert "44.7" in head["retraction_reason"]
        assert data["headline_retracted"] is True

        curve = data["volume_curve"]
        assert curve["available"] is True, curve.get("unavailable_reason")
        pts = curve["points"]
        assert len(pts) >= 5, "a curve needs enough points to show the decay"
        assert [p["multiplier"] for p in pts] == sorted(p["multiplier"] for p in pts)

        # The decay itself: the prototype figure must be far above the production one.
        first = pts[0]
        production = [p for p in pts if p["multiplier"] >= 500]
        assert production, "no production-volume points on the curve"
        assert first["pooled_savings_pct"] > max(
            p["pooled_savings_pct"] for p in production
        ), "the curve does not decay — the retraction is not being demonstrated"
        assert data["realistic_savings_pct_high"] < first["pooled_savings_pct"]

        # And the decomposition that explains WHY.
        proto = data["decomposition_at_prototype_volume"]
        assert proto["dominant_term"] == "fixed per-supplier fees"
        assert proto["from_component_cost_usd"] < 0, (
            "at 1x the MILP pays MORE for parts — that is the whole point"
        )
        assert data["fixed_fee_per_supplier_usd"] > 0
        assert curve["cohort_caveat"], "the shrinking-cohort caveat must be served"
        assert data["caveats"]
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_labels_the_prototype_percentage_and_its_units():
    """`cost_delta_usd` and `savings_pct` were numerically identical (48.09) on the
    published run, which read as a percentage sitting in a USD field. They are
    different quantities from different arms; both now carry their unit."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session)
    client = _make_client_with_db(session)

    try:
        data = client.get("/api/v1/benchmark/summary").json()
        assert data["savings_units"] == "percent"
        assert data["cost_delta_units"] == "usd"
        assert data["savings_pct_is_prototype_volume_only"] is True
        assert data["savings_pct_display_label"], (
            "a UI rendering the bare savings_pct reproduces the retracted headline"
        )
        assert "prototype" in data["savings_pct_display_label"]
        # The label must also name the aggregation and the pool asymmetry, so the
        # two things that make the bare number misleading travel with it.
        assert "pooled" in data["savings_pct_display_label"].lower()
        # "pool" alone is satisfied by the word "pooled" — assert the phrase that
        # can only come from the disclosure itself.
        assert "supplier pool" in data["savings_pct_display_label"].lower()
        assert data["run_tag_meaning"], "run_tag is opaque without this"
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_cascade_risk_delta_uses_the_live_column():
    """`cascade_risk_delta_pct` was pinned at 0.0 for every BOM because it read the
    dead `cascade_risk_score`. The fixture sets blind 0.20 vs graph-aware 0.18 on
    `plan_cascade_risk`, so the delta must now be -10%."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session)
    client = _make_client_with_db(session)

    try:
        data = client.get("/api/v1/benchmark/summary").json()
        assert abs(data["cascade_risk_delta_pct"] - (-10.0)) < 0.01, (
            data["cascade_risk_delta_pct"]
        )
        assert "plan_cascade_risk" in data["cascade_risk_metric"]
        for bd in data["bom_deltas"]:
            assert abs(bd["cascade_risk_delta_pct"] - (-10.0)) < 0.01
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_summary_explains_a_flat_resilience_reduction():
    """A reduction of exactly 0.0 is a measurement, not a gap — the two arm means
    that produced it must be published beside it."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session)
    client = _make_client_with_db(session)

    try:
        r = client.get("/api/v1/benchmark/summary").json()["resilience"]
        assert r["interpretation"]
        assert r["measured_values"]["stress_blind_mc_cvar_95"] == 7.2
        assert r["measured_values"]["stress_graph_mc_cvar_95"] == 6.4
        assert isinstance(r["flat_metrics"], list)
    finally:
        app.dependency_overrides.clear()
        session.close()


# ── Tests: tradeoff + feeds_fallback ─────────────────────────────────────────

def test_tradeoff_always_present():
    """Even if all deltas negative, tradeoff entry still appears."""
    _, Session = _make_test_db()
    session = Session()
    _make_benchmark_rows(session, baseline_cost=100.0, graph_aware_cost=90.0)
    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "tradeoff" in data
        tradeoff = data["tradeoff"]
        assert "bom_name" in tradeoff
        assert "losing_axis" in tradeoff
        assert "narrative" in tradeoff
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_feeds_fallback_flag():
    """Rows with feeds_available containing False → feeds_fallback=True."""
    _, Session = _make_test_db()
    session = Session()

    bom_names = [f"bom_{i:02d}" for i in range(1, 11)]
    for bom in bom_names:
        for graph_aware in [False, True]:
            row = OptimizationRun(
                run_id=1,
                run_tag="benchmark",
                bom_name=bom,
                bom_items_json=[{"component_id": 1, "quantity": 1}],
                strategy="balanced",
                graph_aware=graph_aware,
                total_cost_usd=100.0,
                eta_p50_days=5.0,
                co2_kg=2.5,
                cascade_risk_score=0.4,
                feeds_available={"gpr": False, "acled": True},  # gpr=False -> fallback
                selected_distributor_ids=[1],
                selected_distributor_names=["DigiKey"],
            )
            session.add(row)
    session.commit()

    client = _make_client_with_db(session)

    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200
        assert resp.json()["feeds_fallback"] is True
    finally:
        app.dependency_overrides.clear()
        session.close()


# ── Tests: /benchmark/single-source-components ────────────────────────────────

def test_single_source_components_shape():
    """Mock GraphState with single_source_component_ids={1}, DB fixture -> 200 with correct shape."""
    _, Session = _make_test_db()
    session = Session()

    # Seed DB with real component + distributor + offer
    comp = Component(
        id=1, mpn="STM32F103C8T6", manufacturer="STMicroelectronics",
        manufacturer_country="France", category="Microcontrollers",
        description="ARM Cortex-M3", risk_score=0.2,
    )
    dist = Distributor(
        id=10, name="Mouser Electronics", latitude=33.05, longitude=-97.05,
        city="Mansfield", state="TX", country="USA", is_domestic=True,
    )
    offer = DistributorOffer(
        id=1, component_id=1, distributor_id=10,
        price=4.50, stock=500, sku="MOUSER-STM32", currency="USD", moq=1,
    )
    session.add_all([comp, dist, offer])
    session.commit()

    gs = _MockGraphState(single_source_component_ids=frozenset({1}))
    client = _make_client_with_db(session)

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/single-source-components")

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "components" in data
        assert len(data["components"]) == 1

        comp_data = data["components"][0]
        assert comp_data["component_id"] == 1
        assert comp_data["mpn"] == "STM32F103C8T6"
        assert comp_data["manufacturer"] == "STMicroelectronics"
        assert comp_data["distributor_id"] == 10
        assert comp_data["distributor_name"] == "Mouser Electronics"
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_single_source_components_no_fabricated_strings():
    """Returned mpn must NOT equal 'High-betweenness hub' — must be real Component.mpn."""
    _, Session = _make_test_db()
    session = Session()

    comp = Component(
        id=2, mpn="STM32F103C8T6", manufacturer="STMicroelectronics",
        manufacturer_country="France", category="Microcontrollers",
        description="ARM Cortex-M3", risk_score=0.2,
    )
    dist = Distributor(
        id=20, name="DigiKey", latitude=44.89, longitude=-95.36,
        city="Thief River Falls", state="MN", country="USA", is_domestic=True,
    )
    offer = DistributorOffer(
        id=2, component_id=2, distributor_id=20,
        price=3.75, stock=1000, sku="DK-STM32", currency="USD", moq=1,
    )
    session.add_all([comp, dist, offer])
    session.commit()

    gs = _MockGraphState(single_source_component_ids=frozenset({2}))
    client = _make_client_with_db(session)

    try:
        with patch("app.graph.get_graph_state", return_value=gs):
            resp = client.get("/api/v1/benchmark/single-source-components")

        assert resp.status_code == 200
        components = resp.json()["components"]
        assert len(components) == 1

        mpn = components[0]["mpn"]
        assert mpn != "High-betweenness hub", f"Got fabricated string: {mpn!r}"
        assert mpn == "STM32F103C8T6", f"Expected real MPN, got: {mpn!r}"
    finally:
        app.dependency_overrides.clear()
        session.close()
