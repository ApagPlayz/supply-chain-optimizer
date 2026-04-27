---
phase: 4
slug: benchmark-dashboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-21
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend) / manual (frontend — no Vitest/Jest installed) |
| **Config file** | `backend/pytest.ini` or `backend/pyproject.toml` |
| **Quick run command** | `cd backend && python -m pytest tests/ -q` |
| **Full suite command** | `cd backend && python -m pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/ -q`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-04-01 | 04 | 1 | D-01 | — | N/A | manual | visual inspection: spinner replaces button text during fetch | ✅ | ⬜ pending |
| 04-04-02 | 04 | 1 | D-02 | — | N/A | manual | animate-ping halo visible on high-risk markers | ✅ | ⬜ pending |
| 04-04-03 | 04 | 1 | D-03 | — | N/A | manual | clicking marker scrolls supplier into view in side panel | ✅ | ⬜ pending |
| 04-04-04 | 04 | 1 | D-04 | — | N/A | manual | empty-state message shown when no supplier selected | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements.* Backend pytest suite (14 tests) covers API layer. Frontend changes to MapPage.tsx are verified manually.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Loading spinner during map data fetch | D-01 | No frontend test framework installed | Click "Network Risk" tab, observe button shows spinner while data loads |
| animate-ping halo on high-risk markers | D-02 | CSS animation requires visual check | Observe map markers for high-risk suppliers — should show pulsing halo |
| Side panel scroll-into-view | D-03 | DOM scroll behavior requires browser | Click a map marker, verify side panel scrolls to highlight that supplier |
| Empty-state message | D-04 | UI state requires interaction | Load map tab without selecting a marker — verify placeholder text shown |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
