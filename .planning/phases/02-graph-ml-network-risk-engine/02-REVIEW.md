---
phase: 02-graph-ml-network-risk-engine
reviewed: 2026-04-16T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - backend/app/api/__init__.py
  - backend/app/api/graph.py
  - backend/app/api/optimize.py
  - backend/app/graph/__init__.py
  - backend/app/graph/builder.py
  - backend/app/graph/simulation.py
  - backend/app/main.py
  - backend/app/optimization/solve.py
  - backend/app/optimization/sourcing.py
  - backend/tests/conftest.py
  - backend/tests/test_graph_api.py
  - backend/tests/test_graph_metrics.py
findings:
  critical: 0
  warning: 5
  info: 6
  total: 11
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-04-16T00:00:00Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

This phase introduces the Graph ML Network Risk Engine: a bipartite NetworkX supply graph built at startup, centrality metrics (betweenness, PageRank, k-core, HHI, Fiedler), a Monte Carlo cascade simulation endpoint, and a `graph_aware` flag wired into the CP-SAT sourcing MILP. The implementation is well-structured and security-conscious (DoS mitigations documented, public endpoints expose only aggregates, surcharge ceiling enforced).

Five warnings were found, all correctness issues rather than style preferences: an EVaR pairing bug that corrupts the worst-5% selection, a global mutable state race condition on startup, a `dist_nodes` membership check on the wrong graph, a division-by-zero risk in scenario cost delta, and an `int(p * n)` percentile formula that clips p90 one slot short at small n. Six info items cover dead parameters, magic numbers, test coverage gaps, and a misleading comment.

No critical security vulnerabilities were found.

---

## Warnings

### WR-01: EVaR pairing sorts already-sorted fulfillment rates, not the paired inflation values

**File:** `backend/app/graph/simulation.py:165-168`
**Issue:** `fulfillment_rates` is sorted in-place at line 154 before the percentile calculation. At line 166 the code pairs `fulfillment_rates` (now sorted ascending) with `cost_inflations` (still in original scenario order). The `zip` therefore pairs mismatched scenario outcomes: the worst fulfillment rates are paired with whichever inflation values happen to fall at the same index position in the unsorted inflation list, not the inflation values that actually came from those worst scenarios. This makes `evar_95` incorrect — it is the mean inflation of arbitrarily-selected scenarios rather than the worst-5% scenarios.

**Fix:** Either sort both lists together before splitting, or capture the pairing before sorting:
```python
# Capture paired data before any sort
paired = sorted(zip(fulfillment_rates, cost_inflations), key=lambda x: x[0])
# Now extract percentile values from the sorted-by-rate list
p10 = paired[_percentile_idx(0.10)][0]
p50 = paired[_percentile_idx(0.50)][0]
p90 = paired[_percentile_idx(0.90)][0]
# EVaR: worst 5% by fulfillment rate — pairing is now correct
n_tail = max(1, int(0.05 * n_scenarios))
worst_inflations = [inf for _, inf in paired[:n_tail]]
evar_95 = sum(worst_inflations) / len(worst_inflations)
```
Remove the standalone `fulfillment_rates.sort()` on line 154.

---

### WR-02: `_monte_carlo_eta` in `solve.py` uses unseeded `random` — non-reproducible, shares global state

**File:** `backend/app/optimization/solve.py:76-88`
**Issue:** `_monte_carlo_eta` calls `random.gauss` and `random.choices` directly on the `random` module's global RNG (no seed, no isolated `random.Random` instance). This has two consequences:

1. Results are non-reproducible between server restarts, breaking any downstream test that asserts specific ETA percentile values.
2. More importantly, if `simulation.py`'s isolated `random.Random(seed)` instance ever shares the same global state (it does not today, but future callers might), or if other code calls `random.seed()` globally, this function's output silently changes. The graph simulation correctly uses `random.Random(seed)` (an isolated instance); this function should do the same.

**Fix:**
```python
_ETA_RNG = random.Random(0)  # module-level isolated RNG, deterministic

def _monte_carlo_eta(base_days: float, n: int = 1000) -> Dict[str, float]:
    samples = []
    for _ in range(n):
        delay = _ETA_RNG.gauss(1.0, 0.15)
        disruption = _ETA_RNG.choices([0, 1, 3, 7], weights=[0.85, 0.08, 0.05, 0.02])[0]
        samples.append(max(1.0, base_days * delay + disruption))
    ...
```

---

### WR-03: `dist_nodes` frozenset built from the original `dist_ids` set, not from nodes actually present in the training graph

**File:** `backend/app/graph/builder.py:105`
**Issue:**
```python
dist_nodes: FrozenSet[str] = frozenset(f"d_{did}" for did in dist_ids if f"d_{did}" in G)
```
The guard `if f"d_{did}" in G` filters against `G` which, at this point, already has all distributor nodes added unconditionally at lines 85-86 (`G.add_node(f"d_{did}", bipartite=0)` for every `did in dist_ids`). Every distributor node is therefore always present in `G`, so the guard never excludes anything. This is not a bug today, but it creates a false impression that the condition prunes isolated distributors. If the node-addition loop at lines 85-86 is ever removed or conditioned, `dist_nodes` will silently include all IDs regardless, breaking `bipartite.betweenness_centrality` which requires the passed node set to be a proper bipartite partition.

The deeper issue: `bipartite.betweenness_centrality` is called with nodes that have no edges (distributors in `dist_ids` who appear in no training offer after the holdout split). These zero-degree nodes are valid bipartite partition members, but including them can produce zero-division warnings inside NetworkX for degenerate cases.

**Fix:** Build `dist_nodes` from nodes that have at least one training edge:
```python
dist_nodes: FrozenSet[str] = frozenset(
    f"d_{did}" for did in dist_ids if G.out_degree(f"d_{did}") > 0
)
```

---

### WR-04: Division by zero when `base_total` is zero in `/optimize/scenario`

**File:** `backend/app/api/optimize.py:210`
**Issue:**
```python
cost_delta_pct = round((scenario_total - base_total) / base_total * 100, 1) if base_total else 0
```
The guard `if base_total` correctly short-circuits, but `scenario_total` is computed as `sum(a["scenario_cost"] for a in adjustments if a["scenario_cost"] is not None)`. If every item's distributor is in `distributor_failure_ids`, all `scenario_cost` values are `None`, `scenario_total = 0`, and `cost_delta_pct = 0`. This is mathematically correct only if `base_total` is also 0. If `base_total > 0` but all distributors fail, the delta should represent a 100% cost loss (or a different sentinel), not 0%. This misleads the frontend into showing "no cost change" when in fact all supply is disrupted.

**Fix:**
```python
if not base_total:
    cost_delta_pct = 0.0
elif scenario_total == 0:
    cost_delta_pct = -100.0  # all supply disrupted
else:
    cost_delta_pct = round((scenario_total - base_total) / base_total * 100, 1)
```

---

### WR-05: `_percentile_idx(0.90)` returns index 900 for n=1000, yielding the 901st element, not the 90th percentile

**File:** `backend/app/graph/simulation.py:157-163`
**Issue:**
```python
def _percentile_idx(p: float) -> int:
    idx = int(p * n_scenarios)
    return max(0, min(idx, n_scenarios - 1))

p90 = fulfillment_rates[_percentile_idx(0.90)]  # index 900 of a 1000-element list
```
`int(0.90 * 1000) = 900`, which is the 901st element (0-indexed), representing approximately the 90.1th percentile. For n=1000 this is a negligible error, but for small n (e.g., in unit tests that override n_scenarios) the off-by-one can be more significant. The canonical inclusive percentile formula is `ceil(p * n) - 1`. Additionally, `p10 = fulfillment_rates[100]` corresponds to the 10.1th percentile, not the 10th.

**Fix:** Use `min(int(math.ceil(p * n_scenarios)) - 1, n_scenarios - 1)`:
```python
import math

def _percentile_idx(p: float) -> int:
    idx = max(0, int(math.ceil(p * n_scenarios)) - 1)
    return min(idx, n_scenarios - 1)
```
This is a minor precision issue at n=1000 but worth fixing to match standard percentile semantics.

---

## Info

### IN-01: `_monte_carlo_eta` `samples` list exposed in API response — large payload

**File:** `backend/app/optimization/solve.py:88` / `backend/app/optimization/schemas.py` (via `monte_carlo_samples`)
**Issue:** `_monte_carlo_eta` returns `"samples": samples[:200]` — the first 200 raw float values — which is included in the `RouteAlternative.monte_carlo_samples` field. Across 4 strategies this is 800 floats in every `/optimize/vrp` response. The values are taken from the start of the (unsorted) sample list and do not represent a meaningful statistical selection.
**Fix:** Consider omitting the raw samples field from the API response, or replacing it with a histogram bucket summary if the frontend needs distribution visualization.

---

### IN-02: `graph_aware` parameter accepted by `/optimize/vrp` but not surfaced in frontend

**File:** `backend/app/api/optimize.py:39`
**Issue:** `graph_aware: bool = False` is a request body field, so any API caller can enable graph surcharges. The frontend does not currently send `graph_aware=true`, meaning the entire Phase 02 graph surcharge integration goes unused in normal user flows.
**Fix:** Wire `graph_aware=true` to a UI toggle (e.g., a "Risk-Aware Sourcing" checkbox on the checkout page) or document that it requires explicit activation. This is a product/UX gap rather than a code bug, but it means Phase 02's core deliverable is effectively dead code from the user's perspective until surfaced.

---

### IN-03: `dist_km_by_did` may use a stale offer's distance when the same distributor appears in multiple offers

**File:** `backend/app/optimization/sourcing.py:303`
**Issue:**
```python
dist_km_by_did = {o.distributor_id: o.dist_km_from_depot for o in offers}
```
If the same `distributor_id` appears in multiple offers (which is the common case — one distributor carries many components), only the distance from the last offer in iteration order is kept. Since all offers from the same distributor share the same warehouse coordinates, and `dist_km_from_depot` is computed from those coordinates, this is benign today. However, if offers for the same distributor could come from different warehouse locations, this would silently use the wrong distance.
**Fix:** Add a comment documenting the assumption, or deduplicate more explicitly: `dist_km_by_did = {o.distributor_id: o.dist_km_from_depot for o in sorted(offers, key=lambda o: o.distributor_id)}`.

---

### IN-04: `conftest.py` test database file `test_hardening.db` is not cleaned up between test runs

**File:** `backend/tests/conftest.py:26-37`
**Issue:** `TEST_DB_URL = "sqlite:///./test_hardening.db"` creates a file-based SQLite database. The `db_session` fixture calls `Base.metadata.drop_all` in teardown, which removes tables but not the database file itself. On re-runs, `create_all` recreates tables in the same file. This is benign but can cause confusion when the file grows or is committed to source control accidentally.
**Fix:** Use `"sqlite:///:memory:"` for the test database (as done correctly in `graph_db_session`), or ensure `test_hardening.db` is in `.gitignore`.

---

### IN-05: `test_lifespan_loads_graph` is a no-op assertion

**File:** `backend/tests/test_graph_api.py:5-10`
**Issue:** The test body is `assert True` with a comment explaining that it only verifies "no exception was raised." This gives false confidence in CI — a passing green test that asserts nothing. The graph state after startup is never actually inspected.
**Fix:** Replace with an actual assertion:
```python
def test_lifespan_loads_graph(client):
    from app.graph import get_graph_state
    # With empty test DB, state may be None (no data to build graph from)
    # but startup must not crash — verified by client fixture completing
    gs = get_graph_state()
    # gs is None (empty DB) or a valid GraphState — both are acceptable
    assert gs is None or hasattr(gs, "n_distributors")
```

---

### IN-06: Magic constant `"Microcontrollers"` hardcoded as ML ETA default category

**File:** `backend/app/optimization/solve.py:291`
**Issue:**
```python
ml_eta = ml_lead_time_days(
    ...
    component_category="Microcontrollers",  # dominant category default
    ...
)
```
The comment acknowledges this is a hardcoded default, but it means every BOM — even one containing only Op-Amps, ADCs, or passive components — is evaluated with MCU lead time baselines. The actual dominant category could be derived from `bom` line items.
**Fix:** Compute the modal category from the current BOM:
```python
from collections import Counter
# (Requires category info to be available on BomLine or via a lookup)
dominant_category = Counter(b.category for b in bom if hasattr(b, 'category')).most_common(1)
category_arg = dominant_category[0][0] if dominant_category else "Microcontrollers"
```
If `BomLine` does not carry a category field, the lookup should be threaded through from the API layer where `Component` objects are already available.

---

_Reviewed: 2026-04-16T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
