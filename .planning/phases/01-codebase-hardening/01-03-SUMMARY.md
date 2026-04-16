---
phase: 01-codebase-hardening
plan: 03
subsystem: backend-correctness
tags: [fastapi, sqlalchemy, jwt, n+1-query, refactor, pytest]

# Dependency graph
requires:
  - phase: 01-codebase-hardening
    provides: "conftest.py TestClient + db_session + auth_token fixtures (Plan 01)"
provides:
  - "Idempotent demo_login that persists new users and does not double-commit existing users"
  - "Single-query GET /cart via manual 3-way join (was 2N+1)"
  - "Single-query GET /components via DistributorOffer subquery aggregation (was N+1)"
  - "Shared backend/app/optimization/constants.py that centralizes freight/transport constants"
  - "tests/test_demo_login.py — 5 integration tests asserting token validity, idempotency, and authenticated access"
affects: [phase-02-graph-ml, phase-03-live-feeds, phase-05-benchmark]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared-constants module pattern for optimization package (constants.py imported by costs.py and sourcing.py)"
    - "Subquery aggregation over related-table stats for list endpoints (avoids N+1 via GROUP BY + LEFT JOIN)"
    - "Manual 3-way join for models without ForeignKey/relationship declarations"

key-files:
  created:
    - "backend/app/optimization/constants.py"
    - "backend/tests/test_demo_login.py"
    - ".planning/phases/01-codebase-hardening/01-03-SUMMARY.md"
  modified:
    - "backend/app/api/auth.py"
    - "backend/app/api/cart.py"
    - "backend/app/api/components.py"
    - "backend/app/optimization/costs.py"
    - "backend/app/optimization/sourcing.py"

key-decisions:
  - "Kept the existing CartItem model untouched; used an explicit manual .join(Component, ...).join(Distributor, ...) because CartItem has no ForeignKey/relationship declarations (D-19 defers FK work to Phase 2)"
  - "Used SQLAlchemy subquery aggregation (GROUP BY component_id with min/max/count) + OUTER JOIN for the /components list — a LEFT OUTER JOIN keeps components with zero offers in the result, preserving existing behavior"
  - "Imported LBS_PER_KG and CWT_PER_LB from the shared constants module in sourcing.py as well, even though the plan only called out LTL_BASE/LTL_RATE/KM_PER_MILE — the objective says 'eliminate silent divergence' and the two unit conversions were also duplicated"
  - "Kept the local AVG_KG_PER_UNIT = 0.05 literal in sourcing.py because it is a different constant name than costs.py's AVG_COMPONENT_KG; merging the naming would have been an architectural refactor beyond this plan's scope"

patterns-established:
  - "Any new optimization freight/unit constant lives in backend/app/optimization/constants.py and is imported by consumers"
  - "Demo login follows the standard idempotent upsert pattern — query, add+commit if missing, update+commit if present, refresh once, build token"

requirements-completed:
  - HARD-06

# Metrics
duration: 22min
completed: 2026-04-16
---

# Phase 01 Plan 03: Quick Wins Summary

**Fixed demo login persistence bug, collapsed /cart 2N+1 queries into one join, collapsed /components N+1 offer queries into a single GROUP BY subquery, and centralized freight constants into a shared optimization/constants.py module.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-04-16T16:46:00Z
- **Completed:** 2026-04-16T17:08:00Z
- **Tasks:** 2
- **Files modified:** 5 (plus 2 created)

## Accomplishments

- Demo login now persists newly-created users and returns a JWT whose `sub` claim is a real integer user ID (previously `None` because `db.add` was never called in the new-user branch)
- Demo login existing-user branch no longer double-commits (removed redundant `db.add(user)` + second `db.commit()` + `db.refresh()`)
- 5 new integration tests in `tests/test_demo_login.py` cover first-call creation, token validity, repeated-call success, single-row invariant, and authenticated access to `/auth/me`
- `GET /cart` now issues a single SQL query (3-way join over CartItem + Component + Distributor) instead of 1 + 2N queries
- `GET /components` now issues a single SQL query (subquery aggregation over DistributorOffer joined to Component) instead of 1 + N queries (was 792 queries for the full list of 791 components)
- Freight constants (`KM_PER_MILE`, `LBS_PER_KG`, `CWT_PER_LB`, `TL_RATE_USD_PER_MILE`, `LTL_BASE_FEE_USD`, `LTL_RATE_USD_PER_CWT_MILE`, `GROUND_KM_PER_DAY`, `CO2_G_PER_TON_MILE`) now live once in `backend/app/optimization/constants.py`; `costs.py` and `sourcing.py` import them (sourcing.py uses aliased imports for its short `LTL_BASE`/`LTL_RATE` local names)
- Full backend test suite (66 tests) passes with no regressions

## Task Commits

Each task was committed atomically with `--no-verify` (parallel-executor policy):

1. **Task 1: Fix demo_login + add tests/test_demo_login.py** — `4dc4bde` (fix)
2. **Task 2: N+1 fixes + constants.py extraction** — `6182454` (perf)

## Files Created/Modified

- `backend/app/api/auth.py` — `demo_login` rewritten per D-15/D-16: new-user path now calls `db.add(user); db.commit(); db.refresh(user)`; existing-user path has a single commit+refresh cycle
- `backend/tests/test_demo_login.py` — 5 integration tests using the `client` and `db_session` fixtures from Plan 01's conftest
- `backend/app/api/cart.py` — `get_cart` now issues one `db.query(CartItem, Component, Distributor).join(...).join(...).filter(...)` instead of a Python loop with per-item queries
- `backend/app/api/components.py` — `list_components` builds a GROUP BY subquery over `DistributorOffer` with `min/max/count`, then does a single LEFT OUTER JOIN from `Component` to that subquery; filters and pagination are applied to the joined query
- `backend/app/optimization/constants.py` (NEW) — centralized freight + unit + CO2 constants with source citations
- `backend/app/optimization/costs.py` — replaced the 18-line local constant block with a single import from `constants.py`
- `backend/app/optimization/sourcing.py` — module-level import of freight constants (aliased to short names `LTL_BASE`, `LTL_RATE` for compatibility with the existing function body); removed the 6 local literal assignments that lived inside `solve_sourcing`

## Decisions Made

- **Manual join over relationship-based eager load in cart.py** — CartItem stores `component_id` and `distributor_id` as plain Integer columns without ForeignKey declarations, so `selectinload`/`joinedload` are not available. The manual 3-way join matches the research's Pattern 5 recommendation.
- **Subquery over N+1 fallback in components.py** — A LEFT OUTER JOIN on a GROUPed subquery preserves components that have zero offers (they get `None/None/0` for the price/offer stats, matching the pre-fix behavior where `prices = []` produced `min_price=None, max_price=None, num_offers=0`).
- **Aliased imports in sourcing.py** — Function body uses the short identifiers `LTL_BASE` and `LTL_RATE`. Rewriting the body to use long names would have churned lines outside the stated scope. Aliased import preserves exact call sites.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 — Missing Critical] Also imported `LBS_PER_KG` and `CWT_PER_LB` in sourcing.py**
- **Found during:** Task 2 Step 3 (sourcing.py import update)
- **Issue:** The plan's Step 3 only listed `LTL_BASE`, `LTL_RATE`, `KM_PER_MILE` as the duplicated constants to replace, but `sourcing.py` also locally redefined `LBS_PER_KG = 2.20462` and `CWT_PER_LB = 0.01` — both were already present in costs.py. Leaving these as local literals after extracting the other three would have partially defeated the plan's stated objective ("duplicated constants between costs.py and sourcing.py risk silent divergence").
- **Fix:** Added `LBS_PER_KG` and `CWT_PER_LB` to the import from `app.optimization.constants`, and removed the two local literal lines.
- **Files modified:** `backend/app/optimization/sourcing.py`
- **Verification:** Full test suite (66 tests) passes; sourcing-dependent tests (`test_sourcing.py`, `test_strategies.py`) green.
- **Committed in:** `6182454` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 missing-critical completeness)
**Impact on plan:** No scope creep — the fix makes the constants-extraction genuinely complete rather than partial. Zero functional change (both literal values match the new shared module exactly).

## Issues Encountered

None. All tasks executed on the first attempt; all plan acceptance criteria and grep-based verification checks pass on the first run.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Wave 2 of Phase 01 is complete; the demo login + query performance issues that most directly affect the interviewer demo experience are resolved
- Freight constants centralization makes it safer for Phase 02 (Graph ML) and Phase 03 (live freight feeds) to add new distance-derived features without risking drift between `costs.py` and `sourcing.py`
- The subquery-aggregation pattern in `list_components` is the idiomatic SQLAlchemy shape Phase 02/05 benchmark code should reuse when they need per-component offer stats at scale

## Self-Check: PASSED

Verified claims against disk:
- FOUND: `backend/app/api/auth.py` (demo_login rewritten; `db.add(user)` present in new-user path; `else` block has exactly one commit+refresh)
- FOUND: `backend/tests/test_demo_login.py` (5 tests, all pass)
- FOUND: `backend/app/optimization/constants.py` (contains `LTL_BASE_FEE_USD = 75.0`, `KM_PER_MILE = 1.60934`, `CO2_G_PER_TON_MILE = 161.8`)
- FOUND: `backend/app/optimization/costs.py` (contains `from app.optimization.constants import`; no local `KM_PER_MILE = 1.60934`)
- FOUND: `backend/app/optimization/sourcing.py` (contains `from app.optimization.constants import`; no local `LTL_BASE = 75.0`)
- FOUND: `backend/app/api/cart.py` (contains `.join(Component, CartItem.component_id == Component.id)`; zero `for item in items:` loops)
- FOUND: `backend/app/api/components.py` (contains `.subquery()`; zero `for c in components:` loops)
- FOUND: commit `4dc4bde` in `git log` (Task 1: fix demo_login persistence)
- FOUND: commit `6182454` in `git log` (Task 2: N+1 fixes + constants extraction)
- FULL SUITE: `python3 -m pytest tests/ -x -q` → 66 passed

---
*Phase: 01-codebase-hardening*
*Completed: 2026-04-16*
