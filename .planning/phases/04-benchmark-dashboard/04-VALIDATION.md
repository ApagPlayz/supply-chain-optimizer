---
phase: 4
slug: benchmark-dashboard
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-18
revised: 2026-04-20
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (backend) + vitest (frontend, if present) |
| **Config file** | backend/pytest.ini (or pyproject.toml) / frontend/vitest.config.ts |
| **Quick run command** | `cd backend && pytest tests/test_benchmark_api.py -x -q` |
| **Full suite command** | `cd backend && pytest -x` |
| **Estimated runtime** | ~30 seconds quick; ~90 seconds full |

---

## Sampling Rate

- **After every task commit:** Run quick command for the plan under edit
- **After every plan wave:** Run full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01 T1 | 04-01 | 1 | BENCH-01 | T-04-01-01 | `cascade_risk_score` NOT NULL on every row | unit | `python3 -m pytest tests/test_optimization_run_model.py -x -q` | ✅ created in 04-01 | pending |
| 04-01 T2 | 04-01 | 1 | BENCH-01, BENCH-06 | T-04-01-02 | 20 rows per run, holdout semantics doc'd | integration | `python3 -m pytest tests/test_run_benchmark.py -x -q` | ✅ created in 04-01 | pending |
| 04-01 T3 | 04-01 | 1 | BENCH-05 | T-04-01-03 | Fiedler curve has 6 entries, λ₂ non-zero on connected graph, lanczos wall-clock < 10s | unit | `python3 -m pytest tests/test_fiedler_sequential.py -x -q` | ✅ created in 04-01 | pending |
| 04-01 T4 | 04-01 | 1 | BENCH-01 | — | `is_chinese_origin` propagates from `risk_factors` to Offer construction | regression | `python3 -m pytest tests/test_is_chinese_origin_propagation.py -x -q` | ✅ created in 04-01 | pending |
| 04-02 T1 | 04-02 | 1 | BENCH-02, BENCH-05, BENCH-06 | T-04-02-01..05 | `/benchmark/summary` returns correct keys; 404 on empty DB with run_benchmark instruction; no unaggregated user data | integration | `python3 -m pytest tests/test_benchmark_api.py -x -q` | ✅ created in 04-02 | pending |
| 04-02 T2 | 04-02 | 1 | BENCH-02, BENCH-04 | T-04-02-02 | 14+ tests pass; delta sign convention correct; MC shape validated; no fabricated strings | integration | `python3 -m pytest tests/test_benchmark_api.py -x -q` | ✅ created in 04-02 | pending |
| 04-02 T3 | 04-02 | 1 | VIZ-02 | T-04-02-06 | `/benchmark/single-source-components` returns real MPN + manufacturer from ORM; mpn ≠ "High-betweenness hub" | integration | `python3 -m pytest tests/test_benchmark_api.py::test_single_source_components_shape tests/test_benchmark_api.py::test_single_source_components_no_fabricated_strings -v` | ✅ created in 04-02 | pending |
| 04-03 T1 | 04-03 | 1 | BENCH-03 | — | `api.ts` has `benchmarkAPI` with all methods; `lib/risk.ts` exports `RISK_COLORS` + `riskLabel`; `npx tsc --noEmit` exits 0 | static | `grep -n "benchmarkAPI\|RISK_COLORS\|riskLabel" frontend/src/services/api.ts frontend/src/lib/risk.ts && cd frontend && npx tsc --noEmit` | created in 04-03 | pending |
| 04-03 T2 | 04-03 | 1 | BENCH-03, BENCH-04, BENCH-05, BENCH-06 | — | BenchmarkPage renders hero, 3 KPI cards, MC grouped BarChart, tradeoff card, Fiedler LineChart; `npx tsc --noEmit` exits 0 | static + visual | `cd frontend && npx tsc --noEmit` | created in 04-03 | pending |
| 04-04 T1 | 04-04 | 2 | VIZ-01, VIZ-02, VIZ-03 | T-04-04-01..06 | `api.ts` has `graphAPI.metrics()` and `benchmarkAPI.singleSourceComponents()`; no duplicates | static | `grep -n "graphAPI\|singleSourceComponents" frontend/src/services/api.ts` | modified in 04-04 | pending |
| 04-04 T2 | 04-04 | 2 | VIZ-01, VIZ-02, VIZ-03 | T-04-04-01..06 | MapPage has Network Risk toggle; markers sized by betweenness; single-source halos from real API data (not betweenness proxy); side panel rows use `{mpn} · {manufacturer} · only source: {distributor_name}`; no "High-betweenness hub" string; cascade heatmap present; Routes view unchanged; `npx tsc --noEmit` exits 0 | static + visual | `cd frontend && npx tsc --noEmit && grep -c "High-betweenness" src/pages/MapPage.tsx \|\| true` | modified in 04-04 | pending |

---

## Wave 0 Requirements

- [x] `backend/tests/test_optimization_run_model.py` — stubs for BENCH-01 (OptimizationRun schema, run_id append-only) — **created in 04-01**
- [x] `backend/tests/test_run_benchmark.py` — stubs for BENCH-01, BENCH-06 (run_benchmark.py reproducibility under seed=42) — **created in 04-01**
- [x] `backend/tests/test_benchmark_api.py` — stubs for BENCH-02, BENCH-04, VIZ-02, VIZ-03 (summary delta math, fiedler-curve payload shape, cascade heatmap shape, single-source real data) — **created in 04-02**
- [x] `backend/tests/test_fiedler_sequential.py` — regression test for Pitfall #1 (sequential-removal λ₂ never returns 0 on healthy graph; wall-clock < 10s) — **created in 04-01**
- [x] `backend/tests/test_is_chinese_origin_propagation.py` — regression test for Open Q #1 (offers constructed in /optimize path carry is_chinese_origin from risk_factors) — **created in 04-01**

*Frontend tests are optional unless vitest is already configured.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Benchmark page "hero headline renders correct percentages" | BENCH-03, VIZ-01 | Visual regression of large-font layout | Open `/benchmark`, compare headline to `/benchmark/summary` JSON |
| Map Network Risk toggle + halos from real single-source API | VIZ-02, VIZ-03 | maplibre marker rendering + heatmap overlay requires browser | Toggle to Network Risk, verify single-source distributors have red halo; side panel shows real MPNs (e.g. "STM32F103C8T6") not "High-betweenness hub"; toggle Cascade Risk, verify viridis gradient |
| Fiedler card click interaction reveals affected BOMs | BENCH-04 | Recharts click hit-test requires browser | Click each of the 5 points on the Fiedler curve, verify correct BOM names appear |
| Honest-tradeoff card surfaces when all deltas favor graph-aware | BENCH-06 | Data-dependent rendering | Seed-stable benchmark must always produce at least one losing axis; verify card never renders empty |

---

## Nyquist Compliance Notes

Every task in every plan has at least one `<automated>` verify block:
- 04-01: 4 tasks × pytest commands → compliant
- 04-02: 3 tasks × pytest commands → compliant
- 04-03: 2 tasks × `npx tsc --noEmit` → compliant
- 04-04: 2 tasks × grep + `npx tsc --noEmit` → compliant

No 3 consecutive tasks exist without an automated verify. Wave 0 test files exist (created in 04-01 and 04-02). Nyquist rule satisfied.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**BENCH-02 / BENCH-04 coverage:** `test_benchmark_api.py` Tests 1–12 cover summary shape + delta math + MC shape + feeds_fallback (BENCH-02, BENCH-04).
**VIZ-02 / VIZ-03 coverage:** `test_benchmark_api.py` Tests 13–14 cover single-source real data (VIZ-02); Tests 9–10 cover cascade heatmap shape (VIZ-03).
**All rows verified:** no requirement row in the Phase Requirements table is uncovered by at least one automated command.

**Approval:** pending
