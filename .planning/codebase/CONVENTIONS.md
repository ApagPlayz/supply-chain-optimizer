# Coding Conventions
_Last updated: 2026-04-15_

## Summary
The backend follows standard FastAPI/SQLAlchemy patterns with Pydantic v2 schemas co-located in API modules. The frontend uses React functional components with Zustand stores, strict TypeScript, and Tailwind v4. Both layers are consistent in naming and structure, with well-cited constants in domain modules but no enforced formatter beyond ESLint for TypeScript.

---

## Naming Patterns

### Python (backend)

**Files:**
- `snake_case` throughout: `cart.py`, `components.py`, `lead_time_model.py`, `freight_hubs.py`
- Test files prefixed with `test_`: `test_costs.py`, `test_sourcing.py`, `test_strategies.py`

**Classes:**
- `PascalCase`: `ComponentResponse`, `DistributorOffer`, `StrategyWeights`, `CostBreakdown`, `BomLine`, `MLState`
- Pydantic response models suffixed with `Response`: `CartItemResponse`, `OfferResponse`, `ComponentDetailResponse`
- Pydantic request/input models suffixed with the action: `CartItemAdd`, `UserRegister`, `UserLogin`
- SQLAlchemy models: bare domain nouns — `Component`, `Distributor`, `User`, `CartItem`

**Functions:**
- `snake_case`: `haversine_km`, `transport_cost_usd`, `leg_lead_time_days`, `ml_lead_time_days`, `get_strategy`, `solve_sourcing`
- FastAPI route handlers named as verbs: `list_components`, `get_component`, `add_to_cart`, `remove_from_cart`, `clear_cart`

**Variables/locals:**
- `snake_case` consistently
- Loop variables use short names: `c` for component, `d` for distributor, `o` for offer, `s` for strategy

**Constants:**
- `UPPER_SNAKE_CASE` with inline source citations:
  ```python
  # ATRI 2023: An Analysis of the Operational Costs of Trucking
  TL_RATE_USD_PER_MILE = 2.271
  # EPA SmartWay 2023 heavy-duty truck factor: 161.8 g CO2e / ton-mile
  CO2_G_PER_TON_MILE = 161.8
  ```
- Units always in the constant name: `_USD`, `_KG`, `_KM`, `_DAYS`, `_PER_MILE`

### TypeScript (frontend)

**Files:**
- `PascalCase` for React components and pages: `CartPage.tsx`, `CheckoutPage.tsx`, `NavBar.tsx`
- `camelCase` for stores and services: `authStore.ts`, `cartStore.ts`, `optimizeStore.ts`, `api.ts`
- `camelCase` for config: `vite.config.ts`, `eslint.config.js`

**Interfaces/Types:**
- `PascalCase`, no `I` prefix: `CartItem`, `CartState`, `RouteStop`, `RouteAlternative`, `OptimizeState`
- Domain types in stores mirror backend snake_case field names (e.g. `distributor_id`, `unit_price_usd`)

**Functions/hooks:**
- React hooks: `camelCase` prefixed with `use`: `useCartStore`, `useAuthStore`, `useOptimizeStore`
- Utility functions: `camelCase`: `riskColor`, `riskBadge`, `riskLabel`
- Component functions: `PascalCase`: `KpiCard`, `RankBadge`, `DeltaIndicator`, `MetricRow`

**API namespaces:**
- Suffixed with `API`: `authAPI`, `cartAPI`, `componentsAPI`, `distributorsAPI`, `optimizeAPI`

---

## Module / File Organization Patterns

### Backend

API route modules each contain:
1. `router = APIRouter(prefix=..., tags=[...])`
2. Pydantic request models (Input schemas)
3. Pydantic response models (Output schemas, with `class Config: from_attributes = True`)
4. Route handler functions

Schemas shared across modules go in `backend/app/api/schemas.py`. Domain-specific schemas stay in-module.

The optimization layer is cleanly separated:
- `costs.py` — pure math functions (no dependencies on DB or FastAPI)
- `sourcing.py` — CP-SAT MILP, uses `costs.py` and `strategies.py`
- `routing.py` — TSP solver, no other optimization deps
- `strategies.py` — strategy weight definitions, `normalize_objectives`, `weighted_objective`
- `cross_dock.py` — hub evaluation, depends on `routing.py` and `costs.py`
- `solve.py` — orchestrator that calls sourcing → routing → cross_dock → assembles response

### Frontend

Each page is a single `export default function PageName()` in `frontend/src/pages/`.
Sub-components defined in the same file when page-specific (e.g. `RankBadge`, `MetricRow` in `CheckoutPage.tsx`).
Shared display components live in `frontend/src/components/`.
All API calls route through `frontend/src/services/api.ts` — pages never call `axios` directly.

---

## Import Organization

### Python
```python
# 1. stdlib
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import List, Optional

# 2. third-party
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

# 3. local app imports
from app.core.database import get_db
from app.models.component import Component, DistributorOffer
```

No path aliases; all imports use `app.` prefix from the `backend/` root.

### TypeScript
```typescript
// 1. React and hooks
import { useEffect, useState, useCallback } from 'react';
// 2. router
import { useNavigate } from 'react-router-dom';
// 3. third-party libs (recharts, lucide, framer-motion)
import { motion } from 'framer-motion';
// 4. local stores and services
import { useCartStore } from '../store/cartStore';
import { optimizeAPI } from '../services/api';
```

No `@/` path aliases configured. All imports use relative `../` paths.

---

## Error Handling

### Backend
- FastAPI `HTTPException` is the universal error mechanism for all API-layer failures
- Standard HTTP status codes used correctly: `404` for missing resources, `400` for bad input, `401` for auth failures, `422` for constraint violations (MOQ, stock exceeded)
- Descriptive `detail` strings that include the violated constraint:
  ```python
  raise HTTPException(
      status_code=422,
      detail=f"Minimum order quantity for this offer is {moq} units "
             f"(requested: {int(body.quantity)})",
  )
  ```
- ML functions use `try/except Exception: pass` with explicit fallback to deterministic formula — never propagates ML failures to callers:
  ```python
  try:
      # attempt ML prediction
      return predict_lead_time(...)
  except Exception:
      pass  # fall through to deterministic formula
  return leg_lead_time_days(distance_km, distributor_tier)
  ```
- No custom exception classes; all errors are plain `HTTPException`

### Frontend
- Zustand store actions catch errors and expose them via `error: string | null` state:
  ```typescript
  catch (err: any) {
    set({ loading: false, error: err.response?.data?.detail || 'Failed to load cart' });
  }
  ```
- `addItem` re-throws to let the calling component handle UI feedback:
  ```typescript
  catch (err: any) {
    throw new Error(err.response?.data?.detail || 'Failed to add item');
  }
  ```
- Global 401 interceptor in `api.ts` removes cookie and redirects to `/login`
- `err.response?.data?.detail` pattern propagates FastAPI's error `detail` string to UI

---

## Docstrings and Comments

### Python
- Module-level docstrings used for all optimization files, citing academic/industry references:
  ```python
  """
  Four multi-objective weight profiles.
  Weighted sum scalarization over normalized cost/time/carbon objectives.
  See spec §5.2 — Marler & Arora (2004), Ghodsypour & O'Brien (1998).
  """
  ```
- Route handler docstrings are one-liners describing the endpoint:
  ```python
  """List components with optional filters. Includes price range and offer count."""
  """Get component detail with all distributor offers ranked by price."""
  ```
- Constants have inline comment citations sourcing the value to a specific report/year
- Section separators used in longer files: `# ── Section Name ──────────`

### TypeScript
- Sparse comments; some section headers: `// ── Auth ────`, `// ── Types ────`, `// ── Constants ────`
- `/** ... */` JSDoc used only in `optimizeStore.ts` for one `getSelected` method
- Inline comments explain non-obvious logic (e.g. `// validate structure`, `// Auto-run optimization after cart loads`)

---

## Dataclass vs Pydantic Patterns

**Python dataclasses** are used for optimization-layer data transfer objects (no validation needed, performance matters):
- `BomLine`, `Offer`, `SourcingAssignment`, `OutlierDrop` in `sourcing.py`
- `StrategyWeights` (frozen) in `strategies.py`
- `CostBreakdown` (frozen, with `@property`) in `costs.py`
- `MLState` in `ml/__init__.py`

**Pydantic `BaseModel`** is used for all API request/response schemas (validation required):
- Request bodies: `CartItemAdd`, `UserRegister`, `UserLogin`
- Response models: `CartItemResponse`, `ComponentResponse`, `OfferResponse`
- All response models have `class Config: from_attributes = True` for SQLAlchemy ORM mapping

---

## TypeScript Strict Mode

`tsconfig.json` uses strict TypeScript (inferred from `tseslint.configs.recommended` in `eslint.config.js`). Observed patterns:
- Interfaces preferred over type aliases for object shapes
- Union with `null` for optional fields: `string | null`, `number | null`
- `any` used sparingly and only for `err` in catch blocks (`catch (err: any)`)
- Generic types on `create<CartState>()` for Zustand stores

---

## Linting Configuration

**Frontend:** ESLint via `frontend/eslint.config.js` with:
- `@eslint/js` recommended
- `typescript-eslint` recommended
- `eslint-plugin-react-hooks` (enforces hooks rules)
- `eslint-plugin-react-refresh` (Vite HMR safety)
- Target: `ecmaVersion: 2020`, `globals.browser`

**Backend:** No `pyproject.toml`, `setup.cfg`, or `.flake8` detected. No formatter config (black/ruff/isort) found. Code style is consistent but unenforceable via tooling.

---

## Styling Conventions (Frontend)

- Tailwind CSS v4.2 utility classes inline, no CSS files
- Dark theme throughout: `slate-800/70`, `slate-900`, `slate-400`, `white`
- Opacity modifiers for backgrounds: `bg-green-500/20`, `bg-slate-800/70`
- `backdrop-blur-sm` on card elements
- Color semantics: green = low risk / best, yellow = medium risk, red = high risk / worst
- Risk thresholds: `< 0.3` low (green), `< 0.6` medium (yellow), `≥ 0.6` high (red)
- Animations via `framer-motion` on KPI cards only (staggered `delay` prop pattern)
