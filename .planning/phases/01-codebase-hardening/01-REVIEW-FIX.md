---
phase: 01-codebase-hardening
fixed_at: 2026-04-16T00:00:00Z
review_path: .planning/phases/01-codebase-hardening/01-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-04-16
**Source review:** .planning/phases/01-codebase-hardening/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 7 (2 Critical, 5 Warning)
- Fixed: 7
- Skipped: 0

## Fixed Issues

### CR-01: Hardcoded PostgreSQL credentials in docker-compose.yml

**Files modified:** `docker-compose.yml`, `backend/.env.example`
**Commit:** 4c07948
**Applied fix:** Replaced all hardcoded `logistics_password` / `logistics_user` / `logistics_db` values in the `db` service environment block and the `backend` service `DATABASE_URL` with `${POSTGRES_USER:-logistics_user}`, `${POSTGRES_PASSWORD}` (no default — must be set), and `${POSTGRES_DB:-logistics_db}`. Updated the healthcheck pg_isready call to use the env var form. Added `POSTGRES_USER`, `POSTGRES_PASSWORD=`, and `POSTGRES_DB` entries to `backend/.env.example` with a generation hint comment.

---

### CR-02: `/live-prices/{mpn}/sync` makes an internal call to `get_live_prices`

**Files modified:** `backend/app/api/live_prices.py`
**Commit:** 8f50f89
**Applied fix:** Extracted all source-fetching logic (Nexar, OEMsecrets, DigiKey, TrustedParts iteration) into a new `_fetch_live_offers(mpn) -> tuple` helper that returns `(all_offers, sources_used)` and raises `HTTPException` on no-source / no-offer conditions. `get_live_prices` now calls `_fetch_live_offers` then applies the `include_unauthorized` filter. `sync_component_prices` calls `_fetch_live_offers` inside a `try/except HTTPException` block, deduplicates and converts offers locally using the existing helpers, and references `live_offers` / `sources_used` directly — eliminating all `live.offers` and `live.sources_used` references on the old response object.

---

### WR-01: `filter_price_outliers` silently drops all offers for zero-price components

**Files modified:** `backend/app/optimization/sourcing.py`
**Commit:** 1cb45d0
**Applied fix:** When `prices` is empty (all offers have `price_usd <= 0`), added a `logger.warning` call that identifies the component_id, then calls `kept.extend(group)` before `continue` — so zero-price offers are preserved in the output. This ensures the downstream missing-component check produces a meaningful error (listing the MPN) rather than silently failing, and makes the data quality issue visible in logs.

---

### WR-02: Cart `add_to_cart` does not prevent duplicate entries

**Files modified:** `backend/app/api/cart.py`
**Commit:** fb255aa
**Applied fix:** Added a query for an existing `CartItem` matching `(user_id, component_id, distributor_id)` immediately after the component and distributor existence checks. If a matching row is found, raises `HTTP 409` with a clear message directing the user to remove the existing item or update quantity. This prevents duplicate solver demand and over-ordering.

---

### WR-03: `solve_sourcing` not guarded against empty `bom` input

**Files modified:** `backend/app/optimization/sourcing.py`
**Commit:** 1cb45d0
**Applied fix:** Added an explicit guard at the top of `solve_sourcing`: `if not bom: raise ValueError("BOM is empty — cannot solve sourcing with zero components")`. This replaces the silent no-op OR-Tools OPTIMAL result (empty model) with a clear error before any filtering or model construction occurs.

---

### WR-04: `SECRET_KEY` default value bypasses its own validator

**Files modified:** `backend/app/core/config.py`
**Commit:** e209d48
**Applied fix:** Removed the insecure default `"your-secret-key-change-in-production"` from the `SECRET_KEY` field declaration, making it a required field (`SECRET_KEY: str` with no default). Pydantic-settings will now raise a `ValidationError` at startup if `SECRET_KEY` is absent from the environment, producing a clear config error rather than silently starting with the weak default. Added a generation hint comment above the field.

---

### WR-05: `transit_days` return annotation is `float` but `math.ceil` returns `int`

**Files modified:** `backend/app/optimization/costs.py`
**Commit:** b051a4f
**Applied fix:** Changed the return type annotation on `transit_days` from `-> float` to `-> int`, matching the actual return type of `math.ceil` in Python 3. This aligns the annotation with runtime behavior and prevents subtle type-check failures in strict type checkers or Pydantic serialization when the result is used in float-typed expressions.

---

## Skipped Issues

None — all findings were fixed.

---

_Fixed: 2026-04-16_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
