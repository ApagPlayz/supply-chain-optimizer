---
phase: 3
slug: live-data-feeds
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-17
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio |
| **Config file** | `backend/tests/conftest.py` (existing) |
| **Quick run command** | `cd backend && python -m pytest tests/test_feeds.py -x -q` |
| **Full suite command** | `cd backend && python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds (quick), ~60 seconds (full) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/test_feeds.py -x -q`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 0 | FEED-05, FEED-06 | T-SSRF | Cache returns None on init | unit | `pytest tests/test_feeds.py::test_cache_init -x` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | FEED-05, FEED-06 | T-SSRF | LiveDataCache singleton returns same instance | unit | `pytest tests/test_feeds.py::test_singleton -x` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | FEED-06 | — | `_feed_risk_cents()` returns 0 when cache is None | unit | `pytest tests/test_feeds.py::test_feed_risk_graceful -x` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | FEED-06 | — | `_port_delay_days()` returns 0 when cache is None | unit | `pytest tests/test_feeds.py::test_port_delay_graceful -x` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 2 | FEED-01 | T-KeyLeak | GPR value parsed from XLSX, stored in cache | unit | `pytest tests/test_feeds.py::test_gpr_parse -x` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | FEED-02 | T-KeyLeak | ACLED conflict counts aggregated by country | unit | `pytest tests/test_feeds.py::test_acled_aggregate -x` | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 2 | FEED-01, FEED-02 | — | `_feed_risk_cents()` returns higher surcharge for CN-origin when GPR elevated | unit | `pytest tests/test_feeds.py::test_feed_risk_gpr_signal -x` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 2 | FEED-03 | — | PortWatch congestion proxy computed from port calls deviation | unit | `pytest tests/test_feeds.py::test_portwatch_congestion -x` | ❌ W0 | ⬜ pending |
| 03-03-02 | 03 | 2 | FEED-04 | T-KeyLeak | FRED TSIFRGHT latest value extracted | unit | `pytest tests/test_feeds.py::test_fred_freight -x` | ❌ W0 | ⬜ pending |
| 03-03-03 | 03 | 2 | FEED-05 | — | `/feeds/status` returns 4 feeds with name/fetched_at/status | unit | `pytest tests/test_feeds.py::test_feed_status_endpoint -x` | ❌ W0 | ⬜ pending |
| 03-03-04 | 03 | 3 | FEED-07 | T-KeyLeak | No API keys in frontend bundle | smoke | `grep -rE 'ACLED_KEY\|FRED_API_KEY\|PORTWATCH' frontend/src/ && exit 1 \|\| exit 0` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_feeds.py` — stub test file with all test functions (test_cache_init, test_singleton, test_feed_risk_graceful, test_port_delay_graceful, test_gpr_parse, test_acled_aggregate, test_feed_risk_gpr_signal, test_portwatch_congestion, test_fred_freight, test_feed_status_endpoint)
- [ ] `pip install apscheduler==3.11.2` added to `backend/requirements_minimal.txt`
- [ ] `pip install openpyxl` added to `backend/requirements_minimal.txt` (for GPR XLSX parsing)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| APScheduler actually fires at 15-min interval | FEED-05 | Requires real clock time | Start server, watch logs for 15 min, confirm all 4 feeds log completion timestamps |
| UI shows [stale]/[unavailable] when feeds down | FEED-06 | Requires network kill | Disconnect internet, reload Dashboard, verify badges show Stale/Unavailable (not blank) |
| ACLED OAuth works with real credentials | FEED-02 | Requires real API key registration | Set ACLED_EMAIL + ACLED_KEY in .env, trigger manual refresh, confirm country dict populated |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
