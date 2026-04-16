---
phase: 1
slug: codebase-hardening
status: compliant
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-15
audited: 2026-04-16
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 |
| **Config file** | `backend/tests/conftest.py` |
| **Quick run command** | `cd backend && python -m pytest tests/ -x -q` |
| **Full suite command** | `cd backend && python -m pytest tests/ -v` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/ -x -q`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | HARD-01 | T-1-01 | ValueError raised at startup if SECRET_KEY matches known default or is < 32 chars | unit | `pytest tests/test_security_hardening.py::test_secret_key_validation -x` | ✅ | ✅ green |
| 1-01-02 | 01 | 1 | HARD-02 | T-1-02 | CORS allow_origins reads from env, rejects wildcard | unit | `pytest tests/test_security_hardening.py::test_cors_origins -x` | ✅ | ✅ green |
| 1-01-03 | 01 | 1 | HARD-03 | — | DEBUG defaults to False when env var not set | unit | `pytest tests/test_security_hardening.py::test_debug_default -x` | ✅ | ✅ green |
| 1-01-04 | 01 | 2 | HARD-04 | T-1-04 | Live-price and market endpoints return 401 without token | integration | `pytest tests/test_auth_guards.py -x` | ✅ | ✅ green |
| 1-02-01 | 02 | 1 | HARD-05 | — | No ModuleNotFoundError when importing backend | smoke | `python3 -c "import app.main"` | ✅ | ✅ green |
| 1-03-01 | 03 | 1 | HARD-06 | — | Demo login is idempotent — works for both new and existing user paths | integration | `pytest tests/test_demo_login.py -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `backend/tests/test_security_hardening.py` — 7 tests covering HARD-01, HARD-02, HARD-03 ✅
- [x] `backend/tests/test_auth_guards.py` — 9 tests covering HARD-04 (401 on unauthenticated live-price/market calls) ✅
- [x] `backend/tests/test_demo_login.py` — 5 tests covering HARD-06 (idempotent demo login, both paths) ✅
- [x] `backend/tests/conftest.py` — FastAPI TestClient fixture, test database setup, auth token helper ✅

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Backend imports cleanly after orphan deletion | HARD-05 | Smoke test is a one-liner; no test file needed | `cd backend && python -c "import app.main"; echo $?` → must be 0 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-04-16

## Validation Audit 2026-04-16
| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 6 |
| Escalated | 0 |

All 6 requirements have automated test coverage. 21 tests passing (7 security hardening + 9 auth guards + 5 demo login).
