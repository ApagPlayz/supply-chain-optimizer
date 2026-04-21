# Phase 4: Benchmark Dashboard - Research

**Researched:** 2026-04-21
**Domain:** React/TypeScript frontend — MapPage interactive network-risk overlay polish
**Confidence:** HIGH

## Summary

Plans 04-01 through 04-03 are fully implemented and committed. The benchmark foundation
(run_benchmark.py, OptimizationRun ORM, Fiedler curve), the benchmark API (summary,
fiedler-curve, cascade-heatmap, single-source-components endpoints with 14 tests), and the
BenchmarkPage frontend tab with NavBar routing all exist in git history as of commits
885f436 through 15b219a.

Only 04-04 remains: four targeted fixes to `MapPage.tsx` that were deferred during the
implementation of the Network Risk view. The current code has the full Network Risk
infrastructure (state, API calls, marker rendering, side panel, cascade heatmap) but with
four known regressions or missing polish items identified in the discussion session. All
four fixes are additive modifications to a single file — no new files are required.

**Primary recommendation:** Write 04-04 as a single focused plan targeting `MapPage.tsx`
with four atomic task groups — one per decision in CONTEXT.md — each independently
testable by manual visual inspection.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Keep Routes/Network Risk toggle permanently at `top-4 right-14`. Move Route Stops button from `top-4 right-14` to `top-14 right-14` (below the toggle) to eliminate overlap when a route is selected in Routes view.
- **D-02:** Replace `motion-safe:animate-pulse` with `animate-ping` on the single-source distributor halo ring. The ping animation produces a growing-outward radar/sonar ring effect — more visually alarming and distinct from generic pulse.
- **D-03:** Clicking a distributor marker in Network Risk view opens the side panel AND scrolls the matching component row(s) into view, then highlights them with `ring-1 ring-red-400` outline. Track `selectedDistributorId` state; component rows matching that distributor ID get the highlight class. Highlight clears when panel closes or another marker is clicked.
- **D-04:** Show a small spinner inside the "Network Risk" tab button while `graphAPI.metrics()` is pending. Track `graphMetricsLoading` boolean state; replace the button label with a spinner + "Loading…" or animate the existing label. No full-page overlay — spinner disappears once data arrives.

### Claude's Discretion

- Spinner visual implementation (inline SVG, Lucide `Loader2`, or CSS border spinner) — any consistent with existing codebase patterns.
- Exact `top-14` vs `top-16` vertical offset for Route Stops — whichever clears the toggle without crowding.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Toggle position fix (D-01) | Browser / Client | — | Pure CSS class change in React JSX |
| Halo animation change (D-02) | Browser / Client | — | Tailwind class swap, no backend involvement |
| Marker click → panel scroll (D-03) | Browser / Client | — | useState + scrollIntoView, no API call |
| Loading spinner on tab (D-04) | Browser / Client | API / Backend | State tracks API promise; spinner is purely frontend |

All four changes are frontend-only modifications to `MapPage.tsx`. No backend changes.
No new API endpoints. No new files.

## Standard Stack

### Core (already installed, no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| react | ^18 | Component state and effects | Project baseline [VERIFIED: codebase] |
| tailwindcss | 4.2.2 | Utility classes including `animate-ping`, `ring-*` | Already in project [VERIFIED: package.json] |
| lucide-react | ^1.7.0 | Icon set including `Loader2` for spinner | Already in project [VERIFIED: package.json] |
| react-map-gl | ^8.1.0 | Marker rendering and `mapRef.flyTo` | Already in project [VERIFIED: package.json] |

**No new packages to install.** All required capabilities exist in the installed stack.

### Spinner Choice — Claude's Discretion

The codebase uses inline CSS border-spinner exclusively for loading states
(`rounded-full border border-blue-500 border-t-transparent animate-spin`). `Loader2`
from lucide-react is imported in 0 files currently. [VERIFIED: grep of frontend/src/]

Recommendation: use inline CSS border spinner to stay consistent with all other loading
states in the codebase. Pattern: `w-3 h-3 rounded-full border border-white border-t-transparent animate-spin`.

## Architecture Patterns

### System Architecture Diagram

```
User clicks "Network Risk" tab
        ↓
setMapView('network-risk')        setGraphMetricsLoading(true)
        ↓                                    ↓
useEffect fires                   graphAPI.metrics() fetch
        ↓                                    ↓
singleSourceComponents fetch     response → setGraphMetrics()
        ↓                         setGraphMetricsLoading(false)
setSingleSourceDistributorIds
        ↓
Markers render with:
  - betweenness-based size
  - RISK_COLORS tier color
  - animate-ping halo (D-02) if isSingleSource
        ↓
User clicks marker
        ↓
setShowNetworkRiskPanel(true)
setSelectedDistributorId(dist.id)   ← NEW (D-03)
        ↓
Side panel opens → rows with matching distributor_id
get ring-1 ring-red-400 class + scrollIntoView()
```

### Recommended Project Structure

No structural changes. All modifications are within:
```
frontend/src/
└── pages/
    └── MapPage.tsx   ← sole target file for 04-04
```

### Pattern 1: `animate-ping` Halo Ring (D-02)

**What:** Replace `motion-safe:animate-pulse` with `animate-ping` on the halo element.
Tailwind's `animate-ping` scales from 1→2 and fades to opacity 0, producing an expanding
radar/sonar ring. [VERIFIED: Tailwind 4.2.2 installed; animate-ping is a core Tailwind
animation unchanged since v2]

**Current code (line ~492 of MapPage.tsx):**
```tsx
// CURRENT — wrong animation
<div
  className="absolute inset-0 rounded-full ring-2 ring-red-500 ring-offset-1 motion-safe:animate-pulse"
  style={{ ringOffsetColor: 'transparent' } as React.CSSProperties}
  aria-hidden="true"
/>
```

**Target (D-02 + CONTEXT.md specifics):**
```tsx
// NEW — radar ping ring
<div
  className="absolute inset-0 rounded-full bg-red-500/60 animate-ping"
  aria-hidden="true"
/>
```

Note: The CONTEXT.md specifies `bg-red-500/60 absolute inset-0 rounded-full` — a filled
semi-transparent circle that scales outward. Remove the `ring-*` classes; they are
redundant with the fill approach and create visual noise at small marker sizes.

### Pattern 2: Route Stops Button Position Fix (D-01)

**What:** Both toggle and Route Stops share `top-4 right-14`. Move Route Stops down.

**Current code (line ~686-701 of MapPage.tsx):**
```tsx
{selectedRoute && mapView === 'routes' && (
  <button className={`absolute top-4 right-14 z-10 ...`}>  {/* CONFLICT */}
    Route Stops
  </button>
)}
```

**Target:**
```tsx
{selectedRoute && mapView === 'routes' && (
  <button className={`absolute top-14 right-14 z-10 ...`}>  {/* below toggle */}
    Route Stops
  </button>
)}
```

`top-14` = 3.5rem. The toggle is `h-~34px` at `top-4` (1rem). At standard font size,
`top-14` gives ~8px clearance between them. Use `top-16` (4rem) if visual check shows
crowding. [ASSUMED: exact clearance depends on runtime font size / browser zoom]

### Pattern 3: Marker Click → Side Panel Scroll + Highlight (D-03)

**What:** Track `selectedDistributorId`; clicking a Network Risk marker sets it, side
panel highlights matching rows with `ring-1 ring-red-400` and calls `scrollIntoView`.

**New state:**
```tsx
const [selectedDistributorId, setSelectedDistributorId] = useState<number | null>(null);
const componentRowRefs = useRef<Map<number, HTMLButtonElement>>(new Map());
```

**Marker onClick (inside Network Risk branch):**
```tsx
onClick={() => {
  setShowNetworkRiskPanel(true);
  setSelectedDistributorId(dist.id);
}}
```

**Clear on panel close:**
```tsx
// In the close button handler
onClick={() => {
  setShowNetworkRiskPanel(false);
  setSelectedDistributorId(null);
}}
```

**Row rendering in side panel:**
```tsx
<button
  key={i}
  ref={(el) => {
    if (el) componentRowRefs.current.set(comp.distributor_id, el);
    else componentRowRefs.current.delete(comp.distributor_id);
  }}
  className={`w-full text-left bg-slate-800/40 hover:bg-slate-800/70 rounded-lg px-3 py-2 border-l-2 border-red-500 transition-colors ${
    selectedDistributorId === comp.distributor_id
      ? 'ring-1 ring-red-400'
      : ''
  }`}
  onClick={() => { /* existing flyTo logic */ }}
>
```

**Scroll effect (useEffect keyed on selectedDistributorId):**
```tsx
useEffect(() => {
  if (selectedDistributorId === null) return;
  const el = componentRowRefs.current.get(selectedDistributorId);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}, [selectedDistributorId]);
```

**Edge case:** Multiple components may share the same `distributor_id`. The ref map
stores one element per distributor_id (last rendered wins). The highlight class applies
to ALL matching rows via the className condition — only the last-registered ref scrolls.
This is acceptable for the current data density. [ASSUMED: acceptable UX tradeoff]

### Pattern 4: Loading Spinner on Network Risk Tab (D-04)

**New state:**
```tsx
const [graphMetricsLoading, setGraphMetricsLoading] = useState(false);
```

**Updated fetch in useEffect:**
```tsx
if (!graphMetrics) {
  setGraphMetricsLoading(true);
  graphAPI.metrics()
    .then((res) => {
      setGraphMetrics(res.data);
      setGraphMetricsLoading(false);
    })
    .catch(() => {
      setGraphMetricsLoading(false);
    });
}
```

**Tab button — conditional label:**
```tsx
<button
  role="tab"
  aria-selected={mapView === 'network-risk'}
  onClick={() => { setMapView('network-risk'); setShowNetworkRiskPanel(true); }}
  className={`px-3 py-2 transition-colors flex items-center gap-1.5 ${
    mapView === 'network-risk' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
  }`}
>
  {graphMetricsLoading ? (
    <>
      <div className="w-3 h-3 rounded-full border border-current border-t-transparent animate-spin" />
      Loading…
    </>
  ) : (
    'Network Risk'
  )}
</button>
```

Note: `border-current` inherits the button's text color (white when active, slate-400
otherwise), so the spinner matches the label color without hard-coding. Consistent with
existing `border-blue-500` pattern in the page but adapted for the tab context.

### Anti-Patterns to Avoid

- **Putting `animate-ping` on a ring div:** `animate-ping` is designed for filled elements — it scales the entire element. Applying it to a `ring-*`-only div with no fill produces a nearly invisible animation. Use `bg-red-500/60` fill instead.
- **Using `motion-safe:animate-*`:** `motion-safe:` prefix shows animation only when user prefers motion. For a risk indicator, unconditional `animate-ping` is correct — the animation carries meaning, not just decoration.
- **Setting `graphMetricsLoading` based on `mapView`:** The loading state should track the Promise lifecycle, not the tab state. Multiple tab switches before data loads should not reset the spinner.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Radar/sonar ring animation | Custom CSS keyframe | `animate-ping` (Tailwind built-in) | Identical visual, maintained, tree-shaken |
| Scroll to element | Manual offset calculations | `element.scrollIntoView()` | Browser API handles all scroll container nesting |
| Spinner | SVG animation / custom keyframe | Inline CSS border spinner (existing pattern) | Consistent with all other loading states in codebase |

## Runtime State Inventory

> Phase is a frontend polish pass with no renames or migrations. Skip.

Step 2.5 SKIPPED — no rename/refactor involved.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js / npm | Frontend build | ✓ | verified by package.json presence | — |
| Tailwind CSS | animate-ping, ring-* | ✓ | 4.2.2 | — |
| lucide-react | Optional Loader2 | ✓ | ^1.7.0 | Use CSS spinner (recommended) |
| react-map-gl | Marker, mapRef | ✓ | ^8.1.0 | — |

**Missing dependencies with no fallback:** None.

## Common Pitfalls

### Pitfall 1: `animate-ping` Becomes Invisible at Small Marker Sizes

**What goes wrong:** Markers are 6–22px. The ping animation doubles the element's size
and fades to opacity 0. If the halo div is the same size as the marker, the expanding
ring covers the marker itself, obscuring it.

**Why it happens:** `absolute inset-0` makes the halo exactly the same size as the
marker container. The ping starts at scale(1) = identical to container.

**How to avoid:** Ensure the halo div has `absolute inset-0` so it expands outward from
the container edge. The main marker dot is a sibling inside the same container — the
halo is `position:absolute` behind or above it. As long as the halo div is positioned
correctly relative to the container and the marker dot is also `position:relative` or
explicitly stacked, both are visible. Current container pattern `<div className="relative">`
with `<div>` marker + `<div>` halo is correct.

**Warning signs:** Halo invisible at zoom levels 2-4; markers disappear then reappear.

### Pitfall 2: Multiple Rows per Distributor ID — Only Last Ref Scrolls

**What goes wrong:** If distributor D has 3 single-source components, the
`componentRowRefs` map has one entry for key `D` (the last rendered `<button>`). Only
that row scrolls; the other two also get `ring-1 ring-red-400` from the className
condition, but scroll position goes to the last-rendered one.

**Why it happens:** `useRef<Map<number, HTMLButtonElement>>` maps distributor_id → single
ref. Multiple components per distributor overwrite the ref.

**How to avoid:** Acceptable for v1 — data shows most single-source distributors supply
exactly one critical component. If future data has many, change map to store the first
ref instead of the last (guard: `if (el && !componentRowRefs.current.has(id))`).

**Warning signs:** Wrong row scrolled into view when distributor supplies 2+ components.

### Pitfall 3: `graphMetricsLoading` Stuck After Navigation Away

**What goes wrong:** User clicks Network Risk tab, immediately clicks Routes tab, then
clicks Network Risk again. The in-flight fetch resolves and calls `setGraphMetricsLoading(false)` on an unmounted or stale state path.

**Why it happens:** No cleanup in the useEffect.

**How to avoid:** Add cancelled flag pattern (same as the existing `roadPaths` useEffect
in MapPage.tsx lines 196-229). The existing graph metrics fetch already does `if (!graphMetrics) return` — the cancelled pattern just prevents the setState call after unmount.

**Warning signs:** Spinner shows permanently after rapid tab switching.

### Pitfall 4: Toggle Width Changes When Spinner Appears (D-04)

**What goes wrong:** The "Network Risk" button text is fixed-width text. Swapping it for
spinner + "Loading…" text changes the button width, causing the toggle pill to resize and
shift layout.

**Why it happens:** Button width driven by content.

**How to avoid:** Apply `min-w-[96px]` or `w-28` to the Network Risk button to pin its
width. Alternatively, keep "Network Risk" text but show the spinner as a prefix.

## Code Examples

### Verified patterns from codebase

#### Inline CSS Spinner (existing pattern, multiple files)
```tsx
// Source: MapPage.tsx line 375 (verified in codebase)
<div className="w-3 h-3 rounded-full border border-blue-500 border-t-transparent animate-spin" />
```

#### Cancelled Fetch Pattern (existing pattern)
```tsx
// Source: MapPage.tsx lines 196-229 (verified in codebase)
let cancelled = false;
// ... fetch ...
.then((result) => {
  if (!cancelled) { setState(result); }
});
return () => { cancelled = true; };
```

#### flyTo on Marker Click (existing pattern)
```tsx
// Source: MapPage.tsx line 822-824 (verified in codebase)
if (dist && mapRef.current) {
  mapRef.current.flyTo({ center: [dist.longitude, dist.latitude], zoom: 5, duration: 800 });
}
```

#### scrollIntoView (Web Platform — no library needed)
```tsx
// Source: [ASSUMED — standard Web API]
element.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `motion-safe:animate-pulse` halo | `animate-ping` halo | 04-04 (D-02) | Radar ring instead of fade — more alarming |
| Route Stops at `top-4 right-14` | Route Stops at `top-14 right-14` | 04-04 (D-01) | Eliminates layout collision with toggle |
| Marker click only opens panel | Marker click opens panel + scrolls rows | 04-04 (D-03) | Full interaction loop — map to list navigation |
| No loading state on tab switch | Spinner in Network Risk tab during fetch | 04-04 (D-04) | User knows data is loading |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5 |
| Config file | `backend/pytest.ini` |
| Quick run command | `cd backend && python -m pytest tests/test_benchmark_api.py -x -q` |
| Full suite command | `cd backend && python -m pytest -x -q` |

### Phase Requirements → Test Map

All 04-04 changes are pure frontend UI polish. The four fixes have no backend surface:
no new endpoints, no schema changes, no model changes. Backend test suite (14 benchmark
API tests, passing as of commit dadffda) is unaffected.

| Behavior | Test Type | Command | Notes |
|----------|-----------|---------|-------|
| animate-ping halo visible | Visual / manual | — | Browser dev tools: verify computed animation |
| Route Stops below toggle, no overlap | Visual / manual | — | Load page with a route active |
| Click marker → rows highlight + scroll | Manual interaction | — | Click a red marker, verify panel behavior |
| Spinner shows during metric fetch | Manual + network throttle | — | DevTools → Network → Slow 3G |

**Frontend unit tests:** The project has no Vitest/Jest setup. Tests are backend-only
(pytest). [VERIFIED: no jest.config.* or vitest.config.* found in frontend/]

### Sampling Rate
- **Per task commit:** `cd backend && python -m pytest tests/test_benchmark_api.py -x -q` (confirms no backend regression)
- **Phase gate:** Manual visual verification of all 4 interactions before `/gsd-verify-work`

### Wave 0 Gaps
None — no new test files needed. Backend tests are unaffected. Frontend has no test
infrastructure to extend.

## Security Domain

> ASVS Level 1 enforced.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No auth changes |
| V3 Session Management | No | No session changes |
| V4 Access Control | No | Read-only UI changes |
| V5 Input Validation | No | No user inputs added |
| V6 Cryptography | No | No crypto |

**Security assessment:** 04-04 is UI-only. All API calls (`graphAPI.metrics()`,
`benchmarkAPI.singleSourceComponents()`) are existing calls already in the codebase with
existing auth interceptors. No new security surface is introduced.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `top-14` provides sufficient clearance between toggle and Route Stops button | Pattern 2 | Minor visual crowding — fix by changing to `top-16` |
| A2 | Multiple rows per distributor in the single-source panel is an acceptable UX tradeoff for v1 | Pattern 3 | Poor UX if many components per distributor; see Pitfall 2 mitigation |
| A3 | `element.scrollIntoView()` works inside the panel's `flex-1 overflow-y-auto` container | Pattern 3 | May not scroll if panel scroll container is not the nearest scrollable ancestor |

## Open Questions

1. **D-04 button width stability**
   - What we know: Button content changes from text to spinner+text; widths differ.
   - What's unclear: Whether the visual shift is noticeable enough to fix.
   - Recommendation: Add `min-w-[96px]` or verify in browser; if imperceptible, omit.

2. **`scrollIntoView` across nested scroll containers**
   - What we know: The side panel uses `flex-1 overflow-y-auto` for its scroll container.
   - What's unclear: Whether `scrollIntoView` will respect this or try to scroll the window.
   - Recommendation: If standard `scrollIntoView` doesn't work, use `el.scrollIntoView()` on the panel body ref directly, or use `panelBodyRef.current.scrollTop = el.offsetTop`.

## Sources

### Primary (HIGH confidence)
- `frontend/src/pages/MapPage.tsx` — full file read; all line references verified
- `frontend/src/lib/risk.ts` — verified RISK_COLORS and riskLabel exports
- `frontend/src/services/api.ts` — verified graphAPI.metrics() and benchmarkAPI.singleSourceComponents()
- `frontend/package.json` — verified tailwindcss 4.2.2, lucide-react ^1.7.0, react-map-gl ^8.1.0
- `.planning/phases/04-benchmark-dashboard/04-CONTEXT.md` — all four decisions D-01..D-04

### Secondary (MEDIUM confidence)
- `backend/tests/test_benchmark_api.py` — verified 14 tests, all benchmark API routes covered
- Git log — confirmed 04-01/02/03 implementation commits

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified in package.json; no new deps needed
- Architecture: HIGH — single file target; all patterns verified in existing codebase
- Pitfalls: MEDIUM — A2/A3 are plausible risks based on code analysis, not observed failures

**Research date:** 2026-04-21
**Valid until:** 2026-05-21 (stable UI libraries, no external dependencies)
