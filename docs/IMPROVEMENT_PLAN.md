# Portfolio Improvement Plan — Supply Chain Optimization

**Created:** 2026-06-18
**Goal:** Close the credibility gaps that stop this project from impressing senior DS / supply-chain hiring managers (Amazon SCOT, BCG/McKinsey, Google, UPS, ML firms), then add the differentiators that make it stand out.

This plan is derived from a code-level audit (ground truth, not the STATE docs) plus research on what 2026 employers actually reward.

---

## Honest baseline: what's real vs. overstated

### Genuinely strong (lead with these)
- **CP-SAT sourcing MILP** — real decision vars, demand/stock/MOQ constraints, integer cent-scaling, real `Minimize` (`optimization/sourcing.py`). Best interview asset.
- **Legitimate graph theory** — Fiedler/algebraic connectivity, k-core, HHI, seeded Monte Carlo with EVaR-95 (`graph/builder.py`, `graph/simulation.py`).
- **Real, cited emission factors** — EPA SmartWay, ICAO, IATA + correct haversine (`constants.py`).
- **FastAPI + Docker + 210 backend tests** — engineering maturity ahead of most portfolios.

### Overstated / weak (the gaps)
1. **ML learns nothing real.** Prophet fit on a `np.random` synthetic 52-pt series, seasonality off, no holdout/MAPE/baseline (`seeds/train_forecasts.py`). Lead-time & regime sklearn models regress deterministic functions of their own inputs (`lead_time_model.py:153`). Violates the project's own "real data only" rule.
2. **Flagship claim disproven by own benchmark.** `.planning/BENCHMARK-RESULTS.md` = +0.00% cost / +0.00% risk on all 10 BOMs. Graph layer shows no quantified benefit.
3. **Phase 6 scenario endpoints are hardcoded** (e.g. +15% cost, +5d ETA in `resilience.py:158`), not the Monte Carlo output. Most dangerous: collapses under one curl.
4. **Data claim overstated.** "791 parts from Nexar/Octopart APIs" actually loads a static HuggingFace snapshot (`seed_db.py:150`). Prices real; demand & ETA synthetic.
5. **Nothing deployed.** No git remote → CI never ran. Render URLs 404. README badge is a placeholder. localhost-only.

---

## Priority stack (sequenced; each 1–3 days)

### P0 — Un-hardcode the scenario endpoints  *(1–2d, CRITICAL)*
Wire the real Monte Carlo simulation into the three `resilience.py` scenario endpoints (distributor-failure, geopolitical-risk, delivery-target). Replace hardcoded deltas with computed results. Add a test asserting the response is data-derived (varies with inputs), not constant.

### P1 — Real demand data + walk-forward backtest  *(2–3d)*
- Replace the synthetic demand series with a real signal. Pull **NY Fed GSCPI** and **FRED** (ISRATIO, T10Y2Y) as regressors.
- Build a walk-forward (rolling-origin) backtest harness: ≥3 non-overlapping out-of-sample windows.
- Report **WAPE, Bias (ME), Tracking Signal, RMSE — by horizon (week 1/4/8/12)**. Surface in a dashboard panel.
- Narrative: "I validated Prophet and know where it degrades."

### P2 — Deploy + GitHub + live URL  *(1d)*
- Create GitHub repo (needs user's `gh` auth), push, confirm CI runs.
- Deploy backend + frontend on Render free tier. Put live URL in README. Fix the placeholder badge.

### P3 — Dollar-denominated impact framing  *(1d, no code)*
Add a $ translation to every metric in README + dashboard tooltips. EVaR-95 → "$X procurement spend at risk." Cost saved → "$Y/BOM run." Forecast WAPE → weeks of safety stock at $W carrying cost.

### P4 — Chronos foundation-model benchmark  *(1–2d)*
`chronos-forecasting` vs Prophet on identical holdout windows, same metrics, side-by-side. Cold-start (no-history) parts = natural Chronos zero-shot case. Shows deliberate, evidence-based model selection.

### P5 — MLflow experiment tracking  *(1d)*
Wrap Prophet + the 4 lead-time models (Ridge/RF/GBT/MLP) in MLflow. Log params/metrics/artifacts. Model registry with automated champion selection by RMSE.

---

## Real data sources to integrate (all free, all citable)
- **NY Fed GSCPI** — newyorkfed.org/research/policy/gscpi (monthly Excel)
- **FRED API** — ISRATIO, CPIAUCSL, T10Y2Y (`fredapi`)
- **IMF PortWatch** — portwatch.imf.org — Taiwan Strait chokepoint traffic → semiconductor lead times
- **GDELT** — BigQuery free tier — country-pair tone for Taiwan/China/Malaysia/Korea
- **ACLED** — acleddata.com — use the live API, not a snapshot
- **Nexar SCR** — supply-chain-resilience endpoint to cross-validate Fiedler risk scores

Framing upgrade: from "4 feeds" → "four-layer risk-sensing architecture (macro, geopolitical, port, component)."

## Tools/libraries to add
- `chronos-forecasting` (Apache 2.0) — TSFM benchmark
- `mlflow` — experiment tracking / registry
- `fredapi` — macro regressors
- `statsforecast` / `hierarchicalforecast` (Nixtla) — hierarchical reconciliation (optional)
- `evidently` — drift monitoring (optional, high MLOps signal)
- `stockpyl` — multi-echelon GSM safety stock (optional, high academic signal)

## Target resume one-liner (defensible after ~1 week)
"A risk-aware sourcing control tower combining a CP-SAT procurement optimizer, graph-based network-resilience scoring, and probabilistic disruption simulation — validated against the 2021–22 chip shortage, deployed live, with quantified dollar impact per scenario."

---

## Dependency notes (for parallel build)
- P0 (resilience.py) and P2 (deploy/git) are independent → can run in parallel.
- P1, P4, P5 all touch the forecasting/ML layer → sequence or scope carefully to avoid conflicts.
- P3 depends on P0/P1 numbers being real first.
