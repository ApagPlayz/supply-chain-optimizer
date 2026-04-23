---
phase: 04-benchmark-dashboard
reviewed: 2026-04-23T00:00:00Z
depth: standard
files_reviewed: 20
files_reviewed_list:
  - backend/app/api/__init__.py
  - backend/app/api/benchmark.py
  - backend/app/graph/__init__.py
  - backend/app/main.py
  - backend/app/models/__init__.py
  - backend/app/models/optimization_run.py
  - backend/pytest.ini
  - backend/seeds/run_benchmark.py
  - backend/tests/test_benchmark_api.py
  - backend/tests/test_fiedler_sequential.py
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
  info: 5
  total: 11
status: issues_found
---

# Phase 04: Code Review Report

**Reviewed:** 2026-04-23
**Depth:** standard
**Files Reviewed:** 20
**Status:** issues_found

## Summary

This review covers the Phase 04 benchmark dashboard deliverables: the four `/benchmark/*` API endpoints, `OptimizationRun` ORM model, `seeds/run_benchmark.py` pipeline, `BenchmarkPage` React component, Network Risk overlays in `MapPage`, shared `risk.ts` utilities, and associated test suite.

The implementation is well-structured. Strict nullable constraints on the ORM model, explicit Pitfall-#1 guards on the Fiedler computation, real-data-only enforcement on `single-source-components`, and solid unit test coverage are all notable strengths. No critical security vulnerabilities were found.

Six warnings were identified across production code paths:

- Two data-accuracy issues in `benchmark.py`: a baseline-zero edge case silently reporting `0%` deltas, and a `0.0 or None` coercion corrupting EVaR output
- A missing `await` pattern in `BenchmarkPage`'s retry handler that can race between `setLoading(true)` and `finally`
- An unhandled promise rejection in `MapPage`'s distributor fetch leaving the page stuck on the loading spinner
- A global `app.dependency_overrides` mutation in test helpers that is not atomic with `TestClient` construction
- `datetime.utcnow()` deprecated in Python 3.12+ producing naive datetimes inconsistent with the timezone-aware ORM column

Five informational items cover a deferred import that can mask deploy errors, heatmap zero-point exclusion, a test glob that could produce false positives, a magic number, and duplicate fetch logic.

---

## Warnings

### WR-01: `_pct_delta` returns 0.0 when baseline is 0 — silently hides real deltas

**File:** `backend/app/api/benchmark.py:130-134`

**Issue:** When `baseline == 0.0`, the function returns `0.0` instead of signalling that the division is undefined. If any `OptimizationRun` row has `total_cost_usd=0`, `eta_p50_days=0`, or `cascade_risk_score=0` (e.g., all items skipped during seeding), the corresponding per-BOM delta is silently reported as 0%, distorting the aggregate summary without any warning. The comment "Returns 0.0 if baseline is 0" treats this as documented behaviour, but callers do not handle it specially.

**Fix:**
```python
def _pct_delta(baseline: float, graph_aware: float) -> Optional[float]:
    """Return None if baseline is 0 (undefined), else (graph_aware - baseline) / |baseline| * 100."""
    if baseline == 0.0:
        return None
    return (graph_aware - baseline) / abs(baseline) * 100.0
```
Then filter `None` values inside the list comprehensions before passing to `_safe_mean`, or keep `0.0` but emit a `logger.warning` at the call site when baseline is zero.

---

### WR-02: `baseline_evar_95` / `graph_aware_evar_95` silently coerce `0.0` to `None`

**File:** `backend/app/api/benchmark.py:244-245`

**Issue:** The expressions `_safe_list_mean(baseline_rows, "mc_evar_95") or None` coerce the float `0.0` to `None` because `0.0` is falsy in Python. If every row in the run legitimately has `mc_evar_95 = 0.0` (valid: zero expected shortfall), the API returns `null` for both EVaR fields. The frontend and any downstream consumers cannot distinguish "data unavailable" from "EVaR is genuinely zero".

```python
# current — wrong when mean is exactly 0.0
baseline_evar_95=_safe_list_mean(baseline_rows, "mc_evar_95") or None,
```

**Fix:**
```python
def _none_if_all_missing(rows, attr: str) -> Optional[float]:
    """Return mean when any row has the attr; None only when ALL rows have None."""
    vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
    return mean(vals) if vals else None

baseline_evar_95=_none_if_all_missing(baseline_rows, "mc_evar_95"),
graph_aware_evar_95=_none_if_all_missing(graph_aware_rows, "mc_evar_95"),
```

---

### WR-03: Missing `await` pattern in `BenchmarkPage` retry handler races `setLoading`

**File:** `frontend/src/pages/BenchmarkPage.tsx:198-210`

**Issue:** The retry button's `onClick` fires `setLoading(true)` synchronously, then chains `.then()/.catch()/.finally()` on an un-awaited `Promise.all`. This is functionally equivalent to the `useEffect` version, but the `setLoading(true)` on line 199 and `setLoading(false)` in `.finally()` on line 204 can be interleaved with React's batch updates in React 18's concurrent mode if the promise resolves synchronously (unlikely but possible with a fully-cached response). More importantly, the logic is duplicated (also IN-05) and any future change to the fetch (adding a third endpoint, error type) must be applied in two places.

**Fix:** Extract into a `useCallback`:
```tsx
const loadBenchmark = useCallback(async () => {
  setError(null);
  setLoading(true);
  try {
    const [s, f] = await Promise.all([benchmarkAPI.summary(), benchmarkAPI.fiedlerCurve()]);
    setSummary(s.data);
    setFiedler(f.data);
  } catch (err: any) {
    setError(err.response?.status === 404 ? 'empty' : 'error');
  } finally {
    setLoading(false);
  }
}, []);

useEffect(() => { loadBenchmark(); }, [loadBenchmark]);
// retry button: onClick={loadBenchmark}
```

---

### WR-04: Unhandled rejection from `distributorsAPI.list()` leaves `MapPage` stuck loading

**File:** `frontend/src/pages/MapPage.tsx:188-193`

**Issue:** The `useEffect` that fetches the distributor list has no `.catch()` handler. If the backend is offline or returns a non-2xx response, the unhandled rejection propagates to the browser's global handler, `setLoading(false)` is never called, and the map shows a permanent loading spinner with no user-visible error message.

```tsx
// current — no error handling
useEffect(() => {
  distributorsAPI.list().then((res) => {
    setDistributors(res.data);
    setLoading(false);
  });
}, []);
```

**Fix:**
```tsx
useEffect(() => {
  distributorsAPI.list()
    .then((res) => setDistributors(res.data))
    .catch(() => { /* backend offline — display empty map */ })
    .finally(() => setLoading(false));
}, []);
```

---

### WR-05: `app.dependency_overrides` global mutation not atomic with `TestClient` construction

**File:** `backend/tests/test_benchmark_api.py:106-113`

**Issue:** `_make_client_with_db` sets `app.dependency_overrides[get_db]` and returns the client. The cleanup `app.dependency_overrides.clear()` lives inside each test's individual `finally` block. If `TestClient(app, raise_server_exceptions=False)` raises during `__init__` (e.g., a lifespan startup exception), the `finally` block in the caller is still reached — so cleanup does happen in practice. However, the override is set before the `try` in the test body, meaning any failure inside `_make_client_with_db` itself (e.g., a future assertion added there) would bypass the caller's `finally`. Using a pytest fixture with `yield` is the idiomatic pattern that is always safe:

**Fix:**
```python
@pytest.fixture
def api_client(request, db_session):
    """TestClient with injected in-memory DB session. Always cleans up dependency_overrides."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()
```

---

### WR-06: `datetime.utcnow()` deprecated in Python 3.12+, produces naive datetime

**File:** `backend/seeds/run_benchmark.py:302`

**Issue:** `datetime.utcnow()` was formally deprecated in Python 3.12 and will emit a `DeprecationWarning`. It returns a naive (no `tzinfo`) datetime, which is inconsistent with the `created_at` column declared as `DateTime(timezone=True)` in `optimization_run.py:20`. If the host machine is in a non-UTC timezone, the timestamp written to the BENCHMARK-RESULTS.md will be wrong by the local offset.

```python
ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
```

**Fix:**
```python
from datetime import timezone
ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
```

---

## Info

### IN-01: Deferred `from app.graph import get_graph_state` inside `_require_graph_state` can mask `ImportError` as 503

**File:** `backend/app/api/benchmark.py:112-120`

**Issue:** The import `from app.graph import get_graph_state` is deferred to inside the helper function. Any `ImportError` in `app.graph` (e.g., missing `networkx` package in a deployment) will raise an unhandled exception at request time rather than failing loudly at startup. Moving the import to the module top level (alongside the other imports) would surface deployment errors at startup when they are easier to diagnose.

**Fix:** Add `from app.graph import get_graph_state` at the top of `benchmark.py` alongside the other module-level imports and remove the deferred import inside `_require_graph_state`.

---

### IN-02: Zero-weight heatmap points silently excluded without documentation

**File:** `backend/app/api/benchmark.py:427`

**Issue:** `if normalized_weight > 0:` excludes distributors whose mean cascade risk score is genuinely `0.0`. If the intent is to reduce payload size for the maplibre heatmap, this is reasonable but should be documented. If zero-risk distributors should appear on the heatmap (e.g., to show "safe" anchors), the threshold should be removed or set at a small epsilon rather than strict zero.

---

### IN-03: `test_no_http_registration` substring match could produce a false positive

**File:** `backend/tests/test_run_benchmark.py:139-145`

**Issue:** The test uses `"run_benchmark" not in text` against every `.py` file under `app/`. If a module-level docstring ever mentions the seed script by name (e.g., for documentation), the test will fail even though no HTTP route is registered. A more targeted check — searching for import or route-registration patterns — would be more robust:

```python
# More precise: check for import of the module, not just its name string
import_patterns = ("from seeds.run_benchmark", "import run_benchmark", "include_router.*benchmark.*seeds")
```

---

### IN-04: Magic number `200` for Monte Carlo sample cap should be a named constant

**File:** `backend/seeds/run_benchmark.py:271`

**Issue:** `list(balanced.monte_carlo_samples or [])[:200]` uses `200` inline. The model comment in `optimization_run.py:41` says "trimmed to 200 points" but a reader has to cross-reference two files to confirm they agree. If the cap changes, both sites must be updated manually.

**Fix:**
```python
_MC_SAMPLE_CAP = 200  # must match OptimizationRun.monte_carlo_samples doc

# in _run_one:
monte_carlo_samples=list(balanced.monte_carlo_samples or [])[:_MC_SAMPLE_CAP],
```

---

### IN-05: `BenchmarkPage` fetch logic duplicated between `useEffect` and retry button

**File:** `frontend/src/pages/BenchmarkPage.tsx:151-159`, `200-204`

**Issue:** The same `Promise.all([benchmarkAPI.summary(), benchmarkAPI.fiedlerCurve()])` chain with identical state-update logic appears in both the `useEffect` and the retry button's `onClick`. This is already addressed by the fix proposed in WR-03 (extract to `loadBenchmark` `useCallback`). Noted here to confirm it is a duplication issue, not a distinct logic variation.

---

_Reviewed: 2026-04-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
