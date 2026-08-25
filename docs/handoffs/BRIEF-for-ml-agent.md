# BRIEF — For the dedicated AI/ML agent (hand this file over)

**You are picking up the ML/data-science workstream of a supply-chain optimization portfolio
project.** The owner is applying to AI/ML-in-operations/logistics roles NOW. Two priorities, in
order: (1) the **techniques must be genuinely impressive and resume-defensible**, (2) **it must
actually work**. Modest effect sizes are FINE — a 3% improvement honestly measured beats a 40%
improvement that doesn't survive scrutiny. Overclaiming is the one unforgivable failure here.

**Repo:** `/Users/alessiopagliarulo/Documents/Claude Projects/Logisitics Project`
**Live:** UI https://supply-chain-ui-bhwz.onrender.com · API https://supply-chain-api-qy8x.onrender.com
**Read first:** `LEARNINGS.md`, `docs/MODEL_CI.md`, `docs/RESEARCH_TECHNIQUES.md`,
`handoff-2026-08-24-addendum-technical-inventory-and-open-fixes.md` (full inventory + claim lists).

## Governing principle (non-negotiable in this repo)

> **Fixing means making it work.** Not deleting the feature and documenting that it doesn't.
> Honesty is satisfied by making claims TRUE, not by lowering claims until the broken thing is
> technically disclosed. Every model must beat a stated baseline before it ships; every published
> number must trace to a committed artifact.

## TASK 1 (priority) — published ML numbers describe a model that is no longer deployed

`backend/data/ml_models/metrics.joblib` (retrained 2026-08-24, commit `cf00e43`) is ground truth:
**gradient_boosting**, 1,879 training rows / 1,922 panel rows, 472 families, **28 manufacturers**,
leakage progression R² **+0.8084 (random) → +0.1169 (family-grouped) → −0.3895 (manufacturer-held-out)**,
RMSE reduction vs toughest baseline **4.719 d, 95% CI [2.613, 7.222]**, 18/20 folds.

Stale files still quoting the PREVIOUS run (random_forest, 810 rows, 467 families, 27 mfrs,
+0.638 → +0.082 → −0.550, 6.72 d CI [3.57, 10.26], 16/20):
`docs/MODEL_CI.md` (~lines 94, 191) · `docs/LEAKAGE_PROGRESSION.md` ·
`docs/leakage_progression.json` · `docs/PROJECT_OVERVIEW.md` (~69-71) · `docs/ML_API_PUSH_PLAN.md` (~30).

**Why the existing test doesn't catch it:** `backend/tests/test_docs_match_artifacts.py` compares
`MODEL_CI.md` against `leakage_progression.json` — **both are stale together**, so they agree with
each other while contradicting the deployed model.

Do: regenerate via `cd backend && source venv/bin/activate && python -m seeds.run_leakage_progression`
(let it finish; it may rewrite tracked seed CSVs — `git checkout --` them after). Sync all five docs.
**Add a gate** asserting the leakage artifact's model name / row count / manufacturer count equals
`metrics.joblib` provenance. If you add a `model_ci`-marked test, update the gate-census meta-test.

## TASK 2 — regime training data is not vintage-pinned (revision leakage)

`fetch_regime_feature_frame()` (`backend/app/ml/fred_client.py:335-356`) unconditionally does
`df.to_csv(REGIME_FEATURE_CACHE)` **on read**, with no ALFRED vintage pin — even though the same
file already implements vintage pinning for the Prophet/Census series (`:52, :157-166`). Observed
drift: FRED revised five months in place (2026-05 `ip_semis` 180.92 → 183.80) and appended a
partial row with NaNs. Consequence: the regime model's published Brier/calibration were scored on a
vintage that no longer exists after any test run, and the Render container rewrites its own copy on
first request. Pin it the way the Census series is pinned; make refresh an explicit script; add a
"tests must not dirty tracked files" check.

## TASK 3 — the served model has no uncertainty, and no scheduled retrain

- `GET /ml/lead-time` returns a **bare point estimate** — no interval, no quantiles
  (`backend/app/api/ml.py`, `LeadTimePrediction` ~149-172). For ML-role credibility this is the
  most valuable single upgrade: **split-conformal or Mondrian/grouped conformal prediction
  intervals**, grouped by manufacturer to respect the real dependence structure. `docs/RESEARCH_TECHNIQUES.md`
  already scopes it and it is NOT built. Marginal coverage must be validated, not assumed.
- `get_current_stress_prob()` reads the **last row of a frozen feature frame** (`regime_features.joblib`,
  last index 2026-07-01, currently P(stress)=0.8284). It is genuine model output, not a hardcoded
  scalar, but it **never refreshes** — there is no scheduled retrain. Decide: scheduled retrain, or
  state the freeze honestly in the Model Card.
- `mlAPI.leadTime` is declared at `frontend/src/services/api.ts:611` and **never called**. Either
  surface a prediction (with the interval, once built) on the component page, or stop describing it
  as a live feature. Its docstring currently claims "this is the one the UI makes" — false.

## TASK 4 (the big one — biggest structural gap for Amazon SCOT / o9 / Kinaxis roles)

**There is no inventory/replenishment decision layer at all.** No safety stock, no reorder point,
no service level, no newsvendor critical fractile. `docs/RESEARCH_TECHNIQUES.md §3.4` calls this
"the project's biggest structural gap" and scopes it at 3–4 days. This is the difference between
"solid portfolio project" and "role-matched work sample" for inventory-heavy employers.

The honest, high-value version: connect the **lead-time distribution** (which is why the conformal
intervals in Task 3 come first) to a **newsvendor critical-fractile** order-up-to policy, and
evaluate it against a naive policy on held-out data. Do NOT build decision-focused learning /
SPO+ — `RESEARCH_TECHNIQUES.md` has a reasoned "do NOT build" list explaining why it doesn't apply
here (uncertainty sits in constraints, not objective coefficients). Respect that list.

## What is ALREADY strong — do not "improve" these, and do cite them

Grouped CV with a **measured** leakage progression · 219-fold expanding-window walk-forward with
hyperparameters frozen on a calibration window · Friedman/Nemenyi MCB, Diebold-Mariano,
Clark-West · paired bootstrap CIs (5,000 resamples) · exact McNemar · hand-implemented CRPS /
pinball / Brier / calibration slope+ECE · Croston/SBA/TSB hand-implemented with compound-Bernoulli
predictive distributions · ALFRED vintage-pinned real-time backtesting · ~40 model-CI gates each
tracing to a shipped bug, **including a shuffled-label negative control that tests the gate itself** ·
train/serve schema contracts that fail closed · provenance with data SHA-256 + staleness detection ·
ship gates that require beating ALL naive baselines with a CI excluding zero.

**Verified 2026-08-24:** the regime model's ship gate **PASSES** (`ship_gate_policy: brier`,
`ship_gate_passed: true`, Brier 0.3926 vs persistence 0.5388). It ties persistence on *accuracy*
(0.7306, McNemar p=1.00) and ships on Brier with a written argument — that argument is correct and
is good interview material, not a weakness to hide.

## Honest limits to preserve in any copy you write

Effective n for generalisation is **28 manufacturers**, not 1,879 rows (3 vendors ≈ 66% of the
panel). Lead-time skill is real but small (4.7 d on ~57 d RMSE). All statistical machinery runs
**offline** — the API reads persisted artifacts; the accurate phrase is "rigorously validated
offline modelling pipeline with contract-gated serving," never "ML platform." MLflow is dev-only
(prod always `local_joblib`). Chronos-vs-Prophet is **not** a robust finding (model gap 0.0020 WAPE
< vintage-revision effect 0.0047). ~5-9% of one snapshot's rows are believed mis-resolved and are
retained rather than deleted.

**Never claim:** statsmodels (not installed), conformal prediction (until Task 3 ships),
mixed-effects, decision-focused learning, drift monitoring, production MLflow, live/streaming
inference, a data warehouse, or "a demand forecasting system" (the per-part one was deliberately
deleted as unscoreable — that deletion is itself a good story).

## Gotchas that will cost you an hour each

- `python -m seeds.train_ml_models` **ignores argv** (`--help` starts a real retrain) and has no
  lead-time-only mode. A killed run half-writes artifacts — restore with
  `git checkout -- backend/data/ml_models backend/seeds/data`.
- A clean (non-`-dirty`) provenance SHA needs a **two-step dance**: commit the CSV vintage +
  artifacts, then retrain again (same-day rerun is byte-identical and stamps clean).
- Local strict gates fail exactly one test (`test_the_served_estimator_is_the_one_the_metrics_describe`)
  whenever the gitignored local MLflow store holds a loadable champion — **local-only**, CI and prod
  unaffected. Don't delete the store.
- Never kill pytest mid-flight (poisons `test_hardening.db`; `rm -f backend/test_hardening.db`).
- CI and Render run **Python 3.11**; the local venv is **3.13**. Artifacts are pickled on 3.13.
  Third instance of this bug class already caused two silent production outages.
- Deploys are gated: push → CI (~12 min) → deploy. Render `autoDeploy` is OFF deliberately.
