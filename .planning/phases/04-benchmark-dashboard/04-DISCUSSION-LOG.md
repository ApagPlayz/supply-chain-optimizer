# Phase 4: Benchmark Dashboard - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-21
**Phase:** 04-benchmark-dashboard
**Areas discussed:** Toggle position conflict, Halo animation style, Marker click behavior, Loading states

---

## Toggle Position Conflict

| Option | Description | Selected |
|--------|-------------|----------|
| Move Route Stops below toggle | Keep toggle at top-4 right-14, move Route Stops to top-14 right-14 | ✓ |
| Hide Route Stops in Network Risk view | Only show Route Stops when mapView === 'routes' | |
| Move toggle to left side | Put Routes/Network Risk toggle at top-4 left-4 above legend | |

**User's choice:** Move Route Stops below toggle
**Notes:** Both elements were at `top-4 right-14`, overlapping when a route is selected in Routes view. Stacking vertically preserves both — toggle is persistent, Route Stops is contextual.

---

## Halo Animation Style

| Option | Description | Selected |
|--------|-------------|----------|
| Ping / radar ring | animate-ping — growing outward sonar ring effect | ✓ |
| Pulse / fade (current) | animate-pulse — ring fades in and out in place | |

**User's choice:** Ping / radar ring (`animate-ping`)
**Notes:** More visually alarming, distinct from generic pulse. Standard Tailwind live-alert pattern.

---

## Marker Click Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Open panel + scroll to component | Open side panel AND scroll/highlight matching rows | ✓ |
| Open panel only (current) | Just open the side panel | |
| Fly to marker + open panel | Camera flyTo then open panel | |

**User's choice:** Open panel + scroll to component

| Highlight style | Description | Selected |
|----------------|-------------|----------|
| Ring highlight + auto-scroll | ring-1 ring-red-400 + scrollIntoView | ✓ |
| Background flash then fade | bg-red-900/40 flash animation | |
| You decide | Claude picks style | |

**User's choice:** Ring highlight + auto-scroll (`ring-1 ring-red-400` + `scrollIntoView`)

---

## Loading States

| Option | Description | Selected |
|--------|-------------|----------|
| Spinner on toggle button | Small spinner inside Network Risk tab while fetching | ✓ |
| Nothing / silent (current) | Markers appear small until data arrives | |
| Skeleton panel | Side panel shows skeleton rows while loading | |

**User's choice:** Spinner overlay on the toggle button
**Notes:** Minimal, non-blocking. Disappears once graphAPI.metrics() resolves.

---

## Claude's Discretion

- Spinner visual implementation (Lucide Loader2, inline SVG, or CSS spinner)
- Exact vertical offset for Route Stops button (top-14 vs top-16)

## Deferred Ideas

None.
