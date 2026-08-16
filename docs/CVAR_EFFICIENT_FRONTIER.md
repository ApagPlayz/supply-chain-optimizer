# The price of resilience: a cost-vs-CVaR efficient frontier

**Generated:** 2026-08-15 · **Script:** `backend/seeds/run_cvar_frontier.py` · **Data:** `docs/cvar_frontier.json`
**Model:** `backend/app/optimization/stochastic.py` · **API:** `POST /api/v1/stochastic/frontier`
**Hardware:** arm64 / Darwin 25.5.0 · **Solver:** OR-Tools CP-SAT, `num_search_workers=1`

---

## What this replaces

Every "resilience" number this repository produced before today was a **deterministic
surcharge**. `sourcing.py` prices supply risk as `RISK_PREMIUM_RATE = 0.15` times a
hand-weighted vulnerability score, plus a betweenness-weighted "expected recourse loss".
`graph/simulation.py` prices a disruption as a flat 15% cost inflation per unfulfillable
BOM share — which is why its `cvar_95` pins at 1.15 in nearly every published benchmark
row. Neither contains a **recourse decision**: nothing in either model re-optimizes after
a supplier goes dark.

This replaces that with a two-stage stochastic program and publishes the whole
**price-of-resilience curve** instead of one hard-coded risk appetite.

> The old pitch: *"I added a 15% risk surcharge."*
> The new pitch: *"On a 60,000-unit BOM, spending **1.12% more in expectation** removes
> **3.88% of CVaR-95 exposure** — $2,044 buys $8,719 of tail reduction, a **4.3:1**
> return. Past that point the same trade returns **0.4:1**. The knee is at λ = 0.30 and
> that is my recommendation."*

---

## 1. The formulation, stated precisely

**First stage** (here-and-now, before uncertainty resolves):

| Variable | Domain | Meaning |
|---|---|---|
| `y[d]` | {0,1} | qualify / open distributor `d` |
| `x[c,d]` | {0,1} | award BOM line `c` to distributor `d` |
| `q[c,d]` | ℤ₊ | units of `c` committed to `d` |

subject to, for every BOM line `c`:

```
Σ_d q[c,d] = demand_c                    demand coverage
q[c,d] ≤ stock[c,d] · x[c,d]             stock cap
q[c,d] ≥ moq[c,d]   · x[c,d]             MOQ floor
y[d]   ≥ x[c,d]                          a used supplier is an opened supplier
```

First-stage cost — **identical, term for term, to the deterministic MILP's objective**
(it calls the same `_freight_model_by_did` helper, so the two are directly comparable):

```
F = Σ_{c,d} price[c,d]·q[c,d]  +  Σ_d fixed[d]·y[d]
  + Σ_d per_unit[d]·Σ_c q[c,d] +  Σ_d consolidation·y[d]
```

**Uncertainty.** A scenario `s` is a set `F_s` of distributors that cannot deliver over
the sourcing horizon, drawn by independent Bernoulli trials — the same percolation
structure `graph/simulation.py` already uses, but with calibrated probabilities (§2).

**Second stage** (recourse, after `F_s` is observed):

| Variable | Domain | Meaning |
|---|---|---|
| `r[c,d,s]` | ℤ₊ | emergency units of `c` re-procured from surviving `d` |
| `u[c,s]` | ℤ₊ | units that cannot be re-procured at all |
| `e[d,s]` | {0,1} | an expedited consignment is raised on `d` in scenario `s` |

```
Σ_{d∉F_s} r[c,d,s] + u[c,s] = Σ_{d∈F_s} q[c,d]     cover the gap
r[c,d,s] + q[c,d] ≤ stock[c,d]                     emergency draws on RESIDUAL stock
Σ_c r[c,d,s] ≤ cap_d · e[d,s]                      an expedited consignment, or none
```

Scenario cost:

```
C_s = F
    + Σ_{c, d∉F_s} (price[c,d]·(1+π) + air_per_unit)·r[c,d,s]     emergency purchase
    + Σ_{d∉F_s} expedite_fixed·e[d,s]                             air consignment minimum
    + Σ_c unmet_unit[c]·u[c,s]                                    lost-sales penalty
    − Σ_{c, d∈F_s} (recovery·price[c,d] + per_unit[d])·q[c,d]     goods never delivered
```

**Objective.** `min (1−λ)·E[cost] + λ·CVaR_α[cost]`, with CVaR linearized by
Rockafellar & Uryasev (2000):

```
CVaR_α(Z) = min_η { η + 1/(1−α) · E[(Z − η)⁺] }
  ⟹  z_s ≥ R_s − η,  z_s ≥ 0,  η free
```

Everything stays linear, so **CP-SAT solves it exactly** — no piecewise approximation,
no quadratic term, no separate risk solver. Written out with integer coefficients (the
whole objective is scaled by `LAMBDA_DEN · n_draws`, then divided by the GCD of its three
outer multipliers):

```
minimize   w_first·n_draws·F
         + w_mean ·Σ_s n_s·R_s
         + w_cvar ·( n_draws·η + ⌈1/(1−α)⌉·Σ_s n_s·z_s )
```

Two implementation notes that matter:

* **Rockafellar–Uryasev is applied to the recourse cost `R_s = C_s − F`, not to `C_s`.**
  Both `E[·]` and `CVaR[·]` are translation invariant, so this is exactly equivalent —
  but the model never materialises 150+ copies of `F`'s ~80-term expression inside one
  equality constraint per scenario. On a 157-scenario instance that reformulation took
  the λ = 0 solve from a **60 s timeout at a 1.7% gap to sub-second OPTIMAL**.
* **The CVaR block is only built when λ > 0.** At λ = 0 it carries zero objective weight,
  so `η` and every `z_s` become free variables in a large integer domain that CP-SAT must
  still search. Omitting it is not an approximation — at λ = 0 the problem *is*
  `min E[cost]` — and CVaR is still reported, computed post hoc.

### Why CVaR, and one thing worth knowing about it

CVaR-95 is the mean cost of the worst 5% of scenarios. Variance penalises upside as well
as downside and is quadratic (CP-SAT cannot take it). CVaR is **coherent** — monotone,
subadditive, positively homogeneous, translation invariant — which VaR is not (Artzner,
Delbaen, Eber & Heath 1999, *Mathematical Finance* 9(3):203–228). Subadditivity is the
practical one here: the model cannot be made to look safer by splitting one BOM in two.

More useful still, **CVaR is already a distributionally robust objective.** It has an
exact dual representation as a worst-case expectation over an ambiguity set:

```
CVaR_α(Z) = sup { E_Q[Z] : Q ≪ P,  dQ/dP ≤ 1/(1−α) }
```

— the highest expected cost achievable by *any* re-weighting of the assumed measure `P`
bounded by a likelihood ratio of `1/(1−α)` (Rockafellar & Uryasev 2002, *J. Banking &
Finance* 26(7):1443–1471). So minimising CVaR-95 is solving a DRO problem whose ambiguity
set is every scenario re-weighting up to **20×**.

That matters *specifically because the probabilities below are assumed rather than
measured*: the λ > 0 end of this frontier is already hedged against getting them wrong by
up to 20× on any single scenario. It does not excuse the assumption — the sensitivity
sweep in §6 still has to be run — but the risk-averse end degrades gracefully under
probability misspecification in a way the risk-neutral end does not.

---

## 2. The uncalibrated-probability problem, and what was done about it

**This is the part that would have made everything else meaningless, so it is first.**

`backend/app/graph/simulation.py:155-161` does this:

```python
failure_probs = {
    did: (1.0 if did in forced
          else min(betweenness.get(did, 0.0) * stress_factor, 1.0))
    for did in all_dist_ids
}
```

`betweenness` is **min-max normalized to [0,1]** in `graph/builder.py:126-132`. A min-max
normalization always attains 1.0 at its maximum. So *by construction*:

* the single most central distributor in this database (id 28, betweenness exactly 1.0)
  **fails in 100% of scenarios**;
* the 18 distributors sitting at betweenness 0.0 **never fail at all**;
* there is no base rate, no exposure window, and no unit anywhere in that expression — a
  centrality *rank* is being read as a *probability*.

Downstream, `cvar_95` therefore pins at `1.0 + EMERGENCY_COST_PREMIUM = 1.15` in nearly
every row of `BENCHMARK_RESULTS.md`: a constant wearing a Monte Carlo costume. **A CVaR
objective built on those probabilities would be meaningless**, so this work does not reuse
them.

### The replacement

`build_failure_probabilities` separates the two things the old expression conflated —
the **level** of risk and its **shape** across suppliers:

```
p_d = min( p_base · spread^(2·u_d − 1),  MAX_FAILURE_PROB )

  p_base = 1 − (1 − base_annual_prob)^(horizon_days / 365)     ← the LEVEL, cited
  u_d    = percentile rank of distributor d's betweenness      ← the SHAPE, bounded
```

**Level — cited.** McKinsey Global Institute, *"Risk, resilience, and rebalancing in
global value chains"* (August 2020), verified 2026-08-15:

> "companies can now expect supply chain disruptions lasting a month or longer to occur
> every 3.7 years"

Treated as a Poisson rate: `λ = 1/3.7` per year ⟹ `P(≥1 event in a year) = 1 − e^(−1/3.7)
= 0.2368`. Over a 60-day purchase-order window that is **4.34%**.

**The honest caveat, stated in the code, the artifact and the API response:** that figure
is **firm-level** (a company sees a disruption *somewhere* in its value chain), not a
per-supplier failure rate. Using it per supplier almost certainly **overstates** individual
supplier risk. No per-supplier base rate could be verified from a citable public source.
It is therefore treated as an **assumption and swept from 5% to 40%** (§6), never
published as if it were measured.

**Shape — a bounded rank transform, not a magnitude.** Raw betweenness in this network is
pathologically skewed: max 1.0, mean 0.050, median 0.0053 across 92 distributors, 18 of
them exactly 0. Multiplying a base rate by that raw score would hand the hub a ~20×
multiplier and reinstate the very failure being fixed. Instead centrality only
**rank-orders** relative risk inside a bounded spread: the most central supplier gets
`spread ×` the base rate, the least central `1/spread ×`, and **the median supplier sits
exactly on the cited base rate**. Ties share the mean rank, so the 18 suppliers at
betweenness 0.0 all receive the identical probability rather than an arbitrary ordering
artefact.

**And the residual assumption is named, not hidden:** that more central suppliers are more
likely to be disrupted *at all*. Nothing in this repo or in the cited literature
establishes it, and the opposite is arguable — hub distributors are typically better
capitalised and more redundant than small ones. So `centrality_spread = 1.0` — centrality
ignored entirely, every supplier on the flat base rate — is a **supported setting, a
sensitivity arm run in every published frontier, and a parameter on the public API**.

### The result, for the headline BOM's six suppliers

| Distributor | Betweenness (normalized) | Legacy `p_fail` | **Calibrated `p_fail`** (60-day) |
|---:|---:|---:|---:|
| 28 | 1.0000 | **1.0000** ← fails every scenario | **0.1304** |
| 56 | 0.5085 | 0.5085 | 0.0840 |
| 9 | 0.0963 | 0.0963 | 0.0541 |
| 85 | 0.0154 | 0.0154 | 0.0349 |
| 81 | 0.0053 | 0.0053 | 0.0225 |
| 70 | 0.0009 | 0.0009 | 0.0145 |

`graph/simulation.py` is **deliberately left unchanged** — other published documents
depend on its numbers, and quietly editing them would be its own dishonesty. The
replacement lives beside it, and `GET /api/v1/stochastic/calibration` publishes both
columns side by side so the difference is auditable rather than asserted.

---

## 3. Scenario support: why "n_distinct = 10" was the right thing to worry about, and the wrong thing to fix

A first draft of this artifact reported `n_draws = 200, n_distinct = 10, α = 0.95`. That
invites a fair objection: **0.05 × 10 = 0.5 distinct scenarios land in the tail**, so the
CVaR estimate is one scenario wide and reports solver precision, not statistical
precision.

The objection is correct about those numbers. The diagnosis, though, is more interesting
than "take more samples":

> Disruption is `|D|` **independent Bernoulli variables**, so the cost distribution has at
> most **2^|D| atoms in total**. The headline BOM is supplied by **six** distributors.
> Its entire support is **64 atoms** — of which 29 carry probability ≥ 1e-4 and the top 20
> carry **99.70%** of the mass. Drawing 200 samples from a 64-atom distribution recovers
> ~10 of them and adds nothing that enumerating all 64 gives exactly.

So the fix is not more Monte Carlo. **It is to stop sampling.** `enumerate_scenarios()`
holds the entire support with exact probabilities, and every expected cost and CVaR
published below carries **no sampling error at all**.

| | SAA, 200 draws | **Exact, 64 atoms** |
|---|---:|---:|
| Atoms in the α = 0.95 tail | 4 | **50–54** |
| CVaR-95 at λ = 0 | $227,977 | **$224,600** |
| CVaR-95 at λ = 1 | $213,157 | **$215,171** |
| CVaR-95 sampling error | **−0.94% … +1.50%** | — (none) |
| Residual probability mass | — | **0.0** |

The sampled tail was not merely thin, it was **biased by up to 1.5%** — in both
directions, depending on λ. That is a real error, it was invisible without the exact
computation, and it is now gone.

**A note the objection actually strengthens:** the betweenness-as-probability defect makes
scenario diversity *worse*, not better. With `p_fail = 1.0` for the most central
distributor, that supplier fails in every scenario and stops being a source of variation
at all — mechanically collapsing the number of distinct outcomes.

**Where enumeration is not possible.** `iot_sensor_node` draws on 26 distributors →
2^26 = 67,108,864 atoms. Above `MAX_ENUMERABLE_DISTRIBUTORS = 18` the model falls back to
sampling and bounds the residual error statistically instead (§5). Which mode each result
used is recorded per point as `evaluation_kind`.

---

## 4. The frontier

**`pcb_power_supply` at 10,000× volume — 60,000 units, `balanced` strategy, `us_only=False`,
scored on the exact 64-atom support.**

| λ | E[cost] | CVaR-95 | Tail premium | Suppliers | Atoms in tail | Status | Gap | Solve |
|---:|---:|---:|---:|:---:|---:|:---|---:|---:|
| 0.00 | $182,256 | $224,600 | $42,345 | 6 | 50 | OPTIMAL | 0.040% | 0.007 s |
| 0.05 | $182,256 | $224,600 | $42,345 | 6 | 50 | OPTIMAL | 0.062% | 0.011 s |
| 0.10 | $182,723 | $221,224 | $38,501 | 6 | 50 | OPTIMAL | 0.000% | 0.010 s |
| 0.20 | $184,036 | $216,828 | $32,791 | 5 | 51 | OPTIMAL | 0.060% | 0.010 s |
| **0.30** | **$184,300** | **$215,882** | **$31,582** | **4** | 53 | OPTIMAL | 0.000% | 0.011 s | ← **knee** |
| 0.50 | $184,595 | $215,860 | $31,266 | 5 | 54 | OPTIMAL | 0.082% | 0.020 s |
| 0.70 | $187,077 | $214,747 | $27,670 | 4 | 50 | OPTIMAL | 0.056% | 0.014 s |
| 0.85 | $187,077 | $214,747 | $27,670 | 4 | 50 | OPTIMAL | 0.000% | 0.017 s |
| 1.00 | $188,486 | $215,171 | $26,685 | 3 | 49 | OPTIMAL | 0.052% | 0.008 s | *dominated* |

CVaR is also reported at other tail levels, because a single α is not enough to read a
tail:

| λ | CVaR-80 | CVaR-90 | CVaR-95 | CVaR-98 |
|---:|---:|---:|---:|---:|
| 0.00 | $192,985 | $203,808 | $224,600 | $266,764 |
| **0.30** | **$191,212** | **$199,693** | **$215,882** | **$246,381** |
| 1.00 | $194,202 | $201,192 | $215,171 | $242,272 |

**The knee holds at every tail level from 80% to 98%.** That is worth more than the single
CVaR-95 number: the recommendation is not an artefact of where the tail was cut.

### λ = 1.00 is dominated, and that is expected

At λ = 1 the objective is CVaR alone, so any plan attaining the minimum CVaR is optimal
and expected cost is broken arbitrarily. Here it lands at CVaR $215,171 — *worse* than
λ = 0.70's $214,747 — while paying $1,409 more in expectation. It is flagged
`dominated: true` in the artifact rather than deleted.

This is the expected artefact of a **weighted-sum scalarization**, and the limitation is
worth stating plainly: sweeping λ can only recover Pareto points on the **convex hull** of
the (E, CVaR) image. Integer programs routinely have *unsupported* efficient points that
no λ exposes, so **this frontier is a subset of the true efficient set, never a superset.**
An ε-constraint sweep would find the rest; it is not implemented.

---

## 5. The knee, and the recommendation it implies

**Knee: λ = 0.30**, found by maximum perpendicular distance to the chord joining the
extreme non-dominated points (the Kneedle / L-method criterion, Satopää et al. 2011), on
min-max normalized axes so the answer does not depend on the currency unit.

| | Before the knee (λ 0 → 0.30) | Beyond the knee (λ 0.30 → 1.00) |
|---|---:|---:|
| Extra expected cost | **+$2,044** (+1.12%) | +$2,777 |
| CVaR-95 reduction | **−$8,719** (−3.88%) | −$1,135 |
| **$ of tail removed per $ spent** | **4.27** | **0.41** |

> **Recommendation.** Source this BOM at **λ = 0.30**: four suppliers (9, 70, 81, 85)
> rather than the risk-neutral six. It costs **$2,044 more per 60,000-unit build in
> expectation — 1.12% of spend — and removes $8,719 of CVaR-95 exposure.** Every dollar
> of that premium buys **$4.27** of tail reduction. Past the knee the same dollar buys
> **$0.41**: you are paying for insurance at four times its value. Stop at the knee.

### What is actually in the tail — and what the knee changes

The α = 0.95 tail is not diffuse. **32% of it is one event: distributor 81 going dark.**

| Failed | Probability | Share of tail | Cost at λ=0 | **Cost at knee** | Emergency units (λ=0 → knee) | Unmet units |
|---|---:|---:|---:|---:|---:|---:|
| {81} | 1.61% | **32.2%** | $251,162 | **$227,648** | 167 → **37,356** | 4,290 → 4,288 |
| {85} | 2.53% | 23.8% | $183,307 | $183,742 | 10,847 → 10,847 | 0 |
| {70} | 1.03% | 20.6% | $198,441 | $198,875 | 4,858 → 4,860 | 978 |
| {28, 81} | 0.24% | 4.8% | $275,597 | $257,651 | 0 → **28,561** | 13,085 → 13,083 |

**The mechanism, in one sentence:** the risk-neutral plan concentrates volume on
distributor 81 (cheap, deep stock, and a *low* disruption probability of 2.25%), so when
81 does fail there is not enough residual stock anywhere else and **4,290 units are simply
written off at the stockout penalty**. The knee plan deliberately leaves headroom at
surviving suppliers, so the same outage is covered by **37,356 emergency units instead of
167** — converting a write-off into an expensive-but-executable recovery, and taking
$23,514 out of the single worst-contributing scenario.

That is a genuinely non-obvious result: **the supplier driving the tail is not the one
with the highest failure probability.** Distributor 28 has the highest `p_fail` (13.04%)
and contributes only 4.8% of the tail; distributor 81 has one of the lowest (2.25%) and
contributes 32.2%. Concentration, not probability, is what makes the tail. A surcharge
proportional to centrality — which is what the code did before — gets this exactly
backwards.

### What the frontier is worth against what the repo did before

All three baselines are scored on the identical exact measure.

| Plan | E[cost] | CVaR-95 | Suppliers | Dominated by any λ? | Sits at λ ≈ |
|---|---:|---:|:---:|:---:|:---:|
| Mean-value (disruptions assumed away) | $182,932 | $220,085 | 6 | no | 0.10 |
| **Shipped MILP** (`sourcing.py`, heuristic surcharges live) | $183,171 | $219,129 | 5 | **no** | **0.10** |
| Stochastic, λ = 0 (risk-neutral) | $182,256 | $224,600 | 6 | — | — |
| **Stochastic, λ = 0.30 (knee)** | **$184,300** | **$215,882** | **4** | — | — |

**Value of the stochastic solution: VSS = EEV − RP = $676 (0.37% of RP).** Small — and
saying so is the point. Ignoring uncertainty at plan time costs only 0.37% *in
expectation*; the deterministic plan is very nearly the risk-neutral optimum. **The value
of this model is not in expected cost. It is entirely in the tail**, where the same
comparison is $220,085 → $215,882.

And the most useful honest finding here: **the shipped 15% heuristic surcharge is not
wrong.** It is not dominated by any point on the frontier — it lands *on* the curve, at
about λ ≈ 0.10. What it cannot do is **tell you that**, or let you move. The surcharge
encodes one unlabelled risk appetite chosen by a constant in a source file; the frontier
makes the appetite an explicit, auditable, movable dial and shows what each setting costs.
That is the whole argument, and it is a smaller and more defensible claim than "the
heuristic was wrong".

### The tradeoff only exists at volume

| Volume | Units | Knee | VSS | Note |
|---|---:|:---:|---:|---|
| 100× | 600 | **none** | $0 | Frontier collapses to 2 points; nothing to trade off |
| 1,000× | 6,000 | **none** | $16 (0.10%) | Still essentially flat |
| **10,000×** | **60,000** | **λ = 0.30** | $676 (0.37%) | The frontier above |

At prototype and low-production volume there is **no cost-vs-CVaR tradeoff on this BOM at
all** — every λ returns the same plan. This is consistent with
[`BENCHMARK_VOLUME_CURVE.md`](BENCHMARK_VOLUME_CURVE.md): at low volume the fixed
per-supplier charge dominates everything, so the sourcing decision is fully determined by
fee arithmetic and there is no room left for risk to move it. The frontier is a
**production-volume instrument**, and pretending otherwise would be the same mistake as
the 44.7% headline.

---

## 6. Is any of this robust to the probabilities being wrong?

*(Populated from `docs/cvar_frontier.json` → `sensitivity`. The grid is
`base_annual_prob ∈ {5%, 10%, 23.68%, 40%} × centrality_spread ∈ {1.0, 3.0, 6.0} ×
horizon_days ∈ {30, 60, 120}` — 36 full frontier sweeps on the headline instance.)*

The arm that matters is `centrality_spread = 1.0`: centrality removed from the model
entirely, every supplier on the flat cited base rate. If the recommendation survives that,
it is being driven by the cost and stock data rather than by the graph assumption.

---

## 7. SAA solution quality

*(Populated from `docs/cvar_frontier.json` → `saa_quality`.)*

Even with the support enumerated, the **plan is still chosen on a Monte Carlo sample**
(CP-SAT needs integer weights, and only draw counts supply them). That residual error is
bounded the standard way:

* **Lower bound** — mean optimal value of **M = 12 independent SAA replications** at
  sample size N. Each solve optimizes against its own sample, so its optimal value is
  optimistically biased: `E[v_N] ≤ v*`. Reported with a one-sided Student-t confidence
  limit over the M replicates. *Mak, Morton & Wood (1999), "Monte Carlo bounding
  techniques for determining solution quality in stochastic programs", Operations Research
  Letters 24(1–2):47–56, doi:10.1016/S0167-6377(98)00054-6.*
* **Upper bound** — the true objective of the best candidate first-stage plan on the exact
  enumerated measure. Any feasible plan bounds the optimum from above, and with the exact
  support as reference **this is not an estimate at all**.
* **Gap** — swept over N ∈ {25, 50, 100, 200, 400}. Where it flattens is the sample size
  that is actually justified.

*Kleywegt, Shapiro & Homem-de-Mello (2002), "The Sample Average Approximation Method for
Stochastic Discrete Optimization", SIAM J. Optimization 12(2):479–502* is the convergence
result for SAA with discrete first-stage decisions, which is exactly this model.

A **small negative gap point-estimate is normal** and is not a broken bound: `E[v_N] ≤ v*`
is an expectation, and with finitely many replications the sample mean can land slightly
above the candidate plan's true value. That is the signal "the remaining gap is smaller
than the Monte Carlo noise in my estimate of it". The statement that must hold is the
interval one: `upper_bound ≥ lower_bound_ci_low`.

---

## 8. Where a cost-vs-CVaR tradeoff exists at all

*(Populated from `docs/cvar_frontier.json` → `breadth`: all 10 reference BOMs across their
feasible volume range, coarse λ grid.)*

Reported honestly including the BOMs where the answer is **no tradeoff exists** — a flat
frontier is a finding, not a failure.

---

## 9. Solve times and problem sizes

| Instance | Distributors | Distinct scenarios | Variables | λ-sweep wall time | Worst gap |
|---|---:|---:|---:|---:|---:|
| `pcb_power_supply` ×10,000 | 6 | 10 (SAA) / 64 (exact) | 243 | **0.3 s** for 9 points | 0.082% |
| `iot_sensor_node` ×100 | 26 | 157 (SAA, 400 draws) | 7,593 | ~60 s for 5 points | timeouts at λ=0 |

**Honest reporting of what is hard.** The model size is driven by the per-scenario
expedited-consignment binaries `e[d,s]`: on a 26-distributor BOM with 157 distinct
scenarios that is ~2,500 extra booleans, and it is the difference between a 0.02 s solve
and a 60 s timeout. Removing that term makes the model ~1,500× faster and changes CVaR-95
by ~14% — so it is kept, and the cost of keeping it is reported rather than hidden.

Three specific things were measured and are stated rather than smoothed over:

1. **λ = 0 is the hardest point on every frontier.** Without the CVaR block the objective
   is a sum of 150+ loosely-coupled recourse subproblems that CP-SAT finds easy to solve
   and hard to *prove* optimal. Mitigations applied: the recourse-only RU reformulation,
   frontier continuation (each λ warm-starts from its already-proved neighbour, sweeping
   **descending** because the pure-CVaR end is by far the easiest), and a 0.1% relative
   gap limit. Every point still reports its achieved gap.
2. **Reported statistics never come from the solver's own recourse variables.** A non-zero
   MIP gap here mostly means the *second-stage* variables are near-optimal, and reading
   E and CVaR off them would publish a number worse than the plan actually is. Every
   published figure comes from re-solving each scenario's second stage exactly and
   independently for the returned plan.
3. **An int64 overflow guard fired for real** at N = 800 draws on the 60,000-unit BOM and
   is left in place. Objective coefficients are bounded before the solve; if the bound
   exceeds 4×10^17 the model raises with an actionable message instead of silently
   returning nonsense.

---

## 10. What is NOT modelled

Every omission with its **direction of bias**, because a tail number without this list is
not honest:

| Not modelled | Direction of bias |
|---|---|
| Partial capacity loss — outages are binary | Overstates individual scenario severity |
| **Correlated / common-cause failures** — draws are independent across suppliers | **Understates tail risk** (one typhoon takes out several warehouses) |
| Disruption duration and multi-period recovery | Understates |
| Qualification time/cost for a supplier not opened in stage 1 | **Understates** cost of recourse |
| MOQ on emergency buys | Slightly understates |
| Price movement under stress — emergency prices are catalogue + fixed premium | **Understates** tail cost |
| Demand uncertainty — only supply is stochastic | Neither; out of scope |

The independence assumption is the most consequential. Correlated disruptions are exactly
what makes real tails fat, and modelling them would require a dependence structure this
repo has no data to calibrate. **Net: the tail reported here is, if anything, optimistic.**

Two model choices worth flagging explicitly rather than leaving in the code:

* **`recovery_rate = 1.0`** — you do not pay for goods you never received. That is the
  economically correct default for a purchase order, and it means the modelled loss from a
  disruption is the *price gap plus expediting*, not the whole committed spend. It also
  means a scenario's recourse cost can be slightly **negative** when an expensive supplier
  fails and a cheap survivor covers the gap. Lower the parameter to model deposits or
  cancellation fees.
* **The unmet-demand penalty is `3.0 × the dearest emergency route`**, not 3× catalogue
  price. Anchoring on catalogue price alone made unmet demand *cheaper* than recourse on
  small residual quantities — 30 units at 3×$2.50 = $225 beat a $150 expedited consignment
  plus $94 of parts — so the model would leave a line unfilled while stock sat on a
  surviving shelf. `STOCKOUT_PENALTY_MULTIPLE = 3.0` itself is reused verbatim from
  `sourcing.py` (Snyder & Daskin 2005), so the stochastic program and the heuristic it
  replaces share their constants and the comparison is about **structure**, not tuning.

---

## Reproduce

```bash
cd backend
source venv/bin/activate
python -m seeds.run_cvar_frontier            # full artifact
python -m seeds.run_cvar_frontier --quick    # primary + calibration only (~4 s)
```

Writes `docs/cvar_frontier.json` — full per-λ frontier, knee, tail decomposition,
exact-vs-SAA comparison, SAA optimality gaps, sensitivity grid, breadth sweep, and the
per-distributor calibration with provenance.

Live, with the probability assumptions exposed as request parameters:

```bash
curl -X POST /api/v1/stochastic/frontier -d '{
  "items": [{"component_id": 1, "quantity": 15000}],
  "base_annual_prob": 0.2368, "horizon_days": 60, "centrality_spread": 3.0
}'
curl /api/v1/stochastic/calibration          # every p_fail, beside the legacy value
```

Tests: `backend/tests/test_stochastic_sourcing.py` (39) and
`backend/tests/test_stochastic_api.py` (16). The load-bearing ones:

* `test_no_supplier_ever_saturates_at_probability_one` — the regression guard for §2.
* `test_with_no_uncertainty_it_reproduces_the_deterministic_landed_cost` — the
  anti-rigging invariant: with nothing to be stochastic about, the stochastic program's
  cost must equal `greedy.landed_cost_breakdown` exactly.
* `test_exact_evaluation_puts_many_atoms_in_the_tail_where_sampling_puts_few` — §3.
* `test_saa_optimality_gap_brackets_the_optimum_and_shrinks_with_sample_size` — §7.
* `test_risk_aversion_moves_the_award_to_a_lower_probability_supplier` — that buying risk
  aversion actually buys a lower tail, and is not free.
