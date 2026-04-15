# Testing Patterns
_Last updated: 2026-04-15_

## Summary
The backend has meaningful unit and integration test coverage for the optimization engine and ML layer. All tests use `pytest` with no external dependencies (no DB, no network calls). The frontend has zero test files. There are no CI pipelines configured.

---

## Test Framework

**Runner:** `pytest` (Python)
- Config: No `pytest.ini` or `pyproject.toml` detected. Tests discovered by convention (`test_*.py`).
- Location: `backend/tests/`

**Run Commands:**
```bash
cd backend
pytest tests/                        # run all tests
pytest tests/test_costs.py           # run single file
pytest tests/ -v                     # verbose output
pytest tests/ -k "test_sourcing"     # filter by name
```

**Frontend:** No test framework installed. No `vitest`, `jest`, or `@testing-library` found in `frontend/`.

---

## Test File Organization

All test files live flat in `backend/tests/`:

```
backend/tests/
├── test_costs.py          # pure math functions (haversine, transport, CO2, holding cost)
├── test_routing.py        # TSP solver (GeoPoint, RoutingNode, solve_pickup_tsp)
├── test_sourcing.py       # CP-SAT sourcing MILP (outlier filter, assignment logic)
├── test_strategies.py     # end-to-end 4-strategy integration test (optimize_bom)
├── test_cross_dock.py     # cross-dock hub evaluation + 5% threshold
├── test_fred_client.py    # FRED feature engineering (no live API calls)
├── test_lead_time_model.py  # lead time label lookup + 4-model training
└── test_regime_model.py   # logistic regression pipeline + shortage recall
```

No `conftest.py` at the project root. Fixtures are defined per-file with `@pytest.fixture`.

---

## Test Structure

### Fixture Pattern
Fixtures are defined inline per file using `@pytest.fixture`:

```python
@pytest.fixture
def fixture_bom_and_offers():
    bom = [
        BomLine(component_id=1, mpn="PART-A", quantity=100),
        ...
    ]
    offers = [
        Offer(1, 10, "EastCoastPrime", price_usd=1.20, stock=500, moq=1, is_domestic=True),
        ...
    ]
    distributors = {10: DistributorMeta(...), ...}
    depot = GeoPoint(lat=34.8526, lng=-82.3940)
    return bom, offers, distributors, depot
```

### Helper Factory Functions
Private helper functions (prefixed `_`) used to reduce repetition in tests:

```python
def _offer(cid, did, price, stock=1000, moq=1, domestic=True, name=None):
    return Offer(
        component_id=cid, distributor_id=did, price_usd=price,
        stock=stock, moq=moq, is_domestic=domestic,
        distributor_name=name or f"dist_{did}",
    )

def _make_fake_df() -> pd.DataFrame:
    """Build a minimal monthly DataFrame mimicking FRED output."""
    idx = pd.date_range("2020-01-01", periods=36, freq="MS")
    ...
```

### Assertion Style
Plain `assert` statements. No assertion helpers or matchers. Numeric bounds use range checks:

```python
assert 656 < d < 726           # haversine check ±5%
assert 100 < c < 110           # cost within expected range
assert metrics["shortage_recall"] >= 0.70
assert 0.0 <= prob <= 1.0
```

---

## Mocking

**No mocking framework used.** All tests use real implementations with synthetic/in-memory data.

ML tests build fake DataFrames that mirror FRED structure — no `unittest.mock` or `pytest-mock`:

```python
def _make_fake_df() -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=36, freq="MS")
    data = {
        "capacity_util": [70 + (1 if i >= 18 else 0) * 6 for i in range(36)],
        "inventory_ratio": [1.40 - (0.1 if i >= 18 else 0) for i in range(36)],
        ...
    }
    return pd.DataFrame(data, index=idx)
```

No database session mocking. Tests call optimization functions directly without touching SQLAlchemy.

---

## What IS Tested

### Optimization Layer (well covered)

**`test_costs.py`** — 7 tests
- `haversine_km` against known geographic distance (Greenville SC → Memphis TN, ±5%)
- `transport_cost_usd` both LTL and TL branches with hand-computed expected values
- `transit_days` discrete ceiling behavior
- `leg_lead_time_days` for `"major"` and `"broker"` tier
- `co2_kg` against EPA SmartWay factor
- `holding_cost_usd` annualized formula
- `CostBreakdown.total` property

**`test_routing.py`** — 4 tests
- Single-node TSP returns single ID
- 3-node east coast ordering (nearest-first)
- Empty input returns empty
- Closed-tour total distance calculation

**`test_sourcing.py`** — 6 tests
- Outlier filter drops prices above 5× median
- Outlier filter keeps low-side outliers (real discounts)
- Cheapest offer selected when stock is available
- MOQ constraint respected (allows oversourcing to hit MOQ)
- `us_only=True` rejects international offers
- Stock-insufficient split across multiple distributors

**`test_strategies.py`** — 4 integration tests (call `optimize_bom` end-to-end)
- All 4 strategies produce different routes (regression for the "all same tour" bug)
- All strategies have `cost_breakdown`, `strategy_math`, and academic citations
- Cheapest strategy selects low-price discount brokers
- At least one strategy evaluates cross-dock hub

**`test_cross_dock.py`** — 4 tests
- Single distributor never uses cross-dock
- East coast distributors select a hub in GA/KY/TN/OH/IL/MO/IN
- Cross-dock rejected when improvement < 5% threshold
- Hub evaluation always includes handling fee

### ML Layer (well covered)

**`test_fred_client.py`** — 5 tests
- Feature engineering produces 18 columns (6 series × 3 features)
- No NaN in engineered features
- Correct column naming pattern (`_level`, `_mom3`, `_z12`)
- Stress label fires at correct thresholds (`capacity_util ≥ 75%` AND `inventory_ratio ≤ 1.35`)
- Stress label shape matches input

**`test_regime_model.py`** — 5 tests
- Pipeline builds with `fit` and `predict_proba`
- Training returns fitted pipeline + metrics dict with `val_accuracy` and `shortage_recall`
- `shortage_recall ≥ 0.70` on synthetic chip-shortage data
- `get_current_stress_prob` returns value in `[0, 1]`
- Stress probability higher in stress period than normal period

**`test_lead_time_model.py`** — 9 tests
- Category-to-days lookup (known and unknown categories)
- All category base days are positive
- `build_feature_row` returns dict with expected keys
- Training matrix shape and no-NaN guarantee
- `train_all_models` returns all 4 model names (Ridge, RF, GBM, MLP)
- Each model result has `model`, `rmse`, `mae`, `r2` keys
- `predict_lead_time` returns positive value

---

## What Is NOT Tested (Coverage Gaps)

### API Layer — No Tests
No tests for any FastAPI endpoint. These are all untested:
- `backend/app/api/auth.py` — JWT auth, registration, login, demo login
- `backend/app/api/cart.py` — cart CRUD, MOQ enforcement, stock validation
- `backend/app/api/components.py` — component listing, category filter, offer ranking
- `backend/app/api/distributors.py` — distributor listing
- `backend/app/api/optimize.py` — VRP endpoint, scenario analysis endpoint
- `backend/app/api/ml.py` — ML API endpoints (`/ml/stress`, `/ml/model-comparison`, `/ml/lead-time`)
- `backend/app/api/live_prices.py` — live price API
- `backend/app/api/market_intelligence.py` — market intelligence endpoint

### Database Layer — No Tests
- No tests for SQLAlchemy models (`Component`, `Distributor`, `DistributorOffer`, `CartItem`, `User`)
- No migration tests
- No seed data integrity tests (`backend/seeds/seed_db.py`)

### Frontend — No Tests
- `frontend/` has zero test files
- No test for Zustand store logic (`authStore`, `cartStore`, `optimizeStore`)
- No test for API service layer (`services/api.ts`)
- No component rendering tests
- No E2E tests (no Playwright or Cypress installed)

### ML Integration — Partially Tested
- `ml_lead_time_days` in `costs.py` (the fallback logic) is not directly tested
- `model_store.py` (load/save to disk) has no tests
- `prophet_forecaster.py` and `forecast_tasks.py` have no tests

### Solve Pipeline — Integration Gap
- `backend/app/optimization/solve.py` (the top-level orchestrator) is tested indirectly through `test_strategies.py` but not directly with unit tests for individual stages
- Monte Carlo sampling (ETA percentiles) is not tested

---

## Test Data Strategy

All test data is **hardcoded in-file** with real-world geographic coordinates and realistic price ranges:

```python
# Greenville SC depot used consistently across test files
depot = GeoPoint(lat=34.8526, lng=-82.3940)

# US cities used as distributor locations
DistributorMeta(10, "EastCoastPrime", 35.7796, -78.6382, "Raleigh", "NC", ...)
DistributorMeta(20, "SoutheastMid", 33.7490, -84.3880, "Atlanta", "GA", ...)
```

Synthetic ML training data is built with deliberate signal — stress regime clearly separates at month 18/36/60 boundaries so the model can learn the boundary and `shortage_recall ≥ 0.70` can be reliably asserted.

---

## Adding New Tests

**Where to add:** `backend/tests/test_<module>.py`

**Conventions to follow:**
- Import directly from `app.optimization.*` or `app.ml.*` — no FastAPI test client used yet
- Use `@pytest.fixture` for any shared setup needing more than 3 lines
- Use `_helper()` private functions for repeated object construction
- Assert with range bounds for floating-point results (e.g. `assert 100 < val < 110`)
- Use geographic coordinates from the Greenville SC depot pattern for consistency
- No network calls; build synthetic DataFrames or use hardcoded prices

**To add API endpoint tests (currently missing):**
```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
```
This pattern is not yet used anywhere in the project.
