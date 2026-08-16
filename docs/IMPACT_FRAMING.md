# Dollar-Denominated Impact Framing (P3)

Every abstract metric in this project is paired with a concrete financial
interpretation. This note documents how each dollar figure is derived, so the
numbers can be defended in an interview. **Real-data rule:** no dollar figure is
invented — each is computed from quantities already in the codebase, with any
conversion constant taken from a cited industry source and labeled as an
assumption.

---

## 1. CVaR-95 → "$X of procurement spend at risk"

**Metric.** CVaR-95 (`SimulationResult.cvar_95`, `backend/app/graph/simulation.py`)
is the *mean emergency-procurement cost multiplier over the worst-5% of the 1,000
Monte Carlo cascade-failure scenarios*. Each scenario inflates cost by
`1 + (unfulfillable / BOM_size) × 0.15` (15% emergency premium per unsourceable
line); CVaR-95 averages that multiplier across the worst-5% tail. It is ≥ 1.0.

**Dollar translation.**

```
procurement_spend_at_risk_usd = baseline_component_cost × (CVaR-95 − 1)
```

where `baseline_component_cost` is the sum of each BOM line's **average real
distributor offer price**, drawn from the 8,176-offer distributor dataset
originally sourced via the Nexar API — a static 2024 snapshot, not a live feed
(see [DATA_PROVENANCE.md](DATA_PROVENANCE.md)). Subtracting 1 strips the baseline
bill so the figure is the *extra* dollars a tail disruption would add.

- **Backend:** computed per BOM in `_compute_baseline_metrics`
  (`backend/app/api/resilience.py`) and returned on all three resilience
  endpoints as `procurement_spend_at_risk_usd` (alongside `baseline_cvar_95`).
- **Benchmark:** aggregated across the 10 reference BOMs as
  `baseline_spend_at_risk_usd` = mean(`total_cost_usd × (mc_cvar_95 − 1)`) in
  `backend/app/api/benchmark.py`.
- **UI:** amber "Procurement Spend at Risk · CVaR-95" banner on the Resilience
  page; "Tail risk · CVaR-95 spend at risk" tile on the Benchmark page.

**Assumptions/citations.** None external. The only constant is the 15% emergency
premium, which already lives in `simulation.py` (`EMERGENCY_COST_PREMIUM`). The
figure is otherwise 100% data-derived.

---

## 2. Optimizer cost delta → "$Y saved per BOM run"

**Metric.** The benchmark compares the graph-aware optimizer to the baseline
optimizer over 10 reference BOMs (`backend/app/api/benchmark.py`).

**Dollar translation.**

```
cost_delta_usd = mean( graph_aware.total_cost_usd − baseline.total_cost_usd )
```

over the BOMs common to both arms. Negative ⇒ graph-aware is cheaper (money
saved). `total_cost_usd` is the real landed cost (component + transport + holding)
each optimizer run produced.

- **UI:** "Optimizer impact · $ / BOM run" tile on the Benchmark page.

**Honesty note.** This is intentionally surfaced as a *live, run-dependent* figure,
not a fixed marketing claim. On the current reference set the graph-aware vs
baseline delta sits near the ±2% noise floor (the page already flags this with a
"Low confidence" badge). The dollar tile reflects whatever the real run produced.

**Assumptions/citations.** None external — directly from run totals.

---

## 3. Demand forecasting — what changed, and what is measured now

**This section used to derive a "≈N weeks of safety stock" dollar figure from the
macro Census backtest and attribute it to the per-part forecast the app served.**
That per-part forecast is gone, and so is the dollar figure it fed — not
carried over, because it no longer has a live consumer. What follows is the
accurate replacement: what was removed and why, what the macro backtest still
shows (unchanged, real, kept), and what the new demand-method benchmark shows in
its place.

### 3a. What was removed

The per-part "demand" the app served was `total_stock / 52 × risk_score` —
a magnitude *inferred from inventory position and a risk multiplier*, not
measured, identical in shape across all 791 parts because it borrowed one macro
curve (Census `A34SNO`) for the temporal pattern. Prophet was fit on top of that
fabricated series and produced a 12-week forecast window that closed 17 months
before this line was written, against which no actuals were ever recorded —
unscoreable even in principle, because no public per-SKU demand series exists for
these components against which to check it.

It was removed rather than patched: migration
`0008_drop_synthetic_demand_tables.py` drops `component_demand_history` and
`component_forecasts`; `backend/seeds/train_forecasts.py`,
`backend/app/models/forecast.py`, `backend/app/api/forecasts.py`, and the
`GET /api/v1/forecasts/all` endpoint are deleted; the frontend per-part forecast
sparkline and "stock-out in ~N weeks" badge are gone with them.

### 3b. What the macro backtest still shows (unchanged, real)

The Census `A34SNO` walk-forward backtest ([FORECAST_BACKTEST.md](FORECAST_BACKTEST.md))
never depended on the deleted tables and is unaffected by the deletion:

| Model | WAPE | MAPE | RMSE |
|-------|-----:|-----:|-----:|
| Prophet — trend-only | **0.0251 (2.5%)** | 0.0235 | 1164.41 |
| Prophet — seasonal | 0.0266 (2.7%) | 0.0250 | 1179.02 |
| Seasonal-naive | 0.0438 (4.4%) | 0.0422 | 1501.68 |

Skill score vs. seasonal-naive: **+42.7%** for the trend-only ablation (no yearly seasonal term), +39.3% for
the seasonal variant. This is a real measurement of Prophet on a real aggregate
industry series (197 monthly obs, 2010-01-01 → 2026-05-01, 3 rolling origins,
12-month horizon per origin). It was never evidence about per-part accuracy —
that framing is retired along with the per-part forecast itself — and no dollar
translation is attached to it here anymore, since the safety-stock tooltip that
consumed it no longer exists in the UI.

### 3c. What replaced the per-part demand claim

There is no public per-SKU demand series for electronic components, so this
project does not claim one. What it can measure instead is **which
intermittent-demand method to trust and why**, on a real analogous panel: Monash
car-parts sales (2,674 series × 51 months, 24.1% non-zero, CC-BY 4.0, via
HuggingFace `Monash-University/monash_tsf`) — served at
`GET /api/v1/demand/benchmark`, backed by the committed artifact
`docs/intermittent_demand.json` (produced by
`backend/seeds/run_carparts_backtest.py`), documented in
[docs/INTERMITTENT_DEMAND.md](INTERMITTENT_DEMAND.md).

Protocol: rolling origin, non-overlapping test blocks, refit at every origin
(primary config: horizon 6, 3 origins, train sizes 33/39/45, seasonality 12 —
shared with the macro backtest via `app.ml.backtest.rolling_origins`). Methods
(`zero`, `naive_last`, `climatology`, `croston`, `sba`, `tsb`) emit predictive
distributions (compound Bernoulli × zero-truncated negative binomial), scored
with MASE/RMSSE alongside CRPS and scaled pinball loss.

**The headline finding**, measured across **2,646** scored series: MASE ranks
the degenerate `zero` forecast **1st** (mean Friedman rank **1.66**) — because
MAE/MASE is minimized by the conditional median, and that median is usually zero
on a 24%-non-zero panel — while under proper scoring `zero` falls to **4th** on
CRPS (mean rank 3.67) and **5th** on scaled pinball loss (mean rank 4.12), and
`tsb` wins both. Friedman p < 1e-300; Nemenyi critical difference 0.1466 at
α=0.05. The point and distributional leaderboards disagree, and a horizon-12
sensitivity configuration (2,504 scored series) reproduces the same ordering.

**No dollar translation exists for this finding yet.** It says which forecasting
method is least wrong under a scoring rule that matches the decision's cost
structure — it does not by itself say what a stockout or an over-order costs in
dollars. Connecting the two (an explicit newsvendor critical fractile, a quantile
model fit at that fractile, evaluation in realised dollar cost rather than
forecast error) is Move 1 §1.4 in [docs/ML_API_PUSH_PLAN.md](ML_API_PUSH_PLAN.md)
and is not yet built. Stating that plainly is preferable to inventing an
illustrative dollar figure the way the retired per-part path did.

**Assumptions/citations (macro backtest only, §3b).**
- No dollar-conversion assumptions apply to this section anymore — see above.
- Gneiting & Raftery (2007), *JASA* 102(477):359–378 (proper scoring rules);
  Koning, Franses, Hibon & Stekler (2005), *IJF* 21(3):397–409 (MCB); full
  reference list in `docs/intermittent_demand.json` → `scoring`/`mcb`.

---

## 4. Per-route holding cost (already dollar-denominated)

The checkout cost breakdown already shows a real holding-cost line
(`cost_breakdown.holding_cost`). P3 adds a tooltip documenting its basis:

```
holding_cost = component_value × 25%/yr × (lead_time_days / 365)
```

cited to the same Gartner 2022 rate (`holding_cost_usd` in `costs.py`).

---

## Summary of constants introduced/reused

| Constant | Value | Source | Status |
|----------|-------|--------|--------|
| Inventory carrying rate | 25%/yr | Gartner IT Supply Chain Benchmarks 2022 | **Reused** (`ANNUAL_HOLDING_RATE`) |
| Service factor z | 1.645 (95%) | Standard normal / Silver-Pyke-Peterson | New, labeled assumption |
| Emergency premium | 15%/unsourceable line | Existing `EMERGENCY_COST_PREMIUM` | Reused |

No new hardcoded dollar figures were introduced into the application logic; all
dynamic dollar values are computed from real BOM spend and real simulation output.
