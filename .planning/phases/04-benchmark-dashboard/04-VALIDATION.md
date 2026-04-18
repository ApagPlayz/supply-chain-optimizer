---
phase: 4
slug: benchmark-dashboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-18
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (backend) + vitest (frontend, if present) |
| **Config file** | backend/pytest.ini (or pyproject.toml) / frontend/vitest.config.ts |
| **Quick run command** | `cd backend && pytest tests/test_benchmark -x -q` |
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

*Populated by planner — each task in PLAN.md must map to one or more automated assertions here.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| *TBD by planner* | | | | | | | | | |

---

## Wave 0 Requirements

- [ ] `backend/tests/test_benchmark_models.py` — stubs for BENCH-01 (OptimizationRun schema, run_id append-only)
- [ ] `backend/tests/test_benchmark_pipeline.py` — stubs for BENCH-02, BENCH-05 (run_benchmark.py reproducibility under seed=42)
- [ ] `backend/tests/test_benchmark_api.py` — stubs for BENCH-03, BENCH-06 (summary delta math, fiedler-curve payload shape, cascade heatmap shape)
- [ ] `backend/tests/test_fiedler_sequential.py` — regression test for Pitfall #1 (sequential-removal λ₂ never returns 0 on healthy graph; wall-clock < 10s)
- [ ] `backend/tests/test_is_chinese_origin_propagation.py` — regression test for Open Q #1 (offers constructed in /optimize path carry is_chinese_origin from risk_factors)
- [ ] `backend/tests/conftest.py` — ensure holdout seed fixture + in-memory DB fixture exist

*Frontend tests are optional unless vitest is already configured.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Benchmark page "hero headline renders correct percentages" | BENCH-03, VIZ-01 | Visual regression of large-font layout | Open `/benchmark`, compare headline to `/benchmark/summary` JSON |
| Map Network Risk toggle + halos | VIZ-02, VIZ-03 | maplibre marker rendering + heatmap overlay requires browser | Toggle to Network Risk, verify single-source distributors have red halo; toggle Cascade Risk, verify viridis gradient |
| Fiedler card click interaction reveals affected BOMs | BENCH-04 | Recharts click hit-test requires browser | Click each of the 5 points on the Fiedler curve, verify correct BOM names appear |
| Honest-tradeoff card surfaces when all deltas favor graph-aware | BENCH-06 | Data-dependent rendering | Seed-stable benchmark must always produce at least one losing axis; verify card never renders empty |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
