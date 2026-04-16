---
phase: 02
slug: graph-ml-network-risk-engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-16
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `backend/pytest.ini` or inline `pyproject.toml` |
| **Quick run command** | `cd backend && python -m pytest tests/test_graph_metrics.py tests/test_graph_api.py -q` |
| **Full suite command** | `cd backend && python -m pytest tests/ -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/test_graph_metrics.py tests/test_graph_api.py -q`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 0 | GRAPH-09 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_graph_state_singleton -q` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | GRAPH-01 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_graph_builds_from_db -q` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | GRAPH-10 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_graph_builds_under_2s -q` | ❌ W0 | ⬜ pending |
| 02-01-04 | 01 | 1 | GRAPH-09 | — | N/A | integration | `pytest tests/test_graph_api.py::test_lifespan_loads_graph -q` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | GRAPH-02 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_betweenness_centrality -q` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 2 | GRAPH-03 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_pagerank_centrality -q` | ❌ W0 | ⬜ pending |
| 02-02-03 | 02 | 2 | GRAPH-04 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_fiedler_value -q` | ❌ W0 | ⬜ pending |
| 02-02-04 | 02 | 2 | GRAPH-05 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_kcore_decomposition -q` | ❌ W0 | ⬜ pending |
| 02-02-05 | 02 | 2 | GRAPH-06 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_hhi_per_category -q` | ❌ W0 | ⬜ pending |
| 02-02-06 | 02 | 2 | GRAPH-05 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_single_source_flags -q` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 3 | GRAPH-07 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_monte_carlo_returns_percentiles -q` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 3 | GRAPH-07 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_monte_carlo_reproducible -q` | ❌ W0 | ⬜ pending |
| 02-03-03 | 03 | 3 | GRAPH-07 | — | N/A | unit | `pytest tests/test_graph_metrics.py::test_evar_at_95th_percentile -q` | ❌ W0 | ⬜ pending |
| 02-04-01 | 04 | 4 | GRAPH-08 | T-02-01 | Surcharge ceiling enforced at 15% unit price | unit | `pytest tests/test_graph_metrics.py::test_surcharge_ceiling -q` | ❌ W0 | ⬜ pending |
| 02-04-02 | 04 | 4 | GRAPH-08 | — | N/A | integration | `pytest tests/test_graph_api.py::test_graph_aware_changes_routing -q` | ❌ W0 | ⬜ pending |
| 02-04-03 | 04 | 4 | GRAPH-01 | — | N/A | integration | `pytest tests/test_graph_api.py::test_get_graph_metrics -q` | ❌ W0 | ⬜ pending |
| 02-04-04 | 04 | 4 | GRAPH-07 | — | N/A | integration | `pytest tests/test_graph_api.py::test_post_graph_simulate -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_graph_metrics.py` — stubs for GRAPH-01 through GRAPH-07, GRAPH-09, GRAPH-10
- [ ] `backend/tests/test_graph_api.py` — stubs for GRAPH-08 and endpoint integration tests
- [ ] `backend/tests/conftest.py` — add `graph_state` fixture using in-memory test DB with seeded offers

*Existing pytest infrastructure covers the framework — only new test files needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Startup log line visible in uvicorn output | GRAPH-10 | Log output not captured by TestClient | Start server, check stderr for "Graph built: ... distributors, ... components" |
| graph_aware=true produces visibly different distributor selection in UI | GRAPH-08 | Requires running optimizer with real BOM via browser | Add 3+ components to cart, optimize, compare strategies with/without graph_aware |

---

## Validation Architecture

This phase builds a standalone graph analytics module with no external API dependencies. The validation strategy is:

1. **Wave 0:** Stub test files created first (test file exists but functions raise `NotImplementedError`) — satisfies "File Exists" ✅ for all tasks
2. **Waves 1-3:** Unit tests validate each metric in isolation using a small synthetic in-memory graph (5 distributors, 20 components) — fast, deterministic
3. **Wave 4:** Integration tests validate the full pipeline: lifespan loads graph, endpoints respond correctly, `graph_aware=true` changes the optimizer output

**Monte Carlo reproducibility:** `test_monte_carlo_reproducible` runs simulate() twice with seed=42 and asserts identical P10/P50/P90/EVaR output.

**Surcharge ceiling test:** `test_surcharge_ceiling` asserts that for any (distributor, component) pair, `graph_surcharge_cents <= 0.15 * unit_price_cents`.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
