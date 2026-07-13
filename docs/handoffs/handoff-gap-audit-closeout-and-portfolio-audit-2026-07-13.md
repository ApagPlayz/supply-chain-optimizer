# Handoff — Gap-Audit Close-Out (7 items) + Portfolio Audit & Grade

**Date:** 2026-07-13
**Branch:** `main`
**Status:** All work is **COMPLETE and VERIFIED GREEN**, but **UNCOMMITTED** in the `main` working tree (49 changed/new files).
**Previous handoff (now superseded):** `docs/handoffs/handoff-gap-audit-features-2026-07-08.md` — everything in it was committed and merged (`dbc1d58`, `641f964`, `dae49be`, `a83ef4b`). Do not re-do it.

---

## Goal

Two things the user asked for in one session:

1. **Close out the 7 remaining open items** from `docs/GAP_AUDIT_2026-07-01.md` (the leftovers after the 2026-07-08 feature build). These were delegated to 5 parallel subagents.
2. **Audit the project's portfolio quality** — "how good is it actually?" — get an honest grade and a ranked improvement plan. This was a 6th, read-only subagent.

The user is a job seeker using this project to land interviews at consulting (McKinsey/BCG), big-tech ops (Amazon SCOT, Apple Ops), and DS/ML firms. **Honesty of claims is a hard requirement** — real data only, no fabrication, no overstated results.

---

## Done so far (concrete, with exact paths)

### The headline result: **the project was graded B−**

Full report written to **`docs/PORTFOLIO_AUDIT_2026-07-12.md`** (read this first when resuming).

| Dimension | Grade |
|---|---|
| **OVERALL** | **B−** |
| Technical depth / modeling | B− |
| Engineering quality | B+ |
| Data credibility & honesty of claims | C+ |
| Product / UX / demo-ability | B |
| Interview storytelling (45 min) | B− |

Verdict: *not* a generic LLM-built portfolio app — but the tell is **14 subsystems, each stopping at the first level of depth**. Strongest for consulting (B+/A−), weakest for Amazon SCOT / Apple Ops (C+/B−).

**MOST IMPORTANT SINGLE FINDING — the "44.7% cheaper than greedy" headline is a fixed-fee artifact.**
Greedy is the component-cost minimum *by construction* (`backend/app/optimization/greedy.py:91-117`), so the MILP can only ever win on fixed charges — and the charge is `LTL_BASE_FEE_USD = 75.0` **per supplier** (`backend/app/optimization/constants.py:18`) on toy BOMs of **4 parts / 7 units** (`backend/seeds/run_benchmark.py:113-133`). `iot_sensor_node` "saves 71.75%" to $131.77 — of which **$75 is literally the base fee**. At realistic volume the advantage collapses to ~0–2%. An interviewer finds this in ~5 minutes. **This is the single biggest liability in the project and fixing it is the biggest opportunity (see Next Steps #2).**

Other top weaknesses from the audit (all cited in the report):
- **Betweenness centrality is used as a failure probability** (`backend/app/graph/simulation.py:155-161`) → the most central distributor fails in 100% of scenarios; makes `cvar_95` degenerate (saturates at 1.15), so "spend at risk" is really an assumed 15% constant that the README calls "fully data-derived."
- **The demand forecast served is not the one backtested.** `weekly_draw = total_stock/52 × risk_multiplier` (`backend/seeds/train_forecasts.py:138-141`) — demand derived from *inventory*, one shared macro curve across all 791 parts. The backtest ran on Census `A34SNO`, a different series entirely.
- **Lead-time ML: n=75, one day, one distributor, random split on time-series data**, quoted at R²=0.93 from 15 test points. Two features are constant.
- **README contradicts the repo on five numbers** (see "Known-false claims" below).

### The 7 gap-audit items — all fixed

**(1) ACLED + FRED dormant feeds** — agent found the audit was *half wrong*:
- **FRED never needed a key.** It publishes the freight series (TSIFRGHT) via a **public keyless CSV endpoint** that this repo already uses elsewhere (`backend/app/ml/fred_client.py`). `fetch_fred_freight()` was hard-raising `ValueError("FRED_API_KEY not configured")` for no reason. **Now live, zero secrets** via `fetch_fred_freight_keyless()`.
- **ACLED was the only genuinely dormant feed** — and worse, `_safe_refresh` was logging **"Feed acled refreshed at …"** while it contributed nothing (looked healthy, was dead). Now reports an explicit **inactive** state with the reason + registration URL.
- Files: `backend/app/feeds/__init__.py` (added `CachedFeed.inactive_reason`), `backend/app/feeds/fetchers.py`, `backend/app/feeds/scheduler.py`, `backend/app/api/feeds.py` (new `inactive` status + `detail`, distinct from `unavailable`), `frontend/src/pages/Dashboard.tsx` (renders an "Inactive (no key)" badge — previously an inactive feed rendered as *no badge at all*), `.env.example`, `backend/.env.example`, `render.yaml` (keys as `sync: false`), `backend/tests/test_feeds.py` (35/35 pass).

**(2) Lead-time collector not scheduled** — now runs weekly.
- New file **`.github/workflows/collect-lead-times.yml`** — Mondays 06:00 UTC + manual dispatch; **commits the grown data panel back to the repo.**
- **Deliberately GitHub Actions, not Render cron:** Render cron is a *paid* service type (both services are free-tier, a `type: cron` block would fail the Blueprint sync), AND Render's free filesystem is ephemeral so the appended CSV panel would be wiped on every deploy and could never accumulate. A commented-out Render cron block is left in `render.yaml` for if the user ever moves to a paid plan with a persistent disk.
- The collector was smoke-tested and **really hits the DigiKey API** (creds already in `backend/.env`). The 5 real rows it appended were reverted to keep the diff code-only.

**(3) Anonymous HuggingFace seed dataset** — it's **real, but mislabelled**.
- The dataset is `mdnh/electronic-components-supply-chain` on HuggingFace — verified via the HF API. 791 components genuinely collected via the **Nexar API** (which aggregates Octopart) in 2024, **CC-BY-4.0**, published by an independent user `mdnh` (not Nexar/Octopart themselves).
- **Not synthetic — the credibility problem is framing.** The README/UI call this "Nexar/Octopart API" data, implying a live feed. It's actually a **frozen 2024 static snapshot redistributed by a third party.**
- It IS still load-bearing: `backend/seeds/seed_live.py` (a genuine live Nexar puller) exists but is **unused** — no `NEXAR_CLIENT_ID`/`NEXAR_CLIENT_SECRET` configured anywhere.
- Files: `backend/seeds/seed_db.py` (explicit `DATASET_*` provenance constants: repo, URL, license, uploader, original source, collection date, retrieval date, row count; runtime prints surface it), new **`docs/DATA_PROVENANCE.md`**.
- Incidental bug found, **NOT fixed**: `backend/manage.py::cmd_seed()` imports `run_seed` from `seeds.seed_db`, but that module only defines `seed()` → `python manage.py seed` raises `ImportError`.

**(4) MLflow champion alias not used at serve time** — was decorative, now real.
- Before: `app/main.py:lifespan` → `model_store.load("lead_time")` → `joblib.load(...)`, picking the estimator named in `metrics.joblib["best_lead_time_model"]` with a hardcoded `"gradient_boosting"` default. `mlflow.tracking` was imported **nowhere** under `app/`.
- After: new **`backend/app/ml/serving.py`**. Startup calls `load_ml_state()`, which resolves: (1) **MLflow registry** if `MLFLOW_TRACKING_URI` is set or `backend/mlruns/mlflow.db` exists → loads `models:/lead_time_predictor@champion`; else (2) **on-disk joblib** with an explicit `fallback_reason` string (honest, because Render free tier has no MLflow server). Cheap pre-check so a Render cold boot doesn't block on a socket; `MLFLOW_SERVING=off` skips the probe.
- Exposed: new **`GET /api/v1/ml/model-info`** (source, model name/version/alias/run id, URI, selection metric, artifact mtime, fallback reason). `GET /ml/lead-time` now returns `model_source` + `model_version` on every prediction.
- Also removed a **hardcoded `training_samples=8731`** in `/ml/model-comparison` → now reports `n_training_samples` recorded at fit time (`null` until next retrain, rather than a made-up number).
- Files: `backend/app/ml/serving.py` (NEW), `backend/app/ml/__init__.py`, `backend/app/ml/model_store.py`, `backend/app/main.py`, `backend/app/api/ml.py`, `backend/app/optimization/costs.py` (optimizer's ML lead-time estimator now uses the same resolved model), `backend/seeds/train_ml_models.py`, `backend/tests/test_model_serving.py` (NEW, 8 tests), `docs/MLFLOW.md`.

**(5) Chronos benchmark "implausible timings"** — **the audit was WRONG about the cause, right to be suspicious. The headline flipped.**
- **Chronos really did run.** `chronos-forecasting==2.3.0` + `torch==2.12.1` installed; model is `chronos-bolt-tiny` = 8.65M params, and Bolt is **non-autoregressive** (one forward pass for all 12 steps). Measured: warm `from_pretrained` 0.24 s, warm forward pass ≈2.5 ms. The numbers were *real*, just **unfalsifiable as published** (no hardware, no warm-up separation, weights silently pre-cached, ~2 s torch import excluded, "inference" = one wall-clock over 3 calls).
- **Three genuine defects found and fixed:** (a) `meta["series_id"]` was hardcoded `"IPG3344S"` while `_load_series()` had been repointed to Census M3 **`A34SNO`** — *the doc named a series that was never scored*; (b) the cold-start "Chronos wins" was a **strawman** — Prophet was run with `yearly_seasonality=True` on 6 monthly points; (c) hardcoded WAPE prose in a *generated* doc.
- **Corrected numbers (re-run) — BOTH headlines flip:**

| | old (published) | new (real, A34SNO) |
|---|---|---|
| Prophet WAPE | 0.048 | **0.027** |
| Chronos WAPE | 0.026 | **0.029** |
| Seasonal-naive | 0.087 | 0.044 |
| Verdict | "Chronos zero-shot WINS" | **Prophet wins** (Chronos 10.2% worse; still clears naive) |
| Cold-start (6 pts) | "Chronos 0.054 crushes Prophet 4.53" | Chronos 0.039 vs **Prophet trend-only 0.018** → **the cold-start win disappears** |

- Timing now honest: hardware noted (macOS arm64, Python 3.13.5, torch 2.12.1, 4 threads, CPU), import 2.05 s, `from_pretrained` 0.24 s (`weights_cached: true`), warm-up pass timed and discarded, **20-repeat steady-state micro-benchmark: median 2.64 ms, p95 3.80 ms.**
- Files: `backend/seeds/run_chronos_benchmark.py`, `backend/tests/test_chronos_benchmark.py` (NEW, 8 tests, run without torch), `docs/CHRONOS_BENCHMARK.md`, `docs/chronos_benchmark.json`.
- **NOTE:** `docs/GAP_AUDIT_2026-07-01.md` §1.3 ("Chronos almost certainly wasn't really run… physically implausible") is **incorrect** and should be annotated as such.

**(6) CI runs tests only — no lint/typecheck** — now gated.
- `.github/workflows/ci.yml` gained a third job **`backend-lint`**: `ruff check app` + `mypy app` on every push/PR to main. (Frontend already ran `tsc -b` inside `npm run build`.)
- New **`backend/pyproject.toml`**: ruff `select = ["E","F","I","UP","B"]`, line-length 120, with pragmatic ignores (`E501`; `UP006/UP035/UP037/UP045` legacy-typing modernization ≈640 occurrences deferred; `B008` FastAPI `Depends()` false positive; `I001` import sorting, 49 hits, deferred to avoid clobbering concurrent agent edits). Mypy non-strict (`ignore_missing_imports`), SQLAlchemy plugin on, with a `[[tool.mypy.overrides]]` block disabling ~22 modules where untyped `Column(...)` models (no `Mapped[]`) create false `Column[T]` vs `T` errors. **~50 modules are fully type-checked today.**
- New **`backend/requirements-dev.txt`** (ruff 0.15.21, mypy 2.2.0) — installed in the CI lint job only, not the prod image.
- **Real fixes made along the way:** 14 unused imports, 2 `except … raise` missing `from e`, 2 SQLAlchemy `== True` → `.is_(True)`, and a **real latent bug in `backend/app/main.py`** — `TracerProvider(active_span_processor=BatchSpanProcessor(...))` passed a single processor to a multi-processor param; fixed to `provider.add_span_processor(...)`.
- Files: `.github/workflows/ci.yml`, `README.md` (new "Lint & type-check" section), `backend/pyproject.toml` (NEW), `backend/requirements-dev.txt` (NEW), plus small safe edits in `backend/app/api/{auth,components,distributors,market_intelligence,optimize,resilience,schemas}.py`, `backend/app/core/security.py`, `backend/app/main.py`, `backend/app/models/{order,scenario}.py`.

**(7) Fiedler 0.0 fallback** — now reports the giant component honestly.
- **Root cause was NOT just disconnection.** The old code attempted λ₂ on the giant component using the **stock-weighted (`inv_stock`) Laplacian**, which fails ARPACK convergence (`ARPACK error -1: No convergence`) — *that* is why it silently fell back to 0.0. Switching to the **unweighted** Laplacian of the giant component converges in <0.1 s.
- **Real numbers (live `supply_chain.db`, 92 distributors / 791 components / 8,176 offers):**

| Metric | Value |
|---|---|
| Whole-graph λ₂ (Fiedler) | **0.0** (exact — genuinely disconnected) |
| n_connected_components | **43** |
| Giant component size | **839** of 883 nodes |
| Giant component fraction | **95.0%** |
| **Giant-component λ₂** | **0.2377** |

- API now returns BOTH, clearly labelled (`fiedler_whole_graph` + `fiedler_giant_component` + `n_connected_components` + `giant_component_size`/`fraction`) — deliberately NOT swapping one number for the other and calling it "the Fiedler value."
- Interview line: *"95% of the supplier network sits in one connected component whose own algebraic connectivity is a moderate 0.24 — not fragile, not over-concentrated — while the remaining 5% are genuinely isolated single-sourced parts, which is exactly what the single-source list is for."*
- Files: `backend/app/graph/builder.py`, `backend/app/graph/__init__.py`, `backend/app/api/graph.py`, `backend/tests/test_graph_metrics.py`, `backend/tests/test_graph_api.py`, `frontend/src/pages/MapPage.tsx` (new "Network connectivity" stat block — this value **wasn't rendered anywhere before**), `docs/RESILIENCE_INTERVIEW_GUIDE.md`.

### Bug I fixed myself (introduced by the parallel agents)

The new `backend/tests/test_model_serving.py` uses the conftest `client` fixture, which enters `TestClient(app)` as a **context manager → runs the app lifespan → populates the process-global `GraphState` (and `MLState`) from the REAL DB**. Nothing reset it. Because `resilience._graph()` (`backend/app/api/resilience.py:158`) **prefers the global over building from the test's session**, the leaked graph silently made `test_dual_sourcing_plan_endpoint` read real data → `no_regret_count` 1 → 0 → FAIL.

Verified it was genuinely new (clean `HEAD` in a throwaway worktree = 269 passed, 0 failed), then fixed it at the root: added an **autouse `restore_process_globals` fixture in `backend/tests/conftest.py`** that snapshots/restores both `app.graph` and `app.ml` globals around every test. **The suite is now order-independent, which it was not before.**

---

## Current state

- **ALL GREEN, verified after combining all 6 agents' work:**
  - `cd backend && source venv/bin/activate && python -m pytest tests/ -q -m "not slow" -p no:cacheprovider` → **291 passed, 2 skipped, 1 deselected, 0 failed** (was 269 at HEAD).
  - `ruff check app` → **All checks passed!**
  - `mypy app` → **Success: no issues found in 72 source files**
  - `cd frontend && npx tsc --noEmit` → clean; `npm run build` → compiles.
- **Nothing is mid-edit or broken. No background agents running.** The temp git worktree used for the HEAD comparison was removed and pruned.
- **NOT COMMITTED.** 49 files changed/new, all uncommitted on `main`. Full list at the bottom of this doc.
- The live Render deploy is still running the **old** (pre-this-session) code, because nothing was pushed.

### ⚠️ Known-false claims still in the repo (NOT yet fixed — this is Next Step #1)

These agents corrected their own files but flagged these, which nobody touched:

1. **`README.md:41`** — *"Walk-forward backtest: Prophet **4.8%** vs seasonal-naive **8.7%** on FRED `IPG3344S`"* → must become Prophet **2.7%** vs seasonal-naive **4.4%** on Census M3 / **`A34SNO`**. (The downstream ≈0.8-week / ≈$3.7k-per-$1M derivation changes too.)
2. **`docs/IMPACT_FRAMING.md:74`** — same dead numbers, *"Prophet WAPE = 4.8% vs seasonal-naive 8.7% (skill score +45%)"*, plus the table at ~line 90 (`Prophet | 0.048 | 0.079 | ≈0.95 wk`).
3. **`frontend/src/pages/SchedulerPage.tsx:61-66`** — tooltip still says *"backtested WAPE 4.8% vs 8.7% seasonal-naive (FRED IPG3344S, walk-forward)"*.
4. **README contradicts the repo on five more numbers:** 8,731 vs **8,176** offers; "DigiKey 40%" vs **11.2%**; "195 tests" vs **291**; "EVaR-95" vs the code's explicit **CVaR**; and the Prophet WAPE citation points at a file that no longer contains that number.
5. **README/QUICK_START/`frontend/src/pages/Dashboard.tsx`** still describe the data as a live **"Nexar/Octopart API"** feed → should say *"791 real components, static 2024 snapshot, CC-BY-4.0, redistributed via HuggingFace."*

(`docs/FORECAST_BACKTEST.md` is already correct — Prophet 0.027 vs naive 0.044, skill +39.3%.)

---

## Next steps (ordered)

1. **Decide whether to COMMIT the 49 files** (user has not answered — see Open Questions). If yes: branch off `main` per repo norms, stage, write a clear message. Note `backend/supply_chain.db` and `backend/data/ml_models/*.joblib` are intentionally force-tracked for the free-tier Render deploy — committing regenerated versions is expected.
2. **Fix the known-false claims above (~2 hrs).** The audit calls this **the best impact-per-hour item in the whole project.** The README currently makes claims the code contradicts, while the honesty lives buried in docstrings — exactly backwards.
3. **Re-run the benchmark at realistic BOM scale and publish the savings-vs-volume curve (~1 day).** This is the **highest-leverage item.** It converts the biggest liability into the best story: *"I didn't believe my own 44.7%, decomposed it, and the entire win was the $75 supplier fixed fee. Here is the volume crossover where MILP consolidation actually pays."* That lands at Amazon and McKinsey simultaneously.
4. **Ground disruption probabilities in a cited base rate** instead of betweenness-as-probability, and **surface the tornado chart** — `compute_tornado` already exists in `backend/app/optimization/recommendations.py` and is currently **unused** (~1 day).
5. **Stop quoting R²=0.93 on n=75** — replace with an explicit "my sample is too small to claim this" caveat (~4 hrs). The audit notes this scores *higher* with interviewers than any R² would.
6. **THE "EXCEPTIONAL" ITEM (2–4 days, pick this if you want a step-change):** a **two-stage stochastic program with a CVaR objective**. You already own the scenario generator and the MILP. Sample-average approximation + Rockafellar–Uryasev linearization, sweep λ, and **plot the cost-vs-CVaR efficient frontier.** Replaces "I added a 15% surcharge" with *"here is the price of resilience, and the knee of the curve is my recommendation."*
7. **Missing entirely** (from the audit): a 2-page case study that ends in an actual *recommendation*; dollar figures at business scale (everything today is in the **hundreds** of dollars); a "What this model can't do" section.
8. Smaller leftovers: fix `backend/manage.py::cmd_seed()`'s `ImportError` (`run_seed` → `seed`); annotate `docs/GAP_AUDIT_2026-07-01.md` §1.3 as incorrect; deferred lint debt (repo-wide `UP006` typing sweep, `I001` import sorting, SQLAlchemy `Mapped[]` migration) — all listed in `backend/pyproject.toml` comments + README.

---

## Key files & context

- **READ FIRST on resume:** `docs/PORTFOLIO_AUDIT_2026-07-12.md` — the grade + ranked improvement plan. This is the strategic spine of everything above.
- Other docs: `docs/GAP_AUDIT_2026-07-01.md` (the source audit; §1.3 is wrong), `docs/DATA_PROVENANCE.md` (NEW), `docs/RESILIENCE_INTERVIEW_GUIDE.md`, `docs/CHRONOS_BENCHMARK.md`, `docs/MLFLOW.md`, `docs/ROUTE_A_BUILD_PLAN.md`.
- **Backend venv:** `backend/venv` — activate before pytest/ruff/mypy/seeds.
- **Commands:**
  - Tests: `cd backend && source venv/bin/activate && python -m pytest tests/ -q -m "not slow" -p no:cacheprovider`
  - Lint/type: `cd backend && source venv/bin/activate && ruff check app && mypy app`
  - Frontend: `cd frontend && npx tsc --noEmit && npm run build`
  - Benchmark: `cd backend && source venv/bin/activate && python -m seeds.run_benchmark` (~1 min, appends a new run_id)
  - Deploy: `./launch` (per the `launch` skill — **never** show the user localhost; deploy to Render and share the live URL)
- **Gotchas:**
  - OR-Tools CP-SAT hangs at 0% CPU under bare `python` on macOS unless `num_search_workers=1` (already set in `backend/app/optimization/sourcing.py`).
  - The tail metric is `cvar_95` / `mc_cvar_95` everywhere — **do NOT reintroduce `evar`.**
  - `optimization_runs` is `create_all`-managed, not created by any migration; migrations 0004/0005 are defensive.
  - `audio_dsp_board` BOM is MILP-infeasible under its stock/MOQ and is skipped by the benchmark (9 of 10 BOMs run) — expected, not a bug.
  - **Process globals (`GraphState`, `MLState`) leak across tests** if the app lifespan runs — now guarded by the autouse `restore_process_globals` fixture in `backend/tests/conftest.py`. Don't remove it.
  - Running several file-editing agents on one working tree is a live hazard — one agent ran `git stash`/`reset` mid-session and briefly wiped everyone's uncommitted work. Prefer worktree isolation, or verify the combined diff before committing.

---

## Open questions / decisions pending (waiting on the user)

1. **COMMIT?** 49 files are uncommitted on `main`. The user was asked and has not yet answered. (Recommend: commit — the work is verified green and it's a lot to lose.)
2. **Which improvement track to take next:** the cheap credibility fixes (Next Steps #2–#5) or go straight for the **CVaR efficient frontier** (#6)? The audit's recommendation is to do #2 and #3 first (they're cheap and #3 is the best story), then #6.
3. **USER'S OWN ACTION ITEMS (nobody but the user can do these):**
   - **ACLED** — register free at **https://acleddata.com/register/** (key emailed instantly), then paste `ACLED_EMAIL` + `ACLED_KEY` into **Render → supply-chain-api → Environment**. This is the last genuinely dormant feed.
   - **DigiKey** — copy the creds *already in the local `backend/.env`* into **GitHub → Settings → Secrets and variables → Actions** as `DIGIKEY_CLIENT_ID` / `DIGIKEY_CLIENT_SECRET`. Without these the new weekly workflow runs green but collects nothing.
   - *Optional:* `FRED_API_KEY` (https://fredaccount.stlouisfed.org/apikey) — only upgrades to the authenticated API; **the feed is already live without it**. `MOUSER_API_KEY` (https://www.mouser.com/api-hub/) would add a second independent lead-time source; it isn't configured at all today.

---

## Full uncommitted file list (2026-07-13, `main`)

**Modified (41):**
`.env.example`, `.github/workflows/ci.yml`, `README.md`, `backend/.env.example`,
`backend/app/api/{auth,components,distributors,feeds,graph,market_intelligence,ml,optimize,resilience,schemas}.py`,
`backend/app/core/security.py`, `backend/app/feeds/{__init__,fetchers,scheduler}.py`,
`backend/app/graph/{__init__,builder}.py`, `backend/app/main.py`,
`backend/app/ml/{__init__,model_store}.py`, `backend/app/models/{order,scenario}.py`,
`backend/app/optimization/costs.py`, `backend/seeds/data/a34sno_monthly.csv`,
`backend/seeds/{run_chronos_benchmark,seed_db,train_ml_models}.py`,
`backend/tests/{conftest,test_feeds,test_graph_api,test_graph_metrics}.py`,
`docs/{CHRONOS_BENCHMARK.md,MLFLOW.md,RESILIENCE_INTERVIEW_GUIDE.md,chronos_benchmark.json}`,
`frontend/src/pages/{Dashboard,MapPage}.tsx`, `render.yaml`

**New / untracked (8):**
`.github/workflows/collect-lead-times.yml`, `backend/app/ml/serving.py`, `backend/pyproject.toml`,
`backend/requirements-dev.txt`, `backend/tests/test_chronos_benchmark.py`,
`backend/tests/test_model_serving.py`, `docs/DATA_PROVENANCE.md`, `docs/PORTFOLIO_AUDIT_2026-07-12.md`
