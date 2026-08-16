# ML + API Push Plan (2026-08-15)

**Goal:** turn this repo into a resume project that stands up to an ML/DS interviewer and an
Amazon-SCOT-style ops interviewer. Owner has ~1 week.

**Targets chosen by owner:** ML / Data Science **and** Big-tech ops (SCOT). Not optimizing for
consulting narrative or pure backend this round.

Source audits (2026-08-15, both read-only, verified against current code — not the July audit):
ML subsystem audit + external-API integration audit. Findings summarized inline below.

## Guiding principle (owner correction, 2026-08-15)

**Fixing means making it work. It does not mean deleting the feature and documenting that it
doesn't.** Honesty is a hard requirement, but we satisfy it by making the claims TRUE — not by
lowering the claims until the broken thing is technically disclosed. A disabled model and a
dormant integration showcase nothing, and this repo exists to showcase ML and API skill.

Concretely, when something is found broken:
- a model that loses to its baseline gets **fixed until it wins**, not switched off;
- an integration that is dormant for want of a credential gets the **credential propagated** and
  verified live, not a nicer "inactive" badge;
- a dataset that is too small gets **collected properly** (the panel was 75 rows because only 75
  MPNs were ever queried — there are 791 components and working credentials);
- "we can't claim this" is the outcome of last resort, used only after a real attempt failed, and
  reported with what was tried and what the numbers were.

---

## P0 — Correctness. The code is currently lying. (~1 day)

These are not "improvements"; they are defects that invalidate published numbers.

1. **Lead-time train/serve feature-schema mismatch → constant predictor.**
   `build_observed_matrix` (`backend/app/ml/lead_time_model.py:213-245`) trains on
   `['is_active','log_stock','macro_stress','cat_<5>','src_digikey']`.
   `build_feature_row` (`:73-96`) — what `backend/app/optimization/costs.py:126` actually calls —
   emits `{category,is_domestic,dist_km,tier,macro_stress,risk_score,stock_coverage,is_chinese_origin}`,
   and `_align_row` (`:114-122`) one-hot-encodes with prefix `category_` vs training's `cat_`, then
   zero-fills. Serving vector is always `[0,0,0.9967,0,0,0,0,0,0]`; every prediction is **62.1085 d**.
   Fix: single shared feature builder used by both paths + contract test + variance test.

2. **ML ETA is unreachable even when correct.** `backend/app/optimization/solve.py:385` gate requires
   `route_eta > 31.05 d`; max `eta_p50_days` across all 234 `optimization_runs` is 16.4. Used 0/234.

3. **Frozen scalar masquerading as model output.** `regime.joblib`/`regime_features.joblib` are not
   git-tracked (`.gitignore:41-45`), so production `serving.py:177` reads
   `current_stress_prob = 0.9967` from `metrics.joblib` (baked 2026-07-10) and
   `backend/app/optimization/sourcing.py:466-468` prices risk off it.

4. **Regime model ships despite losing to its baseline** (val_accuracy 0.7333 vs persistence 0.8333;
   macro-F1 0.586; `elevated` recall 0.25). Fix it until it beats persistence: refit on the full
   history rather than pre-2019 only (today it is trained on train<2019 and never refit before
   serving, so it extrapolates 7.5 years and has never seen COVID or the 2021-22 shortage), handle
   the imbalance dumping 9/16 `elevated` months into `stress`, and evaluate with walk-forward
   rather than a single split. Keep persistence as the bar. Ship the artifacts (see item 3) —
   the target state is a real model live in production.

5. **Published R² does not describe the deployed model** — `/ml/model-comparison` returns 0.9291.

6. **EasyPost is dead code with a false docstring.** `backend/app/core/clients/easypost_client.py:11`
   claims "Called from optimize.py when EASYPOST_API_KEY is set"; no such call exists.

7. **"DigiKey API (live), refreshed weekly" is not true yet** — the GitHub Action has run green-no-op
   for 4 weeks (`status=no_keys`); the panel is 75 rows, all `snapshot_date=2026-07-01`.
   **Resolution: make it true.** Push the DigiKey credentials (already in local `backend/.env`) into
   GitHub Actions secrets via `gh secret set`, trigger the workflow, and confirm it collects. Same
   for the five integrations dormant in production — propagate the local credentials to Render via
   the Render API (`RENDER_API_KEY` is in `backend/.env`) and verify against the deployed service.

---

## P1 — Make the ML real, not just correct (~2-3 days)

8. ~~**Censored regression for lead times.**~~ **SUPERSEDED 2026-08-15 — do not build this.** The
   censoring hypothesis (56/75 labels at exactly 30 weeks) was an artifact of a 75-row sample. After
   collecting all 791 components, only **5 of 742** new rows sit at 30 weeks; the target is
   continuous (median 12, mean 19.8, range 2–99, 41 distinct values). A Tobit/AFT model would now be
   the wrong tool.

   **What the data gave instead is better.** Of the 75 MPNs present in both snapshots, the 19 not at
   30 weeks barely moved (6→6, 9→9, 14→14) — but **all 56 that quoted exactly 30 weeks in July
   re-quoted to 40 (14) or 52 (42) weeks in August**, nearly all STMicroelectronics. July's "30" was
   a real ST-wide quote, and the collector captured a genuine lead-time extension in observed data.
   Preserve this: it is the strongest ML-story asset in the repo.

   The live modeling problem is different and sharper: **part-family leakage.** `base_product` alone
   explains **R²=0.82 in sample** (100 STM32F103 variants, 37 ATMEGA328, 31 TMS320), so every split
   must be grouped by family. Doing so drops lead-time R² from **+0.638 to +0.082**, and holding out
   whole manufacturers takes it to **−0.550** — that collapse IS the finding worth presenting.
   (The `0.76 → 0.216` pair this plan originally quoted predates the current panel and is retired;
   the measured figures live in [`leakage_progression.json`](leakage_progression.json), regenerated
   by `python -m seeds.run_leakage_progression`.)

9. **Stop serving forecasts that were never evaluated.** `backend/seeds/train_forecasts.py:109-119`
   derives per-part demand from inventory (`base_rate × risk_multiplier`); output is degenerate —
   verified exactly −16.271576 per step for components 1/2/7/300, i.e. straight lines, because the
   synthetic history is white noise (lag-1 autocorr 0.092). The UI shows these as "Prophet forecasts."
   Either ground per-part demand in something defensible (hierarchical top-down from A34SNO with
   published per-class error). Labelling them in the UI is not sufficient — the fix is a demand
   signal that is actually defensible per part.

10. **Surface the ML in the product.** All four `/ml/*` endpoints have zero frontend callers
    (`frontend/src/services/api.ts` has no `mlAPI` group). A model nothing consumes is not a feature.

---

## P2 — The SCOT item (~2-3 days)

11. **Two-stage stochastic program with a CVaR objective.** Scenario generator and MILP already exist.
    Sample-average approximation + Rockafellar–Uryasev linearization, sweep λ, plot the
    **cost-vs-CVaR efficient frontier**. Replaces "I added a 15% surcharge" with "here is the price of
    resilience and the knee of the curve is my recommendation." Carried over from the July audit,
    where it was rated the single biggest step-change available.

---

## P3 — ML engineering discipline (~1 day, highest respect-per-hour)

12. ~~**Model CI**~~ **DONE 2026-08-16 — see `docs/MODEL_CI.md`.**
    `.github/workflows/model-ci.yml` runs on push/PR to main, retrains the lead-time model on the
    committed observed panel, and fails on train/serve schema divergence, a champion that does not
    beat every naive baseline (paired CI excluding zero), serve-time answer rate below 80% measured
    against the shipped DB, a near-constant predictor, an endpoint whose signature does not cover its
    model's required inputs, and an artifact missing provenance. `MODEL_CI_STRICT=1` promotes a
    SKIPPED gate to a failure, so a gate cannot quietly stop testing. Provenance (`trained_at`,
    `git_sha`, `sklearn_version`, `training_data_sha256`, `n_training_rows`, …) is stamped at fit time
    and published at `GET /ml/model-info`, with a staleness check that WARNS — never fails — when the
    weekly collector has grown the panel past what the served artifact saw.
    Still not done: drift detection on live traffic, automated retrain, and a shared MLflow registry
    (`mlruns/` is still gitignored and dev-only).

---

## Explicitly NOT in scope this round

- Consulting-style case study / business-scale dollar figures (owner deprioritized).
- Generic backend hardening (retries, rate limiting, caching, client-layer tests) beyond what P0
  requires — real gaps, but they serve the backend-eng target that was not chosen.

---

## Owner action items

Most of what was previously on this list is being done automatically — the credentials already
exist in local `backend/.env`, so GitHub Actions secrets (`gh secret set`) and Render env vars
(Render API, key also in `backend/.env`) are being propagated and verified rather than delegated
back to the owner.

Genuinely still owner-only — these need a signup nobody else can complete:
- **ACLED**: register free at https://acleddata.com/register/ (key emailed instantly). Last feed
  with no credential anywhere.
- **Mouser**: https://www.mouser.com/api-hub/ — would add a second *independent* lead-time source,
  which matters for the ML: today every observation comes from a single distributor, so
  `source` is a constant feature and there is no cross-distributor variation to learn from.
