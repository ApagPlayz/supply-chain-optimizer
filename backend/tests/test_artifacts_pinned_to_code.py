"""
Drift guard: the committed ARTIFACTS must agree with the CODE that produced them.

Why this file exists (2026-08-29)
---------------------------------
``tests/test_benchmark_docs_match_artifacts.py`` compares the published markdown
to the committed JSON. That is a *doc-vs-artifact* check, and it has a blind spot
the repo has now hit twice:

    commit 6a33ad0 changed ``app/optimization/sourcing.py`` (milli-cent
    quantisation, risk surcharges, an ``is_chinese_origin`` double-count) and
    hand-edited only the ``meta`` prose of ``docs/volume_sweep.json``. The
    generator was never re-run. The doc and the artifact were stale *together*,
    so ``test_volume_curve_pooled_table_matches_sweep_json`` stayed green while
    both disagreed with the optimizer. A later real re-run of
    ``python -m seeds.run_volume_sweep`` moved a cell: $181,919.39 → $181,908.01,
    5 → 6 suppliers, and the pooled 10,000x row 7.96% → 7.97%.

CLAUDE.md names exactly this failure: *"twice shipped figures that two documents
agreed on while both disagreed with the code."* Nothing can catch it except a
check that re-runs the real code path and compares the result to the bytes on
disk. That is what this file does.

What is pinned here
-------------------
1. ``docs/volume_sweep.json`` — every point of the PRIMARY (deduped) grid is
   re-solved through ``seeds.run_volume_sweep._run_point``, i.e. the generator's
   own function calling the real ``solve_sourcing`` / ``solve_sourcing_greedy``.
   Nothing is reimplemented here. Measured cost: **0.39 s for all 80 points**
   (10 BOMs x 13 multipliers, trimmed to each BOM's stock ceiling, 3 arms each),
   plus ~0.02 s of offer loading. Cheap enough to pin the whole grid rather than
   one token point.

2. ``frontend/src/lib/volumeDecayCurveData.ts`` — the hardcoded fallback table
   the ``/benchmark`` page renders whenever the API is unreachable. It is a
   hand-copied projection of ``docs/volume_sweep.json`` and had already drifted
   once. Here it is re-derived from the committed artifact using the generator's
   own ``_pooled_rows`` aggregation and compared row by row.

3. ``docs/diversification_frontier.json`` — the whole k = 1..K sweep is re-solved
   through ``seeds.run_diversification_sweep.sweep_bom``. Measured: 1.0 s to build
   the graph state + 0.15 s for all 10 BOMs. It previously had NO test of any kind
   tying it to anything — not even a doc comparison.

4. ``docs/newsvendor.json`` — the PRIMARY configuration is re-run through
   ``app.optimization.newsvendor.run_panel_evaluation`` at the artifact's own
   ``n_boot``/``seed``. Measured: 3.3 s. Its existing test file states in its own
   docstring that it "does not re-run the evaluation"; this is the missing half.

Deliberately NOT pinned, with sizing (see the survey in this task's report):
  * ``points_raw_pool`` of the volume sweep — the declared CONTROL arm, already
    tied to the primary pool by ``test_raw_and_deduped_pools_agree``.
  * ``benchmark_results.json`` (~137 s) — already has a real pin in
    ``tests/test_diversification_frontier.py::test_unconstrained_solve_still_
    reproduces_published_run5_costs``.
  * ``cvar_frontier.json`` (~1316 s full run; the committed artifact asserts
    ``quick_mode=False``), ``leakage_progression.json`` (~215 s nested CV),
    ``chronos_benchmark.json`` (torch + HF weights), ``forecast_backtest.json``
    (Prophet fits per rolling origin), ``intermittent_demand.json`` (~22 s, and
    already cross-pinned by ``test_newsvendor.py::test_the_recomputed_mase_
    reproduces_the_published_leaderboard``), ``backend_verification.json`` (live
    HTTPS calls to Render). A single-point pin for any of these belongs behind
    ``-m slow``, not in the default suite.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"
SWEEP_JSON = DOCS / "volume_sweep.json"
FRONTEND_FALLBACK_TS = REPO_ROOT / "frontend" / "src" / "lib" / "volumeDecayCurveData.ts"
DB_PATH = REPO_ROOT / "backend" / "supply_chain.db"

REGENERATE = (
    "Re-run `cd backend && ./venv/bin/python -m seeds.run_volume_sweep` "
    "(~1 s) and commit the regenerated docs/volume_sweep.json + "
    "docs/BENCHMARK_VOLUME_CURVE.md."
)

# `_decompose` rounds every dollar figure to cents before it is written out, so
# an exact match is what a reproduction should produce; the tolerances below only
# absorb last-bit float noise across platforms. They are deliberately far tighter
# than the drift they exist to catch (the real 2026-08-29 drift was $11.38 on a
# cost and 0.01pp on a percentage).
MONEY_TOL = 0.011
# Newsvendor carries raw probabilities and per-SKU costs, where 0.011 absolute
# would swallow a real change. Compared on the tighter of absolute/relative.
STAT_ABS_TOL = 1e-9
STAT_REL_TOL = 1e-9

# Wall-clock fields cannot reproduce and are the ONLY ones allowed to differ.
SWEEP_SKIP_FIELDS = frozenset({"solve_seconds"})

# The seeded snapshot every published number is computed from. Asserted rather
# than assumed: DATABASE_URL is CWD-relative and SQLite CREATES rather than
# fails, so running from the wrong directory yields a silently empty database
# (LEARNINGS.md, 2026-08-28).
EXPECTED_ROW_COUNTS = {
    "components": 791,
    "distributors": 92,
    "distributor_offers": 8176,
}


# ── shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sweep() -> Dict[str, Any]:
    if not SWEEP_JSON.is_file():
        pytest.fail(f"docs/volume_sweep.json is missing. {REGENERATE}")
    return json.loads(SWEEP_JSON.read_text())


# ── 1. volume_sweep.json vs the live optimizer ───────────────────────────────

def _compare(
    path: str,
    expected: Any,
    actual: Any,
    problems: List[str],
    *,
    abs_tol: float = MONEY_TOL,
    rel_tol: float = 0.0,
    skip_fields: frozenset = frozenset(),
) -> None:
    """Structural comparison that reports EVERY differing leaf, not just the first."""
    kw = {"abs_tol": abs_tol, "rel_tol": rel_tol, "skip_fields": skip_fields}
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            problems.append(f"{path}: expected an object, re-solve produced {type(actual).__name__}")
            return
        for key in expected:
            if key in skip_fields:
                continue
            if key not in actual:
                problems.append(f"{path}.{key}: missing from the re-solve")
                continue
            _compare(f"{path}.{key}", expected[key], actual[key], problems, **kw)
        for key in actual:
            if key not in expected and key not in skip_fields:
                problems.append(f"{path}.{key}: the re-solve produced a field the artifact lacks")
        return

    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            problems.append(
                f"{path}: artifact has {len(expected)} entries, re-solve produced "
                f"{len(actual) if isinstance(actual, list) else type(actual).__name__}"
            )
            return
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            _compare(f"{path}[{i}]", e, a, problems, **kw)
        return

    if isinstance(expected, bool) or isinstance(actual, bool):
        if expected != actual:
            problems.append(f"{path}: artifact={expected!r} re-solve={actual!r}")
        return

    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        tol = max(abs_tol, rel_tol * abs(float(expected)))
        if abs(float(expected) - float(actual)) > tol:
            problems.append(f"{path}: artifact={expected!r} re-solve={actual!r}")
        return

    if expected != actual:
        problems.append(f"{path}: artifact={expected!r} re-solve={actual!r}")


def test_volume_sweep_artifact_reproduces_from_the_live_optimizer(sweep):
    """
    THE pin: every committed point of the primary sweep grid must still fall out
    of the real optimizer.

    This is the check that ``6a33ad0`` needed and did not have. It calls
    ``seeds.run_volume_sweep._run_point`` — the exact function ``main()`` calls —
    so a change anywhere under ``app/optimization/`` that moves a published cost
    shows up here immediately, whatever the markdown says.
    """
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("ortools")
    if not DB_PATH.exists():
        pytest.skip("backend/supply_chain.db not present")

    from sqlalchemy import text

    from app.core.database import SessionLocal
    from app.optimization.strategies import get_strategy
    from seeds.run_benchmark import BOM_CATALOG, _load_offers_for_bom
    from seeds.run_volume_sweep import STRATEGY_ID, _dedupe_offers, _run_point

    assert sweep["meta"]["strategy"] == STRATEGY_ID, (
        f"the artifact was generated with strategy {sweep['meta']['strategy']!r} but the "
        f"generator now uses {STRATEGY_ID!r}. {REGENERATE}"
    )

    weights = get_strategy(STRATEGY_ID)
    db = SessionLocal()
    problems: List[str] = []
    points_checked = 0
    started = time.perf_counter()
    try:
        for name, counted in EXPECTED_ROW_COUNTS.items():
            got = db.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
            assert got == counted, (
                f"the database this test read has {got} rows in {name}, not {counted}. "
                "Either the seed drifted or pytest was launched from the wrong "
                "directory (DATABASE_URL is CWD-relative and SQLite creates an empty "
                "file rather than failing). Run pytest from backend/."
            )

        for bom_name, entry in sweep["boms"].items():
            expected_points = entry.get("points")
            if not expected_points:
                continue
            assert bom_name in BOM_CATALOG, (
                f"docs/volume_sweep.json carries results for {bom_name!r}, which is no "
                f"longer in run_benchmark.BOM_CATALOG. {REGENERATE}"
            )
            items = BOM_CATALOG[bom_name]
            bom, raw_offers, _meta = _load_offers_for_bom(db, items)
            assert bom and raw_offers, (
                f"{bom_name}: the database returned no BOM lines or no offers, so this "
                "test would have checked nothing."
            )
            deduped, _dups = _dedupe_offers(raw_offers)

            for expected in expected_points:
                actual = _run_point(
                    bom_name, items, bom, deduped, weights, expected["multiplier"]
                )
                points_checked += 1
                for arm_id in ("greedy", "milp_matched", "milp_bench"):
                    arm = actual["arms"].get(arm_id) or {}
                    if arm.get("hit_time_limit"):
                        problems.append(
                            f"boms.{bom_name}.m={expected['multiplier']}.{arm_id}: the "
                            "re-solve hit CP-SAT's 5 s limit and returned FEASIBLE rather "
                            "than OPTIMAL, so this machine cannot reproduce the artifact "
                            "deterministically. This is a solver-environment problem, NOT "
                            "artifact staleness."
                        )
                _compare(
                    f"boms.{bom_name}.points[m={expected['multiplier']}]",
                    expected,
                    actual,
                    problems,
                    skip_fields=SWEEP_SKIP_FIELDS,
                )
    finally:
        db.close()
    elapsed = time.perf_counter() - started

    # Anti-vacuity: this test must actually have solved something. The sweep grid
    # is 10 BOMs trimmed to their stock ceilings; it has never been under 70 points.
    assert points_checked >= 70, (
        f"only {points_checked} sweep points were re-solved — the pin has gone quiet, "
        "which is exactly how a published number drifts unnoticed."
    )
    assert elapsed < 60.0, (
        f"the re-solve took {elapsed:.1f}s; it is budgeted at well under a second and "
        "something has changed materially in the solver configuration."
    )

    assert not problems, (
        f"docs/volume_sweep.json no longer matches what the optimizer produces "
        f"({len(problems)} differing values across {points_checked} re-solved points).\n"
        f"The ARTIFACT is stale, not this test: the code under app/optimization/ has "
        f"moved and the artifact was not regenerated.\n{REGENERATE}\n\n"
        + "\n".join(f"  - {p}" for p in problems[:40])
        + (f"\n  ... and {len(problems) - 40} more" if len(problems) > 40 else "")
    )


# ── 2. the frontend's hardcoded fallback vs the artifact ─────────────────────
#
# WHY A PYTHON TEST AND NOT A VITEST ONE
# --------------------------------------
# The frontend has no unit-test runner at all: frontend/package.json has no
# vitest/jest dependency, no `test` script and no runner config; the only
# automated frontend check is `npm run ui-gate`, a Playwright + axe-core visual
# gate that never reads docs/*.json. Adding a runner would mean a new dependency,
# a config file and new CI wiring for a single assertion.
#
# Meanwhile the aggregation that turns the artifact into these rows ALREADY EXISTS
# in Python — `seeds.run_volume_sweep._pooled_rows`, the same function that writes
# the markdown table. Deriving the expected rows from the generator's own helper
# means nothing is reimplemented, and backend/tests is the suite the standing gate
# runs. Reading a source file as text is also an established convention here (see
# tests/test_run_benchmark.py and tests/test_is_chinese_origin_propagation.py).

_TS_ROW_RE = re.compile(r"\{([^{}]*)\}")
_TS_FIELD_RE = re.compile(r"(\w+)\s*:\s*(-?\d+(?:\.\d+)?)")


def _parse_ts_fallback(source: str) -> List[Dict[str, float]]:
    """Extract VOLUME_SWEEP_FALLBACK's object literals as plain dicts."""
    m = re.search(
        r"export const VOLUME_SWEEP_FALLBACK\s*:\s*VolumeCurvePoint\[\]\s*=\s*\[(.*?)\n\];",
        source,
        re.S,
    )
    assert m, (
        "could not find `export const VOLUME_SWEEP_FALLBACK: VolumeCurvePoint[] = [...]` "
        f"in {FRONTEND_FALLBACK_TS.relative_to(REPO_ROOT)}. If the export was renamed or "
        "restructured, this pin must be updated with it — do not delete it."
    )
    rows = []
    for body in _TS_ROW_RE.findall(m.group(1)):
        fields = {k: float(v) for k, v in _TS_FIELD_RE.findall(body)}
        if fields:
            rows.append(fields)
    return rows


def _expected_fallback_rows(sweep: Dict[str, Any]) -> List[Dict[str, float]]:
    """
    Derive the fallback table from the committed artifact using the GENERATOR's
    own pooled aggregation, so this test cannot disagree with the markdown for
    reasons of arithmetic.
    """
    from seeds.run_volume_sweep import _points_at, _pooled_rows

    boms = sweep["boms"]
    out = []
    for r in _pooled_rows(boms):
        pts = _points_at(boms, r["m"])
        greedy_fixed = sum(float(p["greedy"]["fixed_fee_usd"]) for p in pts)
        out.append({
            "multiplier": float(r["m"]),
            "savings_pct": r["pct"],
            "n_boms": float(r["n"]),
            "units_min": float(r["units_min"]),
            "units_max": float(r["units_max"]),
            "fixed_fee_usd": r["fee"],
            "component_usd": r["comp"],
            "variable_freight_usd": r["var"],
            "fee_share_of_saving_pct": (r["fee"] / r["delta"] * 100.0) if r["delta"] else 0.0,
            "greedy_fixed_share_of_cost_pct": (
                greedy_fixed / r["greedy"] * 100.0 if r["greedy"] else 0.0
            ),
        })
    return out


# field -> (decimal places the TS literal carries, human label)
_FALLBACK_FIELDS: Tuple[Tuple[str, int], ...] = (
    ("savings_pct", 2),
    ("n_boms", 0),
    ("units_min", 0),
    ("units_max", 0),
    ("fixed_fee_usd", 0),
    ("component_usd", 0),
    ("variable_freight_usd", 0),
    ("fee_share_of_saving_pct", 0),
    ("greedy_fixed_share_of_cost_pct", 1),
)


def test_frontend_volume_fallback_matches_sweep_artifact(sweep):
    """
    ``VOLUME_SWEEP_FALLBACK`` is what a visitor sees on /benchmark whenever the
    API is unreachable — i.e. it is PUBLISHED. It is a hand-copied projection of
    docs/volume_sweep.json with nothing tying it to the source, and it had already
    drifted once. Every cell must be the correct rounding of the artifact's value.
    """
    assert FRONTEND_FALLBACK_TS.is_file(), (
        f"{FRONTEND_FALLBACK_TS.relative_to(REPO_ROOT)} is missing — the /benchmark "
        "page's offline fallback table."
    )
    actual = _parse_ts_fallback(FRONTEND_FALLBACK_TS.read_text())
    expected = _expected_fallback_rows(sweep)

    fix = (
        "Regenerate docs/volume_sweep.json if the OPTIMIZER moved "
        "(`cd backend && ./venv/bin/python -m seeds.run_volume_sweep`), then hand-update "
        f"VOLUME_SWEEP_FALLBACK in {FRONTEND_FALLBACK_TS.relative_to(REPO_ROOT)} to match "
        "the artifact. The artifact is the source of truth; the TS table is a copy."
    )

    assert [r["multiplier"] for r in actual] == [r["multiplier"] for r in expected], (
        "the multipliers in VOLUME_SWEEP_FALLBACK no longer match the pooled rows of "
        f"docs/volume_sweep.json.\n  TS       : {[int(r['multiplier']) for r in actual]}\n"
        f"  artifact : {[int(r['multiplier']) for r in expected]}\n{fix}"
    )

    problems: List[str] = []
    for got, want in zip(actual, expected, strict=True):
        m = int(want["multiplier"])
        for field, places in _FALLBACK_FIELDS:
            if field not in got:
                problems.append(f"m={m}: TS row is missing `{field}`")
                continue
            # The TS literal carries the artifact value rounded to `places`; anything
            # further away than half a unit in the last place is real drift.
            tol = 0.5 * (10 ** -places) + 1e-6
            if abs(got[field] - want[field]) > tol:
                problems.append(
                    f"m={m}.{field}: TS={got[field]!r} but the artifact gives "
                    f"{round(want[field], places)!r} (exact {want[field]:.4f})"
                )

    assert not problems, (
        f"{FRONTEND_FALLBACK_TS.relative_to(REPO_ROOT)} disagrees with "
        f"docs/volume_sweep.json in {len(problems)} place(s) — the /benchmark page "
        f"publishes these numbers when the API is down.\n{fix}\n\n"
        + "\n".join(f"  - {p}" for p in problems[:40])
        + (f"\n  ... and {len(problems) - 40} more" if len(problems) > 40 else "")
    )


def test_frontend_production_floor_matches_generator():
    """
    The frontend labels everything at/above ``PRODUCTION_VOLUME_MIN_MULTIPLIER``
    "production volume" and quotes a saving range over that tail. The generator
    defines the same threshold as ``PRODUCTION_FLOOR`` and uses it for the
    equivalent sentence in the markdown. Two constants, one meaning.
    """
    from seeds.run_volume_sweep import PRODUCTION_FLOOR

    src = FRONTEND_FALLBACK_TS.read_text()
    m = re.search(r"export const PRODUCTION_VOLUME_MIN_MULTIPLIER\s*=\s*(\d+)", src)
    assert m, "PRODUCTION_VOLUME_MIN_MULTIPLIER not found in volumeDecayCurveData.ts"
    assert int(m.group(1)) == PRODUCTION_FLOOR, (
        f"the frontend calls >= {m.group(1)}x 'production volume' while "
        f"seeds/run_volume_sweep.PRODUCTION_FLOOR says {PRODUCTION_FLOOR}x. The page and "
        "the published markdown would describe different cohorts."
    )


# ── 3. diversification_frontier.json vs the live optimizer ───────────────────

DIVERSIFICATION_JSON = DOCS / "diversification_frontier.json"


def test_diversification_frontier_reproduces_from_the_live_optimizer():
    """
    ``docs/diversification_frontier.json`` had NO test tying it to anything — no
    doc comparison, no recompute. Its numbers reach the public
    ``/benchmark/diversification`` endpoint, and it was last generated at
    ``0a1aecab`` (2026-08-27), i.e. before the sourcing.py change that moved the
    volume sweep.

    This re-solves the entire k = 1..K frontier through the generator's own
    ``sweep_bom`` — the same function ``main()`` calls, with the same GraphState.
    Measured: ~1.0 s graph build + ~0.15 s for all 10 BOMs.
    """
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("ortools")
    if not DIVERSIFICATION_JSON.is_file():
        pytest.skip("docs/diversification_frontier.json not present")
    if not DB_PATH.exists():
        pytest.skip("backend/supply_chain.db not present")

    from sqlalchemy import text

    from app.core.database import SessionLocal
    from app.graph import get_graph_state
    from app.graph.builder import build_graph_state
    from app.optimization.strategies import get_strategy
    from seeds.run_benchmark import BOM_CATALOG
    from seeds.run_diversification_sweep import STRATEGY_ID, sweep_bom

    artifact = json.loads(DIVERSIFICATION_JSON.read_text())
    expected_by_bom = {r["bom"]: r for r in artifact["boms"]}

    regenerate = (
        "Re-run `cd backend && ./venv/bin/python -m seeds.run_diversification_sweep` "
        "(~2 s) and commit docs/diversification_frontier.json + "
        "docs/DIVERSIFICATION_FRONTIER.md."
    )

    db = SessionLocal()
    problems: List[str] = []
    boms_checked = 0
    try:
        for name, counted in EXPECTED_ROW_COUNTS.items():
            got = db.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
            assert got == counted, (
                f"the database this test read has {got} rows in {name}, not {counted}. "
                "Run pytest from backend/ (DATABASE_URL is CWD-relative)."
            )

        graph_state = get_graph_state() or build_graph_state(db)
        weights = get_strategy(STRATEGY_ID)

        for bom_name, items in BOM_CATALOG.items():
            expected = expected_by_bom.get(bom_name)
            if expected is None:
                problems.append(
                    f"{bom_name}: in BOM_CATALOG but absent from the committed frontier"
                )
                continue
            actual = sweep_bom(db, graph_state, bom_name, items, weights)
            boms_checked += 1
            _compare(f"boms.{bom_name}", expected, actual, problems)
    finally:
        db.close()

    assert boms_checked >= 10, (
        f"only {boms_checked} BOMs were re-solved — the pin has gone quiet."
    )
    assert not problems, (
        f"docs/diversification_frontier.json no longer matches what the optimizer "
        f"produces ({len(problems)} differing values across {boms_checked} BOMs).\n"
        f"{regenerate}\n\n"
        + "\n".join(f"  - {p}" for p in problems[:40])
        + (f"\n  ... and {len(problems) - 40} more" if len(problems) > 40 else "")
    )


# ── 4. newsvendor.json vs the live evaluation ────────────────────────────────

NEWSVENDOR_JSON = DOCS / "newsvendor.json"

# `_run` stamps its own wall-clock onto each configuration; the evaluation itself
# does not produce it.
NEWSVENDOR_SKIP_FIELDS = frozenset({"wall_seconds"})


def test_newsvendor_primary_reproduces_from_the_live_evaluation():
    """
    ``tests/test_newsvendor_docs_match_artifact.py`` says so in its own docstring:
    *"It does not re-run the evaluation ... and does not import
    app.optimization.newsvendor. It reads two committed files and compares them."*
    So nothing tied the published newsvendor numbers to the code that computes
    them. This does.

    Re-runs the PRIMARY configuration only, at the artifact's own ``n_boot`` and
    ``seed``, through the same ``run_panel_evaluation`` the generator calls.
    Measured: 3.3 s. The four sensitivity arms are the same call with one argument
    changed and would cost ~14 s more for no additional coverage of the code path.
    """
    if not NEWSVENDOR_JSON.is_file():
        pytest.skip("docs/newsvendor.json not present")

    from app.optimization.newsvendor import run_panel_evaluation
    from seeds.run_newsvendor import N_BOOT, SEED

    artifact = json.loads(NEWSVENDOR_JSON.read_text())
    meta = artifact.get("meta", {})
    assert meta.get("n_boot") == N_BOOT and meta.get("bootstrap_seed") == SEED, (
        f"the artifact was generated with n_boot={meta.get('n_boot')} "
        f"seed={meta.get('bootstrap_seed')} but seeds/run_newsvendor now uses "
        f"n_boot={N_BOOT} seed={SEED}; the two are not comparable. "
        "Re-run `cd backend && ./venv/bin/python -m seeds.run_newsvendor`."
    )

    started = time.perf_counter()
    actual = run_panel_evaluation(n_boot=N_BOOT, seed=SEED)
    elapsed = time.perf_counter() - started

    expected = artifact["primary"]
    problems: List[str] = []
    _compare(
        "primary", expected, actual, problems,
        abs_tol=STAT_ABS_TOL, rel_tol=STAT_REL_TOL,
        skip_fields=NEWSVENDOR_SKIP_FIELDS,
    )

    assert elapsed < 90.0, (
        f"the newsvendor re-run took {elapsed:.1f}s against a 3.3s measurement — "
        "the evaluation has changed shape and this pin needs re-budgeting."
    )
    assert not problems, (
        f"docs/newsvendor.json's `primary` block no longer matches what "
        f"app.optimization.newsvendor produces ({len(problems)} differing values).\n"
        "The ARTIFACT is stale: re-run `cd backend && ./venv/bin/python -m "
        "seeds.run_newsvendor` and commit docs/newsvendor.json + the "
        "RESEARCH_TECHNIQUES.md section it feeds.\n\n"
        + "\n".join(f"  - {p}" for p in problems[:40])
        + (f"\n  ... and {len(problems) - 40} more" if len(problems) > 40 else "")
    )
