---
phase: 5
slug: prophet-demand-forecasting
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-27
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend) / vitest (frontend) |
| **Config file** | `backend/pytest.ini` or `backend/pyproject.toml` |
| **Quick run command** | `cd backend && python -m pytest tests/ -x -q` |
| **Full suite command** | `cd backend && python -m pytest tests/ -v && cd ../frontend && npm test -- --run` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/ -x -q`
- **After every plan wave:** Run full suite
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | FORE-01 | — | No import errors from prophet_forecaster.py | unit | `cd backend && python -c "import app.forecaster"` | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 1 | FORE-01 | — | Alembic migration applies cleanly | integration | `cd backend && alembic upgrade head` | ❌ W0 | ⬜ pending |
| 05-02-01 | 02 | 2 | FORE-02 | — | Training script produces forecast rows for all 791 components | integration | `cd backend && python -m seeds.train_forecasts && python -c "from app.db import SessionLocal; s=SessionLocal(); print(s.execute('SELECT COUNT(*) FROM component_forecasts').scalar())"` | ❌ W0 | ⬜ pending |
| 05-03-01 | 03 | 3 | FORE-03 | — | Forecast API returns 200 with data | integration | `curl -s http://localhost:8000/api/v1/forecasts/all \| python -c "import sys,json; d=json.load(sys.stdin); assert len(d)>0"` | ❌ W0 | ⬜ pending |
| 05-03-02 | 03 | 3 | FORE-03 | — | SchedulerPage renders sparklines without console errors | manual | Browser inspection | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_forecaster.py` — import test for FORE-01
- [ ] `backend/tests/test_forecast_api.py` — endpoint smoke test for FORE-03
- [ ] Alembic migration file for `component_demand_history` and `component_forecasts` tables

*Existing pytest infrastructure assumed — Wave 0 adds forecast-specific test stubs only.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Sparkline renders inline on each of 791 component cards without browser lag | FORE-03 | UI rendering performance cannot be asserted in CLI tests | Load SchedulerPage in browser, scroll through all cards, check DevTools for no console errors and acceptable frame rate |
| Stock-out badge appears correctly when demand > stock within 12 weeks | FORE-03 | Requires visual confirmation of badge color and text | Identify a component where stock exhaustion is predicted; confirm badge shows "Stock-out in ~N weeks" with correct N |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
