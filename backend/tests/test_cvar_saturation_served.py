"""CVaR-95 saturation must reach the reader, not just the simulator.

OUTSTANDING_WORK.md item 13, second half. `graph/simulation.run_monte_carlo` has
computed `p_shortfall`, `p_total_shortfall`, `cvar_95_ceiling` and
`cvar_95_saturated` since the 2026-08-28 sweep — and until now persisted none of
them. The benchmark wrote `mc_cvar_95` alone, so 10 of the 18 published
(BOM x scenario) resilience cells carried a **bit-identical CVaR tie at the 1.15
ceiling** with nothing on the page or in the artifact to say the metric had
simply run out of room. A reader had no way to tell "the two plans are equally
exposed" from "this measurement cannot tell them apart", and on 8 of those 10
cells they are NOT equally exposed: `p_total_shortfall` separates them by 0.23
to 0.90.

`test_cvar_saturation.py` proves the estimator saturates. THIS file proves the
saturation is persisted, served and flagged:

  1. The four columns exist on `optimization_runs` and the benchmark fills them.
  2. `/benchmark/summary` flags a scenario whose BOM PAIRS are ceiling-tied, and
     NAMES the tied BOMs — a count alone cannot be checked against anything.
  3. It does NOT over-flag: one saturated arm still leaves a measurable gap, so
     it is not a ceiling tie.
  4. A run that predates the columns reports UNKNOWN, never a False nobody
     measured.
  5. The discriminating measure ships with the same paired bootstrap interval
     the published deltas carry — a bare mean here would repeat item 12's defect.
  6. The published artifact carries the flag on every resilience row, and the
     flag earns its place: it marks real ties that `p_total_shortfall` breaks.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "SECRET_KEY", "test-secret-key-that-is-at-least-32-characters-long-for-testing"
)
os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.database import Base, get_db  # noqa: E402
from app.graph.simulation import EMERGENCY_COST_PREMIUM  # noqa: E402
from app.main import app  # noqa: E402
from app.models.optimization_run import OptimizationRun  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "docs" / "benchmark_results.json"

CEILING = round(1.0 + EMERGENCY_COST_PREMIUM, 4)

# The four columns this file exists to defend. Named once so a rename has to
# come through here rather than silently dropping a column from the schema.
SATURATION_COLUMNS = (
    "mc_p_shortfall",
    "mc_p_total_shortfall",
    "mc_cvar_95_ceiling",
    "mc_cvar_95_saturated",
)


# ── Fixtures: a panel whose saturation we control exactly ────────────────────

def _make_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine), engine


def _row(
    bom, arm, graph_aware, scenario, cost, plan_risk, cvar, dids,
    p_shortfall=None, p_total=None, ceiling=None, saturated=None, run_id=1,
):
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
        mc_p_shortfall=p_shortfall,
        mc_p_total_shortfall=p_total,
        mc_cvar_95_ceiling=ceiling,
        mc_cvar_95_saturated=saturated,
        feeds_available={"gpr": True},
        selected_distributor_ids=dids,
        selected_distributor_names=[f"D{d}" for d in dids],
    )


def _seed(session, *, measured: bool, stress_graph_at_ceiling: bool = True):
    """Nine BOMs. Under STRESS both arms sit at the ceiling with genuinely
    different `p_total_shortfall`; under TARGETED the graph arm sits below it.

    That asymmetry is the whole point: stress must be flagged as a ceiling tie
    and targeted must NOT be, from the same fixture, so a test that flags
    everything and a test that flags nothing both fail.
    """
    for i in range(9):
        bom = f"bom_{i:02d}"
        identical = i < 2
        blind_ids, graph_ids = [1], ([1] if identical else [1, 2])
        graph_cost = 100.0 if identical else 130.0

        def _sat(is_at_ceiling):
            return (is_at_ceiling if measured else None)

        def _val(x):
            return (x if measured else None)

        # nominal — the cost-premium panel, nothing at the ceiling
        session.add(_row(bom, "milp", False, "nominal", 100.0, 0.25, 1.05, blind_ids,
                         _val(0.10), _val(0.02), _val(CEILING), _sat(False)))
        session.add(_row(bom, "milp", True, "nominal", graph_cost, 0.25, 1.05, graph_ids,
                         _val(0.10), _val(0.02), _val(CEILING), _sat(False)))

        # stress — BOTH arms pinned: the cvar delta is 0.0 by arithmetic, while
        # p_total_shortfall says the graph arm is materially better.
        g_cvar = CEILING if stress_graph_at_ceiling else 1.10
        session.add(_row(bom, "milp", False, "stress", 100.0, 0.5, CEILING, blind_ids,
                         _val(1.0), _val(0.37), _val(CEILING), _sat(True)))
        session.add(_row(bom, "milp", True, "stress", graph_cost, 0.5, g_cvar, graph_ids,
                         _val(1.0), _val(0.37 if identical else 0.12),
                         _val(CEILING), _sat(stress_graph_at_ceiling)))

        # targeted — blind pinned, graph BELOW the ceiling: a real measurement.
        session.add(_row(bom, "milp", False, "targeted", 100.0, 1.0, CEILING, blind_ids,
                         _val(1.0), _val(0.50), _val(CEILING), _sat(True)))
        session.add(_row(bom, "milp", True, "targeted", graph_cost, 1.0 if identical else 0.5,
                         CEILING if identical else 1.09, graph_ids,
                         _val(1.0), _val(0.50 if identical else 0.05),
                         _val(CEILING), _sat(bool(identical))))

        session.add(_row(bom, "greedy", False, "nominal", 160.0, 0.3, 1.08, [1, 2, 3],
                         _val(0.2), _val(0.05), _val(CEILING), _sat(False)))
        session.add(_row(bom, "greedy_add", False, "nominal", 140.0, 0.3, 1.07, [1, 2],
                         _val(0.2), _val(0.05), _val(CEILING), _sat(False)))
    session.commit()


def _summary(**seed_kwargs) -> dict:
    Session, _engine = _make_db()
    session = Session()
    _seed(session, **seed_kwargs)

    def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/benchmark/summary")
        assert resp.status_code == 200, resp.text
        return resp.json()["resilience"]
    finally:
        app.dependency_overrides.clear()
        session.close()


@pytest.fixture
def resil() -> dict:
    return _summary(measured=True)


# ── 1. The columns exist and the schema carries them ─────────────────────────

def test_the_schema_carries_every_saturation_column():
    """A served field with no column behind it is a field that reads NULL forever."""
    _Session, engine = _make_db()
    cols = {c["name"] for c in inspect(engine).get_columns("optimization_runs")}
    for name in SATURATION_COLUMNS:
        assert name in cols, f"optimization_runs is missing {name}"


def test_the_migration_that_adds_them_is_the_head_revision():
    """0009 must actually be reachable, or a deployed DB never gets the columns."""
    versions = BACKEND_ROOT / "migrations" / "versions"
    text = (versions / "0009_cvar_saturation_columns.py").read_text()
    assert "down_revision" in text and "'0008'" in text
    for name in SATURATION_COLUMNS:
        assert name in text, f"migration 0009 does not add {name}"


# ── 2. A ceiling tie is flagged, and the tied BOMs are named ─────────────────

def test_a_scenario_whose_pairs_are_ceiling_tied_is_flagged(resil):
    assert resil["cvar95_ceiling"] == pytest.approx(CEILING)
    assert resil["stress_cvar95_saturated"] is True
    assert resil["stress_cvar95_reduction"] == pytest.approx(0.0, abs=1e-12), (
        "the fixture's stress arms are both pinned, so the delta must be exactly 0.0 — "
        "if it is not, this test is no longer testing a ceiling tie"
    )


def test_the_tied_boms_are_named_not_merely_counted(resil):
    tied = resil["stress_cvar95_ceiling_tied_boms"]
    assert isinstance(tied, list) and len(tied) == 9
    assert tied == sorted(tied), "names must be deterministic"
    assert tied[0] == "bom_00"


def test_the_note_says_the_tie_is_arithmetic_and_names_the_ceiling(resil):
    note = resil["saturation_note"]
    assert f"{CEILING:.4f}" in note, "the note must quote the ceiling it is about"
    assert "ARITHMETIC" in note.upper()
    assert "p_total_shortfall" in note
    # Composed from the panel, not a fixed sentence.
    assert "9 of 9 stress BOM pairs" in note


def test_the_interpretation_carries_the_saturation_warning(resil):
    """The one string a client is most likely to render on its own."""
    assert resil["saturation_note"] in resil["interpretation"]


# ── 3. It must not over-flag ─────────────────────────────────────────────────

def test_one_saturated_arm_is_not_a_ceiling_tie(resil):
    """Targeted has the blind arm pinned and the graph arm below it.

    That gap is a real measurement, so flagging it would train a reader to
    discount a genuine result. Only the two plan-identical BOMs tie there.
    """
    assert resil["targeted_cvar95_reduction"] > 0.0
    tied = resil["targeted_cvar95_ceiling_tied_boms"]
    assert tied == ["bom_00", "bom_01"], tied


def test_the_flag_clears_when_the_pinned_arm_comes_off_the_ceiling():
    """Drop the graph arm below the ceiling under stress and stress must clear.

    Targeted still has its two plan-identical pairs tied, so the note keeps its
    targeted clause and loses its stress one — which is the finer assertion: the
    note is composed per scenario, not switched on globally.
    """
    resil = _summary(measured=True, stress_graph_at_ceiling=False)
    assert resil["stress_cvar95_saturated"] is False
    assert resil["stress_cvar95_ceiling_tied_boms"] == []
    assert "stress BOM pairs" not in resil["saturation_note"]
    assert "2 of 9 targeted BOM pairs" in resil["saturation_note"]


# ── 4. Unmeasured is not the same answer as "no" ─────────────────────────────

def test_a_run_that_predates_the_columns_reports_unknown_not_false():
    resil = _summary(measured=False)
    assert resil["stress_cvar95_saturated"] is None
    assert resil["targeted_cvar95_saturated"] is None
    assert resil["stress_cvar95_ceiling_tied_boms"] is None
    assert resil["cvar95_rows_measured"] is None
    assert "NOT KNOWN" in resil["saturation_note"]
    assert resil["stress_p_total_shortfall_reduction"] is None
    assert resil["p_total_shortfall_intervals"] == {}


# ── 5. The discriminating measure ships with its interval ────────────────────

def test_the_discriminating_measure_is_served_where_cvar_ties(resil):
    """0.0 on CVaR, and a real, signed number on the measure that still resolves."""
    delta = resil["stress_p_total_shortfall_reduction"]
    assert delta is not None and delta > 0.0, (
        "the fixture's graph arm halves P(total shortfall) under stress; if this is "
        "0.0 the served field is not reading mc_p_total_shortfall"
    )
    assert resil["stress_cvar95_reduction"] == pytest.approx(0.0, abs=1e-12)


def test_the_discriminating_measure_is_never_published_bare(resil):
    """Item 12's bar applies to this delta too: no mean without an interval."""
    ci = resil["p_total_shortfall_intervals"]["stress_p_total_shortfall_reduction"]
    for field in ("mean", "ci95_low", "ci95_high", "significant", "n", "n_effective"):
        assert field in ci, f"interval missing {field}"
    assert ci["mean"] == pytest.approx(resil["stress_p_total_shortfall_reduction"])
    assert ci["n"] == 9
    assert ci["n_effective"] == 7
    assert sorted(ci["zero_plan_boms"]) == ["bom_00", "bom_01"]


def test_the_published_delta_partition_is_unchanged_by_the_new_intervals(resil):
    """`intervals` is the contract for the FIVE published deltas. The shortfall
    intervals live in their own dict precisely so this partition does not move."""
    assert set(resil["significant_metrics"]) | set(resil["non_significant_metrics"]) == {
        "nominal_cost_premium_pct",
        "stress_cascade_risk_reduction",
        "stress_cvar95_reduction",
        "targeted_cascade_risk_reduction",
        "targeted_cvar95_reduction",
    }
    assert "stress_p_total_shortfall_reduction" not in resil["intervals"]


def test_both_arm_means_behind_the_measure_are_published(resil):
    mv = resil["measured_values"]
    for key in (
        "stress_blind_p_total_shortfall", "stress_graph_p_total_shortfall",
        "targeted_blind_p_total_shortfall", "targeted_graph_p_total_shortfall",
    ):
        assert mv.get(key) is not None, f"{key} not served"
    assert mv["stress_blind_p_total_shortfall"] > mv["stress_graph_p_total_shortfall"]


# ── 6. The published artifact — the 18 rows a reader actually quotes ─────────

@pytest.fixture(scope="module")
def artifact() -> dict:
    assert ARTIFACT.exists(), f"missing benchmark artifact: {ARTIFACT}"
    return json.loads(ARTIFACT.read_text())


def test_every_published_resilience_row_carries_the_flag(artifact):
    rows = artifact["value_of_resilience"]
    assert len(rows) == 18, f"expected the 18 published cells, got {len(rows)}"
    for r in rows:
        for field in (
            "cvar_95_ceiling", "cvar_95_saturated",
            "p_total_shortfall_blind", "p_total_shortfall_graph",
            "p_total_shortfall_reduction",
        ):
            assert field in r, f"{r['bom']}/{r['scenario']} published without {field}"
        assert r["cvar_95_ceiling"] == pytest.approx(CEILING)


def test_no_published_cvar_may_exceed_its_own_ceiling(artifact):
    for r in artifact["value_of_resilience"]:
        for arm in ("cvar_95_blind", "cvar_95_graph"):
            assert r[arm] <= r["cvar_95_ceiling"] + 1e-9, (
                f"{r['bom']}/{r['scenario']} {arm}={r[arm]} exceeds the ceiling"
            )


def test_the_saturation_flag_agrees_with_the_numbers_beside_it(artifact):
    """The flag is derived, so it must be re-derivable from the same row."""
    for r in artifact["value_of_resilience"]:
        at_ceiling = (
            r["cvar_95_blind"] >= r["cvar_95_ceiling"] - 1e-9
            and r["cvar_95_graph"] >= r["cvar_95_ceiling"] - 1e-9
        )
        assert bool(r["cvar_95_saturated"]) is at_ceiling, (
            f"{r['bom']}/{r['scenario']} flag={r['cvar_95_saturated']} but "
            f"blind={r['cvar_95_blind']} graph={r['cvar_95_graph']} "
            f"ceiling={r['cvar_95_ceiling']}"
        )


def test_the_flag_earns_its_place_on_the_published_run(artifact):
    """The reason this is worth shipping, asserted against the real artifact.

    There ARE saturated cells, their CVaR reduction IS exactly zero, and on most
    of them `p_total_shortfall` shows the two plans are not equally exposed at
    all. If this ever goes red because no cell saturates, the flag has become
    decoration and the note above it must be retired with it.
    """
    rows = artifact["value_of_resilience"]
    saturated = [r for r in rows if r["cvar_95_saturated"]]
    assert saturated, "no published cell is saturated — the flag says nothing"
    for r in saturated:
        assert r["cvar_95_reduction"] == pytest.approx(0.0, abs=1e-9), (
            "a saturated cell cannot have a non-zero CVaR delta"
        )
    broken = [r for r in saturated if abs(r["p_total_shortfall_reduction"]) > 1e-9]
    assert broken, (
        "every ceiling tie is also a p_total_shortfall tie — the discriminating "
        "measure discriminates nothing on this run"
    )
    assert artifact["resilience_summary"]["cvar_95_saturated_cells"] == len(saturated)
    assert artifact["resilience_summary"]["cvar_95_ceiling"] == pytest.approx(CEILING)
