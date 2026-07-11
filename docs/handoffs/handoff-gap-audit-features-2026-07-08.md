# Handoff — Gap-Audit Feature Build (benchmark, recommendation engine, graph-aware resilience)

**Date:** 2026-07-08
**Branch:** `main` (all work uncommitted in the working tree — user has NOT been asked to commit yet)

---

## Goal

Close the substantive findings from the 2026-07-01 gap audit (`docs/GAP_AUDIT_2026-07-01.md`)
that make the project genuinely impressive to consulting/ops + ML/DS interviewers.
This session did two phases:

1. **Quick-win credibility pass** (DONE): fix fabrications/mislabels the audit flagged.
2. **Three substantive features** (DONE): the optimizer-vs-greedy dollar benchmark, a
   recommendation engine, and making "graph-aware" sourcing genuinely change decisions.

Everything below is **built, tested (269 backend tests pass), and documented**. The only
outstanding thing is a user decision on whether to **commit** and optionally eyeball the UI.

---

## Done so far (concrete changes, exact paths)

### Phase 1 — Quick-win credibility fixes
- **Fixed `fulfillment_rates.sort()` tail-pairing bug** in `backend/app/graph/simulation.py`
  (was mutating the list in place before pairing with `cost_inflations`; now uses a separate
  `sorted_rates` copy for percentiles).
- **Renamed EVaR → CVaR everywhere** (the metric is Conditional VaR / Expected Shortfall, not
  Entropic VaR). Touched: `simulation.py` (`cvar_95` field), `app/api/graph.py`,
  `app/api/benchmark.py`, `app/api/resilience.py`, `app/models/optimization_run.py`
  (DB column `mc_evar_95` → `mc_cvar_95`), `seeds/run_benchmark.py`, several tests, and
  frontend `BenchmarkPage.tsx` / `ResiliencePage.tsx` / `services/api.ts` / docs.
  - Added migration `backend/migrations/versions/0004_rename_evar_to_cvar.py` (defensive,
    `create_all`-managed table) and **altered the committed `backend/supply_chain.db`** column
    directly; stamped `alembic_version` to `0004`.
  - Also relabeled the "SIR cascade" docstrings in `simulation.py` as honest single-round
    percolation (no propagation/recovery).
- **Removed hardcoded `21 days / +5%` fake supplier numbers** in
  `frontend/src/pages/ResiliencePage.tsx`. Backend now returns REAL geography-derived lead
  times: added `_real_alt_suppliers()` + `alternative_suppliers` field to the three resilience
  endpoints in `backend/app/api/resilience.py`; `BOMImpactTable.tsx` made `cost_delta_pct`
  optional (dropped the fabricated cost column).
- **Rewrote `docs/RESILIENCE_INTERVIEW_GUIDE.md`** to numbers reproduced from a real run
  (Fiedler ≈ 0.0 / 43 graph components; DigiKey 11.2% of offers, not 40%; DigiKey-failure = 0
  orphans / ~0% cost; etc.).

### Phase 2 — Three substantive features

**(A) Optimizer-vs-greedy benchmark** — `backend/app/optimization/greedy.py` (NEW):
`solve_sourcing_greedy` (naive cheapest-per-line), `solve_sourcing_greedy_add`
(consolidation-aware ADD heuristic), `landed_cost_breakdown` (scores any plan with the
MILP's exact cost fn). `backend/app/optimization/sourcing.py` got a shared
`_transport_cost_by_did()` helper so greedy + MILP price transport identically (anti-rigging).
`backend/seeds/run_benchmark.py` rewritten to run arms `{greedy, greedy_add, milp_blind,
milp_graph}` × scenarios `{nominal, stress, targeted}` and write two tables. `app/api/benchmark.py`
now partitions by `arm` with `savings_pct/usd_per_bom/usd_annualized` (+ `ANNUAL_REORDERS=12`)
and a `resilience` section. **Result: MILP is 44.7% cheaper than naive greedy, 33.9% vs ADD,
via order consolidation (~$75/supplier fixed charge).**

**(B) Recommendation engine** — `backend/app/optimization/recommendations.py` (NEW):
`compute_criticality_sweep`, `compute_dual_sourcing_plan`, `compute_tornado`. Three cached
endpoints appended to `backend/app/api/resilience.py`: `POST /resilience/criticality-sweep`,
`/dual-sourcing-plan`, `/sensitivity`. Frontend: new 4th "Recommendations" tab in
`ResiliencePage.tsx` + `frontend/src/components/CriticalitySweepTable.tsx`,
`DualSourcingTable.tsx`, `TornadoChart.tsx` (NEW), types/methods added to `services/api.ts`.
**Real data: most-critical distributor = Component Stockers USA (5 orphans, ~$500 at risk);
dual-sourcing split = 14 no-regret / 10 hedge / 14 supplier-development of 38 single-source.**

**(C) Graph-aware resilient sourcing (dual-sourcing constraint)** —
`backend/app/optimization/sourcing.py`: `solve_sourcing(...)` got `require_dual_source=False`;
`_graph_surcharge_cents` re-derived as expected-disruption-loss (Snyder–Daskin, added
`EMERGENCY_REPROCURE_PREMIUM=0.15`); model build refactored into a nested `_build_and_solve(cap)`;
added a per-distributor line-count cap (`≤⌈n/2⌉`) with escalation. **It only fires when the
blind plan is single-hub** (solves blind first, checks distinct-distributor count == 1) — so
already-diversified BOMs are NOT reshuffled (this fixed a `medical_monitoring_device`
regression). Also set `solver.parameters.num_search_workers = 1` (reproducibility + avoids a
macOS OR-Tools multi-worker deadlock under bare `python`). `backend/app/optimization/solve.py`:
`optimize_bom(...)` passes `require_dual_source` through; `run_benchmark.py` milp-graph arm now
uses `graph_aware=True, require_dual_source=True`.
**Result (run_id=4): 5 single-hub BOMs diversify 1→2 suppliers, targeted-outage cascade risk
drops from 1.0 (smart_meter 1.00→0.00, pcb 1.00→0.25, iot 1.00→0.50, robotics 1.00→0.50,
industrial 1.00→0.75) for a 5.6–84.5% premium; the 4 already-diversified BOMs unchanged, +0%.**
Interview guide's graph-aware section rewritten to this real result with honest caveats.

### DB migrations / schema
- `backend/migrations/versions/0005_benchmark_and_plan_risk_columns.py` (NEW) adds columns
  `scenario, plan_cascade_risk, arm, n_distinct_suppliers, n_orders` to `optimization_runs`.
  Applied to committed `supply_chain.db`; `alembic_version` stamped `0005`.

---

## Current state

- **Working:** full backend suite **269 passed, 2 skipped** (`cd backend && source venv/bin/activate
  && python -m pytest tests/ -q -m "not slow" -p no:cacheprovider`). Frontend `npx tsc --noEmit`
  = 0 errors and `npm run build` compiles.
- **Benchmark DB:** `optimization_runs` has run_ids 1 (old, 18 rows), 2/3/4 (72 rows each). **run_id=4
  is the latest and canonical** (dual-sourcing enabled). `.planning/BENCHMARK-RESULTS.md` regenerated.
- **Nothing is mid-edit or broken.** No background agents running.
- **NOT committed.** Everything is uncommitted in the `main` working tree (see git status below).
- **Not yet done:** no live click-through of the new Recommendations tab / Benchmark page in a
  running app (type-check + build pass, but not visually eyeballed).

---

## Next steps (ordered)

1. **Ask the user whether to commit.** If yes: branch off `main` first (per repo norms), stage the
   new + modified files, write a clear message. NOTE: `backend/supply_chain.db` (10.6MB) and
   `backend/data/ml_models/*.joblib` are force-included git blobs — they're intentionally tracked
   for free-tier Render deploy (see audit item 2.1). Committing regenerated DB is expected here.
2. **Optional: visual QA.** Run backend (`cd backend && source venv/bin/activate && python -m
   uvicorn app.main:app --reload`) + frontend (`cd frontend && npm run dev`), open the Resilience
   page → "Recommendations" tab (criticality sweep + dual-sourcing + tornado) and the Benchmark
   page (should now show a MATERIAL resilience section from run_id=4, not the honest-null fallback).
3. **Remaining gap-audit items still OPEN** (from `docs/GAP_AUDIT_2026-07-01.md`, not tackled this
   session — lower priority): dormant ACLED+FRED feeds (keys absent from `.env`/`render.yaml`);
   anonymous HuggingFace seed dataset in `seeds/seed_db.py`; MLflow champion alias not used at serve
   time; lead-time collector not scheduled; CI runs tests only (no ruff/mypy); Chronos benchmark has
   implausible timings; Fiedler 0.0 fallback could report real λ₂ of largest component.
4. **Optional feature polish:** BenchmarkPage lacks a per-BOM greedy/MILP ledger (only aggregates);
   the fuller ledger is in `.planning/BENCHMARK-RESULTS.md`. Add a `bom_savings: List[...]` field to
   `/benchmark/summary` if a per-BOM table in the UI is wanted.

---

## Key files & context

- **Guide (the deliverable):** `docs/RESILIENCE_INTERVIEW_GUIDE.md` — fully rewritten, has the
  benchmark 44.7% headline, recommendation-engine section, and the graph-aware resilience table.
- **Audit + plan:** `docs/GAP_AUDIT_2026-07-01.md`, `docs/ROUTE_A_BUILD_PLAN.md`.
- **Backend venv:** `backend/venv` (activate before pytest / running seeds).
- **Regenerate benchmark:** `cd backend && source venv/bin/activate && python -m seeds.run_benchmark`
  (single-worker now, completes in ~1 min; appends a new run_id).
- **Gotchas:**
  - OR-Tools CP-SAT hangs at 0% CPU under bare `python` on macOS unless
    `num_search_workers=1` (already set in `sourcing.py:~515`).
  - `optimization_runs` is `create_all`-managed, NOT created by any migration — migrations 0004/0005
    are defensive (`_has_column` guards) so a from-scratch `alembic upgrade` won't fail on the missing
    table; the committed DB was altered directly + stamped.
  - The tail metric is `cvar_95` / `mc_cvar_95` everywhere now — do NOT reintroduce `evar`.
  - `audio_dsp_board` BOM is MILP-infeasible under its stock/MOQ and is skipped by the benchmark
    (9 of 10 BOMs run) — expected, not a bug.
- **Design decisions locked this session:** two-baseline benchmark (naive + ADD); graph-aware
  Phase-1 (surcharge + hard dual-sourcing cap) NOT the full CVaR-MILP; dual-sourcing fires only on
  single-hub BOMs; report all resilience results honestly (dual-sourcing hedges idiosyncratic
  single-node failure, not correlated stress).

### Git status snapshot (2026-07-08, all uncommitted on `main`)
Modified (key): `backend/app/api/{benchmark,graph,resilience}.py`, `backend/app/graph/simulation.py`,
`backend/app/models/optimization_run.py`, `backend/app/optimization/{solve,sourcing}.py`,
`backend/seeds/run_benchmark.py`, `backend/supply_chain.db`, several `backend/tests/*`, docs,
`frontend/src/pages/{BenchmarkPage,ResiliencePage}.tsx`, `frontend/src/services/api.ts`,
`frontend/src/components/BOMImpactTable.tsx`.
Untracked (new, key): `backend/app/optimization/{greedy,recommendations}.py`,
`backend/migrations/versions/0004_*.py` + `0005_*.py`, `backend/tests/{test_greedy,test_recommendations}.py`,
`frontend/src/components/{CriticalitySweepTable,DualSourcingTable,TornadoChart}.tsx`,
`.planning/BENCHMARK-RESULTS.md`.
(Note: many other `??`/`M` entries — mouser_client, intermittent.py, lead_time_*, seeds/data/*,
GAP_AUDIT/ROUTE_A docs — predate this session, from earlier Route-A ML work.)

---

## Open questions / decisions pending (waiting on user)

1. **Commit?** Nothing committed yet — user must say whether/how to commit (and whether to branch).
2. **Visual QA?** Whether the user wants to eyeball the new Recommendations tab + Benchmark page.
3. **Which remaining gap-audit items (step 3 above) to tackle next, if any** — all lower priority
   than the three features just completed.
