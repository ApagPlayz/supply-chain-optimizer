# Sub-Project A — Interview Walkthrough

A one-page whiteboard-ready explanation of the sourcing + routing +
cross-dock system. Target audience: supply chain / operations / data
science interview at McKinsey, BCG, Amazon Ops, Apple Ops.

**Read §4 carefully before you use this.** The single most likely way to lose
credibility in this interview is to describe an objective function the code does
not implement. §4 describes the one it *does* implement, and §9 gives you the
answers to the follow-up questions that description invites.

## 1. Business framing

A US PCB manufacturer runs a production run of 50 wireless IoT sensor
nodes. The BOM contains 5 electronic components sourced from a market
of 92 distributors offering 8,176 competing price offers (real data —
a static 2024 snapshot originally sourced via Nexar/Octopart, redistributed
on HuggingFace under CC-BY-4.0). We need to decide *which distributor fills
each line*, and
*which route the pickup truck takes*, balancing cost, delivery time,
and carbon emissions.

## 2. Decision variables

- `x[c,d] ∈ {0,1}` — is component c sourced from distributor d?
- `q[c,d] ∈ ℤ≥0` — quantity
- `y[d] ∈ {0,1}` — is distributor d visited at all?

## 3. Constraints

- Demand coverage: Σ_d q[c,d] = demand[c]
- Stock cap: q[c,d] ≤ stock[c,d] · x[c,d]
- MOQ floor: q[c,d] ≥ moq[c,d] · x[c,d] (and q[c,d] ≥ x[c,d] when moq = 1,
  so a selected offer must ship at least one unit)
- Distributor linking: y[d] ≥ x[c,d]
- Domestic-only sourcing: implemented as a **pre-filter on the offer set**,
  not as a posted constraint — international offers are removed before the
  model is built, so those `x[c,d]` variables never exist. Same effect,
  smaller model. Say it this way if asked; the equivalent written constraint
  is `x[c,d] = 0 for international d`.

Two more constraints exist but are **conditional**, not always posted:

- Line-count cap: Σ_c x[c,d] ≤ k ∀d — only on the `require_dual_source`
  path. The model is solved blind first; the cap is added and re-solved only
  if the blind solve put the whole BOM on one distributor.
- Minimum distributors: Σ_d y[d] ≥ k, with y pinned to genuine use — the
  price-of-resilience frontier endpoint.

There is **no capacity constraint** on distributors or hubs anywhere.

## 4. Objective function — what the solver actually minimizes

This is a **two-stage decomposition**, not a single multi-objective program.
Be precise about this; it is checkable in thirty seconds by anyone who opens
`backend/app/optimization/sourcing.py`.

### 4a. Stage 1 — sourcing MILP (CP-SAT): minimizes landed cost only

Every term below is denominated in **dollars** (built in integer milli-cents so
CP-SAT stays exact). There is **no lead-time term and no carbon term in it**:

```
minimize   Σ_(c,d)  price[c,d]              · q[c,d]     # component spend
         + Σ_d      fixed_freight[d]        · y[d]       # fixed-charge freight …
         + Σ_(c,d)  per_unit_freight[d]     · q[c,d]     #   … and its variable part
         + Σ_d      supplier_open_charge    · y[d]       # charge per supplier opened
         + Σ_(c,d)  stockout_risk_surcharge · x[c,d]     # risk premium
         + Σ_(c,d)  graph_surcharge[c,d]    · q[c,d]     # graph_aware mode only
         + Σ_(c,d)  feed_risk_surcharge     · q[c,d]     # live GPR / ACLED feeds
```

**The freight term is the interesting one.** It is a genuine **fixed-charge
transportation model** (Balinski 1965; Kuehn & Hamburger 1963), split in two:

| | Domestic distributor | International distributor |
|---|---|---|
| `fixed_freight[d]` (paid once to open d) | LTL base fee, **$75** — FreightWaves SONAR Q4 2023 / Old Dominion tariff | Air consignment minimum, **$150** — DHL/FedEx commercial |
| `per_unit_freight[d]` (paid per unit actually shipped) | 0.05 kg/unit × lbs × cwt × miles × **$0.43/cwt-mi** | 0.05 kg/unit × **$5.00/kg** — IATA Cargo Market Report 2023 |

The fixed/variable split is what makes this a real integer program rather than
a lookup: opening a second supplier costs a fixed fee that must be earned back
in unit price. That trade-off is the entire reason CP-SAT is here.

**The risk surcharge**, described by mechanism (quote the mechanism, not the
coefficient — the constants live in `sourcing.py` and move):

- an offer-level premium on `x[c,d]`, priced as a **bounded fraction of that
  offer's unit price**;
- the fraction is `P(macro stress)` — a probability from the trained regime
  model — multiplied by an offer **vulnerability index** built from two
  checkable facts on the offer: manufacturer origin, and stock-to-MOQ coverage;
- the bound is a **chosen policy ceiling, not a fitted quantity**. It is set so
  the surcharge can break a tie between comparable offers but can never
  overturn a large genuine price difference. Say "policy knob with a stated
  bound", never "calibrated" — nothing in this repo fits it from data.

`graph_surcharge` (betweenness-concentration risk) and `feed_risk_surcharge`
(live GPR / ACLED signals) are additive surcharges on `q[c,d]` and are also
directional risk *weights*, not probabilities. `graph_surcharge` only appears
in `graph_aware` mode.

### 4b. The four strategies differ by three levers, not by three weights

`w_cost`, `w_time` and `w_carbon` **never reach the Stage 1 solver.** Time and
carbon enter Stage 1 through three per-strategy proxy levers carried on
`StrategyWeights`:

| Lever | What it does | Why it proxies time/carbon |
|---|---|---|
| `us_only_sourcing` | Hard pre-filter dropping international offers | International legs are air freight — the single biggest lead-time *and* carbon lever |
| `transport_penalty_scale` | Multiplies **both** freight terms, so a higher value pushes the argmin toward nearby distributors | Fewer km = fewer transit days and fewer tonne-miles |
| `consolidation_bonus_usd` | A USD **charge** per supplier opened (named "bonus", it is added to a minimized objective, so it is a penalty) | Each extra pickup adds a handling window *and* ≥1 transit day, because leg transit is `ceil(km / 800)` — even a 50 km leg costs a full day |

Actual values in the code:

| Strategy | `us_only` | `transport_penalty_scale` | supplier-open charge | Basis |
|---|---|---|---|---|
| Lowest Cost | no | 1.0 (true landed cost) | $0.50 | Weber 1991 |
| Fastest | yes | 1.0 | $150.00 | Toyota / JIT |
| Lowest Carbon | yes | 2.5 | $2.50 | CDP Supply Chain |
| Balanced | yes | 1.5 | $2.00 | Ghodsypour & O'Brien 1998 |

The `$150` on Fastest is 2× the $75 LTL base fee, i.e. it prices the time cost
of opening one more supplier. Those two numbers were **swept against real BOMs
of 2/5/12/25/40 lines**, not guessed: before the sweep, "Fastest Delivery"
routinely produced the *longest* tour of the four strategies (9.5 d vs 5.5 d for
"greenest" at 12 and 40 lines, with 13 pickup stops). That is a good story —
tell it. It shows you measured a proxy instead of trusting it.

Strategies share a cached Stage 1 solve only when **all three** levers match,
so in practice each of the four runs its own MILP.

### 4c. Stage 2 — pickup TSP (see §6), then Stage 3 — cross-dock

Stage 2 takes `D* = {d : y[d] = 1}` from Stage 1 as **fixed input** and solves a
single-vehicle symmetric TSP over it. Stage 3 then evaluates cross-dock
consolidation on the resulting shipments. Stage 2 cannot revise Stage 1's
supplier choice, and Stage 1 has no visibility of the tour it will produce —
that is the price of decomposing (see §9, Q2).

### 4d. Where the three weights genuinely act

Exactly two places, both **downstream of sourcing**:

1. **`cross_dock.py::_weighted_objective`** — scoring hubs and applying the
   accept/reject threshold. Un-normalized; the `×100` on days and `×10` on kg
   are **ad-hoc unit bridges, not derived weights**. They are defensible only
   because both sides of the direct-vs-hub comparison pass through the same
   transform, which leaves the argmin within one strategy unchanged. Say that
   out loud before an interviewer says it for you.
2. **`solve.py`** — min-max normalizing the four **already-finished**
   alternatives against each other, then `w_cost·cost_n + w_time·time_n +
   w_carbon·carbon_n`. *This* is the weighted-sum scalarization (Marler & Arora
   2004), and it is real — but it compares four plans it did not shape.

And be honest about how far even that goes: the resulting `weighted_total` is
**reported, not acted on**. It is surfaced in `strategy_math` and displayed on
the checkout page. The four alternatives are ranked by *per-objective standard
competition ranking* (cost, speed, carbon, distance ranks computed
independently), and the user chooses. Nothing in the backend selects a winner by
weighted total.

**Honest one-line summary — memorize this:** *a cost-minimizing fixed-charge
MILP with per-strategy proxy levers, composed with a TSP, plus a weighted-sum
scalarization used for hub choice and for presenting the finished alternatives.
Calling it a tri-objective MILP would be wrong.*

**Cost constants and where each is actually used** (do not attribute all of
these to the MILP objective — only the first two rows are in it):

| Constant | Value | Source | Used in |
|---|---|---|---|
| LTL base + per-cwt | $75 + $0.43/cwt·mi | FreightWaves SONAR 2023 | Stage 1 freight (domestic), route legs |
| Air base + per-kg | $150 + $5.00/kg | DHL/FedEx consignment minimum + IATA Cargo Market Report 2023 | Stage 1 freight (international) |
| TL rate | $2.271/mi | ATRI 2023 | Route/hub legs **only when a leg is ≥ 10,000 lbs** — a 50-unit electronics BOM never reaches it |
| Truck CO₂ | 161.8 g/**short** ton-mi | EPA SmartWay Technical Documentation 2013, via EDF Green Freight Handbook 2014 p.11 | Route metrics + cross-dock objective — **not** Stage 1 |
| Air CO₂ | 0.5 kg/tonne-km | GLEC Framework v3.2 (long-haul dedicated freighter, tank-to-wheel; 503 g CO₂e/tonne-km) | International leg metrics — **not** Stage 1 |
| Holding cost | 25%/yr | Gartner 2022 | Reported `cost_breakdown` — **not** Stage 1 |
| Ground speed | 800 km/day | BTS CFS 2022 | `transit_days = ceil(km/800)` — lead time, **not** Stage 1 |

## 5. Why CP-SAT (not pure LP, not pure OR-Tools routing)

- Integer quantities (`q[c,d] ∈ ℤ`) make it a MILP, not LP
- Combinatorial supplier selection via `x[c,d] ∈ {0,1}`, with a genuine
  fixed charge on `y[d]` — the LP relaxation would open fractional suppliers
- OR-Tools routing handles vehicle flow, not supplier selection
- CP-SAT treats linear integer programs as MILP-equivalent and is
  faster than CBC on small combinatorial problems
- Already a transitive dependency via OR-Tools routing

## 6. Pipeline

```
BOM → Outlier Filter → Stage 1 CP-SAT Sourcing →
Stage 2 TSP → Stage 3 Cross-Dock Evaluation → 4 RouteAlternatives
```

**Outlier filter:** Drop any offer where `price > 5 × median(price)`
for that MPN. One-sided (low discounts stay). Aberdeen Group 2020.

**Stage 1 (Sourcing MILP):** CP-SAT minimizes component spend **plus
fixed-charge freight plus a per-supplier charge plus risk surcharges**, subject
to demand / stock / MOQ / linking. Not "picks the cheapest offers" — the fixed
charge is exactly what stops it doing that.

**Stage 2 (TSP):** haversine distance matrix over the selected distributors,
solved two ways and the response says which one ran. At or below 8 stops
every tour is enumerated (8!/2 = 20,160 tours, 7 ms measured) and the answer
is a proven optimum; above that it is OR-Tools routing, PATH_CHEAPEST_ARC +
GUIDED_LOCAL_SEARCH, which returns a good local optimum and says so
(`routing_solver.proven_optimal = false`). Real carts here produce 1-4 stops,
so the exact path is what the site actually runs. International distributors
are air-freight legs, not truck stops — they never enter the tour.

**Stage 3 (Cross-dock):** exhaustive enumeration over a fixed set of 10 candidate
hubs — every hub is scored on the strategy's weighted objective and the argmin
wins, exact by construction since the set is fixed and tiny. There is no
Lagrangian relaxation and no capacity constraint (hubs are modelled as
uncapacitated and always available, so there is nothing to relax); an earlier
version of this doc claimed "Lagrangian relaxation of the Capacitated Facility
Location Problem (Daskin 2013, Ch. 4)," which was never true of this code. A hub
is taken only if there are **≥2 shipments** and it beats direct pickup by
**more than 5% on the weighted objective** — note the threshold is applied to
the *objective*, not to cost, so a time- or carbon-weighted strategy can accept
a hub that costs slightly more. The response reports both percentages
separately (`objective_savings_pct` vs `savings_vs_direct_pct`) so the two are
never confused.

## 7. Why the four strategies diverge — and when they don't

The lever, per objective:

- `cost`: dominated by component price. Verified on the demo BOM: post-filter,
  the max/min price ratio for the same MPN across distributors is **3.8× to
  17.1×** (ESP32-WROOM-32UE-N4 3.80×; STM32F103C8T6 17.14×; GD25Q64CSIGR 9.01×;
  ESP8266EX 4.33×; ATMEGA328P-PU 8.14×). This is the lever.
- `time`: distributor handling tier + `ceil(distance / 800)` — discrete days,
  not a distance scalar. International legs use a door-to-door air model
  (fixed handling + uplift wait + flight time over actual distance + clearance),
  so two international suppliers on different continents get different ETAs.
- `carbon`: actual shipment weight × distance, at the truck factor domestically
  and the air factor internationally — varies by SKU and quantity.
- `cross-dock decision`: differs per strategy because the weighted objective
  differs — "fastest" avoids hubs (dwell time), "greenest" prefers them
  (tonne-mile reduction).

**Do not claim the four are always distinct.** They are not, and the backend
says so rather than inventing differences. `strategy_divergence` groups the
alternatives on the **sourcing assignment set** — the (component, distributor,
quantity) triples — and publishes how many genuinely distinct plans came back.
When all four converge, the API says in plain words that "the fixed per-supplier
freight charge dominates at this size, so there is nothing left for the
cost/time/carbon weightings to trade off — the alternatives are one plan shown
four times, not four options." Identical plans share ranks instead of being
separated by list order.

That degenerate case is a **feature to talk about, not a bug to hide**: on a
small BOM the $75 fixed charge dwarfs the price spread, so one supplier wins
under every lever setting. It is the correct answer to the model as posed, and
it is exactly the kind of thing a naive dashboard would paper over.

## 8. Extensions (Sub-Project B)

- **A real lead-time term inside the Stage 1 objective** — the clean fix that
  retires the two proxy levers. This is the honest #1 item and it is flagged
  in-source next to the calibrated proxy values.
- Two-echelon joint MILP (facility + routing in one program)
- Time windows on distributor pickup
- Stochastic demand (Monte Carlo + robust optimization)
- OSRM driving distances instead of haversine (the map already calls OSRM, but
  only for a display polyline — the optimizer never sees a road distance)
- Weather + traffic per-leg ETA adjustment
- Air freight as an explicit decision variable
- ε-constraint or a true Pareto front, if genuine multi-objective is wanted

## 9. The follow-up questions you will actually get

**Q1. "So this isn't really a multi-objective optimization, is it?"**
Correct, and I'd rather say so than dress it up. Stage 1 is a single-objective
cost minimization. Time and carbon enter it as three named proxy levers, and the
weighted sum runs *after* sourcing — on hub choice, and on presenting the four
finished plans. A true multi-objective program would need lead time and CO₂ as
linear terms inside the Stage 1 objective. That is the top item on the extension
list, and the proxies are there because they were cheap and measurable, not
because I think they're equivalent.

**Q2. "Why decompose sourcing and routing instead of solving them jointly?"**
Three reasons, in order of honesty. (1) The joint problem is a two-echelon
location-routing problem, which is materially harder — the fixed-charge
supplier-selection MILP and the TSP are each easy, their composition is not.
(2) The decomposition is **not optimal**: Stage 1 chooses suppliers without
knowing the tour Stage 2 will build over them, so it can pick a set that is
cheap to buy from and expensive to drive between. `transport_penalty_scale` is
a partial hedge against exactly that, which is why it exists. (3) At the real
problem size the gap is small — carts here select 1–4 distributors, and with
four or fewer stops there is very little tour cost left to trade against unit
price. I'd want the joint model before scaling this to a 40-line BOM.

**Q3. "Why weighted-sum scalarization rather than an ε-constraint method or a
Pareto front?"**
Weighted sum is the standard first move (Marler & Arora 2004) and it is what the
four strategy profiles express. Its known weakness is real: a weighted sum
cannot reach points on a **non-convex** part of the Pareto frontier, no matter
how you choose the weights. Here that matters less than usual, because I'm not
using it to search — I'm using it to *score four plans that already exist*, so
there is no frontier being traversed. If I wanted a real frontier I'd use
ε-constraint: minimize cost subject to CO₂ ≤ ε, and sweep ε.

**Q4. "Your weights are reported but never used to pick anything. Why publish
them?"**
Because they are the strategy's stated preference and the user picks the
alternative. The number is transparency, not a decision. I'd rather show the
scalarization and let someone check my arithmetic than have a hidden ranking
rule. If I wanted the backend to choose, `weighted_total` is the argmin to use —
but then I'd owe a defence of the weights themselves, which are literature-cited
profiles, not elicited from a decision-maker.

**Q5. "Those `×100` and `×10` factors in the cross-dock objective — where do
they come from?"**
Nowhere. They are ad-hoc unit bridges that put days and kg of CO₂ on a roughly
dollar-like scale so the weights aren't swamped by raw magnitude. They're
legitimate for exactly one reason: both sides of the direct-vs-hub comparison
pass through the identical transform, so the argmin within a strategy is
unaffected. They would be indefensible if I used them to compare *across*
strategies — which is why the cross-strategy comparison uses min-max
normalization instead. The honest fix is monetizing days and kg (a
per-day delay cost and an internal carbon price) so the objective is in dollars
throughout.

**Q6. "Is the tour actually optimal?"**
At ≤8 stops, yes, and provably: every distinct tour is enumerated on the same
integer-metre matrix, `n!/2` after folding reversal symmetry — 20,160 at 8
stops, measured at 7 ms. Above 8 it's GUIDED_LOCAL_SEARCH and the response says
`proven_optimal = false`. The cut is at 8 because 9 stops is 66 ms and 10 stops
is 0.70 s, and this runs synchronously in one uvicorn worker on 0.5 CPU, so it
blocks the whole API while it runs. Also worth knowing: GUIDED_LOCAL_SEARCH has
**no convergence criterion** — it always spends its full time budget.

**Q7. "Is the risk premium a probability?"**
Only one factor of it is. `P(macro stress)` comes from a trained regime model
with a published ship gate. The vulnerability index it multiplies is a
hand-weighted directional score, and the ceiling on the whole surcharge is a
chosen policy bound, not an estimate. So the product is a **risk weight, not a
calibrated expected cost**. The same caveat applies to the graph and feed
surcharges. I'd want a proper expected-recourse-cost formulation before calling
any of it a probability.

**Q8. "Why is the endpoint called `/optimize/vrp` if it's a TSP?"**
Historical. It predates the pivot and is kept so the public API and frontend
don't break. It's a single-vehicle, uncapacitated, symmetric TSP with no time
windows — one vehicle, one transit callback, no capacity dimension. The route
name is a legacy label, not a claim about the model.

**Q9. "Where does the data actually come from?"**
A static 2024 Nexar/Octopart snapshot redistributed on HuggingFace under
CC-BY-4.0: 791 components, 92 distributors, 8,176 offers, all in the served
database. Prices, suppliers and stock are real. Nothing in the pipeline is
synthetic — where real data doesn't exist for something, the code says so
rather than filling the gap.
