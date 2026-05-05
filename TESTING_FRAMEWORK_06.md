# Phase 6 Testing Framework: Interactive Resilience Dashboard

**Date Created:** 2026-05-05
**Phase:** 06-interactive-resilience-dashboard
**Objective:** Comprehensive testing strategy for scenario API endpoints, ResiliencePage UI, and mathematical correctness verification.

**Audience:** QA engineers, data scientists validating Monte Carlo results, frontend developers, interview stakeholders.

---

## Part 1: Testing Infrastructure & Tools

### 1.1 Required Tools & Installation

#### Backend Testing Stack

```bash
# Python testing framework
pip install pytest==7.4.3 pytest-cov==4.1.0 pytest-asyncio==0.21.1

# API testing & mocking
pip install httpx==0.24.1 pytest-mock==3.11.1

# Mathematical validation
pip install numpy==1.24.3 scipy==1.11.2 pandas==2.0.3

# Performance profiling
pip install pytest-benchmark==4.0.0 line_profiler==4.0.3

# Load testing
pip install locust==2.15.1

# Database (if using SQLite for testing)
pip install sqlite3  # built-in

# Cache validation tools
pip install fakeredis==2.19.0  # mock Redis for cache testing

# Tracing validation
pip install opentelemetry-api==1.19.0 opentelemetry-sdk==1.19.0
pip install opentelemetry-exporter-jaeger==1.19.0
```

#### Frontend Testing Stack

```bash
# React testing
npm install --save-dev @testing-library/react@14.0.0
npm install --save-dev @testing-library/jest-dom@6.1.4
npm install --save-dev @testing-library/user-event@14.5.1

# Component snapshot testing
npm install --save-dev jest-snapshot==29.7.0

# Visual regression testing
npm install --save-dev jest-image-snapshot==6.1.0

# API mocking
npm install --save-dev msw@1.3.1  # Mock Service Worker

# Performance profiling
npm install --save-dev react-test-utils==0.5.0
npm install --save-dev @testing-library/performance==0.1.0

# E2E testing (for full scenario flows)
npm install --save-dev cypress==13.3.0
npm install --save-dev @cypress/schematic==2.5.1

# Accessibility testing
npm install --save-dev jest-axe==8.0.0
npm install --save-dev @axe-core/react==4.7.2
```

#### Supporting Tools

```bash
# API documentation & testing
pip install fastapi==0.103.0 pydantic==2.3.0

# Graphing/visualization for test reports
pip install matplotlib==3.7.2 plotly==5.16.1

# Docker for containerized testing
# Install Docker Desktop (https://www.docker.com/products/docker-desktop)

# Database inspection tools
pip install pgcli==4.0.1  # PostgreSQL CLI (if using PostgreSQL)
pip install sqlite3-cli==0.0.1
```

---

### 1.2 Testing Environment Setup

#### Backend Test Environment

```bash
# Create virtual environment
python -m venv test-env
source test-env/bin/activate

# Install backend dependencies
cd backend
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Must include testing tools from 1.1

# Set up test database
export DATABASE_URL="sqlite:///./test.db"
export REDIS_URL="redis://localhost:6379/1"  # Use fakeredis if no Redis

# Run database migrations for test schema
alembic upgrade head
```

#### Frontend Test Environment

```bash
# Install Node.js dependencies
cd frontend
npm install

# Configure test environment
export REACT_APP_API_BASE_URL="http://localhost:8000/api/v1"
export NODE_ENV="test"

# Initialize test data fixtures
npm run test:setup  # Must populate fixture data
```

#### Docker-Compose for Local Testing

```yaml
# docker-compose.test.yml (in root)
version: '3.8'
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: supply_chain_test
      POSTGRES_PASSWORD: test_password
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 10s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 10s
      retries: 5

  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "6831:6831/udp"
      - "16686:16686"  # Jaeger UI
    environment:
      COLLECTOR_ZIPKIN_HTTP_PORT: 9411

  backend:
    build: ./backend
    environment:
      DATABASE_URL: "postgresql://postgres:test_password@postgres:5432/supply_chain_test"
      REDIS_URL: "redis://redis:6379/0"
      OTEL_EXPORTER_JAEGER_AGENT_HOST: jaeger
      OTEL_EXPORTER_JAEGER_AGENT_PORT: 6831
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      jaeger:
        condition: service_started

  frontend:
    build: ./frontend
    environment:
      REACT_APP_API_BASE_URL: "http://localhost:8000/api/v1"
    ports:
      - "3000:3000"
    depends_on:
      - backend
```

**Start test environment:**
```bash
docker-compose -f docker-compose.test.yml up -d
docker-compose -f docker-compose.test.yml logs -f backend
```

---

## Part 2: Mathematical Verification Framework

### 2.1 Monte Carlo Fulfillment Rate Validation

Monte Carlo cascade simulations must return P10, P50, P90 values representing fulfillment probability distribution. These are mathematically sound only if they satisfy strict ordering.

#### Invariant 1: Percentile Ordering

**Rule:** For any scenario response, `P10 ≤ P50 ≤ P90`

**Test Implementation:**

```python
# tests/test_monte_carlo_math.py
import pytest
from backend.app.services.monte_carlo import simulate_cascade
import numpy as np

def test_percentile_ordering_distributor_failure():
    """Verify P10 ≤ P50 ≤ P90 for distributor failure simulation."""
    response = simulate_cascade(
        scenario="distributor_failure",
        distributor_id=1,
        num_simulations=10000
    )
    
    p10 = response['fulfillment_p10']
    p50 = response['fulfillment_p50']
    p90 = response['fulfillment_p90']
    
    assert p10 <= p50, f"P10 ({p10}) must be ≤ P50 ({p50})"
    assert p50 <= p90, f"P50 ({p50}) must be ≤ P90 ({p90})"
    assert 0 <= p10 and p90 <= 1, "All percentiles must be in [0, 1]"

def test_percentile_ordering_geopolitical_risk():
    """Verify P10 ≤ P50 ≤ P90 for GPR scenario."""
    response = simulate_cascade(
        scenario="geopolitical_risk",
        gpr_factor=1.5,
        num_simulations=10000
    )
    
    p10 = response['fulfillment_p10']
    p50 = response['fulfillment_p50']
    p90 = response['fulfillment_p90']
    
    assert p10 <= p50 <= p90, "Percentiles must be ordered"

def test_percentile_ordering_delivery_target():
    """Verify P10 ≤ P50 ≤ P90 for delivery acceleration scenario."""
    response = simulate_cascade(
        scenario="delivery_target",
        target_days=14,
        num_simulations=10000
    )
    
    assert response['fulfillment_p10'] <= response['fulfillment_p50'] <= response['fulfillment_p90']
```

#### Invariant 2: Scenario Monotonicity

**Rule:** Riskier scenarios (distributor failure, GPR spike) should degrade fulfillment rates.

**Test Implementation:**

```python
def test_fulfillment_degradation_under_risk():
    """Verify that introducing risk decreases fulfillment rates."""
    baseline = simulate_cascade(scenario="baseline", num_simulations=10000)
    
    risky = simulate_cascade(
        scenario="distributor_failure",
        distributor_id=1,  # Assume largest distributor
        num_simulations=10000
    )
    
    # Fulfillment should decrease under failure
    assert baseline['fulfillment_p50'] >= risky['fulfillment_p50'], \
        "Baseline P50 should be ≥ failure scenario P50"
    
    assert baseline['fulfillment_p10'] >= risky['fulfillment_p10'], \
        "Baseline P10 should be ≥ failure scenario P10"

def test_fulfillment_improvement_under_delivery_slack():
    """Verify that relaxing delivery target improves fulfillment."""
    tight = simulate_cascade(
        scenario="delivery_target",
        target_days=7,
        num_simulations=10000
    )
    
    slack = simulate_cascade(
        scenario="delivery_target",
        target_days=14,
        num_simulations=10000
    )
    
    # More delivery days = better fulfillment
    assert slack['fulfillment_p50'] >= tight['fulfillment_p50'], \
        "Relaxed delivery target should improve P50 fulfillment"
```

#### Invariant 3: Cost Delta Sign Consistency

**Rule:** Cost deltas must reflect business logic (failures = higher cost, faster delivery = higher cost).

**Test Implementation:**

```python
def test_cost_delta_signs():
    """Verify cost deltas have correct signs."""
    failure_response = simulate_cascade(scenario="distributor_failure", distributor_id=1)
    
    # Distributor failure should increase cost (rerouting penalty)
    cost_delta_pct = failure_response['cost_delta_pct']
    assert cost_delta_pct > 0, "Distributor failure should increase cost (cost_delta_pct > 0)"
    
    # Verify the cost increase is reasonable (< 50% for single distributor)
    assert cost_delta_pct < 50, "Cost increase should be < 50% for single distributor failure"

def test_delivery_acceleration_cost_delta():
    """Verify faster delivery increases cost."""
    accel_response = simulate_cascade(
        scenario="delivery_target",
        target_days=7
    )
    
    # Acceleration should increase cost
    assert accel_response['cost_delta_pct'] > 0, \
        "Faster delivery should increase cost (cost_delta_pct > 0)"
    assert accel_response['cost_delta_pct'] < 30, \
        "Cost increase for 7-day delivery should be < 30%"
```

#### Invariant 4: ETA Delta Realism

**Rule:** ETA deltas must reflect feasible rerouting (minimum +0 days for same-distributor, max +30 days for longest alternative).

**Test Implementation:**

```python
def test_eta_delta_bounds():
    """Verify ETA deltas are within feasible bounds."""
    response = simulate_cascade(scenario="distributor_failure", distributor_id=1)
    
    eta_delta = response['eta_delta_days']
    
    # ETA should increase (rerouting takes longer)
    assert eta_delta >= 0, "ETA delta should be >= 0 (rerouting takes time)"
    
    # But realistically bounded (not adding 90 days for one distributor failure)
    assert eta_delta <= 30, "ETA delta should be <= 30 days for single distributor"

def test_eta_delta_null_for_slack_suppliers():
    """If alternative suppliers exist in-region, ETA delta should be ~0."""
    response = simulate_cascade(
        scenario="distributor_failure",
        distributor_id=1,  # Assume large distributor with alternatives
        num_simulations=1000
    )
    
    # If alternatives exist, ETA impact should be minimal
    eta_delta = response['eta_delta_days']
    assert eta_delta <= 5, "ETA delta should be small if alternatives exist in-region"
```

### 2.2 Cost Delta Accuracy Verification

Cost deltas are calculated by comparing baseline optimizer run vs scenario optimizer run. Verify the delta calculation is correct.

```python
def test_cost_delta_calculation():
    """Verify cost_delta_pct is calculated correctly."""
    response = simulate_cascade(scenario="distributor_failure", distributor_id=1)
    
    baseline_cost = response['baseline_cost']
    scenario_cost = response['scenario_cost']
    cost_delta_pct = response['cost_delta_pct']
    
    # Verify delta calculation: (scenario - baseline) / baseline * 100
    expected_delta = ((scenario_cost - baseline_cost) / baseline_cost) * 100
    
    assert abs(cost_delta_pct - expected_delta) < 0.1, \
        f"Cost delta mismatch: got {cost_delta_pct}%, expected {expected_delta}%"
```

### 2.3 Risk Score Delta Validation

Risk scores (Fiedler eigenvalue) change under different scenarios. Verify the direction makes sense.

```python
def test_risk_score_direction():
    """Verify risk score changes in expected direction."""
    baseline_response = simulate_cascade(scenario="baseline")
    failure_response = simulate_cascade(scenario="distributor_failure", distributor_id=1)
    
    baseline_risk = baseline_response['baseline_risk_score']
    scenario_risk = failure_response['scenario_risk_score']
    
    # Distributor failure should decrease Fiedler (higher risk = lower Fiedler)
    # So scenario_risk < baseline_risk (lower Fiedler = worse)
    assert scenario_risk <= baseline_risk, \
        "Distributor failure should decrease Fiedler value (increase risk)"
    
    risk_delta = failure_response['risk_delta']
    assert risk_delta < 0, \
        "Risk delta should be negative (Fiedler decreased)"
```

---

## Part 3: Frontend UI Testing Framework

### 3.1 Component Unit Tests

#### ResiliencePage Tab Navigation Test

```typescript
// frontend/src/pages/__tests__/ResiliencePage.test.tsx
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ResiliencePage } from '../ResiliencePage';
import * as api from '../../services/api';

jest.mock('../../services/api');

describe('ResiliencePage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders 3 scenario tabs', () => {
    render(<ResiliencePage />);
    
    expect(screen.getByRole('tab', { name: /Distributor Failure/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Geopolitical Risk/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Delivery Acceleration/i })).toBeInTheDocument();
  });

  test('tab switching loads correct scenario', async () => {
    const mockResponse = {
      baseline_cost: 1000,
      scenario_cost: 1032,
      cost_delta_pct: 3.2,
      baseline_eta_days: 7,
      scenario_eta_days: 10,
      eta_delta_days: 3,
      baseline_risk_score: 0.45,
      scenario_risk_score: 0.32,
      risk_delta: -0.13,
      fulfillment_p10: 0.85,
      fulfillment_p50: 0.92,
      fulfillment_p90: 0.98,
      affected_bom_ids: ['BOM-001', 'BOM-002'],
      affected_suppliers: ['Supplier-A', 'Supplier-B']
    };

    (api.simulateDistributorFailure as jest.Mock).mockResolvedValueOnce(mockResponse);

    render(<ResiliencePage />);
    
    const tab = screen.getByRole('tab', { name: /Distributor Failure/i });
    fireEvent.click(tab);
    
    await waitFor(() => {
      expect(screen.getByText('3.2%')).toBeInTheDocument(); // Cost delta
      expect(screen.getByText('+3 days')).toBeInTheDocument(); // ETA delta
    });
  });

  test('async loading spinner appears during API call', async () => {
    (api.simulateDistributorFailure as jest.Mock).mockImplementationOnce(
      () => new Promise(resolve => setTimeout(() => resolve(mockResponse), 1000))
    );

    render(<ResiliencePage />);
    
    fireEvent.click(screen.getByRole('tab', { name: /Distributor Failure/i }));
    
    expect(screen.getByTestId('scenario-spinner')).toBeInTheDocument();
    
    await waitFor(() => {
      expect(screen.queryByTestId('scenario-spinner')).not.toBeInTheDocument();
    });
  });

  test('error boundary catches and displays API errors', async () => {
    (api.simulateDistributorFailure as jest.Mock).mockRejectedValueOnce(
      new Error('API timeout')
    );

    render(<ResiliencePage />);
    
    fireEvent.click(screen.getByRole('tab', { name: /Distributor Failure/i }));
    
    await waitFor(() => {
      expect(screen.getByText(/failed to load scenario/i)).toBeInTheDocument();
    });
  });
});
```

#### DeltaCard Component Test

```typescript
// frontend/src/components/__tests__/DeltaCard.test.tsx
import React from 'react';
import { render, screen } from '@testing-library/react';
import { DeltaCard } from '../DeltaCard';

describe('DeltaCard', () => {
  test('displays all 4 metrics correctly', () => {
    const deltas = {
      cost_delta_pct: 3.2,
      eta_delta_days: 3,
      risk_delta: -0.13,
      fulfillment_p50: 0.92
    };

    render(
      <DeltaCard
        label="Cost Impact"
        baseline={1000}
        scenario={1032}
        delta={deltas.cost_delta_pct}
        unit="%"
      />
    );

    expect(screen.getByText('3.2%')).toBeInTheDocument();
    expect(screen.getByText('$1,000 → $1,032')).toBeInTheDocument();
  });

  test('color codes positive/negative deltas', () => {
    // Cost increase = red (negative for business)
    const { container: costContainer } = render(
      <DeltaCard label="Cost" baseline={1000} scenario={1032} delta={3.2} unit="%" />
    );
    expect(costContainer.querySelector('.text-red-600')).toBeInTheDocument();

    // Risk decrease (negative delta) = green (good for resilience)
    const { container: riskContainer } = render(
      <DeltaCard label="Risk" baseline={0.45} scenario={0.32} delta={-0.13} unit="" />
    );
    expect(riskContainer.querySelector('.text-green-600')).toBeInTheDocument();
  });

  test('formats large numbers with commas', () => {
    render(
      <DeltaCard
        label="Cost"
        baseline={1234567}
        scenario={1234567 * 1.05}
        delta={5}
        unit="$"
      />
    );

    expect(screen.getByText(/1,234,567/)).toBeInTheDocument();
  });
});
```

#### MonteCarloChart Component Test

```typescript
// frontend/src/components/__tests__/MonteCarloChart.test.tsx
import React from 'react';
import { render, screen } from '@testing-library/react';
import { MonteCarloChart } from '../MonteCarloChart';

describe('MonteCarloChart', () => {
  test('renders area chart with 3 scenario bands', () => {
    const scenarios = [
      {
        name: 'Baseline',
        p10: 0.88,
        p50: 0.95,
        p90: 0.99,
        color: '#3b82f6'
      },
      {
        name: 'Distributor Failure',
        p10: 0.75,
        p50: 0.85,
        p90: 0.92,
        color: '#ef4444'
      },
      {
        name: 'GPR Spike',
        p10: 0.80,
        p50: 0.89,
        p90: 0.96,
        color: '#f97316'
      }
    ];

    render(<MonteCarloChart scenarios={scenarios} />);

    // Verify chart renders
    expect(screen.getByTestId('monte-carlo-chart')).toBeInTheDocument();

    // Verify legend entries
    expect(screen.getByText('Baseline')).toBeInTheDocument();
    expect(screen.getByText('Distributor Failure')).toBeInTheDocument();
    expect(screen.getByText('GPR Spike')).toBeInTheDocument();
  });

  test('tooltips show P10/P50/P90 on hover', async () => {
    // This requires mocking Recharts
    // Use jest-mock-recharts or similar
  });

  test('respects scenario ordering (baseline first)', () => {
    // Verify visual layering
  });
});
```

### 3.2 Integration Tests

#### Full Scenario Flow Test

```typescript
// frontend/src/pages/__tests__/ResiliencePage.integration.test.tsx
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ResiliencePage } from '../ResiliencePage';
import * as api from '../../services/api';

jest.mock('../../services/api');

describe('ResiliencePage Full Scenario Flows', () => {
  test('distributor failure scenario flow: select → simulate → view results', async () => {
    const user = userEvent.setup();
    const mockResponse = {
      baseline_cost: 10000,
      scenario_cost: 10320,
      cost_delta_pct: 3.2,
      baseline_eta_days: 7,
      scenario_eta_days: 10,
      eta_delta_days: 3,
      baseline_risk_score: 0.45,
      scenario_risk_score: 0.32,
      risk_delta: -0.13,
      fulfillment_p10: 0.85,
      fulfillment_p50: 0.92,
      fulfillment_p90: 0.98,
      affected_bom_ids: ['BOM-001', 'BOM-002', 'BOM-003'],
      affected_suppliers: ['Supplier-A', 'Supplier-B']
    };

    (api.simulateDistributorFailure as jest.Mock).mockResolvedValueOnce(mockResponse);

    render(<ResiliencePage />);

    // Step 1: Click Distributor Failure tab
    await user.click(screen.getByRole('tab', { name: /Distributor Failure/i }));

    // Step 2: Select a distributor from dropdown
    const dropdown = screen.getByLabelText(/select distributor/i);
    await user.click(dropdown);
    await user.click(screen.getByRole('option', { name: /digikey/i }));

    // Step 3: Click Simulate button
    await user.click(screen.getByRole('button', { name: /simulate/i }));

    // Step 4: Verify results appear
    await waitFor(() => {
      expect(screen.getByText('3.2%')).toBeInTheDocument();
      expect(screen.getByText('3 days')).toBeInTheDocument();
      expect(screen.getByText('3 BOMs affected')).toBeInTheDocument();
    });

    // Step 5: Verify expandable BOM table
    const expandButton = screen.getByRole('button', { name: /expand/i });
    await user.click(expandButton);

    await waitFor(() => {
      expect(screen.getByText('BOM-001')).toBeInTheDocument();
      expect(screen.getByText('BOM-002')).toBeInTheDocument();
      expect(screen.getByText('BOM-003')).toBeInTheDocument();
    });
  });

  test('geopolitical risk slider updates risk scores in real-time', async () => {
    const user = userEvent.setup();

    const baselineResponse = {
      baseline_cost: 10000,
      scenario_cost: 10000,
      cost_delta_pct: 0,
      baseline_risk_score: 0.45,
      scenario_risk_score: 0.45,
      risk_delta: 0,
      fulfillment_p10: 0.88,
      fulfillment_p50: 0.95,
      fulfillment_p90: 0.99
    };

    const spikeResponse = {
      ...baselineResponse,
      scenario_cost: 10500,
      cost_delta_pct: 5,
      scenario_risk_score: 0.35,
      risk_delta: -0.10,
      fulfillment_p50: 0.89
    };

    (api.simulateGeopoliticalRisk as jest.Mock)
      .mockResolvedValueOnce(baselineResponse)
      .mockResolvedValueOnce(spikeResponse);

    render(<ResiliencePage />);

    await user.click(screen.getByRole('tab', { name: /Geopolitical Risk/i }));

    // Default baseline
    await waitFor(() => {
      expect(screen.getByText('0%')).toBeInTheDocument();
    });

    // Move slider to "Severe" (GPR spike)
    const slider = screen.getByRole('slider', { name: /gpr level/i });
    fireEvent.change(slider, { target: { value: '2' } });

    // Verify updated values
    await waitFor(() => {
      expect(screen.getByText('5%')).toBeInTheDocument();
      expect(screen.getByText('-0.10')).toBeInTheDocument();
    });
  });

  test('delivery acceleration: tighter timeline increases cost', async () => {
    const user = userEvent.setup();

    const relaxedResponse = {
      baseline_cost: 10000,
      scenario_cost: 10050,
      cost_delta_pct: 0.5,
      eta_delta_days: 0,
      fulfillment_p50: 0.98
    };

    const tightResponse = {
      baseline_cost: 10000,
      scenario_cost: 10500,
      cost_delta_pct: 5,
      eta_delta_days: -2,
      fulfillment_p50: 0.90
    };

    (api.simulateDeliveryTarget as jest.Mock)
      .mockResolvedValueOnce(relaxedResponse)
      .mockResolvedValueOnce(tightResponse);

    render(<ResiliencePage />);

    await user.click(screen.getByRole('tab', { name: /Delivery Acceleration/i }));

    // Default: 14 days
    await waitFor(() => {
      expect(screen.getByText('0.5%')).toBeInTheDocument();
    });

    // Tighten to 7 days
    const slider = screen.getByRole('slider', { name: /delivery target/i });
    fireEvent.change(slider, { target: { value: '7' } });

    // Cost should increase
    await waitFor(() => {
      expect(screen.getByText('5%')).toBeInTheDocument();
    });
  });
});
```

---

## Part 4: API Endpoint Testing

### 4.1 Distributor Failure Endpoint Test

```python
# tests/test_resilience_api.py
import pytest
from httpx import AsyncClient
from backend.app.main import app
from backend.app.services.cache import CacheManager

@pytest.fixture
def cache_manager():
    return CacheManager()

@pytest.mark.asyncio
async def test_distributor_failure_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 1}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response schema
        assert 'baseline_cost' in data
        assert 'scenario_cost' in data
        assert 'cost_delta_pct' in data
        assert 'fulfillment_p10' in data
        assert 'fulfillment_p50' in data
        assert 'fulfillment_p90' in data

        # Verify mathematical invariants
        assert data['fulfillment_p10'] <= data['fulfillment_p50'] <= data['fulfillment_p90']
        assert 0 <= data['fulfillment_p10'] and data['fulfillment_p90'] <= 1
        assert data['cost_delta_pct'] > 0  # Failure should increase cost

@pytest.mark.asyncio
async def test_distributor_failure_caching():
    """Verify that repeated requests use cache."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # First request (cache miss)
        import time
        start = time.time()
        response1 = await client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 1}
        )
        time1 = time.time() - start

        # Second request (cache hit)
        start = time.time()
        response2 = await client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 1}
        )
        time2 = time.time() - start

        assert response1.json() == response2.json()
        assert time2 < time1 / 2  # Cache hit should be significantly faster
        assert time2 < 0.1  # Cache hits should be < 100ms

@pytest.mark.asyncio
async def test_distributor_failure_invalid_distributor():
    """Verify graceful error handling for invalid distributor."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": 99999}  # Non-existent
        )

        assert response.status_code == 400
        data = response.json()
        assert 'error' in data
        assert 'distributor_id' in data['error'].lower()
```

### 4.2 Geopolitical Risk Endpoint Test

```python
@pytest.mark.asyncio
async def test_geopolitical_risk_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"gpr_factor": 1.5}  # GPR spike 50%
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert 'baseline_risk_score' in data
        assert 'scenario_risk_score' in data
        assert 'risk_delta' in data

        # GPR spike should decrease Fiedler (increase risk)
        assert data['scenario_risk_score'] < data['baseline_risk_score']
        assert data['risk_delta'] < 0

@pytest.mark.asyncio
async def test_geopolitical_risk_slider_range():
    """Verify GPR slider accepts values in [0.5, 3.0]."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Valid: mild increase
        response = await client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"gpr_factor": 1.2}
        )
        assert response.status_code == 200

        # Valid: severe spike
        response = await client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"gpr_factor": 2.5}
        )
        assert response.status_code == 200

        # Invalid: too low
        response = await client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"gpr_factor": 0.1}
        )
        assert response.status_code == 400

        # Invalid: too high
        response = await client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"gpr_factor": 5.0}
        )
        assert response.status_code == 400
```

### 4.3 Delivery Target Endpoint Test

```python
@pytest.mark.asyncio
async def test_delivery_target_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resilience/delivery-target",
            json={"target_days": 7}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert 'baseline_cost' in data
        assert 'scenario_cost' in data
        assert 'affected_suppliers' in data

        # Tighter delivery should increase cost
        assert data['cost_delta_pct'] > 0

        # Verify which suppliers can meet the target
        assert isinstance(data['affected_suppliers'], list)

@pytest.mark.asyncio
async def test_delivery_target_impossibility():
    """Verify graceful handling when target is impossible (e.g., 1 day)."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/resilience/delivery-target",
            json={"target_days": 1}
        )

        # Should return 400 with helpful error
        assert response.status_code in [400, 422]
        data = response.json()
        assert 'error' in data or 'detail' in data
```

---

## Part 5: Performance Testing Framework

### 5.1 Load Testing with Locust

```python
# tests/load_test.py
from locust import HttpUser, task, between
import random

class ResilienceUser(HttpUser):
    wait_time = between(1, 3)
    
    distributors = list(range(1, 93))  # 92 distributors
    gpr_factors = [1.0, 1.2, 1.5, 2.0, 2.5]
    delivery_days = [7, 10, 14, 21]

    @task(3)
    def distributor_failure(self):
        """Simulate 3x more frequent than others."""
        distributor_id = random.choice(self.distributors)
        self.client.post(
            "/api/v1/resilience/distributor-failure",
            json={"distributor_id": distributor_id}
        )

    @task(2)
    def geopolitical_risk(self):
        gpr_factor = random.choice(self.gpr_factors)
        self.client.post(
            "/api/v1/resilience/geopolitical-risk",
            json={"gpr_factor": gpr_factor}
        )

    @task(2)
    def delivery_target(self):
        target_days = random.choice(self.delivery_days)
        self.client.post(
            "/api/v1/resilience/delivery-target",
            json={"target_days": target_days}
        )

# Run: locust -f tests/load_test.py --host=http://localhost:8000 -u 100 -r 10
```

**Expected Results:**
- P50 latency: 100-500ms (cache miss), < 50ms (cache hit)
- P99 latency: < 2000ms
- Cache hit rate: > 80% after warmup

### 5.2 Benchmark Tests

```python
# tests/test_performance_benchmarks.py
import pytest

@pytest.mark.benchmark
def test_distributor_failure_latency(benchmark):
    """Measure distributor failure simulation latency."""
    from backend.app.services.monte_carlo import simulate_cascade
    
    def run_simulation():
        return simulate_cascade(
            scenario="distributor_failure",
            distributor_id=1,
            num_simulations=10000
        )
    
    result = benchmark(run_simulation)
    assert result['fulfillment_p10'] <= result['fulfillment_p50']

# Run: pytest tests/test_performance_benchmarks.py -v --benchmark-only
```

---

## Part 6: Testing Agentic Team Setup

### 6.1 Multi-Agent Test Coordination

An "agentic team" to fully test Phase 6 consists of specialized agents:

**Team Composition:**

| Agent Role | Responsibility | Tools & Skills | Success Criteria |
|-----------|-----------------|-----------------|-----------------|
| **Math Validator** | Verify Monte Carlo invariants (P10 ≤ P50 ≤ P90), cost/ETA/risk deltas make sense | pytest, numpy, scipy, custom math validator | All invariants pass, no edge-case failures |
| **API Tester** | Test all 3 endpoints, caching, error handling, performance | httpx, pytest, locust, Postman | All endpoints 200/correct response, cache < 100ms, P99 < 2s |
| **Frontend Tester** | Test ResiliencePage, all tabs, tab switching, async loading, error states | Jest, @testing-library/react, Cypress, MSW | All 4 metrics render, tabs switch, spinners appear/disappear, errors handled |
| **Performance Profiler** | Profile backend simulation, identify bottlenecks, measure memory usage | line_profiler, memory_profiler, py-spy, Chrome DevTools | Simulation < 1s per 10k runs, memory stable, no memory leaks |
| **End-to-End Tester** | Full scenario flows, cross-browser, accessibility | Cypress, axe-core, Lighthouse | All 3 scenarios runnable end-to-end, WCAG 2.1 AA, LCP < 2.5s |
| **Interview Validator** | Verify demo narrative works, talking points are accurate | Manual testing + checklist | Demo flows smoothly, talking points are technically accurate |

### 6.2 Agent Workflow (Sequential Phases)

```
Phase 1: Setup (1 hour)
├── Setup test environment (docker-compose, dependencies)
├── Seed fixture data (92 distributors, 791 components, 8731 offers)
└── Warm cache (run baseline scenarios to populate cache)

Phase 2: Unit Testing (4 hours, parallel agents)
├── Math Validator: Run mathematical invariant tests
├── API Tester: Run endpoint unit tests
├── Frontend Tester: Run component unit tests
└── Collect: All unit tests must pass

Phase 3: Integration Testing (4 hours, parallel agents)
├── API Tester: Run caching tests, load tests (Locust)
├── Frontend Tester: Run integration tests (full scenario flows)
├── Performance Profiler: Profile slow paths, identify bottlenecks
└── Collect: All integration tests pass, performance targets met

Phase 4: End-to-End Testing (3 hours, sequential)
├── End-to-End Tester: Run Cypress full flows
├── Performance Profiler: Run Lighthouse, profile frontend
├── Interview Validator: Walk through demo, verify talking points
└── Collect: Demo is smooth, WCAG 2.1 AA compliant, no accessibility issues

Phase 5: Regression Testing (2 hours, scheduled)
├── Run full test suite (unit + integration + E2E)
├── Load test: 100 concurrent users, P99 < 2s
└── Verify: No regressions, cache still working, performance stable

Final Sign-Off: All agents sign off on respective domains
├── Math Validator: ✓ All invariants hold
├── API Tester: ✓ All endpoints functional, P99 < 2s
├── Frontend Tester: ✓ All UI tests pass
├── Performance Profiler: ✓ No bottlenecks, memory stable
├── End-to-End Tester: ✓ All flows work, WCAG AA
└── Interview Validator: ✓ Demo is interview-ready
```

### 6.3 Orchestration Script

```bash
#!/bin/bash
# scripts/run-full-agentic-test.sh

set -e

echo "=== Phase 6 Agentic Test Suite ==="
echo "This script coordinates all test agents"

# Setup
echo "1. Setting up test environment..."
docker-compose -f docker-compose.test.yml up -d
sleep 5
echo "✓ Environment ready"

# Unit Tests (parallel)
echo "2. Running unit tests (parallel)..."
pytest tests/test_monte_carlo_math.py -v &
pytest tests/test_resilience_api.py -v &
npm test -- --testPathPattern="__tests__" &
wait
echo "✓ Unit tests passed"

# Integration Tests (parallel)
echo "3. Running integration tests..."
pytest tests/test_resilience_api.py::test_distributor_failure_caching -v &
npm test -- --testPathPattern="integration" &
locust -f tests/load_test.py --host=http://localhost:8000 -u 50 -r 5 -t 5m --headless --csv=results &
wait
echo "✓ Integration tests passed"

# E2E Tests (sequential)
echo "4. Running E2E tests..."
npx cypress run --config baseUrl=http://localhost:3000 --spec "cypress/e2e/**/*.cy.ts"
echo "✓ E2E tests passed"

# Performance Report
echo "5. Generating performance report..."
python scripts/generate_performance_report.py

# Cleanup
echo "6. Cleaning up..."
docker-compose -f docker-compose.test.yml down

echo "=== All Tests Passed ✓ ==="
```

### 6.4 How to Invoke an Agentic Testing Session

**Step 1: Prepare test environment**

```bash
git clone <repo>
cd logistics-project
python -m venv test-env
source test-env/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
npm --prefix frontend install
```

**Step 2: Start agents (Claude API calls or CLI)**

You can invoke testing agents via Claude API:

```python
# invoke_test_agents.py
import anthropic

client = anthropic.Anthropic()

agents = [
    {
        "name": "MathValidator",
        "prompt": """You are a mathematical validator for Phase 6 testing. Your job is to:
1. Run pytest on tests/test_monte_carlo_math.py
2. Verify all invariants pass (P10 ≤ P50 ≤ P90, cost deltas, ETA deltas)
3. Report any failures with root cause analysis
Report your findings as a structured JSON object with pass/fail status and details."""
    },
    {
        "name": "APITester",
        "prompt": """You are an API tester for Phase 6. Your job is to:
1. Run pytest on tests/test_resilience_api.py
2. Test all 3 endpoints (distributor-failure, geopolitical-risk, delivery-target)
3. Verify caching works (cache hits < 100ms)
4. Run load test: locust -f tests/load_test.py --host=http://localhost:8000 -u 100 -r 10 -t 5m --headless
5. Verify P99 latency < 2000ms
Report findings as JSON with endpoint health, cache performance, and load test results."""
    },
    {
        "name": "FrontendTester",
        "prompt": """You are a frontend tester for Phase 6. Your job is to:
1. Run npm test for ResiliencePage and component tests
2. Run Cypress E2E tests: npx cypress run --headless
3. Verify all 3 tabs render, 4 metrics display, async loading works
4. Check accessibility: npx jest-axe --all
Report findings as JSON with test pass rates, accessibility violations, and UX issues."""
    },
    {
        "name": "PerformanceProfiler",
        "prompt": """You are a performance profiler for Phase 6. Your job is to:
1. Profile Monte Carlo simulation: python -m cProfile -o simulation.prof backend/app/services/monte_carlo.py
2. Analyze with pstats to find bottlenecks
3. Check for memory leaks: memory_profiler backend/app/services/monte_carlo.py
4. Profile React components: npm run profile
5. Report: slowest functions, memory usage, recommendations
Report findings as JSON with top bottlenecks, memory stats, and optimization suggestions."""
    }
]

for agent in agents:
    print(f"\nInvoking {agent['name']}...")
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        messages=[
            {"role": "user", "content": agent['prompt']}
        ]
    )
    print(response.content[0].text)
```

**Step 3: Coordinate results**

```bash
# Run orchestration script
bash scripts/run-full-agentic-test.sh

# Or run agents sequentially
python invoke_test_agents.py > test_results.json
```

**Step 4: Review findings**

```bash
# Parse agent reports
cat test_results.json | jq '.[] | {agent: .name, status: .status, issues: .issues}'

# Generate final sign-off
echo "All test agents reported:"
cat test_results.json | jq '.[] | .name + ": " + .status'
```

---

## Part 7: Test Reporting & Dashboard

### 7.1 Test Report Template

```markdown
# Phase 6 Test Report — 2026-05-XX

## Executive Summary

| Category | Result | Details |
|----------|--------|---------|
| Unit Tests | ✓ PASS | 45/45 tests passing |
| Integration Tests | ✓ PASS | Caching, APIs, E2E flows |
| Performance | ✓ PASS | P99 < 2s, cache < 100ms |
| Accessibility | ✓ PASS | WCAG 2.1 AA compliant |
| Security | ✓ PASS | No injection, proper error handling |

## Mathematical Validation

✓ All Monte Carlo invariants verified:
  - P10 ≤ P50 ≤ P90: PASS (10,000 simulations sampled)
  - Cost delta sign correctness: PASS
  - ETA delta realism: PASS
  - Risk score monotonicity: PASS

## Performance Metrics

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| API P50 latency | < 200ms | 85ms | ✓ |
| API P99 latency | < 2s | 1.2s | ✓ |
| Cache hit rate | > 80% | 92% | ✓ |
| Frontend LCP | < 2.5s | 1.8s | ✓ |
| Load test (100 users) | No 500s | 0 errors | ✓ |

## Test Evidence

- Coverage report: [link to coverage.html]
- Load test report: [link to locust_report.html]
- Accessibility audit: [link to axe_report.json]
- Performance profiling: [link to flame_graph.html]

## Sign-Off

- [x] Math Validator: All invariants pass
- [x] API Tester: All endpoints working, P99 < 2s
- [x] Frontend Tester: All UI tests passing
- [x] Performance Profiler: No bottlenecks
- [x] E2E Tester: All flows working end-to-end
- [x] Interview Validator: Demo is interview-ready

**Status: APPROVED FOR INTERVIEW** ✓
```

### 7.2 Continuous Testing Dashboard (Optional)

```html
<!-- frontend/src/pages/TestDashboard.tsx -->
<Dashboard>
  <Section title="Unit Test Status">
    <TestResult name="Math Invariants" status="PASS" count="10/10" />
    <TestResult name="API Tests" status="PASS" count="15/15" />
    <TestResult name="UI Tests" status="PASS" count="20/20" />
  </Section>

  <Section title="Performance Metrics">
    <MetricCard label="P99 Latency" value="1.2s" target="<2s" status="✓" />
    <MetricCard label="Cache Hit Rate" value="92%" target=">80%" status="✓" />
    <MetricCard label="Frontend LCP" value="1.8s" target="<2.5s" status="✓" />
  </Section>

  <Section title="Load Test">
    <Chart type="line" data={loadTestData} />
    <Stat label="Concurrent Users" value="100" />
    <Stat label="Errors" value="0" status="✓" />
  </Section>
</Dashboard>
```

---

## Summary

This testing framework provides:

1. **Mathematical Soundness** — Verify P10 ≤ P50 ≤ P90, cost/ETA/risk deltas are correct
2. **UI Correctness** — All 4 metrics render, tabs work, async loading, errors handled
3. **Performance Validation** — P99 < 2s, cache < 100ms, no memory leaks
4. **Agentic Coordination** — Multi-role testing team with clear responsibilities and sign-off
5. **Interview Readiness** — Comprehensive documentation, demo checklist, talking points

**Next Steps:**
1. Install tools from Part 1.1
2. Set up environment from Part 1.2
3. Run unit tests (Part 4)
4. Run integration tests (Part 4.2)
5. Run E2E tests (Part 6)
6. Generate report from Part 7
7. Invoke agentic team for full sign-off

This framework is designed to be **interpretable and actionable** — each agent knows exactly what to test, how to verify it, and how to report findings.
