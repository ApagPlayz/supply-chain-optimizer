# Build Plan — Electronics Procurement Decision System

**Rewritten 2026-08-16.** Supersedes the P0–P3 version; those items are done and summarised at
the bottom.

---

## What this project is

**Given a bill of materials, decide which suppliers to buy from.**

Everything in the repo should serve that decision. Three questions feed it:

```
   How many do we need?   ──┐
        (demand)            │
                            │
   When will it arrive?   ──┼──►   WHICH SUPPLIERS, AT WHAT QUANTITY?
      (lead time)           │        CP-SAT MILP
                            │        + two-stage stochastic program
   What if a supplier     ──┘        + CVaR objective / efficient frontier
   fails?  (risk)
```

## Where each link stands

| Link | State | Evidence |
|---|---|---|
| **Demand** | **Synthetic path retired; benchmark done, decision link open** | The synthetic per-part path (`component_demand_history`/`component_forecasts`, magnitude = `total_stock/52 × risk_score` — inferred from inventory, never measured) is gone: migration `0008_drop_synthetic_demand_tables.py` drops both tables. In its place: an intermittent-demand method benchmark on Monash car parts (2,646 scored series, rolling origin, CRPS + scaled pinball + MASE/RMSSE, Friedman/Nemenyi significance) at `GET /api/v1/demand/benchmark` / `docs/intermittent_demand.json`. Headline: MASE ranks the degenerate `zero` forecast 1st (mean rank 1.66); under CRPS it falls to 4th, under scaled pinball loss to 5th; `tsb` wins both (Friedman p < 1e-300). That benchmark still doesn't reach the sourcing decision — §1.4 below. |
| **Lead time** | Works, **at its data ceiling** | `docs/leakage_progression.json`: R² +0.638 random → +0.082 family-grouped → **−0.550** holding out whole manufacturers. On an unseen vendor it is worse than predicting the mean. 27 manufacturers, three of them 66% of rows. |
| **Risk** | Works | Regime classifier ships on Brier + calibration and prices a premium in `sourcing.py`; CVaR frontier prices the tail against a cited base rate. |
| **Decision** | **Strongest part of the repo** | MILP + SAA + Rockafellar–Uryasev CVaR, λ-swept frontier with a knee at $4.27 of tail risk removed per $1 of expected cost, VSS, out-of-sample seeds, documented convex-hull limitation. |

**Consequence for the roadmap:** the lead-time model is done improving — at 27 manufacturers no
algorithm change moves it, so stop investing there. The work is connecting **demand** to the
decision, and propagating **uncertainty** through it.

---

## Move 1 — Connect demand to the decision (the newsvendor link)

**The method: decision-focused learning via the newsvendor critical fractile.**

The newsvendor optimum is the **τ-quantile of demand**, where τ = Cu / (Cu + Co) — underage cost
over underage plus overage. And because the newsvendor cost function *is* the pinball (check)
loss, **fitting a quantile regressor directly at τ is provably the decision-optimal predictor.**
No differentiable solver layer, no SPO+ machinery — the loss function and the decision coincide.

One narrative in four steps, not four separate techniques:

**1.1 Retire the synthetic per-part demand — done.** `component_demand_history`,
`component_forecasts`, and the Prophet-on-noise path in `seeds/train_forecasts.py` are gone
(migration `0008_drop_synthetic_demand_tables.py`). There is no public source of real per-part
demand for these components. The demand story moved to the Monash car-parts panel: **2,674 series
× 51 months, 136,374 observations, 24.1% non-zero** — real intermittent spare-parts demand, the
closest available analogue to electronic-component demand.

**1.2 Give the forecasts a distribution — done.** Croston / SBA / TSB now emit predictive
distributions (compound Bernoulli × zero-truncated negative binomial) instead of point forecasts,
using the rolling-origin protocol shared with the macro A34SNO backtest via
`app.ml.backtest.rolling_origins`.

**1.3 Score with proper scoring rules — done.** CRPS and scaled pinball loss are scored alongside
MASE/RMSSE, with MCB (Friedman rank test + Nemenyi critical differences) across the **2,646**
scored series in the primary config (horizon 6, 3 origins, train sizes 33/39/45, seasonality 12; a
horizon-12 sensitivity config on 2,504 series reproduces the same ordering). **The headline
finding:** MASE ranks the degenerate `zero` forecast **1st** (mean Friedman rank **1.66**) —
MAE/MASE is minimised by the conditional median, and that median is usually zero on a 24%-non-zero
panel — while under proper scoring `zero` falls to **4th** on CRPS (mean rank 3.67) and **5th** on
scaled pinball loss (mean rank 4.12), and `tsb` wins both (Friedman p < 1e-300, Nemenyi critical
difference 0.1466 at α=0.05). The point and distributional leaderboards disagree. Artifact:
`docs/intermittent_demand.json`, produced by `backend/seeds/run_carparts_backtest.py`, served at
`GET /api/v1/demand/benchmark`, documented in
[`docs/INTERMITTENT_DEMAND.md`](INTERMITTENT_DEMAND.md).

**1.4 Optimise the decision, then evaluate on decision cost — not started.** Set an explicit Cu/Co
(service parts have a defensible asymmetry — a stockout on a spare is expensive relative to holding
one), derive τ, fit a quantile model at τ (`LightGBM objective="quantile", alpha=τ`), and score
every method on **realised newsvendor cost in dollars**, not forecast error. The deliverable is one
chart showing the method that wins on MASE is not the method that wins on cost. This is the one
piece of Move 1 still open — until it lands, 1.1–1.3's finding is real but does not move a dollar
figure anywhere in the app.

**Key references**
- Ban & Rudin (2019), "The Big Data Newsvendor," *Operations Research* 67(1):90–108
- Bertsimas & Kallus (2020), "From Predictive to Prescriptive Analytics," *Man. Sci.* 66(3)
- Kolassa (2020), *IJF* 36(1):208–211 — why the best point forecast depends on the error measure
- Gneiting & Raftery (2007), *JASA* 102(477):359–378 — strictly proper scoring rules
- Koning, Franses, Hibon & Stekler (2005), *IJF* 21(3):397–409 — MCB

**Why SPO+ is deliberately not used:** Elmachtoub & Grigas (2022) requires uncertainty in the
*objective coefficients* with a fixed feasible region. Our uncertain demand sits in *constraints*.
The critical-fractile route reaches the same destination correctly.

---

## Move 2 — Propagate uncertainty instead of passing point estimates

**The method: split conformal prediction, grouped (Mondrian) by part family.**

One idea in three places.

**2.1 Lead time publishes an interval, not a point.** At R² +0.08 family-grouped and −0.55 on
unseen manufacturers, a point estimate is not a defensible product. A **distribution-free 80%
interval with a finite-sample coverage guarantee** is. Conformal prediction gives exactly that
under exchangeability, with no distributional assumption. Must be grouped/Mondrian by
`base_product` to match the CV design — vanilla split conformal would leak siblings across the
calibration boundary the same way a random split does. Report **empirical coverage vs nominal**
and a **PIT histogram**.

**2.2 The optimizer consumes the interval.** `supply_risk` carries the interval rather than a
scalar, so downstream risk pricing reflects predictive uncertainty instead of implying precision
the model does not have.

**2.3 The tail number gets error bars.** Finish the SAA optimality-gap confidence interval: M
independent replications for a statistical lower bound, evaluate the chosen first-stage plan on a
large held-out scenario sample for the upper bound, report the gap with a CI, sweep N to show
where it stabilises. `out_of_sample_seeds` and the exact-vs-SAA comparison already exist;
`SAA_GAP_REPLICATIONS = 12` and the `n_replications = 10` default are both below the literature
floor and should rise.

**Key references**
- Gibbs & Candès (2021), "Adaptive Conformal Inference Under Distribution Shift," *NeurIPS 34*;
  journal version *JMLR* 25 (2024)
- Romano, Patterson & Candès (2019), "Conformalized Quantile Regression," *NeurIPS 32*
- MAPIE (scikit-learn-contrib) — implements CQR / EnbPI; may be config rather than code
- Mak, Morton & Wood (1999), *OR Letters* 24(1–2):47–56 — SAA bounding
- Kleywegt, Shapiro & Homem-de-Mello (2002), *SIAM J. Opt.* 12(2):479–502

**The two moves are one project.** A quantile is a decision under asymmetric cost; a conformal
interval is a quantile with a coverage guarantee. They share the pinball loss. Move 1 applies it
to demand, Move 2 applies it to lead time.

---

## Move 3 — Already built

Model CI (35 gates, `docs/MODEL_CI.md`), the measured leakage progression
(`docs/leakage_progression.json`), artifact provenance and staleness at `/ml/model-info`, the
benchmark retraction with its volume curve, the CVaR frontier, and live DigiKey / Nexar /
OEMsecrets pricing in production. No further work planned.

---

## Deliberately not building

A one-page appendix. The reasoning is worth more than the implementations would be.

| Not building | Why |
|---|---|
| Bertsimas–Sim robust frontier | A second frontier alongside one we already have. Real, just redundant. |
| Mixed-effects / partial-pooling lead-time model | The model is at its data ceiling at 27 manufacturers. A better estimator changes nothing. |
| ALFRED vintage-data backtest | Genuinely novel, but tangential to the decision spine. |
| SPO+ / PyEPO | Uncertainty is in constraints, not objective coefficients. Wrong tool. |
| Causal forests / DML on the distributor panel | No randomisation, no instrument. |
| Hierarchical reconciliation (MinT/ERM) | Monash car parts ships no product taxonomy — no hierarchy to reconcile. |
| Wasserstein DRO | Needs an SOCP solver; CP-SAT cannot do conic constraints. |
| Deep learning anywhere here | The MLP already in the model zoo scores cv_R² = −0.056. |
| Hyperparameter optimisation | Fold spread is ±0.32 R². Any gain is inside the noise. |
| SHAP on the 177-feature model | Most one-hot columns carry 1–5 rows. |
| Censored / Tobit regression | Retired: censoring was a 75-row artifact; 5 of 742 new rows sit at the ceiling. |

Full detail and citations: `docs/RESEARCH_TECHNIQUES.md`.

---

## Sequencing

| | Work | Days | Status |
|---|---|---|---|
| 1 | 1.1 retire synthetic demand + 1.2 predictive distributions | 1.5 | **done** |
| 2 | 1.3 CRPS / pinball / MCB–Nemenyi | 1.5 | **done** |
| 3 | 1.4 newsvendor critical fractile + decision-cost evaluation | 2 | open |
| 4 | 2.1 conformal intervals + 2.2 optimizer consumption | 1.5 | open |
| 5 | 2.3 SAA gap CI | 1 | open |

**If only one more thing gets built: 1.4.** 1.1–1.3 shipped the benchmark and the significance
tests; 1.4 is the piece that would turn that benchmark into a decision — the chart where the best
forecast is not the best decision — and it is the only step left in Move 1.

---

## Owner action items

- **Mouser API key** (free, mouser.com/api-hub) → `backend/.env`. The client and collector are
  already written; only the key is missing. It is the one change that lifts the lead-time model's
  ceiling, because it adds a second measurement of the same MPN and turns `source` from a constant
  into a real feature.
- ACLED (acleddata.com/register) for the last dormant feed. SupplyMaven / TrustedParts if the
  market-intelligence panel should show live data.

---

## Completed (previous plan, 2026-08-15)

- **P0 correctness** — train/serve schema divergence that made every lead-time prediction the
  constant 62.1085 d; an ML adoption gate that discarded the prediction in 234/234 runs; a frozen
  `current_stress_prob` scalar serving as if it were live model output; false "live" integration
  claims; dead-code docstrings.
- **P1 data + models** — DigiKey panel 75 → 817 rows across all 791 components, 9 → 56 columns,
  migrations 0006/0007 persisting part-level features; serving coverage 7% → 94.4%; regime model
  rebuilt on walk-forward and shipped on Brier + calibration; ML surfaced in the UI (model card,
  supply risk, macro stress); all 9 previously-orphaned endpoints given consumers.
- **P2 optimization** — two-stage stochastic program with CVaR objective and efficient frontier.
- **P3 model CI** — 35 gates derived from the failures above.
