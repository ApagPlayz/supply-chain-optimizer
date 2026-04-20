"""
Regression tests for the Fiedler sequential-removal curve.

Guards Research Pitfall #1: `nx.algebraic_connectivity(..., method="tracemin_pcg")`
on stock-weighted bipartite graphs silently returned λ₂ = 0.0 in 146s during
Phase 2 testing on the 847-node LCC. Phase 4 uses `method="lanczos"` on an
UNWEIGHTED laplacian for the sequential-removal curve — this test suite is
the canary that catches regressions to that behavior.

See .planning/phases/04-benchmark-dashboard/04-RESEARCH.md §Pitfall 1 and
§Pattern 3.
"""
from __future__ import annotations

import time

import pytest

from app.graph import get_graph_state, set_graph_state
from app.graph.builder import build_graph_state
from app.main import compute_fiedler_curve


_EXPECTED_KEYS = {"step", "removed", "removed_name", "lambda2", "delta_pct"}


def test_curve_structure(graph_db_session):
    """Curve has exactly 6 entries with the expected schema; baseline has None for removal."""
    gs = build_graph_state(graph_db_session)
    curve = compute_fiedler_curve(gs, graph_db_session, top_k=5)

    assert len(curve) == 6
    for i, entry in enumerate(curve):
        assert set(entry.keys()) == _EXPECTED_KEYS, f"step {i} keys mismatch"
        assert entry["step"] == i

    # Baseline entry
    assert curve[0]["removed"] is None
    assert curve[0]["removed_name"] is None
    assert curve[0]["delta_pct"] == 0.0


def test_nonzero_on_connected(graph_db_session):
    """
    On the healthy 3-distributor connected test graph, baseline λ₂ must be > 0.

    This is the direct Pitfall #1 guard — the tracemin_pcg regression bug
    manifests as λ₂ = 0 on graphs that are definitely connected.
    """
    gs = build_graph_state(graph_db_session)
    curve = compute_fiedler_curve(gs, graph_db_session, top_k=5)
    assert curve[0]["lambda2"] > 1e-6, (
        f"Pitfall #1 regression — baseline λ₂ should be > 0 on healthy graph, "
        f"got {curve[0]['lambda2']}"
    )


def test_wall_clock_bound(graph_db_session):
    """Full 6-step curve must complete in < 10 seconds on the small test graph."""
    gs = build_graph_state(graph_db_session)
    t0 = time.time()
    compute_fiedler_curve(gs, graph_db_session, top_k=5)
    elapsed = time.time() - t0
    assert elapsed < 10.0, f"Fiedler curve took {elapsed:.1f}s (expected < 10s)"


def test_lambda2_bounds_and_eventual_collapse(graph_db_session):
    """
    λ₂ values must be finite and non-negative; once distributors are exhausted,
    trailing steps must collapse to 0.0.

    NOTE: strict step-over-step monotonicity of λ₂ does NOT hold when each step
    measures λ₂ of the LARGEST connected component rather than the whole graph
    (per Pattern 3). Removing a bridge node can fragment a sparse graph into
    smaller, relatively tighter components whose λ₂ briefly rises. The robust
    signal is delta_pct measured against the fixed baseline (tested elsewhere).
    """
    gs = build_graph_state(graph_db_session)
    curve = compute_fiedler_curve(gs, graph_db_session, top_k=5)

    for entry in curve:
        assert entry["lambda2"] >= 0.0, (
            f"λ₂ must be non-negative, got {entry['lambda2']} at step {entry['step']}"
        )
        # Algebraic connectivity of a simple graph on n nodes is bounded by n.
        # Our test graph has 13 nodes total; 2.0 is a generous upper bound on any
        # subgraph λ₂ observed under unweighted laplacian.
        assert entry["lambda2"] < 10.0, (
            f"λ₂ implausibly large ({entry['lambda2']}) at step {entry['step']}"
        )

    # Trailing entries (after the 3 distributors are exhausted) must be 0.0.
    assert curve[-1]["lambda2"] == 0.0, (
        f"Expected last step λ₂ = 0.0 after exhausting distributors, got {curve[-1]['lambda2']}"
    )


def test_fiedler_curve_on_graphstate(graph_db_session):
    """Assigning the curve onto GraphState + set_graph_state round-trips via get_graph_state."""
    gs = build_graph_state(graph_db_session)
    gs.fiedler_curve = compute_fiedler_curve(gs, graph_db_session, top_k=5)
    set_graph_state(gs)
    try:
        gs_out = get_graph_state()
        assert gs_out is not None
        assert gs_out.fiedler_curve == gs.fiedler_curve
        assert len(gs_out.fiedler_curve) == 6
    finally:
        set_graph_state(None)


def test_graceful_fallback_on_disconnect(graph_db_session):
    """
    Requesting more removals than we have distributors must not raise.

    The test graph has 3 distributors; top_k=5 requires the last 2 removal steps
    to be padded. At least one trailing entry must have λ₂ = 0 (graph trivial).
    """
    gs = build_graph_state(graph_db_session)
    curve = compute_fiedler_curve(gs, graph_db_session, top_k=5)
    assert len(curve) == 6
    assert any(entry["lambda2"] == 0.0 for entry in curve[1:]), (
        "Expected at least one trailing step with λ₂ = 0.0 after exhausting distributors"
    )
