---
status: partial
phase: 04-benchmark-dashboard
source: [04-VERIFICATION.md]
started: 2026-04-23T00:00:00Z
updated: 2026-04-23T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Route Stops layout (D-01)
expected: With any route selected and Routes tab active, the Route Stops button sits visually below the toggle pill, not behind or overlapping it
result: [pending]

### 2. animate-ping halo visible on sole-source distributor markers (D-02)
expected: On MapPage → Network Risk tab, sole-source distributor markers display a pulsing animate-ping halo animation
result: [pending]

### 3. Marker click opens panel + scrolls row (D-03)
expected: Clicking a map marker opens the side panel and scrolls the corresponding table row into view, highlighting it
result: [pending]

### 4. Panel close clears highlight (D-03)
expected: Closing the side panel clears the row highlight state
result: [pending]

### 5. Loading spinner in Network Risk tab button (D-04)
expected: With Slow 3G throttling in DevTools, the Network Risk tab button shows a loading spinner while fetching graph metrics
result: [pending]

### 6. Error copy in Network Risk panel header (D-04)
expected: With /graph/metrics blocked in DevTools, the panel shows "Risk data unavailable — reload to retry"
result: [pending]

## Summary

total: 6
passed: 0
issues: 0
pending: 6
skipped: 0
blocked: 0

## Gaps
