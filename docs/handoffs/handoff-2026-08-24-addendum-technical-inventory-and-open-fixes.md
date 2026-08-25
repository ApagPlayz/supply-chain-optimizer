# Addendum — Technical Inventory & Open Fixes (2026-08-24, late)

**Read with** `handoff-2026-08-24-remaining-work-after-release.md` (the main remaining-work list).
This adds findings from two deep read-only code inventories run after the release, and records
six fixes that were IDENTIFIED BUT NOT APPLIED because macOS revoked file-read access mid-session.

## Session-ending environment failure (context for why nothing below is done)

macOS TCC revoked Terminal's read access to `~/Documents` mid-session: all reads returned
`Operation not permitted` while WRITES still worked. Four fix-agents were launched and then
stopped, having applied NOTHING — the working tree is exactly as it was after build `9722b93`.
Fix: System Settings → Privacy & Security → Files and Folders → Terminal → enable Documents
Folder (or Full Disk Access), then FULLY QUIT Terminal (Cmd-Q) and reopen.

## State: nothing lost

All work through build `9722b93` is committed, pushed, and live (verified: UI + API on
`9722b93`, verify_backend 42/42, CI + Model CI + gated deploy green). Only uncommitted files are
this addendum, the main remaining-work handoff, and `.claude/agent-memory/**` (never commit).

## OPEN FIX 1 — doc overclaims an OR interviewer catches in seconds (~1h)

1. **"Lagrangian relaxation of the Capacitated Facility Location Problem (Daskin 2013 Ch.4)"** —
   claimed at `backend/app/optimization/cross_dock.py:11` and `docs/OPTIMIZATION_DESIGN.md §3.4`.
   FALSE: no multipliers, no relaxation, **no capacity constraints**. It is exhaustive enumeration
   of 10 hardcoded freight hubs, argmin of a weighted objective, ≥5% acceptance threshold. The
   honest version is still respectable (exact because the candidate set is tiny).
2. **"Asymmetric TSP"** (`docs/OPTIMIZATION_DESIGN.md §3.3`) — the matrix is haversine, therefore
   symmetric by construction. Also `/optimize/vrp` is a **single-vehicle uncapacitated TSP** (one
   vehicle, no capacity dimension, no time windows) — do NOT rename the endpoint, note it as
   historical in the doc.
3. **Tri-objective MILP claim** (`§3.2`: `w_cost·F_cost + w_time·F_time + w_carbon·F_carbon`) —
   the code minimizes **cost only** (`strategies.py` admits this in-source). Time/carbon enter only
   via `us_only`, `transport_penalty_scale`, `consolidation_bonus_usd`. Keep the good story that
   these proxies were measured and re-tuned in Aug 2026 after "Fastest Delivery" produced the
   LONGEST tour of the four strategies.
4. **`GET /ml/lead-time` docstring lies** (`backend/app/api/ml.py` ~615): says "This is the normal
   call, and the one the UI makes." No frontend code calls it — `mlAPI.leadTime` is declared in
   `frontend/src/services/api.ts:611` and never invoked.

## OPEN FIX 2 — two live bugs undercutting the project's best story (~1h)

1. **`backend/app/optimization/recommendations.py:238,264`** — `p_fail = min(betweenness * stress_factor, 1.0)`
   reads raw centrality AS a probability: no base rate, no exposure window, no units. This is the
   exact pathology already fixed in `graph/builder.py` and `graph/simulation.py` (where it made the
   top distributor fail in 100% of scenarios and returned zero impact for 91 of 92 distributors).
   It feeds the LIVE `POST /resilience/dual-sourcing-plan` (called from `ResiliencePage.tsx:397`)
   and publishes `p_fail_current`/`p_fail_second` as if calibrated.
   FIX: route through `build_failure_probabilities()` in `backend/app/optimization/stochastic.py:289`
   (McKinsey base rate → constant-hazard → PO window; centrality only as a BOUNDED RANK TRANSFORM
   `p_base · spread^(2u−1)` capped at 0.5). Do not invent a new calibration.
2. **`backend/app/api/optimize.py:110-125`** builds every `Offer` without `distributor_country`, so
   the dataclass default `"US"` applies to all 92 distributors including ~40 in Shenzhen — every
   ACLED conflict lookup asks about the United States. (ACLED is currently key-gated/inactive, so
   the fix may be latent rather than observable — verify and say which.)

## OPEN QUESTION — contested, must be resolved (30 min)

Two inventory agents DISAGREED on whether the macro stress regime model's ship gate is currently
ON. One: gate PASSES on Brier (0.3926 vs persistence 0.5388), so `current_stress_prob` (0.8284)
feeds `_stockout_risk_premium_cents` in `sourcing.py`. The other: gate is OFF because it loses to
persistence, so `macro_stress = 0.0` and that risk premium is **silently inert**. Resolve from code
+ `metrics.joblib` + `curl https://supply-chain-api-qy8x.onrender.com/api/v1/ml/stress`. This is the
difference between "my optimizer prices macro risk" and "that path is dead code" — know it before
an interview.

## OPEN FIX 3 — stale ML numbers describe an undeployed model (~2h)

Committed `metrics.joblib` (retrained `cf00e43`, 2026-08-24) says: **gradient_boosting**, 1,879
training / 1,922 panel rows, 472 families, 28 manufacturers, leakage R² **+0.8084 → +0.1169 →
−0.3895**, RMSE reduction **4.719 d CI [2.613, 7.222]**, 18/20 folds.
Still stale: `docs/MODEL_CI.md` (~94, ~191), `docs/LEAKAGE_PROGRESSION.md`,
`docs/leakage_progression.json`, `docs/PROJECT_OVERVIEW.md` (~69-71), `docs/ML_API_PUSH_PLAN.md`
(~30) — all carry the OLD run (random_forest, 810 rows, 467 families, 27 mfrs, +0.638 → +0.082 →
−0.550, 6.72 d CI [3.57, 10.26], 16/20).
**`backend/tests/test_docs_match_artifacts.py` cannot catch this** — it compares MODEL_CI.md to
leakage_progression.json and both are stale together. Regenerate via
`cd backend && python -m seeds.run_leakage_progression`, sync the docs, and ADD A GATE comparing
the leakage artifact's model name / row count / manufacturer count to `metrics.joblib` provenance.
(If a `model_ci`-marked test is added, update the gate-census meta-test.)

## OPEN FIX 4 — repo presentation (~1h, no code)

- **No LICENSE file** though README claims MIT. Note bundled data is HuggingFace CC-BY-4.0.
- **GitHub description / homepage / topics all blank** (`gh repo edit ApagPlayz/supply-chain-optimizer`).
- **`docs/README.md` index** — 37 docs, no reading path. Curate top 5 (PROJECT_OVERVIEW, MODEL_CI,
  CVAR_EFFICIENT_FRONTIER, DATA_PROVENANCE, RESEARCH_TECHNIQUES); mark handoffs/, loop-brief,
  AUTONOMOUS-LOOP, ML_API_PUSH_PLAN, DASHBOARD-CONTRACT, FRONTEND_VERIFICATION, SCENARIO_API,
  history/ as internal working notes. **Do not `git mv` while other agents edit docs.**

## Technical inventory — what to claim, what NOT to claim

**CLAIM (verified in code):** two-stage stochastic MILP with integer recourse; SAA + exact 2^n
support enumeration; Rockafellar-Uryasev CVaR linearization applied to RECOURSE cost (documented
60s-timeout → sub-second speedup); λ-frontier with descending-order warm starts; Kneedle knee
detection; Mak-Morton-Wood optimality-gap CI; VSS; per-point MIP-gap convergence filtering (387
solves, 57 excluded and disclosed); adaptive scenario budget backed by a measured table;
probability calibration anchoring level on a cited base rate with centrality as a bounded rank
transform. Fixed-charge freight network in CP-SAT with cited tariffs; OR-Tools TSP; NetworkX
betweenness/PageRank/k-core/Fiedler curves; 1,000-scenario percolation Monte Carlo → CVaR-95.
ML: grouped CV with measured leakage progression; 219-fold walk-forward; hyperparameters frozen on
a calibration window; Friedman/Nemenyi, Diebold-Mariano, Clark-West, paired bootstrap (5,000),
exact McNemar; hand-implemented CRPS / pinball / Brier / calibration-ECE and Croston/SBA/TSB;
ALFRED vintage-pinned real-time backtests; ~40 model-CI gates incl. a shuffled-label NEGATIVE
CONTROL; train/serve schema contracts that fail closed; provenance with data SHA-256 + staleness.
Data: quota-aware resumable idempotent weekly DigiKey collector (a real moat).

**DO NOT CLAIM:** VRP (it's a TSP), Lagrangian relaxation / CFLP, articulation points, EVPI,
Bertsimas-Sim, newsvendor / decision-focused learning, conformal prediction, mixed-effects,
statsmodels (not installed), drift monitoring, production MLflow (dev-only; prod is always
`local_joblib`), a data warehouse / dbt / Airflow, production Postgres (it's SQLite), or a live
Nexar catalogue feed (static 2024 HuggingFace snapshot).

**Best interview result in the repo:** 32% of the α=0.95 tail is ONE distributor going dark — and
that distributor has one of the LOWEST failure probabilities (2.25%), while the highest-probability
one (13.04%) contributes 4.8%. Concentration drives the tail, not probability — a direct empirical
refutation of centrality-proportional surcharging, which is what this codebase used to do.

**Honest limits to state before being asked:** the statistical machinery all runs OFFLINE (the API
reads persisted artifacts — say "rigorously validated offline pipeline with contract-gated
serving," not "ML platform"); effective n is **28 manufacturers**, not 1,879 rows; lead-time skill
is real but small (4.7 d on ~57 d RMSE); the regime model TIES persistence on accuracy and ships on
Brier; the stochastic program is proven only on small-pool BOMs (≤~6 suppliers — a 55-supplier
instance returns UNKNOWN); network is 92×791, demo scale. Also dead/unreachable: `POST
/graph/simulate`, `GET /ml/lead-time`, all `/market/*`, and `graph_aware`/`us_only` are never sent
by the UI so the MILP's graph surcharge never runs in the live checkout path.

## Ordered next steps

1. Restore file access (see top), reopen Terminal, resume from the main remaining-work handoff.
2. Apply OPEN FIX 1 + 2 + resolve the OPEN QUESTION (~2.5h) — these are pure downside protection.
3. Apply OPEN FIX 3 (stale numbers) and OPEN FIX 4 (LICENSE/metadata/index).
4. Full verification battery → commit → `./launch --anyway` (push → CI ~12 min → gated deploy).
5. Live frontend click-through incl. the never-rendered `/frontier` page, the new 404, BEST badges;
   owner cold-start Demo Login test in their own browser after 15+ min idle.
6. Decide the Resilience page (gap 70) and the AUTHORSHIP question — both still open with the owner.
