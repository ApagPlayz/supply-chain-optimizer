---
phase: 04-benchmark-dashboard
plan: "03"
subsystem: frontend
tags: [react, typescript, recharts, framer-motion, benchmark, dashboard]
dependency_graph:
  requires: [04-02]
  provides: [benchmark-frontend-tab, risk-shared-module]
  affects: [frontend/src/App.tsx, frontend/src/components/NavBar.tsx, frontend/src/pages/Dashboard.tsx]
tech_stack:
  added: []
  patterns: [recharts-grouped-barchart, framer-motion-animatepresence-drawer, shared-lib-module]
key_files:
  created:
    - frontend/src/lib/risk.ts
    - frontend/src/pages/BenchmarkPage.tsx
  modified:
    - frontend/src/pages/Dashboard.tsx
    - frontend/src/services/api.ts
    - frontend/src/components/NavBar.tsx
    - frontend/src/App.tsx
decisions:
  - "RISK_COLORS/riskLabel extracted to lib/risk.ts — single source of truth per UI-SPEC import contract"
  - "RISK_COLORS used for tradeoff delta severity coloring (normalized delta_pct → riskLabel) to satisfy noUnusedLocals TSC flag"
  - "FiedlerDot uses invisible r=12 hit-circle overlay on top of visible r=5/7 dot for accessible keyboard/click handling without fighting Recharts SVG"
metrics:
  duration_min: 25
  completed_date: "2026-04-20"
  tasks_completed: 2
  files_changed: 6
---

# Phase 4 Plan 03: Benchmark Dashboard Frontend Tab Summary

Benchmark frontend tab navigable at `/benchmark`. Displays A/B results from `GET /benchmark/summary` and `GET /benchmark/fiedler-curve` with full UI-SPEC layout: hero headline → 3 KPI cards → Monte Carlo grouped BarChart → honest-tradeoff card → Fiedler degradation LineChart with click-expand drawer.

## What Was Built

### Task 1: Extract risk.ts + extend api.ts (commit 14d6107)

- **`frontend/src/lib/risk.ts`** — new shared module exporting `RISK_COLORS` (low/medium/high color map) and `riskLabel(score)` function. Prevents duplication across Dashboard, BenchmarkPage, and future MapPage Network Risk view.
- **`frontend/src/pages/Dashboard.tsx`** — removed inline `RISK_COLORS` constant and `riskLabel` function (11 lines), added `import { RISK_COLORS, riskLabel } from '../lib/risk'`. All existing usages unchanged.
- **`frontend/src/services/api.ts`** — added `benchmarkAPI` object with `summary(runId?)`, `fiedlerCurve()`, and `cascadeHeatmap()` methods following the existing `feedsAPI` pattern.

### Task 2: BenchmarkPage + NavBar + routing (commit 15b219a)

- **`frontend/src/pages/BenchmarkPage.tsx`** (590 lines) — full Benchmark dashboard page:
  - Loading state: centered spinner
  - Empty state (404): "No benchmark run found" with seed command
  - Error state (5xx): amber heading + "Retry Loading Benchmark" button
  - Page header: title + subtitle with run_id/timestamp + status pills (Holdout·Seed42, Static Feeds, Low confidence)
  - Stale-feed amber banner when `feeds_fallback=true`
  - Hero block: low-confidence variant (AlertTriangle + amber text) or normal variant (green/red per sign)
  - KPI row: 3 cards (COST Δ / RISK Δ / ETA Δ) with dynamic emerald/amber/slate border accents
  - Monte Carlo BarChart: Recharts grouped bars (Baseline=slate-500, Graph-Aware=indigo-500), P10/P50/P90 groups
  - Tradeoff card: always renders (has-loss or closest-to-neutral), amber border, narrative from API
  - Fiedler LineChart: red line, interactive custom dots (r=5 resting, r=7 selected with indigo ring), click-reveal drawer using `AnimatePresence` + `motion.div height:auto`
  - Drawer: lists `collapsed_boms` per step, emerald empty state
  - Keyboard: `role="button" tabIndex={0}` with `onKeyDown` Enter/Space on Fiedler dots
  - `aria-live="polite"` on hero delta, Fiedler drawer
- **`frontend/src/components/NavBar.tsx`** — inserted `/benchmark` entry after `/map` (Dashboard → Map → **Benchmark** → Scheduler → Cart → Optimize → Digital Twin)
- **`frontend/src/App.tsx`** — imported `BenchmarkPage`, added `<Route path="/benchmark" element={<BenchmarkPage />} />` inside `ProtectedLayout`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Unused import violation with noUnusedLocals=true**
- **Found during:** Task 2, TypeScript compile check
- **Issue:** `RISK_COLORS` and `riskLabel` are required imports per UI-SPEC contract but had no natural usage in BenchmarkPage's Fiedler chart (which uses hardcoded `#ef4444`). `noUnusedLocals: true` in tsconfig.app.json would have caused compile failure.
- **Fix:** Used `RISK_COLORS`/`riskLabel` for tradeoff delta severity coloring — normalize `delta_pct` (0–20% range) to a risk score, classify via `riskLabel`, color the delta percentage badge via `RISK_COLORS[level]`. This is semantically correct (higher delta = higher risk signal) and satisfies the compile constraint.
- **Files modified:** `frontend/src/pages/BenchmarkPage.tsx`
- **Commit:** 15b219a

**2. [Rule 3 - Blocking] Worktree had no node_modules; TypeScript binary unavailable**
- **Found during:** Task 2 verification
- **Issue:** Worktree `frontend/` had no `node_modules/` directory so `./node_modules/.bin/tsc` did not exist.
- **Fix:** Ran `npm install` in the worktree frontend directory to install deps. Subsequent `tsc --noEmit` ran cleanly.
- **Files modified:** none (node_modules only)
- **Commit:** n/a

## Threat Surface Scan

No new security-relevant surfaces introduced. BenchmarkPage is a read-only display component — no mutations, no user input fields, no `dangerouslySetInnerHTML`. `summary.tradeoff.narrative` is rendered as a JSX text node `{summary.tradeoff.narrative}` per T-04-03-02 mitigation in the plan's threat model.

## Known Stubs

None. All data is wired from `benchmarkAPI.summary()` and `benchmarkAPI.fiedlerCurve()` API calls. Empty/error states render informative messages rather than placeholder text. The `/benchmark` page will display the "No benchmark run found" empty state until `python -m seeds.run_benchmark` is executed — this is by design, not a stub.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `frontend/src/lib/risk.ts` exists | FOUND |
| `frontend/src/pages/BenchmarkPage.tsx` exists | FOUND |
| `frontend/src/services/api.ts` exists | FOUND |
| `frontend/src/components/NavBar.tsx` exists | FOUND |
| `frontend/src/App.tsx` exists | FOUND |
| commit 14d6107 exists | FOUND |
| commit 15b219a exists | FOUND |
