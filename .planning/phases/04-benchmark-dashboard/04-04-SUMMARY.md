---
phase: 04-benchmark-dashboard
plan: "04"
subsystem: frontend
tags: [map, network-risk, ui-polish, animation, accessibility]
dependency_graph:
  requires: ["04-03"]
  provides: ["04-04"]
  affects: ["frontend/src/pages/MapPage.tsx"]
tech_stack:
  added: []
  patterns:
    - "cancelled-flag pattern for async effects (prevents setState after unmount)"
    - "useRef<Map> ref registry for scrollIntoView on programmatic selection"
    - "animate-ping for radar/sonar halo effect on critical markers"
    - "globalThis.Map to escape name shadowing by react-map-gl Map import"
key_files:
  created: []
  modified:
    - frontend/src/pages/MapPage.tsx
decisions:
  - "top-16 (not top-14) for Route Stops button — locked by UI-SPEC to avoid 3-way overlap with toggle and cascade sub-toggle"
  - "bg-red-500/60 animate-ping replaces ring-2/animate-pulse — radar/sonar feel per D-02"
  - "globalThis.Map used to avoid TypeScript shadowing by react-map-gl Map import"
  - "Accepted v1 tradeoff: last-rendered ref wins when distributor has multiple single-source rows (RESEARCH.md Pitfall 2)"
  - "border-current on tab-button spinner so color follows active/inactive button text state"
metrics:
  duration: "~25 minutes"
  completed: "2026-04-21"
  tasks_completed: 3
  files_modified: 1
---

# Phase 04 Plan 04: MapPage Network Risk Polish (D-01..D-04) Summary

**One-liner:** Four Network Risk view fixes — non-overlapping Route Stops layout (top-16), animate-ping radar halo on sole-source distributors, click-to-scroll+highlight in side panel, and loading/error-aware Network Risk tab button with cancelled-flag lifecycle safety.

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Layout + halo (D-01 + D-02) | 0d8554b | frontend/src/pages/MapPage.tsx |
| 2 | Marker click → side panel scroll + highlight (D-03) | b2fd755 | frontend/src/pages/MapPage.tsx |
| 3 | Loading spinner + error message on Network Risk tab (D-04) | 83ea2c5 | frontend/src/pages/MapPage.tsx |

## What Was Built

### D-01: Route Stops button layout fix
Changed Route Stops `<button>` from `absolute top-4 right-14` to `absolute top-16 right-14`. The `top-16` value was locked by `04-UI-SPEC.md` to ensure no three-way overlap between the toggle pill (top-4), cascade sub-toggle (top-14), and Route Stops button. The toggle pill wrapper at `top-4 right-14` and cascade sub-toggle at `top-14 right-14` were left untouched.

### D-02: Radar halo on single-source distributor markers
Replaced the `ring-2 ring-red-500 ring-offset-1 motion-safe:animate-pulse` halo div (plus its `ringOffsetColor` inline style) with `bg-red-500/60 animate-ping`. The new implementation uses Tailwind's animate-ping (expanding fill + fade) for a sonar/radar feel rather than a dim pulsing ring.

### D-03: Marker click → side panel scroll + row highlight
Five coordinated edits:
1. Added `selectedDistributorId` state (`useState<number | null>(null)`)
2. Added `componentRowRefs` ref map (`useRef(new globalThis.Map<number, HTMLButtonElement>())`) — uses `globalThis.Map` to avoid name conflict with the `Map` component imported from `react-map-gl/maplibre`
3. Network Risk marker `onClick` now calls both `setShowNetworkRiskPanel(true)` and `setSelectedDistributorId(dist.id)`
4. Panel close button `onClick` now clears `setSelectedDistributorId(null)`
5. Component row `<button>` gains a `ref` callback that registers/deregisters in the ref map, and its `className` conditionally applies `ring-1 ring-red-400` when `selectedDistributorId === comp.distributor_id`
6. A `useEffect` keyed on `[selectedDistributorId]` calls `scrollIntoView({ behavior: 'smooth', block: 'nearest' })` on the matched ref

**Known tradeoff:** when a distributor supplies multiple components, only the last-rendered row's ref is in the map (Pitfall 2 from RESEARCH.md). All rows still get the highlight ring correctly because the conditional uses `selectedDistributorId === comp.distributor_id`. Accepted v1 tradeoff.

### D-04: Loading spinner + error message on Network Risk tab
Four edits:
1. Added `graphMetricsLoading` and `graphMetricsError` boolean state
2. Rewrote Network Risk useEffect with cancelled-flag pattern — `setGraphMetricsLoading(true)` before fetch, `setGraphMetricsLoading(false)` in both `.then` and `.catch`, `setGraphMetricsError(true)` in `.catch` only. Return cleanup sets `cancelled = true` preventing setState after rapid tab-switching
3. Network Risk tab button gets `min-w-[96px]` for stable width during label swap, and conditionally renders `<span className="flex items-center gap-2"><div spinner/> Loading…</span>` vs `'Network Risk'`. Spinner uses `border-current` (not `border-blue-500`) so it follows the button's text color in both active/inactive states
4. Side panel header shows `<p className="text-xs text-slate-400">Risk data unavailable — reload to retry</p>` (em dash U+2014, ellipsis U+2026) when `graphMetricsError` is true

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed TypeScript shadowing of built-in Map by react-map-gl Map import**
- **Found during:** Task 2 verification (npm run build)
- **Issue:** `useRef<Map<number, HTMLButtonElement>>(new Map())` caused TS errors `Expected 1 arguments, but got 0` and `'new' expression, whose target lacks a construct signature` because `Map` was shadowed by `import Map from 'react-map-gl/maplibre'`
- **Fix:** Changed to `useRef(new globalThis.Map<number, HTMLButtonElement>())` which references the JavaScript built-in explicitly
- **Files modified:** frontend/src/pages/MapPage.tsx (line 184)
- **Commit:** 83ea2c5 (included in Task 3 commit)

### Out-of-Scope Pre-existing Issue (Deferred)

**BenchmarkPage.tsx TS2322:** Pre-existing TypeScript error in `frontend/src/pages/BenchmarkPage.tsx` line 514 — `Formatter` type mismatch in recharts tooltip. Existed before this plan's changes. Out of scope. Logged for follow-up.

## Verification Results

All grep contract checks passed:

```
D-01: top-16 right-14 on Route Stops button (line 720)
D-01: top-4 right-14 still on toggle pill (line 671) — unchanged
D-02: bg-red-500/60 animate-ping on halo div (line 515)
D-02: 0 occurrences of motion-safe:animate-pulse
D-03: 5 occurrences of selectedDistributorId
D-03: ring-1 ring-red-400 on component row className (line 864)
D-03: scrollIntoView({ behavior: 'smooth', block: 'nearest' }) (line 305)
D-03: componentRowRefs appears 4 times (decl, get, set, delete)
D-04: 5 occurrences of MetricsLoading (state decl + 3 setters + tab-button conditional)
D-04: 4 occurrences of MetricsError (state decl + 2 setters + panel conditional)
D-04: min-w-[96px] on Network Risk tab button only (line 687)
D-04: border border-current border-t-transparent animate-spin spinner (line 691)
D-04: 'Risk data unavailable — reload to retry' with em dash (line 826)
D-04: 'Loading…' with U+2026 horizontal ellipsis (line 692)
D-04: 2 cancelled flags, 2 cleanup returns
```

TypeScript: No errors in MapPage.tsx (`npx tsc --noEmit` reports only pre-existing BenchmarkPage issue).

## Known Stubs

None. All data flows are wired to real API responses.

## Threat Flags

None. No new network endpoints, auth paths, or schema changes introduced.

## Self-Check: PASSED

- frontend/src/pages/MapPage.tsx: FOUND (modified)
- Commit 0d8554b: FOUND (D-01 + D-02)
- Commit b2fd755: FOUND (D-03)
- Commit 83ea2c5: FOUND (D-04)
- No files deleted by commits (verified via git diff --diff-filter=D)
