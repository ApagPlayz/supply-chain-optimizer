---
phase: 04-benchmark-dashboard
reviewed: 2026-04-21T00:00:00Z
depth: standard
files_reviewed: 36
files_reviewed_list:
  - backend/app/api/__init__.py
  - backend/app/api/benchmark.py
  - backend/app/api/feeds.py
  - backend/app/api/graph.py
  - backend/app/api/optimize.py
  - backend/app/core/config.py
  - backend/app/feeds/__init__.py
  - backend/app/feeds/fetchers.py
  - backend/app/feeds/scheduler.py
  - backend/app/graph/__init__.py
  - backend/app/graph/builder.py
  - backend/app/graph/simulation.py
  - backend/app/main.py
  - backend/app/models/__init__.py
  - backend/app/models/optimization_run.py
  - backend/app/optimization/costs.py
  - backend/app/optimization/solve.py
  - backend/app/optimization/sourcing.py
  - backend/pytest.ini
  - backend/requirements_minimal.txt
  - backend/seeds/run_benchmark.py
  - backend/tests/conftest.py
  - backend/tests/test_benchmark_api.py
  - backend/tests/test_feeds.py
  - backend/tests/test_fiedler_sequential.py
  - backend/tests/test_graph_api.py
  - backend/tests/test_graph_metrics.py
  - backend/tests/test_is_chinese_origin_propagation.py
  - backend/tests/test_optimization_run_model.py
  - backend/tests/test_run_benchmark.py
  - frontend/src/App.tsx
  - frontend/src/components/NavBar.tsx
  - frontend/src/lib/risk.ts
  - frontend/src/pages/BenchmarkPage.tsx
  - frontend/src/pages/Dashboard.tsx
  - frontend/src/pages/MapPage.tsx
  - frontend/src/services/api.ts
findings:
  critical: 0
  warning: 6
  info: 7
  total: 13
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-04-21
**Depth:** standard
**Files Reviewed:** 36
**Status:** issues_found

## Summary

This phase delivers the benchmark dashboard backend (4 new `/benchmark/*` endpoints, `OptimizationRun` ORM model, `seeds/run_benchmark.py` pipeline), the Fiedler sequential-removal curve, live data feeds wiring, and the React frontend for `BenchmarkPage`, `MapPage` Network Risk view, and shared `risk.ts` utilities.

Overall the code is well-structured, security-conscious (hardcoded URL constants, no user-supplied URLs, feed-credential isolation, graph-surcharge ceiling), and thoroughly tested. No critical vulnerabilities were found.

Six warnings were identified: a silent data-loss path in the benchmark commit logic, a division-by-zero edge case in the `_monte_carlo_eta` helper, stale `fulfilled_rates`/`cost_inflations` pairing after in-place sort, an unhandled promise rejection in MapPage, a missing `await` on an unresolved route-fetch promise chain, and a leaked dependency-override in benchmark API tests when the pre-request throws. Seven informational items cover dead code, magic numbers, duplicate logic, and minor type-safety gaps.

---

## Warnings

### WR-01: Benchmark pipeline silently drops failures and commits a partial run

**File:** `backend/seeds/run_benchmark.py:346-356`
**Issue:** The `main()` loop calls `_run_one()` for each (BOM, graph_aware) combination inside the `try` block but commits once after the entire loop. If `_run_one` returns `None` for some BOMs (solver failure, missing offers) the loop continues and `db.commit()` persists a partial run with fewer than 20 rows. The `/benchmark/summary` endpoint then returns aggregate deltas over an inconsistent row set, potentially producing misleading dashboard metrics with no indication that rows are missing.
**Fix:** Count successful rows and raise before commit if the total is below the expected 20:
```python
successful = 0
for bom_name, bom_items in catalog.items():
    for graph_aware in (False, True):
        row = _run_one(...)
        if row is not None:
            successful += 1

if successful < len(catalog) * 2:
    logger.warning(
        "Partial benchmark run: %d/%d rows succeeded — aborting commit",
        successful, len(catalog) * 2,
    )
    db.rollback()
    return 1

db.commit()
```

---

### WR-02: Division-by-zero in `_monte_carlo_eta` when `n=0`

**File:** `backend/app/optimization/solve.py:77-88`
**Issue:** `_monte_carlo_eta` indexes into `samples` at `int(0.1 * n)` and `int(0.5 * n)`. The parameter `n` defaults to 1000 and is never passed as 0 by current callers, but the function is a module-level helper with no guard. If called with `n=0`, `samples` is empty and `samples[0]` raises `IndexError`. The function is also non-reproducible because it uses `random.gauss`/`random.choices` from the global RNG without seeding.
**Fix:** Guard against empty `n` and document the reproducibility caveat:
```python
def _monte_carlo_eta(base_days: float, n: int = 1000) -> Dict[str, float]:
    if n <= 0:
        return {"p10": base_days, "p50": base_days, "p90": base_days, "samples": []}
    ...
```

---

### WR-03: EVaR pairing is broken by in-place sort of `fulfillment_rates`

**File:** `backend/app/graph/simulation.py:153-169`
**Issue:** `fulfillment_rates.sort()` sorts the list in-place at line 154, destroying the original positional correspondence between `fulfillment_rates[i]` and `cost_inflations[i]`. The `paired = sorted(zip(fulfillment_rates, cost_inflations), ...)` call on line 166 then zips the already-sorted `fulfillment_rates` with the original-order `cost_inflations`, producing incorrect pairs and therefore a wrong EVaR value.
**Fix:** Sort a copy, or zip before sorting:
```python
# Pair before any sort
paired = sorted(
    zip(fulfillment_rates, cost_inflations),
    key=lambda x: x[0]
)
# Percentiles from paired
p10 = paired[_percentile_idx(0.10)][0]
p50 = paired[_percentile_idx(0.50)][0]
p90 = paired[_percentile_idx(0.90)][0]

n_tail = max(1, int(0.05 * n_scenarios))
worst_inflations = [inf for _, inf in paired[:n_tail]]
evar_95 = sum(worst_inflations) / len(worst_inflations)
```

---

### WR-04: Unhandled promise rejection from `distributorsAPI.list()` in MapPage

**File:** `frontend/src/pages/MapPage.tsx:188-193`
**Issue:** The `useEffect` for loading distributors does not attach a `.catch()` handler. If the API call fails (backend offline, 5xx), the unhandled rejection propagates to the global promise rejection handler and `setLoading(false)` is never called, leaving the page stuck in the infinite loading spinner.
```tsx
useEffect(() => {
  distributorsAPI.list().then((res) => {
    setDistributors(res.data);
    setLoading(false);
  });
  // No .catch — loading stays true forever on error
}, []);
```
**Fix:**
```tsx
useEffect(() => {
  distributorsAPI.list()
    .then((res) => setDistributors(res.data))
    .catch(() => {/* silently fail — show empty map */})
    .finally(() => setLoading(false));
}, []);
```

---

### WR-05: Cascade heatmap fetch ignores missing `cascadeActive` in eslint-disable dependency

**File:** `frontend/src/pages/MapPage.tsx:291-299`
**Issue:** The cascade heatmap `useEffect` has `// eslint-disable-line react-hooks/exhaustive-deps` suppressing the warning about `cascadeHeatmapData` missing from the dependency array. The guard `if (cascadeHeatmapData.length > 0) return;` reads stale closure data — if the parent component re-renders and resets `cascadeHeatmapData` to `[]` (e.g., on a view change) the effect will NOT re-fetch because `cascadeActive` has not changed. This is a latent stale-closure bug: toggling Network Risk off and on while cascade is active will show empty heatmap until the user deactivates and reactivates the toggle.
**Fix:** Either remove the cache-hit guard (the fetch is cheap) or add `cascadeHeatmapData.length` to the dependency array without suppressing the lint warning:
```tsx
useEffect(() => {
  if (!cascadeActive || cascadeHeatmapData.length > 0) return;
  benchmarkAPI.cascadeHeatmap()
    .then((res) => setCascadeHeatmapData(res.data.points))
    .catch(() => {});
}, [cascadeActive, cascadeHeatmapData.length]);
```

---

### WR-06: Benchmark API test fixture leaks `dependency_overrides` on unexpected server error

**File:** `backend/tests/test_benchmark_api.py:99-114`
**Issue:** `_make_client_with_db` sets `app.dependency_overrides[get_db]` but only clears it in individual test `finally` blocks. If `TestClient(app, ...)` itself raises (during the lifespan event), `app.dependency_overrides` is never cleared before the exception propagates, potentially contaminating subsequent tests that share the same process. `raise_server_exceptions=False` suppresses this for request errors but not for `__init__`-time failures.
**Fix:** Use a context manager pattern in the helper:
```python
from contextlib import contextmanager

@contextmanager
def _client_with_db(session):
    app.dependency_overrides[get_db] = lambda: (yield session)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
```
Then each test uses `with _client_with_db(session) as client:` and the try/finally in each test becomes unnecessary.

---

## Info

### IN-01: `_require_graph_state` is duplicated across `benchmark.py` and `graph.py`

**File:** `backend/app/api/benchmark.py:112-120`, `backend/app/api/graph.py:56-64`
**Issue:** The identical `_require_graph_state` helper is copy-pasted verbatim in both API modules.
**Fix:** Extract to `app.graph` or a shared `app.api._helpers` module and import.

---

### IN-02: Magic constant `top_k=5` is duplicated between `main.py` call site and doc string

**File:** `backend/app/main.py:147`, `backend/app/main.py:22`
**Issue:** The constant `5` for `top_k` appears in both the function signature default-value comment and the call site. If changed in one place the two diverge.
**Fix:** Define `_FIEDLER_TOP_K = 5` as a module-level constant above `compute_fiedler_curve` and reference it at the call site.

---

### IN-03: `ETA Δd` KPI sub-label unit mismatch — shows days as percentage-like string

**File:** `frontend/src/pages/BenchmarkPage.tsx:386-391`
**Issue:** The ETA KPI card formats its value as `${eta_delta_pct.toFixed(1)}d` (using days) but the field name is `eta_delta_pct`. The backend returns this as a mean-of-delta-pct, not a raw day delta. The label "P50 delivery time, 10 BOMs" is also vague about whether it's a percentage or an absolute day difference.
**Fix:** Rename either the backend field to `eta_delta_days` if it returns days, or update the UI formatting to append `%` and correct the sub-label to "% change in P50 delivery time".

---

### IN-04: `fetchRoadPath` in MapPage uses an external OSRM public instance with no API key

**File:** `frontend/src/pages/MapPage.tsx:83-98`
**Issue:** The app sends user route coordinates (lat/lng pairs) to `https://router.project-osrm.org` — a public demo server operated by third parties. This leaks route geometry. The demo server's terms of service prohibit production use.
**Fix:** Either self-host an OSRM instance, use a commercial routing API with a configured key, or proxy the request through the backend (which is already under CORS control).

---

### IN-05: `requirements_minimal.txt` pins `apscheduler==3.11.2` but other deps are unpinned

**File:** `backend/requirements_minimal.txt:48`
**Issue:** Only `apscheduler` has a version pin. All other packages (fastapi, sqlalchemy, ortools, etc.) are unpinned, making builds non-reproducible and potentially introducing breaking changes on fresh installs. The `psycopg[binary]` entry is also present even though the app uses SQLite by default.
**Fix:** Pin all production dependencies, or use `pip-compile` / `uv lock` to generate a reproducible lockfile. Remove `psycopg[binary]` if PostgreSQL is not used in the target deployment.

---

### IN-06: `_distributor_tier` is duplicated in `optimize.py` and `run_benchmark.py`

**File:** `backend/app/api/optimize.py:29-34`, `backend/seeds/run_benchmark.py:119-124`
**Issue:** The function body is identical in both files.
**Fix:** Move to `app.optimization.sourcing` or a shared utility module and import in both locations.

---

### IN-07: `BenchmarkPage` retry handler duplicates the entire `useEffect` data-fetch logic

**File:** `frontend/src/pages/BenchmarkPage.tsx:198-210`
**Issue:** The "Retry Loading Benchmark" button's `onClick` duplicates the exact same `Promise.all([benchmarkAPI.summary(), benchmarkAPI.fiedlerCurve()])` chain that is already in the `useEffect` at lines 151-159. If the fetch logic changes (e.g., adding a third endpoint), both sites must be updated.
**Fix:** Extract the fetch logic into a named `loadBenchmark` callback with `useCallback` and reference it from both `useEffect` and the retry button.

---

_Reviewed: 2026-04-21_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
