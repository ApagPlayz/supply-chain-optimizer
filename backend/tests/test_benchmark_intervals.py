"""The benchmark is held to the same statistical bar as the ML models.

Why this file exists
--------------------
Until 2026-08-28 every published resilience delta on ``/benchmark`` was an
**uninterval'd mean over 9 BOMs**. ``grep -rn "bootstrap\\|ci_low\\|std_error"``
returned nothing across ``app/graph/``, ``seeds/run_benchmark.py`` and
``app/api/benchmark.py``: no confidence interval, no standard error, no
replicate, a single fixed seed, one run — and ``-0.0072x`` published to four
decimal places.

That is not merely thin. It **contradicts the repo's own ship standard**: the
lead-time model may only ship by beating its baselines with a *paired bootstrap
CI excluding zero*, and the Model Card says so prominently. A reviewer who reads
that page and then sees bare means on the benchmark page is entitled to ask why
one artifact is held to a looser bar than the other. There is no good answer.

What was added
--------------
A paired **percentile bootstrap over the BOM clusters** — 10,000 resamples, seed
42 — around each published delta. The BOM is the resample unit because both arms
of every per-BOM delta come from the same BOM, the same offer pool and the same
simulation seed, so the BOM is the independent cluster. Critically, **nothing is
re-solved**: every per-BOM delta is already stored in ``optimization_runs``, so
the intervals are computed from values run 5 already wrote and no published mean
moves.

The honest outcome on run 5, which these tests pin
--------------------------------------------------
Two of the four resilience deltas do **not** clear zero, and the effective panel
is 7, not 9 — ``drone_flight_controller`` and ``rf_transceiver_module`` select an
identical plan in both arms and contribute an exact 0.0 to every mean. Both facts
are published rather than hidden. Expect some deltas to be non-significant; that
is the real finding about a nine-BOM benchmark.

If a test here fails
--------------------
Do not widen the interval, drop the ``excludes zero`` rule, or quietly re-run the
benchmark to get a friendlier panel. The rule is the standard the ML models are
already held to.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-characters-long-for-testing")
os.environ.setdefault("DEBUG", "true")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.benchmark import (
    BOOTSTRAP_N,
    BOOTSTRAP_SEED,
    _plan_differs,
    paired_bootstrap_ci,
)
from app.core.database import Base, get_db
from app.main import app
from app.models.optimization_run import OptimizationRun

REPO_ROOT = BACKEND_ROOT.parent
BENCHMARK_PAGE = REPO_ROOT / "frontend" / "src" / "pages" / "BenchmarkPage.tsx"

PUBLISHED_DELTAS = [
    "stress_cascade_risk_reduction",
    "stress_cvar95_reduction",
    "targeted_cascade_risk_reduction",
    "targeted_cvar95_reduction",
    "nominal_cost_premium_pct",
]


# ── The estimator itself ──────────────────────────────────────────────────────

def test_bootstrap_is_deterministic_under_its_published_seed():
    """Same panel, same seed, same interval — every time.

    An interval a reader cannot reproduce is worth no more than the bare mean it
    replaced, so the seed is published beside every figure.
    """
    panel = [0.25, 0.0, -0.75, 0.0, 0.0, -0.25, 0.0, 0.0, 0.0]
    first = paired_bootstrap_ci(panel)
    second = paired_bootstrap_ci(panel)
    assert first == second
    assert paired_bootstrap_ci(panel, seed=BOOTSTRAP_SEED) == first


def test_bootstrap_reports_the_panel_size_it_used():
    ci = paired_bootstrap_ci([1.0, 2.0, 3.0])
    assert ci["n"] == 3
    assert ci["mean"] == pytest.approx(2.0)


def test_an_all_zero_panel_is_never_significant():
    """The degenerate case that must not be allowed to read as a result.

    Every BOM contributing an exact 0.0 gives lo == hi == 0.0. `excludes zero` is
    deliberately strict (`lo > 0 or hi < 0`), so an interval that merely *touches*
    zero is not significant.
    """
    ci = paired_bootstrap_ci([0.0] * 9)
    assert ci["ci95_low"] == 0.0
    assert ci["ci95_high"] == 0.0
    assert ci["significant"] is False


def test_an_interval_that_touches_zero_is_not_significant():
    """Run 5's `stress_cvar95_reduction` is exactly this shape.

    One BOM moves, eight are hard zeros. The mean is positive (+0.0014) but the
    lower bound sits ON zero, because a resample can draw nine zeros. Published
    as a bare mean it looks like a small win; it is not one.
    """
    panel = [0.0128] + [0.0] * 8
    ci = paired_bootstrap_ci(panel)
    assert ci["mean"] > 0.0
    assert ci["ci95_low"] == 0.0
    assert ci["significant"] is False


def test_a_consistently_signed_panel_clears_zero():
    ci = paired_bootstrap_ci([0.4, 0.5, 0.45, 0.55, 0.6, 0.5, 0.42])
    assert ci["ci95_low"] > 0.0
    assert ci["significant"] is True


def test_a_consistently_negative_panel_also_clears_zero():
    """Significance is two-sided: a delta that is reliably WORSE is a finding too."""
    ci = paired_bootstrap_ci([-0.4, -0.5, -0.45, -0.55, -0.6, -0.5, -0.42])
    assert ci["ci95_high"] < 0.0
    assert ci["significant"] is True


@pytest.mark.parametrize("panel", [[], [0.5]])
def test_a_panel_too_small_to_bound_says_so_instead_of_guessing(panel):
    ci = paired_bootstrap_ci(panel)
    assert ci["ci95_low"] is None and ci["ci95_high"] is None
    assert ci["significant"] is False
    assert "note" in ci


# ── Which BOMs actually carry information ─────────────────────────────────────

class _Row:
    def __init__(self, ids, cost):
        self.selected_distributor_ids = ids
        self.total_cost_usd = cost


def test_plan_identity_is_distributor_set_plus_landed_cost():
    """Two BOMs in run 5 pick the SAME plan in both arms.

    `optimization_runs` keeps no line-level assignment snapshot, so plan identity
    is inferred from the two things it does store. Same set AND same cost = the
    same plan (an exact 0.0 on every delta). Same set at a DIFFERENT cost means
    the quantities moved, which is a different plan.
    """
    assert _plan_differs(_Row([57, 81, 85], 794.72), _Row([57, 81, 85], 794.72)) is False
    assert _plan_differs(_Row([85], 159.56), _Row([47, 85], 270.69)) is True
    assert _plan_differs(_Row([1, 2], 100.0), _Row([2, 1], 100.0)) is False   # order-free
    assert _plan_differs(_Row([1, 2], 100.0), _Row([1, 2], 90.0)) is True     # qty moved


# ── The run-5 panel, pinned ───────────────────────────────────────────────────
#
# The stored per-BOM deltas for run 5, in BOM-name order. Written out literally so
# this test states the finding rather than re-deriving it from whatever happens to
# be in the database.
_RUN5_STRESS_CASCADE = [0.25, 0.0, -0.75, 0.0, 0.0, -0.25, 0.0, 0.0, 0.0]
_RUN5_STRESS_CVAR = [0.0128, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
_RUN5_TARGETED_CASCADE = [0.25, 0.0, 0.5, 0.5, 0.75, 1.0, 0.0, 0.75, 0.25]
_RUN5_TARGETED_CVAR = [0.0345, 0.0, 0.0307, 0.0, 0.0, 0.09, 0.0, 0.0615, 0.0615]


def test_run5_stress_deltas_do_not_clear_zero():
    """The honest outcome, published rather than hidden.

    Under broad stress neither cascade risk nor CVaR-95 separates the two arms on
    nine BOMs. The cascade mean is NEGATIVE (graph-aware looks worse) and its
    interval spans zero; the CVaR interval sits on zero. Neither may be quoted as
    a result in either direction.
    """
    cascade = paired_bootstrap_ci(_RUN5_STRESS_CASCADE)
    assert cascade["significant"] is False
    assert cascade["ci95_low"] < 0.0 < cascade["ci95_high"]

    cvar = paired_bootstrap_ci(_RUN5_STRESS_CVAR)
    assert cvar["significant"] is False


def test_run5_targeted_deltas_do_clear_zero():
    """The two figures that survive the bar the ML models are held to."""
    cascade = paired_bootstrap_ci(_RUN5_TARGETED_CASCADE)
    assert cascade["significant"] is True
    assert cascade["ci95_low"] > 0.0

    cvar = paired_bootstrap_ci(_RUN5_TARGETED_CVAR)
    assert cvar["significant"] is True
    assert cvar["ci95_low"] > 0.0


def test_dropping_the_two_zero_plan_boms_moves_the_estimate():
    """Why `n_effective` has to be reported separately from `n`.

    The two plan-identical BOMs are index 1 and 6. They are not evidence of a
    null effect — they are BOMs the treatment never touched — and leaving them in
    shrinks the mean by a fifth. Report both panels, claim neither as the other.
    """
    full = paired_bootstrap_ci(_RUN5_TARGETED_CASCADE)
    effective = paired_bootstrap_ci(
        [d for i, d in enumerate(_RUN5_TARGETED_CASCADE) if i not in (1, 6)]
    )
    assert full["n"] == 9 and effective["n"] == 7
    assert effective["mean"] > full["mean"]


# ── The served response ───────────────────────────────────────────────────────

def _make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def _row(bom, arm, graph_aware, scenario, cost, plan_risk, cvar, dids, run_id=1):
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
        eta_p10_days=4.0,
        eta_p50_days=5.0,
        eta_p90_days=6.0,
        co2_kg=2.5,
        cascade_risk_score=0.0,
        plan_cascade_risk=plan_risk,
        n_distinct_suppliers=len(dids),
        n_orders=len(dids),
        monte_carlo_samples=[float(i) for i in range(10)],
        mc_cvar_95=cvar,
        feeds_available={"gpr": True},
        selected_distributor_ids=dids,
        selected_distributor_names=[f"D{d}" for d in dids],
    )


def _seed(session, n_boms=9, n_identical=2, targeted_gap=0.5):
    """Nine BOMs; `n_identical` of them pick the same plan in both arms.

    Mirrors run 5's shape: a real targeted effect, no stress effect, and a couple
    of structurally-zero BOMs dragging every mean toward zero.
    """
    for i in range(n_boms):
        bom = f"bom_{i:02d}"
        identical = i < n_identical
        blind_ids, graph_ids = [1], ([1] if identical else [1, 2])
        blind_cost = 100.0
        graph_cost = 100.0 if identical else 130.0
        for scen, b_risk, g_risk, b_cvar, g_cvar in [
            # nominal: the cost-premium panel
            ("nominal", 0.25, 0.25, 1.15, 1.15),
            # stress: identical in both arms -> an all-zero delta panel
            ("stress", 0.5, 0.5, 1.15, 1.15),
            # targeted: a real, consistently-signed effect on the BOMs that moved
            ("targeted", 1.0, 1.0 if identical else 1.0 - targeted_gap, 1.15, 1.15),
        ]:
            session.add(_row(bom, "milp", False, scen, blind_cost, b_risk, b_cvar, blind_ids))
            session.add(_row(bom, "milp", True, scen, graph_cost, g_risk, g_cvar, graph_ids))
        session.add(_row(bom, "greedy", False, "nominal", 160.0, 0.3, 1.2, [1, 2, 3]))
        session.add(_row(bom, "greedy_add", False, "nominal", 140.0, 0.3, 1.2, [1, 2]))
    session.commit()


def _client(session):
    def _override():
        yield session
    app.dependency_overrides[get_db] = _override
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def summary():
    Session = _make_db()
    session = Session()
    _seed(session)
    client = _client(session)
    try:
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200, resp.text
        yield resp.json()
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_every_published_delta_is_served_with_an_interval(summary):
    """The defect in one assertion: no published delta may ship bare."""
    intervals = summary["resilience"]["intervals"]
    for metric in PUBLISHED_DELTAS:
        assert metric in intervals, f"{metric} published with no interval"
        ci = intervals[metric]
        for field in ("ci95_low", "ci95_high", "significant", "n", "n_effective"):
            assert field in ci, f"{metric} interval missing {field}"


def test_the_interval_qualifies_the_number_it_sits_beside(summary):
    """The interval's mean IS the published scalar — not a second estimate.

    A CI computed off a different panel from the number it decorates would be
    worse than no CI at all.
    """
    resil = summary["resilience"]
    for metric in PUBLISHED_DELTAS:
        assert resil[metric] == pytest.approx(resil["intervals"][metric]["mean"], abs=1e-6)


def test_n_effective_excludes_the_boms_whose_plan_never_changed(summary):
    """Two of nine BOMs pick an identical plan; they are counted AND named."""
    resil = summary["resilience"]
    assert resil["n_boms"] == 9
    assert resil["n_effective_boms"] == 7
    for metric in PUBLISHED_DELTAS:
        ci = resil["intervals"][metric]
        assert ci["n"] == 9
        assert ci["n_effective"] == 7
        assert sorted(ci["zero_plan_boms"]) == ["bom_00", "bom_01"]


def test_significance_partitions_every_delta_exactly_once(summary):
    resil = summary["resilience"]
    sig = set(resil["significant_metrics"])
    nonsig = set(resil["non_significant_metrics"])
    assert sig | nonsig == set(PUBLISHED_DELTAS)
    assert not (sig & nonsig)
    for metric in PUBLISHED_DELTAS:
        assert (metric in sig) is resil["intervals"][metric]["significant"]


def test_a_delta_with_no_effect_is_reported_as_not_significant(summary):
    """Both arms score identically under stress, so nothing may be claimed."""
    resil = summary["resilience"]
    for metric in ("stress_cascade_risk_reduction", "stress_cvar95_reduction"):
        assert resil["intervals"][metric]["significant"] is False
        assert metric in resil["non_significant_metrics"]


def test_a_real_effect_survives_the_bar(summary):
    ci = summary["resilience"]["intervals"]["targeted_cascade_risk_reduction"]
    assert ci["significant"] is True
    assert ci["ci95_low"] > 0.0
    # The effective panel is the stronger statement, and it is served too.
    assert ci["mean_effective"] > ci["mean"]
    assert ci["significant_effective"] is True


def test_the_response_discloses_its_own_method_and_seed(summary):
    ci = summary["resilience"]["intervals"]["targeted_cascade_risk_reduction"]
    assert ci["n_boot"] == BOOTSTRAP_N == 10_000
    assert ci["seed"] == BOOTSTRAP_SEED == 42
    assert "bootstrap" in ci["method"].lower()
    note = summary["resilience"]["inference_note"]
    assert "10,000" in note and "seed 42" in note
    assert summary["resilience"]["n_effective_definition"]


def test_adding_intervals_did_not_move_any_published_mean(summary):
    """The bootstrap resamples STORED deltas. It must not re-estimate them."""
    resil = summary["resilience"]
    # bom 00/01 identical (0.0 delta); 7 BOMs move 1.0 -> 0.5 under targeted.
    assert resil["targeted_cascade_risk_reduction"] == pytest.approx(7 * 0.5 / 9)
    assert resil["stress_cascade_risk_reduction"] == pytest.approx(0.0)


# ── The page must not render a null result as a win ───────────────────────────

def test_the_page_gates_its_improvement_colour_on_significance():
    """THE GATE: a delta whose CI covers zero is not rendered as a win.

    `improvementColor` paints a metric GREEN when it moved in the good direction.
    Before this change it was gated on materiality alone, so a −8.33 pp mean whose
    interval runs −0.278 to +0.056 would have been coloured as a real movement.
    Every one of the four scenario tiles must now pass its metric's significance
    into that decision.
    """
    src = BENCHMARK_PAGE.read_text()
    for metric in PUBLISHED_DELTAS[:4]:
        assert f"sigOf('{metric}')" in src, (
            f"{metric} is coloured without consulting its bootstrap interval"
        )
    # The nominal premium tile is coloured through the same gate.
    assert "sigOf('nominal_cost_premium_pct')" in src


def test_the_page_states_in_words_when_an_interval_covers_zero():
    """Neutral colour is not enough — a reader must be told, in place.

    The mean stays on screen (hiding a measurement is its own dishonesty) but it
    is labelled as not distinguishable from zero, beside the number, not in a
    footnote.
    """
    src = BENCHMARK_PAGE.read_text()
    assert "covers zero" in src
    assert "not a result" in src
    assert "distinguishable from no effect" in src


def test_every_resilience_tile_renders_its_interval():
    src = BENCHMARK_PAGE.read_text()
    for metric in PUBLISHED_DELTAS:
        assert f"ciOf('{metric}')" in src, f"{metric} rendered with no interval beside it"
    # Four scenario tiles + the nominal premium tile.
    assert src.count("<CiNote ") == 5


def test_the_page_reports_n_and_n_effective_separately():
    """A mean over 9 BOMs of which 2 are structurally zero is not a mean over 9."""
    src = BENCHMARK_PAGE.read_text()
    assert "n_effective_boms" in src
    assert "zeroPlanBoms" in src
    assert "effective" in src
