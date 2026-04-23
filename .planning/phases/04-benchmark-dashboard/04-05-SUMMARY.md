---
plan: 04-05
phase: 04-benchmark-dashboard
status: complete
gap_closure: true
started: 2026-04-23
completed: 2026-04-23
---

## What Was Built

Closed the single remaining build blocker for Phase 04: a TypeScript TS2322 error on `BenchmarkPage.tsx:514` that prevented `npm run build` from succeeding.

**The change — one line, surgical:**

| | Code |
|---|---|
| Before | `formatter={(value: number) => [value.toFixed(4), 'λ₂']}` |
| After | `formatter={(value) => [typeof value === 'number' ? value.toFixed(4) : '—', 'λ₂']}` |

## Root Cause

recharts' `Tooltip` `formatter` prop is typed as `Formatter<ValueType, NameType>` where `ValueType = number | string | Array<number | string>`. The callback receives `value: ValueType | undefined`. Annotating the parameter as `: number` narrows the input type incompatibly — TypeScript raises TS2322 "Type '(value: number) => [string, string]' is not assignable to type 'Formatter<ValueType, NameType>'".

## Why the `typeof` Guard (Not a Cast)

Removing the annotation lets TypeScript infer the recharts-compatible signature. The `typeof value === 'number'` guard preserves the current runtime behaviour (chart data points are always numbers) while satisfying the type checker's requirement that `undefined | string | (number|string)[]` cases are handled. This is idiomatic TypeScript — no `@ts-ignore`, no `as Formatter`, no `as unknown`, no escape hatches.

## Build Transition

| Check | Before | After |
|---|---|---|
| `cd frontend && npx tsc -b` | exit 2 (TS2322) | exit 0 ✓ |
| `cd frontend && npm run build` | fails (tsc -b error) | exit 0, dist/ produced ✓ |

## Regression Verification

- **Plan 04-04 artifacts on MapPage.tsx:** `animate-ping`, `ring-1 ring-red-400`, `Risk data unavailable — reload to retry` — all three grep passes confirmed, MapPage.tsx untouched.
- **Backend pytest:** `tests/test_benchmark_api.py` — 14 passed, 0 failed.
- **File length:** 594 lines before and after (no blank lines added/removed).
- **No escape hatches:** `@ts-ignore`, `@ts-expect-error`, `as Formatter` counts all 0.

## Key Files

### Modified
- `frontend/src/pages/BenchmarkPage.tsx` — line 514 only (1 line changed)

## Self-Check: PASSED
