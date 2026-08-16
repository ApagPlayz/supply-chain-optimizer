# Research Backlog — Statistical & OR Techniques Worth Adding

**Compiled 2026-08-15/16** from a literature scan (2023–2026) plus verification against this
repo's actual data artifacts. Every citation below was checked to exist; nothing here is
recalled from memory.

**How to use this doc:** each item states whether *our real data can actually support it*.
That column is the point. A technique this project cannot honestly support is not a backlog
item — it is a trap, and the "Do not build" section at the bottom is as valuable as the rest.

---

## The strategic finding that reorders everything

Verified against the artifacts on disk:

| Asset | Reality | Consequence |
|---|---|---|
| **Monash car parts** (`docs/intermittent_demand.json`) | **2,674 series × 51 months**, 24.1% non-zero, **2,646 scored** under the rolling-origin protocol | **Now carrying the demand story** — proper scoring rules and significance testing shipped (1.1/1.2 below); still supports a newsvendor study (1.4) and conformal calibration. |
| Census M3 A34SNO (`docs/forecast_backtest.json`) | `n_obs=197`, **`n_windows=3`**, horizon 12 → **36 test points from 3 origins** | The weakest evidence in the repo. No significance test is possible. Saying so is worth more than another model. |
| CVaR frontier (`docs/cvar_frontier.json`) | tail atoms now 31–54 after calibration work; largest single atom still 32–80% of tail mass | Tail estimate improved but remains atom-dominated at low volume. Report it. |
| Lead-time panel | 817 rows, **2 snapshots**, one distributor | Supports the ST-extension *event narrative*; supports almost no inference. |

**Therefore: stop pointing new statistics at the 197-point macro series. Point them at car parts.**
Nearly every item below gets cheaper and more defensible under that reframe.

---

## Track 1 — Demand forecasting (Monash car-parts panel)

### 1.1 Re-score the intermittent-demand benchmark distributionally — **done**
*Effort: estimated 2–3 days; actual ~1. Data support: full.*

The hypothesis was that **MAE/MASE is minimized by the conditional median, and with 24%
non-zero demand that median is frequently zero**, so a MASE leaderboard on intermittent
demand can reward a degenerate near-zero forecast. **Confirmed, and more starkly than
expected.** Every method (Croston/SBA/TSB/naive, plus a `climatology` reference and an
explicit `zero` forecast added to test the hypothesis directly) now emits a compound
Bernoulli × zero-truncated negative binomial predictive distribution, scored by CRPS and
scaled pinball loss alongside MASE/RMSSE. Across 2,646 series:

- **`zero` — forecasting nothing, every period — wins both MASE and RMSSE outright**
  (mean Friedman rank 1.66 of 6).
- Under CRPS it falls to 4th, under scaled pinball loss to 5th; `tsb` wins both.
- Kendall's τ between the MASE and pinball orderings is **−0.20** — the leaderboards are
  mildly anti-correlated, not merely reshuffled.

The original guess in this section ("TSB wins on MASE may be partly a metric artifact") was
half right: TSB does not win MASE at all once the degenerate forecast is on the board.
Full write-up: [`docs/INTERMITTENT_DEMAND.md`](INTERMITTENT_DEMAND.md).

- Kolassa, S. (2020). "Why the 'best' point forecast depends on the error or accuracy measure."
  *IJF* 36(1):208–211. doi:10.1016/j.ijforecast.2019.02.017
- Kolassa, S. (2016). "Evaluating predictive count data distributions in retail sales
  forecasting." *IJF* 32(3):788–803. doi:10.1016/j.ijforecast.2015.12.004
- Gneiting, T. & Raftery, A.E. (2007). "Strictly Proper Scoring Rules, Prediction, and
  Estimation." *JASA* 102(477):359–378.
  https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf

**Why it lands:** "I noticed my accuracy metric was structurally biased toward zero forecasts on
intermittent demand, re-scored the benchmark distributionally, and the winner changed" is a
senior observation *and* a correction of our own work.

### 1.2 Significance testing across series (MCB / Nemenyi) + rolling origin — **done**
*Effort: 1–2 days. Data support: full on car parts; explicitly NOT on A34SNO.*

The single split is gone: the car-parts protocol is now rolling origin (horizon 6, three
origins, train sizes 33/39/45), sharing `app.ml.backtest.rolling_origins` with the macro
backtest so the two cannot drift apart. MCB ships across 2,646 series: Friedman χ²(5) with
the Iman–Davenport F correction, plus Nemenyi critical differences (**CD = 0.147** at
α = 0.05), with the critical-difference diagram data — mean ranks, CD, and the
non-separated cliques — in the artifact. Under CRPS and scaled pinball loss **every pair is
separated**; under MASE `tsb` and `sba` are not.

**One claim in the original plan was wrong, and the implementation disproved it.** This
section asserted that "naive nests inside several of our methods". It does not: Croston at
α → 0 returns its *initialisation*, not the sample mean, so neither `naive_last` nor
`climatology` is a parameter restriction of any Croston-family method. The two nestings
that genuinely exist are `croston ⊂ sba` (SBA = Croston × (1 − φ/2), Croston is φ = 0) and
`zero ⊂ {croston, sba, tsb}` (the p = 0 restriction of the compound-Bernoulli model).
Clark–West is applied to those and Diebold–Mariano to the rest. The zero-restriction case
turns out to be **degenerate** — with f₁ = 0 the CW adjustment collapses to 2·y·f₂, which is
≥ 0 for any non-negative forecast, so rejection is automatic — and is reported flagged
rather than dropped. The one informative nested result is `croston → sba`: t = 11.33,
p = 4.5e-30.

- Koning, Franses, Hibon & Stekler (2005). "The M3 competition: Statistical tests of the
  results." *IJF* 21(3):397–409. — origin of MCB.
- Tashman, L.J. (2000). "Out-of-sample tests of forecasting accuracy." *IJF* 16(4):437–450.
- Harvey, Leybourne & Newbold (1997). "Testing the equality of prediction mean squared errors."
  *IJF* 13(2):281–291 — small-sample correction to Diebold–Mariano (1995).
- Clark, T.E. & West, K.D. (2007), *J. Econometrics* 138(1):291–311 — **required instead of DM
  when models are nested**; naive nests inside several of our methods, so raw DM is invalid there.

**The honest half matters as much:** state that MCB is right for 2,658 series and *wrong* for
A34SNO, where 3 origins cannot support any test. Refusing to run an unpowered test is the
differentiator; most portfolio projects run a t-test on three numbers.

### 1.3 Retire the synthetic per-part demand — **done**
*Effort: 0.5 day (actual). Data support: n/a — this was a deletion.*

`component_demand_history` (791 × 52 weeks) and `component_forecasts` are gone —
migration `0008_drop_synthetic_demand_tables.py` drops both, along with
`backend/seeds/train_forecasts.py`, `backend/app/models/forecast.py`,
`backend/app/api/forecasts.py`, and the `GET /api/v1/forecasts/all` endpoint. The
series had a real temporal *shape* (borrowed from Census M3 `A34SNO`) but a
fabricated *magnitude*: `base_rate = total_stock / 52 × risk_score` — demand
inferred from inventory position and a risk multiplier, causally backwards, and
identical in shape across all 791 parts. The Prophet fit on top of it predicted a
12-week window that closed 17 months before this line was written, against which
no actuals were ever recorded — unscoreable even in principle. There is no public
source of real per-part demand for these components, so it was removed rather
than patched, and Monash now carries the demand story:
`GET /api/v1/demand/benchmark`, backed by `docs/intermittent_demand.json`
(script: `backend/seeds/run_carparts_backtest.py`), documented in
[`docs/INTERMITTENT_DEMAND.md`](INTERMITTENT_DEMAND.md).

---

## Track 2 — Lead-time model

> **Every lead-time number in this track is measured by
> `python -m seeds.run_leakage_progression` and published in
> [`leakage_progression.json`](leakage_progression.json) /
> [`LEAKAGE_PROGRESSION.md`](LEAKAGE_PROGRESSION.md).** An earlier revision of this
> file quoted the progression from memory as `0.95 → 0.19–0.29 → 0.06` on "684 rows,
> 28 manufacturers". All five of those figures were wrong. They are corrected below.

### 2.1 Conformal prediction intervals, grouped by part family
*Effort: 1–2 days. Data support: yes (n=810 rows, 467 families, 27 manufacturers).*

Nothing in the repo currently makes a *calibrated uncertainty* claim. The lead-time point
estimate is weak by construction (family-grouped R² = **+0.163 median / +0.082 mean** over
50 `GroupKFold` folds, fold sd 0.242; the served `metrics.joblib`, which uses repeated
`GroupShuffleSplit` instead, reports +0.181 median / +0.189 mean — same story, different
resampler), but a calibrated
80% interval on the same data is genuinely useful — and it is what the optimizer actually wants
to consume. Adaptive Conformal Inference is a short online update, distribution-free, and holds
under distribution shift. **Must be grouped/Mondrian by family**, matching the CV design.

- Gibbs, I. & Candès, E. (2021). "Adaptive Conformal Inference Under Distribution Shift."
  *NeurIPS 34*:1660–1672. Journal version *JMLR* 25 (2024),
  https://www.jmlr.org/papers/v25/22-1218.html
- Angelopoulos, Candès & Tibshirani (2023). "Conformal PID Control for Time Series Prediction."
  *NeurIPS 2023*.
- Romano, Patterson & Candès (2019). "Conformalized Quantile Regression." *NeurIPS 32*.
- MAPIE (scikit-learn-contrib): https://github.com/scikit-learn-contrib/MAPIE — implements
  EnbPI/CQR/`MapieTimeSeriesRegressor`, so this may be config rather than code.

Report **coverage vs nominal** and a **PIT histogram**. A lumpy PIT is itself an honest result.

### 2.2 Partial pooling / mixed effects with a manufacturer random effect
*Effort: 1–2 days. Data support: yes, and it is the statistically correct tool.*

Effective sample for generalization is **27 manufacturers**, not 810 rows, and **15 of them have
≤6 rows** — while three vendors (Analog Devices, TI, STMicroelectronics) supply 66% of the panel.
Shrinkage handles the tiny groups that a one-hot GBM either memorizes or ignores. This
addresses the family-leakage problem directly rather than routing around it. `statsmodels`
MixedLM or a small Bayesian model.

### 2.3 Present the leakage collapse as a headline result
*Effort: ~0 (already measured). Data support: [`leakage_progression.json`](leakage_progression.json).*

Same estimator, same 810 rows, same feature pipeline, same seed — only the fold boundary moves:

| Split regime | R² mean | R² median | fold sd |
|---|---:|---:|---:|
| random rows (**the wrong protocol**) | **+0.638** | +0.638 | 0.079 |
| `GroupKFold` by part family (`base_product`) | **+0.082** | +0.163 | 0.242 |
| `GroupKFold` by manufacturer | **−0.550** | −0.166 | 0.815 |

50 folds per regime (5-fold × 10 shuffles, seed 42), champion `random_forest`. Full protocol,
per-fold scores and the naive baselines on the identical folds:
[`LEAKAGE_PROGRESSION.md`](LEAKAGE_PROGRESSION.md).

**The negative number is the interesting one, and it should be stated exactly.** R² is scored
against the *held-out fold's own* mean, so R² < 0 means the model's squared error exceeds that
vendor's entire label variance: on a manufacturer it has never quoted, the model has no
explanatory power at all. It is not beaten by the trivial predictors there — `train_mean` scores
−2.464 on the same folds — so the honest claim is that the model is the best member of a set in
which **nothing generalises to an unseen vendor**, not that the model is uniquely bad.

Most candidates never discover this about their own project. The collapse, with the diagnostic
that found it, is worth more than any model.

> **Do not confuse this with in-sample identity-column R².** Fitting a per-level mean on all
> rows and scoring it on those same rows gives `base_product` **0.823** (360 levels over 810
> rows) and `mpn` 0.938. Those are not cross-validated, not model scores, and not the
> random-split figure — they are the *measurement of the redundancy* that makes a random split
> leak in the first place. Quoting one of them as the random-split R² is exactly the error this
> document used to contain.

---

## Track 3 — Optimization / OR

### 3.1 CVaR *is* distributionally robust optimization — free reframe
*Effort: 0 (one paragraph). Data support: n/a.*

CVaR_α(Z) = sup{E_Q[Z] : Q ≪ P, dQ/dP ≤ 1/α} — a worst-case expectation over a
likelihood-ratio-bounded ambiguity set. Stating this turns "I used a risk measure" into "I solved
a distributionally robust program," which is the same work described in the vocabulary an OR
interviewer listens for.

- Rockafellar, R.T. & Uryasev, S. (2002). "Conditional value-at-risk for general loss
  distributions." *J. Banking & Finance* 26(7):1443–1471.
  https://sites.math.washington.edu/~rtr/papers/rtr187-CVaR2.pdf
- Artzner, Delbaen, Eber & Heath (1999). "Coherent Measures of Risk." *Mathematical Finance*
  9(3):203–228.

### 3.2 Bertsimas–Sim price of robustness — a second frontier
*Effort: 1–2 days. Data support: yes; stays in CP-SAT.*

A budget-of-uncertainty parameter Γ caps how many coefficients simultaneously hit worst case, and
**the robust counterpart of a MILP stays a MILP of essentially the same size** — no conic solver,
so it plugs into the existing stack. Sweep Γ, plot cost-vs-Γ beside cost-vs-CVaR, and explain the
distinction: **CVaR trades expected cost against tail cost; Bertsimas–Sim trades expected cost
against worst-case constraint violation.** Complements, not substitutes.

- Bertsimas, D. & Sim, M. (2004). "The Price of Robustness." *Operations Research* 52(1):35–53.
  doi:10.1287/opre.1030.0065

### 3.3 SAA optimality-gap confidence interval
*Effort: ~1 day. Data support: yes; partially built already.*

M independent SAA replications give a statistically optimistic lower bound; evaluating the chosen
first-stage plan on a much larger held-out scenario sample gives the upper bound; report the
**gap with a confidence interval** and sweep N to show where it stabilizes. `out_of_sample_seeds`
and the exact-vs-SAA comparison already exist in `docs/cvar_frontier.json` — this finishes it.

- Mak, W-K., Morton, D.P. & Wood, R.K. (1999). "Monte Carlo bounding techniques for determining
  solution quality in stochastic programs." *OR Letters* 24(1–2):47–56.
  doi:10.1016/S0167-6377(98)00054-6
- Kleywegt, Shapiro & Homem-de-Mello (2002). "The Sample Average Approximation Method for
  Stochastic Discrete Optimization." *SIAM J. Optimization* 12(2):479–502.

### 3.4 Newsvendor critical fractile — the decision-focused-learning centerpiece
*Effort: 3–4 days. Data support: yes, on car parts.*

Closes the loop between the forecasting track and the optimizer, currently the project's biggest
structural gap. The newsvendor optimum **is** the τ-quantile of demand where τ = Cu/(Cu+Co), and
because newsvendor cost *is* the pinball/check loss, **fitting a quantile regressor at τ is
provably the decision-optimal predictor** — no differentiable solver layer needed. Set an explicit
Cu/Co (service parts have a defensible asymmetry), fit LightGBM `objective="quantile", alpha=τ`,
and evaluate on **realized newsvendor cost, not MASE**. Show that the method winning on MASE is
not the method winning on decision cost.

- Ban, G-Y. & Rudin, C. (2019). "The Big Data Newsvendor: Practical Insights from Machine
  Learning." *Operations Research* 67(1):90–108.
  https://pubsonline.informs.org/doi/10.1287/opre.2018.1757
- Bertsimas, D. & Kallus, N. (2020). "From Predictive to Prescriptive Analytics." *Management
  Science* 66(3):1025–1044.
- Oroojlooyjadid, Snyder & Takáč (2020). "Applying Deep Learning to the Newsvendor Problem."
  *IISE Transactions* 52(4):444–463. https://arxiv.org/abs/1607.02177

**Scarf's min-max newsvendor** (1958, in Arrow/Karlin/Scarf; orig. RAND P-910,
https://www.rand.org/pubs/papers/P910.html) is the closed-form DRO version of the same decision —
mean/variance ambiguity only, no solver. Half a day of garnish that pairs beautifully.

---

## Track 4 — Evaluation integrity (cuts across everything)

### 4.1 Real-time / vintage data via ALFRED — high novelty, low effort
*Effort: 1–2 days. Data support: yes, same free FRED API.*

Census M3 and FRED series are **revised after first publication**. Backtesting on the currently
revised series uses data that did not exist at the forecast origin — an optimistic bias, and a
leakage class distinct from the usual ML ones. ALFRED (ArchivaL FRED, https://alfred.stlouisfed.org)
serves every historical vintage through the same API via a `vintage_dates` parameter.

- Croushore, D. & Stark, T. (2001). "A real-time data set for macroeconomists."
  *J. Econometrics* 105(1):111–130. Philadelphia Fed RTDSM:
  https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists
- "Forecast Evaluation for Data Scientists: Common Pitfalls and Best Practices,"
  https://arxiv.org/abs/2203.10716

Quantifying "using revised data flattered WAPE by X%" is a headline finding for one API parameter.
*Verify A34SNO vintage availability on the live site before publishing any claim.*

### 4.2 Reframe the Chronos result with contamination awareness
*Effort: ~0.5 day, mostly writing. Data support: n/a.*

**Do not add a fourth foundation model** — a 3-window benchmark cannot support it. The valuable
move is the skeptical framing: A34SNO is a public, FRED-mirrored macro series that Chronos's
pretraining corpus may contain, so a zero-shot result on it could partly reflect memorization.
Report it as illustrative, not as evidence of generalization.

- Karaouli et al. (2025). "How Foundational are Foundation Models for Time Series Forecasting?"
  *NeurIPS 2025*, https://arxiv.org/abs/2510.00742
- Toner et al. (2025). "Performance of Zero-Shot Time Series Foundation Models on Cloud Data,"
  ICLR 2025 workshop, https://arxiv.org/abs/2502.12944
- fev-bench (Amazon/AWS), https://arxiv.org/abs/2509.26468 — reports win rates with **bootstrapped
  confidence intervals** rather than point ranks; worth copying.
- GIFT-Eval, https://arxiv.org/abs/2410.10393 — ships a certified non-leaking pretraining corpus.

**Genuine opening:** no one appears to have rigorously benchmarked TSFMs zero-shot on intermittent
spare-parts demand — GIFT-Eval and fev-bench are dominated by dense series. Chronos-2
(https://arxiv.org/abs/2510.15821) against Croston/SBA/TSB on 2,674 car-parts series, scored with
CRPS and tested with Nemenyi, would be novel *and* fix the sample-size problem at once.

---

## Do NOT build — and say why, in the docs

Stating these is worth real credibility.

- **SPO+ / PyEPO.** Elmachtoub & Grigas (2022), *Management Science* 68(1):9–26,
  https://arxiv.org/abs/1710.08005 — applies only when uncertainty sits in the **objective
  coefficients** with a fixed feasible region. Our uncertain demand sits in **constraints**, so
  plain SPO+ is the wrong tool. The constraint-side extension (https://arxiv.org/abs/2311.08022)
  is research-grade. Survey: Mandi et al. (2024), *JAIR* 81:1623–1701,
  https://arxiv.org/abs/2307.13565. **Being able to say why it does not apply beats bolting it on.**
  Counterweight worth citing: Zalando's June 2025 production inventory system
  (https://engineering.zalando.com/posts/2025/06/inventory-optimisation-system.html) runs
  LightGBM + Monte Carlo + black-box optimization at 5M SKUs — plain predict-then-optimize, not DFL.
- **Causal inference / DML / causal forests on the distributor panel.** No randomization, no
  instrument, no treatment/control panel. Chernozhukov et al. (2018) and Wager & Athey (2018)
  both need unconfoundedness we cannot defend. *Narrow exception:* the observed ST lead-time
  extension is a genuine dated shock, and an event-study with non-ST parts as controls would be
  defensible — but with two snapshots it is a descriptive before/after, and must be labelled so.
- **Hierarchical reconciliation (MinT/ERM).** No hierarchy to reconcile — Monash car parts ships
  series IDs with no product taxonomy, and temporal reconciliation over 51 months yields 4 annual
  points.
- **Wasserstein DRO** (Mohajerin Esfahani & Kuhn, https://arxiv.org/abs/1505.05116). Highest
  technical ceiling, but the Euclidean-ball form needs an SOCP solver and CP-SAT cannot do conic
  constraints — a second solver stack. Stretch goal only.
- **SPCI** (Xu & Xie, ICML 2023) — fits a secondary quantile regressor on lagged residuals;
  nowhere near enough residual history on a 197-point series.
- **Any deep learning on this data.** The MLP already in our own model zoo scores
  `cv_r2_mean = −0.262` on family-grouped folds ([`leakage_progression.json`](leakage_progression.json)).
  That is the answer.
- **Hyperparameter optimization (Optuna).** Fold spread on the family-grouped folds is
  **±0.242 R²** (sd over 50 folds; range −0.62 to +0.44) against a champion mean of +0.082.
  Any tuning gain is a fraction of the noise band — a number we could not defend.
- **SHAP on the 177-feature lead-time model.** Most one-hot columns carry 1–5 observations; it
  would narrate noise with a nice waterfall. SHAP on a 6-feature model, or on manufacturer
  effects from the mixed model, is defensible.
- **Censored / Tobit / AFT regression.** Already retired: the censoring was a 75-row artifact,
  and only 5 of 742 new rows sit at the 30-week ceiling.

---

## Suggested sequencing

**If only three:** 1.2 (significance testing), 1.1 (distributional re-scoring), 3.4 (newsvendor).
All three run on the car-parts panel at genuine scale and tell one coherent story:
*"I found my metric was measuring the wrong functional, tested the ranking properly across 2,658
series, then showed the forecast that wins on accuracy is not the forecast that wins on decision
cost."*

**Week 1:** 1.2 → 1.1 → 3.1 (free) → 1.3 (deletion).
**Week 2:** 3.4 → 2.1 → 3.3.
**Opportunistic:** 4.1 (cheap, high novelty), 4.2 (mostly writing), 3.2 (second frontier chart).
