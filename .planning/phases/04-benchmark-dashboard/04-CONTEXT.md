# Phase 4: Benchmark Dashboard - Context

**Gathered:** 2026-04-21
**Status:** Ready for planning

<domain>
## Phase Boundary

04-04 delivers the interactive Network Risk map overlay: a Routes/Network Risk view toggle on MapPage, distributor markers sized by betweenness centrality and colored by risk tier, animated radar-ring halos for single-source distributors (sourced from real `/benchmark/single-source-components` API), a right-docked side panel listing single-source components with clickable rows, and a cascade heatmap toggle. Plans 01-03 are already complete and committed — only 04-04 remains.

</domain>

<decisions>
## Implementation Decisions

### Toggle Position Layout
- **D-01:** Keep Routes/Network Risk toggle permanently at `top-4 right-14`. Move Route Stops button from `top-4 right-14` to `top-14 right-14` (below the toggle) to eliminate the overlap when a route is selected in Routes view. Toggle is persistent; Route Stops is contextual — stacking them vertically preserves both.

### Halo Animation Style
- **D-02:** Replace `motion-safe:animate-pulse` with `animate-ping` on the single-source distributor halo ring. The ping animation produces a growing-outward radar/sonar ring effect — more visually alarming and distinct from generic pulse animations. Standard Tailwind pattern for live-alert indicators.

### Marker Click Behavior in Network Risk View
- **D-03:** Clicking a distributor marker in Network Risk view opens the side panel AND scrolls the matching component row(s) into view, then highlights them with `ring-1 ring-red-400` outline. Track `selectedDistributorId` state; component rows matching that distributor ID get the highlight class. Highlight clears when panel closes or another marker is clicked.

### Loading States
- **D-04:** Show a small spinner inside the "Network Risk" tab button while `graphAPI.metrics()` is pending. Track `graphMetricsLoading` boolean state; replace the button label with a spinner + "Loading…" or animate the existing label. No full-page overlay — spinner disappears once data arrives. Side panel shows normal empty state ("No single-source components detected") until `singleSourceComponents` resolves.

### Claude's Discretion
- Spinner visual implementation (inline SVG, Lucide `Loader2`, or CSS border spinner) — any consistent with existing codebase patterns
- Exact `top-14` vs `top-16` vertical offset for Route Stops — whichever clears the toggle without crowding

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

No external specs — requirements fully captured in decisions above. Relevant existing files:

### Existing implementation
- `frontend/src/pages/MapPage.tsx` — current (uncommitted) implementation; contains all Network Risk view code needing the 4 fixes above
- `frontend/src/lib/risk.ts` — RISK_COLORS and riskLabel shared module (already imported in MapPage)
- `frontend/src/services/api.ts` — benchmarkAPI.singleSourceComponents() and graphAPI.metrics() already wired

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RISK_COLORS` / `riskLabel` from `lib/risk.ts` — already imported in MapPage, used for marker coloring
- `benchmarkAPI.singleSourceComponents()` and `graphAPI.metrics()` — already called in MapPage Network Risk useEffect
- Lucide icons (`X`, `Route`, `Globe`, etc.) — already imported; use `Loader2` for spinner if consistent

### Established Patterns
- Tailwind `animate-ping` — standard Tailwind class, no custom CSS needed for radar halo
- State pattern: `useState<'routes' | 'network-risk'>('routes')` — follow same pattern for `graphMetricsLoading` boolean
- Side panel already uses `ref` on the scroll container via `flex-1 overflow-y-auto` — can use `element.scrollIntoView()` on highlighted rows

### Integration Points
- `MapPage.tsx` is self-contained — no new files needed for 04-04 fixes; all changes are additive modifications
- Route Stops button is at line ~686-701; toggle is at lines 648-670; swap `top-4` → `top-14` on Route Stops only

</code_context>

<specifics>
## Specific Ideas

- Halo: Use `animate-ping` with `bg-red-500/60` (semi-transparent fill) and `absolute inset-0 rounded-full` — creates the classic expanding sonar ring
- Highlight: `ring-1 ring-red-400` on the component `<button>` row, scroll with `element.scrollIntoView({ behavior: 'smooth', block: 'nearest' })`

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 04-benchmark-dashboard*
*Context gathered: 2026-04-21*
