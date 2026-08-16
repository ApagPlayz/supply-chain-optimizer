# The price of resilience: a cost-vs-CVaR efficient frontier

**Script:** `backend/seeds/run_cvar_frontier.py` · **Data:** `docs/cvar_frontier.json`
**Model:** `backend/app/optimization/stochastic.py` · **API:** `POST /api/v1/stochastic/frontier`
**Solver:** OR-Tools CP-SAT, `num_search_workers=1` · **Run date, commit, input hashes and
hardware:** see [Provenance](#provenance) at the foot of this document, generated from the
artifact rather than typed here.

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

<!-- GENERATED:headline_pitch:BEGIN -->

> The old pitch: *"I added a 15% risk surcharge."*
> The new pitch: *"On a 60,000-unit BOM, spending **1.12% more in expectation** removes **3.88% of CVaR-95 exposure** — $2,044 buys $8,719 of tail reduction, a **4.27:1** return. Past that point the same trade returns **0.41:1**. The knee is at λ = 0.3 and that is my recommendation."*

<!-- GENERATED:headline_pitch:END -->

---

## 0. Solve quality: which points are actually on the frontier

> **Read this before any number below.** A frontier point is only a frontier point if
> CP-SAT actually *proved* its first-stage choice near-optimal. A previous full run of
> this script published 153 λ-points of which **49 carried an optimality gap above 5%
> (worst: 93.4%)** and 22 returned status `FEASIBLE` rather than `OPTIMAL` at the 15 s /
> 60 s time limits — and nothing in the artifact or in this document said so. A plan
> whose objective could be 93% away from the unknown optimum tells you nothing about the
> price of resilience.
>
> That is now fixed at the source. **Every point in `docs/cvar_frontier.json` carries
> `solver_status`, `mip_gap_pct`, `hit_time_limit`, `converged` and, when it failed to
> converge, an `excluded_reason`.** Non-converged points are *kept* — deleting them would
> hide the cost of the compute budget — but they are excluded from every knee, every
> reported spread and every headline figure in this document. The rule is
> `converged := status == OPTIMAL (proved to within the 0.1% relative gap limit) OR
> mip_gap_pct ≤ 5%`.
>
> **The headline is unaffected.** Every λ-solve in the primary arm — the arm §4, §5 and
> the "$ of tail removed per $ spent" figure are built on — returned `OPTIMAL`, at the
> gaps shown per point in the §4 table. Whatever fails to converge does so in the breadth
> and sensitivity arms, on much larger supplier pools against a much shorter per-solve
> budget, and the tables below flag those instances individually. That the primary arm is
> fully proved is asserted by `test_the_headline_arm_is_fully_proved`, not assumed.

<!-- GENERATED:solve_quality:BEGIN -->

Across the whole run, **387 λ-solves** were performed. **330** converged; **57** did not and are excluded from every knee, spread and headline below. **63** returned a status other than `OPTIMAL`.

| | |
|---|---:|
| Solves | 387 |
| Converged (`OPTIMAL`, or gap ≤ 5%) | 330 |
| **Not converged — excluded from the frontier** | **57** |
| Non-`OPTIMAL` solver returns | 63 |
| MIP gap: median | 0.052% |
| MIP gap: p90 | 51.102% |
| MIP gap: p99 | 91.504% |
| **MIP gap: worst** | **92.779%** |
| Solves above a 1% gap | 62 |
| Solves above a 5% gap | 57 |

Per arm:

| Arm | Solves | Converged | Non-`OPTIMAL` | Worst gap |
|---|---:|---:|---:|---:|
| `breadth` | 150 | 93 | 63 | 92.779% |
| `primary` | 27 | 27 | 0 | 0.082% |
| `saa_endpoint_stability` | 30 | 30 | 0 | 0.098% |
| `sensitivity` | 180 | 180 | 0 | 0.100% |

Worst single solve: arm `breadth`, instance `automotive_ecu_x1`, λ = 1.0 — status `FEASIBLE` at a **92.779%** gap against a 15.0s limit.

<!-- GENERATED:solve_quality:END -->

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

Until 2026-08-16, `backend/app/graph/simulation.py` did this:

```python
failure_probs = {
    did: (1.0 if did in forced
          else min(betweenness.get(did, 0.0) * stress_factor, 1.0))
    for did in all_dist_ids
}
```

and `betweenness` was **min-max rescaled to [0,1]** on top of networkx's own
normalization in `graph/builder.py`. A min-max rescale always attains 1.0 at its
maximum. So *by construction*:

* the single most central distributor in this database (id 28) **failed in 100% of
  scenarios**;
* the 18 distributors sitting at a rescaled betweenness of 0.0 **never failed at all**;
* there was no base rate, no exposure window, and no unit anywhere in that expression — a
  centrality *rank* was being read as a *probability*.

Downstream, `cvar_95` therefore pinned at `1.0 + EMERGENCY_COST_PREMIUM = 1.15` in nearly
every row of `BENCHMARK_RESULTS.md`: a constant wearing a Monte Carlo costume. **A CVaR
objective built on those probabilities would be meaningless**, so this work never reused
them.

> **Status note, 2026-08-16.** Separate work has since removed the min-max rescale from
> `graph/builder.py` and pointed `graph/simulation.py` at the very
> `build_failure_probabilities` described below, so the defect no longer ships. The
> section is kept in the past tense rather than deleted: it is the reason this model
> calibrates its own probabilities instead of inheriting them, and the argument does not
> survive being quietly tidied away. One consequence for *this* document is that the
> "legacy `p_fail`" column that used to sit beside the calibrated one can no longer be
> reproduced from live code — the rescaled betweenness it was read off no longer exists —
> so the table below reports the betweenness and the calibrated probability the committed
> artifact actually contains, and nothing it cannot substantiate.

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

**Shape — a bounded rank transform, not a magnitude.** Betweenness in this network is
pathologically skewed, with a long tail of distributors at or near zero. Multiplying a
base rate by that raw score would hand the hub an order-of-magnitude multiplier and
reinstate the very failure being fixed. Instead centrality only **rank-orders** relative
risk inside a bounded spread: the most central supplier gets `spread ×` the base rate,
the least central `1/spread ×`, and **the median supplier sits exactly on the cited base
rate**. Ties share the mean rank, so suppliers with identical betweenness all receive the
identical probability rather than an arbitrary ordering artefact. This is also why the
table below is unchanged by the `graph/builder.py` normalization fix: a rank transform is
invariant to any monotone rescaling of its input.

**And the residual assumption is named, not hidden:** that more central suppliers are more
likely to be disrupted *at all*. Nothing in this repo or in the cited literature
establishes it, and the opposite is arguable — hub distributors are typically better
capitalised and more redundant than small ones. So `centrality_spread = 1.0` — centrality
ignored entirely, every supplier on the flat base rate — is a **supported setting, a
sensitivity arm run in every published frontier, and a parameter on the public API**.

### The result, for the headline BOM's six suppliers

<!-- GENERATED:calibration_table:BEGIN -->

| Distributor | Betweenness | **Calibrated `p_fail`** (60-day) |
|---:|---:|---:|
| 28 | 0.245752 | **0.1304** |
| 56 | 0.183436 | **0.0840** |
| 9 | 0.124957 | **0.0541** |
| 85 | 0.099427 | **0.0349** |
| 81 | 0.025237 | **0.0225** |
| 70 | 0.017099 | **0.0145** |

Base rate 0.236827 annual over 60 days, centrality spread 3.0, capped at `MAX_FAILURE_PROB` = 0.5. **No supplier is anywhere near probability 1.0** — which is the whole point. The resulting scenario set has P(no disruption) = 0.69 and 0.335 expected failures per scenario over 6 distributors.

<!-- GENERATED:calibration_table:END -->

`GET /api/v1/stochastic/calibration` publishes the same per-distributor figures live, so
the calibration is auditable rather than asserted.

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

<!-- GENERATED:exact_vs_saa_table:BEGIN -->

| | SAA, 200 draws | **Exact, 64 atoms** |
|---|---:|---:|
| Atoms in the α = 0.95 tail | 4 | **49–54** |
| CVaR-95 at λ = 0 | $227,977 | **$224,600** |
| CVaR-95 at λ = 1 | $213,157 | **$215,171** |
| CVaR-95 sampling error | **-0.94% … +1.50%** | — (none) |
| Residual probability mass | — | **0.0** |

The sampled tail was not merely thin, it was **biased by up to 1.50%** — in both directions, depending on λ. That is a real error, it was invisible without the exact computation, and it is now gone.

<!-- GENERATED:exact_vs_saa_table:END -->

**A note the objection actually strengthens:** the betweenness-as-probability defect (§2)
made scenario diversity *worse*, not better. With `p_fail = 1.0` for the most central
distributor, that supplier failed in every scenario and stopped being a source of
variation at all — mechanically collapsing the number of distinct outcomes. This model
never inherited those probabilities, and as of 2026-08-16 they are fixed at the source
too.

**Where enumeration is not possible.** `iot_sensor_node` draws on 26 distributors →
2^26 = 67,108,864 atoms. Above `MAX_ENUMERABLE_DISTRIBUTORS = 18` the model falls back to
sampling and bounds the residual error statistically instead (§5). Which mode each result
used is recorded per point as `evaluation_kind`.

---

## 4. The frontier

**`pcb_power_supply` at 10,000× volume — 60,000 units, `balanced` strategy, `us_only=False`,
depot San Francisco (37.7749 / −122.4194), scored on the exact 64-atom support.**

> **The depot is load-bearing, not scenery.** It sets every distributor's
> `dist_km_from_depot`, which sets the freight model, which changes the optimum — not
> just the freight line. The same BOM at the same volume against the Memphis reference
> hub (35.1495 / −90.0490, which `POST /stochastic/frontier` uses by default) gives
> E = $147,272 and **four** suppliers at λ = 0, against the $182,256 and six below.
> The endpoint therefore echoes the depot it used in `instance.depot_lat/depot_lng` and
> accepts it as a request parameter; pass San Francisco to reproduce this table.

<!-- GENERATED:frontier_table:BEGIN -->

| λ | E[cost] | CVaR-95 | Tail premium | Suppliers | Atoms in tail | Status | Gap | Solve | On frontier |
|---:|---:|---:|---:|:---:|---:|:---|---:|---:|:---:|
| 0.00 | $182,256 | $224,600 | $42,344 | 6 | 50 | OPTIMAL | 0.040% | 0.008 s | yes |
| 0.05 | $182,256 | $224,600 | $42,344 | 6 | 50 | OPTIMAL | 0.062% | 0.011 s | yes |
| 0.10 | $182,723 | $221,224 | $38,501 | 6 | 50 | OPTIMAL | 0.000% | 0.010 s | yes |
| 0.20 | $184,036 | $216,828 | $32,792 | 5 | 51 | OPTIMAL | 0.060% | 0.018 s | yes |
| **0.30** | **$184,300** | **$215,882** | **$31,582** | **4** | 53 | OPTIMAL | 0.000% | 0.010 s | yes ← **knee** |
| 0.50 | $184,595 | $215,860 | $31,266 | 5 | 54 | OPTIMAL | 0.082% | 0.027 s | yes |
| 0.70 | $187,077 | $214,747 | $27,670 | 4 | 50 | OPTIMAL | 0.056% | 0.014 s | yes |
| 0.85 | $187,077 | $214,747 | $27,670 | 4 | 50 | OPTIMAL | 0.000% | 0.022 s | yes |
| 1.00 | $188,486 | $215,171 | $26,685 | 3 | 49 | OPTIMAL | 0.052% | 0.008 s | yes *dominated* |

CVaR is also reported at other tail levels, because a single α is not enough to read a tail:

| λ | CVaR-80 | CVaR-90 | CVaR-95 | CVaR-98 |
|---:|---:|---:|---:|---:|
| 0.00 | $192,985 | $203,808 | $224,600 | $266,764 |
| **0.30** | **$191,212** | **$199,693** | **$215,882** | **$246,381** |
| 1.00 | $194,202 | $201,192 | $215,171 | $242,272 |

*Solve quality for this sweep: 9 of 9 λ points converged, worst MIP gap 0.082%, statuses `OPTIMAL`, per-solve limit 60s.*

<!-- GENERATED:frontier_table:END -->

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

<!-- GENERATED:knee_table:BEGIN -->

**Knee: λ = 0.3**, found by maximum perpendicular distance to the chord joining the extreme non-dominated points (the Kneedle / L-method criterion, Satopää et al. 2011), on min-max normalized axes so the answer does not depend on the currency unit — and computed on the **9 converged points only** (0 excluded).

| | Before the knee (λ 0 → 0.3) | Beyond the knee (λ 0.3 → 1) |
|---|---:|---:|
| Extra expected cost | **+$2,044** (+1.12%) | +$2,777 |
| CVaR-95 reduction | **−$8,719** (−3.88%) | −$1,135 |
| **$ of tail removed per $ spent** | **4.27** | 0.41 |

> **Recommendation.** Source this BOM at **λ = 0.3**: 4 suppliers (9, 70, 81, 85) rather than the risk-neutral 6. It costs **$2,044 more per 60,000-unit build in expectation — 1.12% of spend — and removes $8,719 of CVaR-95 exposure.** Every dollar of that premium buys **$4.27** of tail reduction. Past the knee the same dollar buys **$0.41**. Stop at the knee.

<!-- GENERATED:knee_table:END -->

### What is actually in the tail — and what the knee changes

<!-- GENERATED:tail_table:BEGIN -->

The α = 0.95 tail is not diffuse. **32% of it is one event: distributor 81 going dark.**

| Failed | Probability | Share of tail | Cost at λ=0 | **Cost at knee** | Emergency units (λ=0 → knee) | Unmet units (λ=0 → knee) |
|---|---:|---:|---:|---:|---:|---:|
| {81} | 1.61% | **32.2%** | $251,162 | **$227,648** | 167 → **37,356** | 4,290 → 4,288 |
| {85} | 2.53% | **23.8%** | $183,307 | **$183,742** | 10,847 → **10,847** | 0 → 0 |
| {70} | 1.03% | **20.6%** | $198,441 | **$198,875** | 4,858 → **4,860** | 978 → 978 |
| {28, 81} | 0.24% | **4.8%** | $275,597 | **$257,651** | 0 → **28,561** | 13,085 → 13,083 |

<!-- GENERATED:tail_table:END -->

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

Every baseline is scored on the identical exact measure, and dominance is tested against
the converged frontier points only.

<!-- GENERATED:baselines_table:BEGIN -->

| Plan | E[cost] | CVaR-95 | Suppliers | Dominated by any λ? | Sits at λ ≈ |
|---|---:|---:|:---:|:---:|:---:|
| Mean-value (disruptions assumed away) | $182,932 | $220,085 | 6 | no | **0.1** |
| **Shipped MILP** (`sourcing.py`, heuristic surcharges live) | $183,171 | $219,128 | 5 | no | **0.1** |
| **Shipped MILP**, graph-aware (`sourcing.py`, betweenness term on) | $183,171 | $219,128 | 5 | no | **0.1** |
| Stochastic, λ = 0 (risk-neutral) | $182,256 | $224,600 | 6 | — | — |
| **Stochastic, λ = 0.3 (knee)** | **$184,300** | **$215,882** | **4** | — | — |

**Value of the stochastic solution: VSS = EEV − RP = $676 (0.37% of RP).** Ignoring uncertainty at plan time costs 0.37% *in expectation*; the deterministic plan is very nearly the risk-neutral optimum. **The value of this model is not in expected cost. It is entirely in the tail**, where the same comparison is $220,085 → $215,882.

<!-- GENERATED:baselines_table:END -->

That the VSS is **small** is the point, not an embarrassment: it says the deterministic
optimizer was already close to the risk-neutral optimum, and that everything this model
adds, it adds in the tail.

And the most useful honest finding here: **the shipped 15% heuristic surcharge is not
wrong.** It is not dominated by any point on the frontier — it lands *on* the curve, at
about λ ≈ 0.10. What it cannot do is **tell you that**, or let you move. The surcharge
encodes one unlabelled risk appetite chosen by a constant in a source file; the frontier
makes the appetite an explicit, auditable, movable dial and shows what each setting costs.
That is the whole argument, and it is a smaller and more defensible claim than "the
heuristic was wrong".

### The tradeoff only exists at volume

<!-- GENERATED:volume_table:BEGIN -->

| Volume | Units | Knee | VSS | λ points converged |
|---|---:|:---:|---:|:---:|
| 100× | 600 | **none** | $0.00 (0.00%) | 9/9 |
| 1,000× | 6,000 | **none** | $15.91 (0.10%) | 9/9 |
| 10,000× | 60,000 | **λ = 0.3** | $676 (0.37%) | 9/9 |

<!-- GENERATED:volume_table:END -->

At prototype and low-production volume there is **no cost-vs-CVaR tradeoff on this BOM at
all** — every λ returns the same plan. This is consistent with
[`BENCHMARK_VOLUME_CURVE.md`](BENCHMARK_VOLUME_CURVE.md): at low volume the fixed
per-supplier charge dominates everything, so the sourcing decision is fully determined by
fee arithmetic and there is no room left for risk to move it. The frontier is a
**production-volume instrument**, and pretending otherwise would be the same mistake as
the 44.7% headline.

---

## 6. Is any of this robust to the probabilities being wrong?

The disruption probabilities are an **assumption** (§2), so the deliverable is not a point
estimate of the knee — it is the range the knee moves over when the assumption is flexed.
The grid is `base_annual_prob ∈ {5%, 10%, 23.68%, 40%} × centrality_spread ∈ {1.0, 3.0,
6.0} × horizon_days ∈ {30, 60, 120}`, each cell a full λ sweep on the headline instance.

The arm that matters is `centrality_spread = 1.0`: centrality removed from the model
entirely, every supplier on the flat cited base rate. If the recommendation survives that,
it is being driven by the cost and stock data rather than by the graph assumption.

<!-- GENERATED:sensitivity:BEGIN -->

**36 full frontier sweeps** on the headline instance (`pcb_power_supply` ×10,000), over `base_annual_prob` × `centrality_spread` × `horizon_days`.

* A knee exists in **31 of 36** cells; the knee λ takes the values 0.25, 0.5, 0.75.
* In the **centrality-ignored arm** (`centrality_spread = 1.0`, 12 cells — every supplier on the flat cited base rate), a knee exists in **11** of them.
* 36 of 36 sweeps had every λ point converge; **0** did not and their aggregates are built on the converged subset.

| base rate | spread | horizon | p_median | scenarios | knee λ | knee suppliers | extra E[cost] | CVaR-95 reduction | CVaR reduction available | all λ converged |
|---:|---:|---:|---:|---:|:---:|:---:|---:|---:|---:|:---:|
| 5.00% | 1 | 30 d | 0.42% | 4 | **none** | — | — | — | 0.09% | yes |
| 5.00% | 1 | 60 d | 0.84% | 6 | 0.25 | 4 | 0.35% | 0.50% | 0.50% | yes |
| 5.00% | 1 | 120 d | 1.67% | 7 | 0.25 | 4 | 0.34% | 1.23% | 1.48% | yes |
| 5.00% | 3 | 30 d | 0.52% | 5 | **none** | — | — | — | 0.12% | yes |
| 5.00% | 3 | 60 d | 1.05% | 6 | 0.25 | 5 | 0.03% | 0.11% | 0.20% | yes |
| 5.00% | 3 | 120 d | 2.08% | 8 | 0.25 | 4 | 0.51% | 0.69% | 0.69% | yes |
| 5.00% | 6 | 30 d | 0.60% | 5 | **none** | — | — | — | 0.20% | yes |
| 5.00% | 6 | 60 d | 1.20% | 6 | **none** | — | — | — | 0.52% | yes |
| 5.00% | 6 | 120 d | 2.39% | 7 | 0.25 | 6 | 0.25% | 0.73% | 1.03% | yes |
| 10.00% | 1 | 30 d | 0.86% | 6 | 0.25 | 4 | 0.35% | 0.53% | 0.53% | yes |
| 10.00% | 1 | 60 d | 1.72% | 7 | 0.25 | 4 | 0.34% | 1.27% | 1.55% | yes |
| 10.00% | 1 | 120 d | 3.40% | 8 | 0.25 | 4 | 0.32% | 3.18% | 4.32% | yes |
| 10.00% | 3 | 30 d | 1.07% | 7 | 0.25 | 5 | 0.03% | 0.11% | 0.22% | yes |
| 10.00% | 3 | 60 d | 2.14% | 8 | 0.25 | 4 | 0.52% | 0.71% | 0.71% | yes |
| 10.00% | 3 | 120 d | 4.24% | 9 | 0.25 | 4 | 0.93% | 3.27% | 3.42% | yes |
| 10.00% | 6 | 30 d | 1.23% | 6 | **none** | — | — | — | 0.53% | yes |
| 10.00% | 6 | 60 d | 2.46% | 7 | 0.25 | 6 | 0.26% | 0.74% | 1.06% | yes |
| 10.00% | 6 | 120 d | 4.87% | 10 | 0.25 | 5 | 1.39% | 1.81% | 2.00% | yes |
| 23.68% | 1 | 30 d | 2.20% | 7 | 0.25 | 4 | 0.34% | 1.63% | 2.31% | yes |
| 23.68% | 1 | 60 d | 4.35% | 9 | 0.25 | 4 | 0.31% | 3.86% | 5.27% | yes |
| 23.68% | 1 | 120 d | 8.50% | 17 | 0.25 | 4 | 0.26% | 2.94% | 4.00% | yes |
| 23.68% | 3 | 30 d | 2.74% | 8 | 0.25 | 4 | 0.68% | 2.26% | 2.31% | yes |
| 23.68% | 3 | 60 d | 5.41% | 10 | 0.25 | 4 | 1.12% | 3.88% | 4.33% | yes |
| 23.68% | 3 | 120 d | 10.59% | 18 | 0.25 | 6 | 1.03% | 3.59% | 7.27% | yes |
| 23.68% | 6 | 30 d | 3.14% | 7 | 0.25 | 5 | 0.53% | 1.02% | 1.39% | yes |
| 23.68% | 6 | 60 d | 6.22% | 11 | 0.25 | 5 | 1.37% | 1.85% | 2.45% | yes |
| 23.68% | 6 | 120 d | 12.17% | 15 | 0.25 | 6 | 1.03% | 1.32% | 3.79% | yes |
| 40.00% | 1 | 30 d | 4.11% | 8 | 0.25 | 4 | 0.31% | 3.71% | 5.03% | yes |
| 40.00% | 1 | 60 d | 8.05% | 15 | 0.25 | 4 | 0.27% | 3.12% | 4.24% | yes |
| 40.00% | 1 | 120 d | 15.46% | 24 | 0.5 | 4 | 0.80% | 1.64% | 1.73% | yes |
| 40.00% | 3 | 30 d | 5.12% | 10 | 0.25 | 4 | 1.07% | 3.74% | 4.13% | yes |
| 40.00% | 3 | 60 d | 10.03% | 17 | 0.25 | 5 | 1.61% | 5.19% | 6.97% | yes |
| 40.00% | 3 | 120 d | 19.26% | 27 | 0.75 | 4 | 4.36% | 3.56% | 3.62% | yes |
| 40.00% | 6 | 30 d | 5.88% | 10 | 0.25 | 5 | 1.31% | 1.77% | 2.29% | yes |
| 40.00% | 6 | 60 d | 11.53% | 14 | 0.5 | 5 | 3.08% | 2.80% | 3.65% | yes |
| 40.00% | 6 | 120 d | 22.12% | 22 | 0.5 | 5 | 2.16% | 1.61% | 4.45% | yes |

<!-- GENERATED:sensitivity:END -->

---

## 7. SAA solution quality

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

<!-- GENERATED:saa_quality:BEGIN -->

Reference measure: **exact**.

| N | λ | Lower bound (mean of M) | LB 95% CI low | Upper bound | Gap | Gap 95% CI high | Gap % | Wall |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 25 | 0 | $183,037 | $181,588 | $182,256 | −$781 | $668 | -0.428% | 0.3 s |
| 25 | 0.5 | $201,951 | $191,094 | $200,091 | −$1,860 | $8,996 | -0.930% | 0.3 s |
| 25 | 1 | $218,275 | $198,756 | $214,748 | −$3,526 | $15,992 | -1.642% | 0.3 s |
| 50 | 0 | $182,654 | $181,671 | $182,256 | −$398 | $585 | -0.218% | 0.3 s |
| 50 | 0.5 | $199,977 | $192,616 | $200,091 | $114 | $7,475 | 0.057% | 0.3 s |
| 50 | 1 | $214,790 | $201,777 | $214,747 | −$43.57 | $12,969 | -0.020% | 0.4 s |
| 100 | 0 | $182,433 | $181,616 | $182,256 | −$177 | $640 | -0.097% | 0.5 s |
| 100 | 0.5 | $197,804 | $193,171 | $200,091 | $2,287 | $6,919 | 1.143% | 0.5 s |
| 100 | 1 | $210,324 | $202,139 | $214,747 | $4,422 | $12,607 | 2.059% | 0.5 s |
| 200 | 0 | $182,426 | $181,927 | $182,256 | −$171 | $329 | -0.094% | 1.1 s |
| 200 | 0.5 | $200,410 | $197,886 | $200,091 | −$320 | $2,205 | -0.160% | 0.7 s |
| 200 | 1 | $215,162 | $210,907 | $214,747 | −$415 | $3,840 | -0.193% | 0.6 s |
| 400 | 0 | $182,249 | $181,909 | $182,256 | $6.65 | $347 | 0.004% | 3.2 s |
| 400 | 0.5 | $199,851 | $197,071 | $200,091 | $240 | $3,019 | 0.120% | 1.0 s |
| 400 | 1 | $214,269 | $209,413 | $214,747 | $478 | $5,334 | 0.223% | 0.8 s |

The interval statement that must hold — `upper_bound ≥ lower_bound_ci_low` — holds in **15 of 15** cells.

**Endpoint stability** over N ∈ [50, 100, 200, 400, 800] × seed ∈ [42, 1337, 2718] (15 sweeps): the risk-neutral expected cost spans $182,256 – $182,723 (0.26% of the low), and the minimum CVaR-95 spans $214,747 – $215,882 (0.53%).

| N draws | seed | distinct scenarios | risk-neutral E | risk-neutral CVaR-95 | min CVaR-95 | E at min CVaR | scored on | all λ converged |
|---:|---:|---:|---:|---:|---:|---:|:---|:---:|
| 50 | 42 | 7 | $182,256 | $224,600 | $215,171 | $188,486 | `exact` | yes |
| 50 | 1337 | 6 | $182,256 | $224,600 | $215,635 | $184,724 | `exact` | yes |
| 50 | 2718 | 6 | $182,723 | $221,223 | $215,171 | $188,486 | `exact` | yes |
| 100 | 42 | 8 | $182,256 | $224,600 | $215,171 | $188,486 | `exact` | yes |
| 100 | 1337 | 8 | $182,256 | $224,600 | $215,171 | $188,486 | `exact` | yes |
| 100 | 2718 | 11 | $182,256 | $224,600 | $214,747 | $187,077 | `exact` | yes |
| 200 | 42 | 10 | $182,256 | $224,600 | $215,171 | $188,486 | `exact` | yes |
| 200 | 1337 | 12 | $182,256 | $224,600 | $215,848 | $184,667 | `exact` | yes |
| 200 | 2718 | 15 | $182,256 | $224,600 | $215,353 | $188,724 | `exact` | yes |
| 400 | 42 | 14 | $182,256 | $224,600 | $214,747 | $187,077 | `exact` | yes |
| 400 | 1337 | 17 | $182,256 | $224,600 | $214,747 | $187,077 | `exact` | yes |
| 400 | 2718 | 16 | $182,256 | $224,600 | $215,171 | $188,486 | `exact` | yes |
| 800 | 42 | 18 | $182,256 | $224,600 | $214,747 | $187,077 | `exact` | yes |
| 800 | 1337 | 18 | $182,256 | $224,600 | $215,882 | $184,300 | `exact` | yes |
| 800 | 2718 | 20 | $182,256 | $224,600 | $214,846 | $187,185 | `exact` | yes |

*The M x N replication solves inside `saa_optimality_gap` are run by app/optimization/stochastic.py, which does not surface their per-solve CP-SAT status, so they are NOT represented in the run-level solve_quality block. The `endpoint_stability` rows below are, and each carries its own statuses / worst_mip_gap_pct / all_points_converged.*

<!-- GENERATED:saa_quality:END -->

---

## 8. Where a cost-vs-CVaR tradeoff exists at all

All 10 reference BOMs across their feasible volume range on the coarse λ grid. Reported
honestly including the BOMs where the answer is **no tradeoff exists** — a flat frontier
is a finding, not a failure — and including the instances where the solver did not
converge inside the 15 s breadth budget, which are marked and excluded rather than
quietly averaged in.

<!-- GENERATED:breadth:BEGIN -->

**10 reference BOMs**, 30 (BOM × volume) instances. On **4** of them no λ point converged inside the 15s budget, so no frontier can honestly be reported and the row is marked **excluded**. Of the **26** instances that did produce a frontier, a cost-vs-CVaR tradeoff exists in **9**, spread over **5 of 10 BOMs** (`industrial_motor_driver`, `iot_sensor_node`, `medical_monitoring_device`, `pcb_power_supply`, `rf_transceiver_module`).

| BOM | Distributors | Support | ×volume | Units | Scenarios | Tradeoff? | CVaR-95 reduction available | Price of it | Worst gap | all λ converged |
|---|---:|:---|---:|---:|---:|:---:|---:|---:|---:|:---:|
| `iot_sensor_node` | 26 | sampled (2^26) | 1× | 5 | 97 | no | $0.00 (0.00%) | $0.00 | 88.62% | **NO** |
| `iot_sensor_node` | 26 | sampled (2^26) | 10× | 50 | 97 | no | $0.00 (0.00%) | $0.00 | 73.12% | **NO** |
| `iot_sensor_node` | 26 | sampled (2^26) | 100× | 500 | 97 | no | $0.00 (0.00%) | $0.00 | 0.00% | yes |
| `iot_sensor_node` | 26 | sampled (2^26) | 1,000× | 5,000 | 97 | **yes** | $57.33 (0.40%) | $42.46 | 13.77% | **NO** |
| `iot_sensor_node` | 26 | sampled (2^26) | 10,000× | 50,000 | 97 | **yes** | $121 (0.04%) | $0.00 | 0.10% | yes |
| `drone_flight_controller` | 44 | sampled (2^44) | 1× | 7 | 152 | **excluded** | — | — | 67.08% | **NO** |
| `pcb_power_supply` | 6 | exact, 64 atoms | 1× | 6 | 10 | no | $0.00 (0.00%) | $0.00 | 0.09% | yes |
| `pcb_power_supply` | 6 | exact, 64 atoms | 10× | 60 | 10 | no | $0.00 (0.00%) | $0.00 | 0.00% | yes |
| `pcb_power_supply` | 6 | exact, 64 atoms | 100× | 600 | 10 | **yes** | $81.80 (4.36%) | $116 | 0.00% | yes |
| `pcb_power_supply` | 6 | exact, 64 atoms | 1,000× | 6,000 | 10 | **yes** | $86.73 (0.52%) | $134 | 0.00% | yes |
| `pcb_power_supply` | 6 | exact, 64 atoms | 10,000× | 60,000 | 10 | **yes** | $9,721 (4.33%) | $4,976 | 0.08% | yes |
| `industrial_motor_driver` | 46 | sampled (2^46) | 1× | 7 | 167 | no | $0.00 (0.00%) | $0.00 | 10.71% | **NO** |
| `industrial_motor_driver` | 46 | sampled (2^46) | 10× | 70 | 167 | **yes** | $10.47 (0.13%) | $62.91 | 17.50% | **NO** |
| `rf_transceiver_module` | 29 | sampled (2^29) | 1× | 4 | 111 | no | $0.00 (0.00%) | $0.00 | 92.69% | **NO** |
| `rf_transceiver_module` | 29 | sampled (2^29) | 10× | 40 | 111 | no | $0.00 (0.00%) | $0.00 | 77.45% | **NO** |
| `rf_transceiver_module` | 29 | sampled (2^29) | 100× | 400 | 111 | no | $0.00 (0.00%) | $0.00 | 20.27% | **NO** |
| `rf_transceiver_module` | 29 | sampled (2^29) | 1,000× | 4,000 | 111 | **yes** | $1,006 (2.91%) | $7,765 | 0.03% | yes |
| `automotive_ecu` | 57 | sampled (2^57) | 1× | 7 | 181 | **excluded** | — | — | 92.78% | **NO** |
| `automotive_ecu` | 57 | sampled (2^57) | 10× | 70 | 181 | no | $0.00 (0.00%) | $0.00 | 70.01% | **NO** |
| `medical_monitoring_device` | 44 | sampled (2^44) | 1× | 8 | 157 | **excluded** | — | — | 71.77% | **NO** |
| `medical_monitoring_device` | 44 | sampled (2^44) | 10× | 80 | 157 | no | $0.00 (0.00%) | $0.00 | 33.82% | **NO** |
| `medical_monitoring_device` | 44 | sampled (2^44) | 100× | 800 | 157 | **yes** | $254 (1.37%) | $254 | 70.00% | **NO** |
| `medical_monitoring_device` | 44 | sampled (2^44) | 1,000× | 8,000 | 157 | **yes** | $3,228 (0.95%) | $5,042 | 0.18% | yes |
| `smart_meter` | 51 | sampled (2^51) | 1× | 4 | 170 | **excluded** | — | — | 69.62% | **NO** |
| `smart_meter` | 51 | sampled (2^51) | 10× | 40 | 170 | no | $0.00 (0.00%) | $0.00 | 14.88% | **NO** |
| `robotics_servo_driver` | 46 | sampled (2^46) | 1× | 9 | 157 | no | $0.00 (0.00%) | $0.00 | 46.33% | **NO** |
| `audio_dsp_board` | 31 | sampled (2^31) | 1× | 7 | 117 | no | $0.00 (0.00%) | $0.00 | 86.21% | **NO** |
| `audio_dsp_board` | 31 | sampled (2^31) | 10× | 70 | 117 | no | $0.00 (0.00%) | $0.00 | 45.45% | **NO** |
| `audio_dsp_board` | 31 | sampled (2^31) | 100× | 700 | 117 | no | $0.00 (0.00%) | $0.00 | 0.10% | yes |
| `audio_dsp_board` | 31 | sampled (2^31) | 1,000× | 7,000 | 117 | no | $0.00 (0.00%) | $0.00 | 0.09% | yes |

<!-- GENERATED:breadth:END -->

---

## 9. Solve times and problem sizes

<!-- GENERATED:solve_times:BEGIN -->

| Instance | Distributors | Distinct scenarios | Variables | λ points | λ-sweep wall time | Worst gap | λ not converged |
|---|---:|---:|---:|---:|---:|---:|---:|
| `pcb_power_supply` ×100 (primary arm) | 6 | 10 (SAA) / 64 (exact) | 243 | 9 | **0.4 s** | 0.000% | 0 |
| `pcb_power_supply` ×1,000 (primary arm) | 6 | 10 (SAA) / 64 (exact) | 243 | 9 | **0.4 s** | 0.000% | 0 |
| `pcb_power_supply` ×10,000 (primary arm) | 6 | 10 (SAA) / 64 (exact) | 243 | 9 | **0.3 s** | 0.082% | 0 |
| `automotive_ecu` ×10 (breadth arm) | 57 | 181 (SAA, 200 draws) | 22182 | 5 | 76.1 s | 70.01% | 4 |
| `automotive_ecu` ×1 (breadth arm) | 57 | 181 (SAA, 200 draws) | — | 5 | 76.0 s | 92.78% | 5 |
| `industrial_motor_driver` ×1 (breadth arm) | 46 | 167 (SAA, 200 draws) | 13575 | 5 | 75.8 s | 10.71% | 4 |
| `smart_meter` ×10 (breadth arm) | 51 | 170 (SAA, 200 draws) | 16634 | 5 | 75.8 s | 14.88% | 4 |
| `drone_flight_controller` ×1 (breadth arm) | 44 | 152 (SAA, 200 draws) | — | 5 | 75.6 s | 67.08% | 5 |
| `iot_sensor_node` ×1 (breadth arm) | 26 | 97 (SAA, 200 draws) | 4713 | 5 | 60.8 s | 88.62% | 1 |
| `iot_sensor_node` ×10 (breadth arm) | 26 | 97 (SAA, 200 draws) | 4713 | 5 | 59.6 s | 73.12% | 2 |
| `iot_sensor_node` ×1,000 (breadth arm) | 26 | 97 (SAA, 200 draws) | 4713 | 5 | 41.6 s | 13.77% | 1 |
| `iot_sensor_node` ×100 (breadth arm) | 26 | 97 (SAA, 200 draws) | 4713 | 5 | 19.0 s | 0.00% | 0 |
| `iot_sensor_node` ×10,000 (breadth arm) | 26 | 97 (SAA, 200 draws) | 4713 | 5 | 5.3 s | 0.10% | 0 |

*The five slowest breadth instances are listed, plus every volume of `iot_sensor_node` (the instance this section used to quote stale figures for). The full set is in `docs/cvar_frontier.json` → `breadth`. A `—` in the Variables column is an instance where no λ point converged at all, so the entry carries its `excluded_reason` instead of a frontier.*

<!-- GENERATED:solve_times:END -->

**Honest reporting of what is hard.** The model size is driven by the per-scenario
expedited-consignment binaries `e[d,s]`: on a large-pool BOM with a hundred-plus distinct
scenarios that is thousands of extra booleans, and it is the difference between a 0.02 s
solve and a time-limit hit. Removing that term makes the model far faster and changes
CVaR-95 materially — so it is kept, and the cost of keeping it is reported rather than
hidden, per instance, in the table above and in the §0 solve-quality summary.

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
python -m seeds.run_cvar_frontier              # full artifact (~20 min)
python -m seeds.run_cvar_frontier --quick      # primary + calibration only (~4 s)
python -m seeds.run_cvar_frontier --render-only # re-render this doc from the JSON, no solves
```

Writes `docs/cvar_frontier.json` — full per-λ frontier, knee, tail decomposition,
exact-vs-SAA comparison, SAA optimality gaps, sensitivity grid, breadth sweep, the
run-level solve-quality distribution, and the per-distributor calibration with provenance.

> **This document has a generator.** Every numeric block above sits between
> `GENERATED:<block>:BEGIN` and `GENERATED:<block>:END` HTML-comment markers and is written
> from `docs/cvar_frontier.json` by `render_doc()` in the same script — because these
> numbers used to be hand-transcribed, and hand transcription is exactly how §6/§7/§8 came
> to point at artifact keys that did not exist and how the §9 `iot_sensor_node` row came to
> quote a run that no longer existed. Prose, caveats and derivations live *outside* the
> markers and the generator never touches them. `backend/tests/test_cvar_doc_matches_artifact.py`
> fails the build if the two ever disagree again.
>
> A `--quick` artifact is **partial** by design: it contains `primary` and `calibration`
> only, and the generated §6/§7/§8 blocks then say so explicitly instead of pointing at
> keys that are not there.

Live, with the probability assumptions exposed as request parameters:

```bash
curl -X POST /api/v1/stochastic/frontier -d '{
  "items": [{"component_id": 1, "quantity": 15000}],
  "base_annual_prob": 0.2368, "horizon_days": 60, "centrality_spread": 3.0
}'
curl /api/v1/stochastic/calibration          # every p_fail, beside the legacy value
```

**Reproducing §4 and §5 from the endpoint rather than the script.** The λ grid must
contain 0.3 (it does), the pool must be small enough to score on the exact support (6
distributors → 64 atoms, it is), and the depot must be the artifact's:

```bash
curl -X POST /api/v1/stochastic/frontier -d '{
  "items": [{"component_id": 429, "quantity": 20000},   
            {"component_id": 431, "quantity": 10000},   
            {"component_id": 457, "quantity": 20000},   
            {"component_id": 442, "quantity": 10000}],  
  "depot_lat": 37.7749, "depot_lng": -122.4194
}'
# ids are LM317DCY / TPS767D325PWP / UA78M33CDCY / OPA861ID at 10,000x the
# pcb_power_supply BOM in seeds/run_benchmark.py -- resolve them by MPN if they move
# -> recommendation.knee_lambda                        0.3
#    recommendation.cvar_removed_per_dollar_spent      4.266
#    recommendation.extra_expected_cost_usd            2043.83
#    recommendation.cvar_reduction_usd                 8718.79
```

Verified 2026-08-16: those four figures come back identical to `docs/cvar_frontier.json`.
Omit `depot_lat`/`depot_lng` and the endpoint answers the same question from Memphis —
a real frontier, but not this one.

Tests: `backend/tests/test_stochastic_sourcing.py` (50) and
`backend/tests/test_stochastic_api.py` (22). The load-bearing ones:

* `test_no_supplier_ever_saturates_at_probability_one` — the regression guard for §2.
* `test_with_no_uncertainty_it_reproduces_the_deterministic_landed_cost` — the
  anti-rigging invariant: with nothing to be stochastic about, the stochastic program's
  cost must equal `greedy.landed_cost_breakdown` exactly.
* `test_exact_evaluation_puts_many_atoms_in_the_tail_where_sampling_puts_few` — §3.
* `test_saa_optimality_gap_brackets_the_optimum_and_shrinks_with_sample_size` — §7.
* `test_risk_aversion_moves_the_award_to_a_lower_probability_supplier` — that buying risk
  aversion actually buys a lower tail, and is not free.
* `test_a_timeout_is_a_budget_error_and_never_claims_infeasibility` and
  `test_a_proven_infeasibility_is_a_distinct_error_type` — the regression guards for the
  status-mapping defect described below.
* `test_a_flat_frontier_is_described_rather_than_left_for_the_reader_to_infer` — a flat
  frontier must SAY it is flat, not arrive as a null recommendation beside identical rows.

### A defect this endpoint shipped with, and what it taught

Until 2026-08-16 the model treated **any** CP-SAT status outside {OPTIMAL, FEASIBLE} as
infeasible, and the API turned that into
`422 "No feasible sourcing plan exists for this BOM"`. CP-SAT reports `UNKNOWN` when the
time limit expires **before finding any solution** — a statement about the search budget
that carries no information about feasibility. An audit against a live instance found
**6 of 7 realistic BOMs returning that 422**; every one of them was in fact solvable.

The cause was not the time limit. Model size grows linearly in distinct scenarios × pool
size, and on a 55-supplier BOM 200 draws deduplicate to 183 distinct scenarios and a
~29,000-variable model. Measured at λ = 0.5 on one worker: 60 draws → 9,424 variables →
**OPTIMAL in 2.6 s**; 200 draws → 28,937 variables → **no feasible solution at all**,
and tripling the limit to 15 s only reached a 21% gap. Tripling the budget does not
rescue it; sizing the scenario set does, and lands on the same plan.

Three lessons, now encoded rather than remembered:

1. **A solver status is a diagnosis. Collapsing four statuses into one error blames the
   user for the service's own budget.** `INFEASIBLE`, `UNKNOWN` and `MODEL_INVALID` are
   now distinct exception types mapping to 422, 503 and 500.
2. **The scenario count is the lever, not the clock.** `fit_scenario_set` sizes the
   *solve* set to a variable budget while the *evaluation* set stays full — thinning
   costs SAA choice error, which `saa_optimality_gap` bounds, and leaves the published
   E and CVaR untouched.
3. **A partial frontier beats an error.** Four of six λ points, clearly labelled, is a
   usable answer; a confident wrong 422 is not.

---

## Provenance

<!-- GENERATED:provenance:BEGIN -->

- **Generated:** 2026-08-16T22:02:45Z (UTC)
- **Generator:** `seeds.run_cvar_frontier`
- **Commit:** `241ae9e6959c8f53558556dcaae1f4b394d0dbca` — ⚠️ **DIRTY WORKING TREE.** UNCOMMITTED CHANGES: this artifact was generated from a working tree that did not match its git commit. Checking out the recorded SHA alone will NOT reproduce these numbers. Regenerate from a clean tree before treating them as published.
- **Input `component_database`:** `backend/supply_chain.db` · sha256 `1abb53c6957e7bf5…`
- **Input `ml_metrics`:** `backend/data/ml_models/metrics.joblib` · sha256 `56748d404cf8eea9…`
- **Input `ml_regime_model`:** `backend/data/ml_models/regime.joblib` · sha256 `cbe110ecbba55052…`
- **Input `ml_lead_time_models`:** `backend/data/ml_models/lead_time.joblib` · sha256 `c2a9e0627cea3bef…`
- **Python:** 3.13.5 · macOS-26.5-arm64-arm-64bit-Mach-O
- **Run mode:** full
- **Wall clock:** 1297.4 s
- **Hardware:** arm64 / Darwin 25.5.0

<!-- GENERATED:provenance:END -->
