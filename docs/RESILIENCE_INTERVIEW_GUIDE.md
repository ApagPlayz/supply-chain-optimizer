# Resilience Dashboard — Interview Narrative

> **Every number in this guide is reproduced from a real run against the seeded
> DB (2026-07-06).** No illustrative or aspirational figures. If the demo shows
> something different, trust the demo and update this file — never quote a number
> you can't reproduce live. Where the honest number is unflattering, the honest
> framing is the stronger interview move; those are called out explicitly below.

## Opening: The Problem

Modern supply chains are optimized for cost and speed, but fragility is hidden in
the network structure. We've built a tool that makes that structure visible and
quantifiable — and, importantly, that tells the truth about it, including where the
network turns out to be *robust*.

## The Graph Resilience Metrics

**Story:** I model the supply base as a bipartite distributor→component graph and
compute standard spectral/graph metrics on it: algebraic connectivity (Fiedler
value), betweenness centrality, PageRank, k-core, and HHI concentration.

**The real, honest headline (this is a strength, not a weakness — lead with the
candor):**

- **The graph fragments into 43 disconnected components.** Whole-graph algebraic
  connectivity is therefore **exactly 0.0** — mathematically correct, not a solver
  failure, and not by itself informative (a disconnected graph always has λ₂ = 0
  no matter how tightly-knit the pieces are). The API and UI now report that
  number *and* a second one that actually says something: **λ₂ of the giant
  (largest) connected component is 0.238**, computed on 839 of 883 total nodes
  (**95.0%** of the graph). *"The whole-graph number is a floor by construction —
  what matters is that 95% of the network sits in one component, and that
  component's own connectivity (0.238) is moderate, not fragile: it would take
  removing several well-placed distributors, not just one, to fracture it
  further. The other 5% — 44 nodes — are the real single-point risks: parts or
  distributors with no path into the main network at all, which is exactly what
  the single-source list below enumerates."*
- **Concentration is real but modest:** DigiKey is the single largest distributor
  at **11.2% of all offers** (918 of 8,176); the top 5 (DigiKey, Verical, Mouser,
  Arrow, Newark) together are **~34%**. *"There's no single point that owns half
  the supply — concentration is moderate, which the HHI confirms."*

**Why this framing wins:** the tempting story is "one distributor owns 40%, the
network is one failure from collapse." The data doesn't support that, and an
interviewer who pokes it would catch a fabrication. The real story — *weak global
connectivity but genuine per-line redundancy* — is more nuanced and more credible.

## Scenario 1: Distributor Failure (Graph-Based)

**Demo:** "Distributor Failure" tab → select **DigiKey** → simulate. BOM used for
these numbers: 8 real DigiKey-supplied components.

- **Real result:** **0 components orphaned. Cost delta ≈ 0%. Risk score unchanged
  (~0.106). Fulfillment P10/P50/P90 unchanged.**
- **Narrative (the honest, strong version):** *"This is the tool proving resilience
  where it exists. Every DigiKey line on this BOM has at least one real alternative
  distributor, so a full DigiKey outage is absorbed with essentially zero cost or
  fulfillment impact. A tool that only ever manufactures a crisis isn't useful — the
  value is that it can also tell procurement 'you're already hedged here, spend your
  redundancy budget elsewhere.'"*
- **The pivot to where it *does* bite:** *"The interesting question is which
  distributor, if lost, actually hurts. I can sweep every distributor and rank them
  by real orphan count and cost delta — that ranked list is the procurement
  deliverable, not any single scenario."* (See the "next build" note at the bottom —
  the distributor-ranking sweep is the natural next feature.)

**Key metrics on the cards:** cost delta, ETA delta, risk delta, and P10/P50/P90
fulfillment — all computed from the Monte Carlo, all real.

## Scenario 2: Geopolitical Risk (Live Feeds + Graph)

We pull live, keyless data from **two sources today: GPR (Geopolitical Risk Index)
and IMF PortWatch (port disruption).** Two further connectors — ACLED (conflict
events) and FRED (freight indices) — are built and degrade gracefully, but are
**dormant in the current deployment because their API keys aren't provisioned.**
Say that plainly if asked; don't claim four live feeds.

**Demo:** Adjust risk slider to **2.0x** current GPR.

- **Real result:** BOM risk score rises **0.106 → 0.188**; **2 components migrate a
  risk tier** (one medium→high, one low→medium); cost delta **+0.1%**.
- **Narrative:** *"During an actual crisis I can scale the live GPR signal and see,
  instantly and traceably, which specific components cross a risk tier. The dollar
  delta here is small because this BOM is well-diversified — but the tier migration
  tells me exactly where to watch."*

**Live feed values at last run:** GPR ≈ 128.8; PortWatch LA/LB 1.01, NY/NJ 1.01,
Savannah 0.87.

## Scenario 3: Delivery Acceleration (Optimization Constraint)

**Demo:** Set delivery target to **14 days**.

- **Real result:** Of 92 distributors, **37 can meet a 14-day window, 55 cannot**
  (lead time derived from real distributor geography, not a constant). Cost delta
  **+0.5%**; scenario ETA capped at 14.0 days.
- **Honest nuance:** *"Baseline BOM ETA is already ~3 days because the fastest
  supplier per line is close, so a 14-day target isn't binding on cost here — it
  mainly prunes the slow half of the supplier base. Tighten the slider and you watch
  suppliers drop out and the premium climb."*

**Key metrics:** suppliers capable vs. cannot-meet (real lists), cost delta, ETA,
risk delta.

## The Interview Hook

After running 2–3 scenarios:

*"The real power is that these are honest trade-offs, not a dashboard that always
screams red. When your CFO asks 'are we exposed to DigiKey?' I can show them: on
this BOM, no — you're hedged. When they ask 'what would a 2-week delivery floor
cost?' I can show the real supplier split and premium. And when the topology *is*
fragile — the network splits into 43 components and 5% of nodes sit outside the
main one entirely — I can point at exactly which components are single-threaded,
while also being honest that the 95% giant component itself is moderately
connected (λ₂ = 0.238), not on the verge of collapse. That's supply chain
optimization you can defend line by line."*

## Technical Depth (If Asked)

- **Graph metrics:** algebraic connectivity (Fiedler), betweenness centrality,
  PageRank, k-core decomposition, HHI. Computed with NetworkX; the API reports
  BOTH whole-graph λ₂ (exactly 0.0 — the graph is disconnected, 43 components)
  AND λ₂ of the giant connected component (0.238, on the unweighted Laplacian —
  ARPACK does not converge on the stock-weighted Laplacian for this graph size,
  confirmed empirically, so the unweighted version is used and labeled as such).
- **Monte Carlo simulation:** 1,000 single-round percolation scenarios (fixed
  seed=42). Each independently fails distributors weighted by normalized betweenness,
  then checks which BOM lines lose *all* their suppliers. This is percolation, **not**
  an SIR/time-cascade model — no propagation or recovery dynamics — and I'll say so
  rather than overclaim.
- **Tail metric:** **CVaR-95 (Conditional VaR / Expected Shortfall)** — the mean
  emergency-procurement cost multiplier over the worst-5% of scenarios. (Earlier
  drafts mislabeled this "EVaR"/Entropic VaR; it is CVaR.)
- **Live feed integration:** GPR + PortWatch live (keyless); ACLED + FRED built but
  dormant pending keys. All degrade gracefully with no fabricated fallback values.
- **Optimization:** CP-SAT (OR-Tools) fixed-charge sourcing MILP, single-worker for
  reproducibility (seed=42). Benchmarked vs naive + consolidation-aware greedy
  baselines through one shared cost function (the "44.7% / 33.9% cheaper" headline is
  a fixed-fee artifact — see the benchmark section below before quoting it).
  Resilient mode = graph surcharge (betweenness × expected recourse cost,
  Snyder–Daskin) **plus** a hard dual-sourcing cap (`≤⌈n/2⌉ lines per distributor`)
  that fires only on single-hub BOMs — see the graph-aware section for the real
  cost-vs-cascade-risk trade-off numbers.
- **Caching / perf:** 1-hour TTL scenario cache; P99 < 2s; cache hits < 50ms;
  OpenTelemetry tracing.

## Demo Checklist

- [ ] All three tabs visible and clickable
- [ ] Distributor dropdown populated (>50 distributors listed)
- [ ] Risk slider smooth (0.5x to 5.0x)
- [ ] Delivery slider smooth (1–90 days)
- [ ] Simulate buttons trigger API calls <2s each
- [ ] Delta cards show cost/ETA/risk changes
- [ ] Monte Carlo chart renders with confidence bands
- [ ] BOM impact table expandable, showing **real** per-supplier lead times
- [ ] Error messages user-friendly if backend unavailable
- [ ] No console errors or TypeScript violations
- [ ] Caching verified: 2nd request ~100ms faster than 1st

## Talking Points Summary

1. "Supply chain resilience is a graph problem — find the critical nodes, and be
   honest about the ones that turn out not to be critical."
2. "Monte Carlo shows distribution tails (CVaR-95), not just means — that's where
   the risk lives."
3. "Overlay live geopolitical data (GPR, PortWatch) to surface regional concentration."
4. "Quantify the cost of resilience — and prove redundancy where it already exists."
5. "Optimize under constraints — a real MILP that jointly handles MOQ, stock, cost,
   delivery and risk. And I audited its headline: the '44.7% cheaper than a naive
   buyer' was a fixed-fee artifact that decays to ~3% at production volume. It's a
   feasibility tool, not a cost tool." *(See the benchmark section — this is the
   strongest story here, precisely because it's the one where I caught myself.)*
6. "Turn analysis into a decision — a ranked dual-sourcing plan (14 no-regret fixes),
   not just delta cards."

## System Requirements (Local Demo)

- Backend: `python -m uvicorn app.main:app --reload` (port 8000)
- Frontend: `npm start` (port 3000)
- Database: SQLite at `supply_chain.db`
- Optional Jaeger for tracing; app works without it.

## Seed Data & Provenance

The system ships with 791 real electronic components, 92 distributors and 8,176 offers
from a public electronic-components supply-chain dataset — originally collected via the
Nexar API in **2024**, redistributed on HuggingFace (`mdnh/electronic-components-supply-chain`,
CC-BY-4.0). Prices and stock are **real observed distributor offers**, but they are a
**frozen 2024 snapshot, not a live feed** — say "static snapshot," never "live Nexar API."
(`seeds/seed_live.py` is a genuine live Nexar puller, but no Nexar credentials are
configured, so it is not what produced this data.) See `docs/DATA_PROVENANCE.md`. **Lead times** are collected from DigiKey/Mouser as real
observed data via the lead-time collector (`app/ml/lead_time_collector.py`) — never
a synthetic formula. **Per-part demand magnitude is illustrative**; the real,
defensible demand signal is the Census M3 New Orders backtest
(`docs/FORECAST_BACKTEST.md`), and the per-SKU forecasting technique is validated on
the real Monash intermittent-demand dataset.

## Reproduce These Numbers

All figures above were captured on 2026-07-12 from the seeded `supply_chain.db`:
whole-graph Fiedler = 0.0 (43 graph components; mathematically exact, not a solver
fallback); giant-component Fiedler = 0.238 (839/883 nodes = 95.0% of the graph, computed
on the unweighted Laplacian — see `backend/app/graph/builder.py`); DigiKey 11.2% of 8,176 offers (top-5 ≈ 34%);
DigiKey-failure on an 8-line BOM → 0 orphans / ~0% cost / risk 0.106 unchanged;
GPR 2.0x → risk 0.106→0.188, 2 tier migrations, +0.1% cost; 14-day target → 37/92
suppliers capable, +0.5% cost. Re-run before any demo and update if they drift.

## The Optimizer Benchmark — READ THIS BEFORE YOU QUOTE 44.7%

> **DO NOT say "my optimizer is 44.7% cheaper than a naive buyer."** It is true as
> arithmetic and worthless as a claim, and a good interviewer will dismantle it in
> about five minutes. Say the thing below instead — it is a *better* answer, and it
> is the one the data supports. Full analysis: `docs/BENCHMARK_VOLUME_CURVE.md`.

**Why the headline is an artifact.** The greedy baseline picks the cheapest offer per
BOM line, which makes it the **component-cost minimum by construction**. The MILP
therefore *cannot* beat it on component cost — it can only win on fixed charges. And
each distinct distributor opened costs a flat **$75 (LTL) / $150 (air)** freight fee.
Now look at the scale the benchmark actually runs at:

| `iot_sensor_node` at 1× (4 parts, 5 units) | |
|---|---:|
| Component cost | **$6.96** |
| Fixed freight fees | **$450.00** |
| Total "landed cost" | $466.39 |

**Fixed fees are 96.5% of the number being optimized.** The MILP consolidates 3
suppliers → 1, avoids $341 of fees, and books a 72% "saving" on a **seven-dollar**
order. Aggregated across all 10 BOMs, of a $3,326 total saving: **+$3,863 is avoided
fixed fees**, +$24 is variable freight, and **−$561 is component cost** — i.e. fixed
fees are **116% of the saving**, and the MILP pays *more* for the parts. It loses on
component cost in **10 of 10** BOMs (it must — greedy is the component-cost minimum)
and funds that loss entirely out of avoided supplier fees.

**The saving is a constant, not a rate.** It is `$75 × suppliers avoided`, so it
barely moves with volume while component cost grows linearly. Only the denominator
changes:

| Volume (`iot_sensor_node`) | Saving % | Absolute saving |
|---|---:|---:|
| 5 units (as benchmarked) | **72.4%** | $337.79 |
| 50 units | 54.4% | $304.41 |
| 500 units | 17.8% | $266.76 |
| 5,000 units | 9.3% | $1,122 |
| 50,000 units | **3.1%** | $3,790 |

Aggregate across BOMs (pooled — the same definition that produced the published
44.66%): **47.7% → ~2.8%.** At any volume a real manufacturer would actually order,
this optimizer's cost edge is **noise**.

*(Caveat worth volunteering: the stock snapshot can't support production volume for
every BOM, so the high-volume cohort is smaller than the low-volume one — 10 BOMs at
1×, 5 at 500×, 2 at 10,000×. The decay is not an artifact of that thinning: it holds
within each individual BOM too, as the `iot_sensor_node` column above shows.)*

### What to say instead (this is the good version)

> *"My benchmark said the optimizer was 44.7% cheaper than a naive buyer. I didn't
> believe it, so I decomposed it — and the entire win was the $75-per-supplier fixed
> freight fee. On a 4-part, 5-unit BOM, component cost is seven dollars and fixed fees
> are $450, so 'optimization' was really just 'don't pay the shipping charge three
> times.' The MILP even pays more for the parts. I re-ran it as a function of volume:
> the advantage decays from 72% to about 3% by 50,000 units, because the saving is a
> constant and only the denominator grows. So the honest claim is that this optimizer
> is a **feasibility and flexibility** tool, not a cost tool — it respects MOQ and
> stock, it can split a line across distributors where greedy structurally can't, and
> it does the cost/time/carbon tradeoff. Its cost edge at production volume is
> approximately zero, and I'd rather tell you that than have you find it."*

That answer demonstrates the thing the 44.7% never could: that you audit your own
results, you understand fixed-charge economics well enough to know *where* a win comes
from, and you will not oversell a number to a stakeholder. **This is the strongest
story in the project — lead with it.**

**The mechanism, named properly:** this is the classic fixed-charge / facility-location
tradeoff (Balinski 1961). The MILP is solving it correctly. The problem was never the
solver — it was that the instance was too small for the answer to mean anything.

**If they ask "so is the MILP useless?"** — no, and say why precisely: it produces
*executable* plans (hard stock/MOQ constraints — the greedy baseline happily orders
2,500 units from an offer holding 1), it can split a line across distributors, and it
proves optimality. Those are real. They are just not *cost* wins.

**Known modelling flaw, disclose it if pressed:** `_transport_cost_by_did` charges
every opened supplier freight for a full representative BOM shipment regardless of how
little it actually ships, so splitting across 3 suppliers *triples* variable freight
instead of dividing it. Re-scored with freight allocated by real shipped weight, even
the residual ~3% edge at scale decays to **0.68%**. It is on the fix list, and it is
not fixed yet.

## The Recommendation Engine — from numbers to decisions (shipped)

The 4th "Recommendations" tab turns the dashboard into a ranked procurement
deliverable (all figures real from the DB):

- **Distributor-criticality sweep** — ranks all 92 distributors by real orphan count,
  spend-at-risk, and REI. The most critical node is **Component Stockers USA** (5
  orphaned components, ~$500 spend-at-risk) — *not* the biggest distributor, echoing
  the MIT/Ford "riskiest part isn't the highest-spend part" finding.
- **Ranked dual-sourcing plan** — of 38 single-source components, **14 are "no-regret"**
  (a second source is same-price-or-cheaper — add it now), **10 are "hedge"** (ranked
  by risk-reduction-per-dollar), and **14 are "supplier-development"** (no qualified
  alternative exists — an honest gap, surfaced not hidden).
- **One-way sensitivity / tornado** — total cost / CVaR-95 vs real levers (GPR stress,
  delivery target, most-critical-distributor availability, emergency premium).

## Graph-Aware Resilient Sourcing — the cost of eliminating single points of failure

**The finding that motivates it (tell this first):** the cost-optimal MILP consolidates
each BOM onto the single cheapest distributor to avoid the ~$75 per-supplier fixed
charge. That hub is then a single point of failure — under a *targeted* outage of the
BOM's highest-betweenness distributor, `plan_cascade_risk → 1.0` (the whole BOM
orphans). A soft surcharge can't overcome the fixed-charge economics on cheap parts,
so resilience needs a **hard constraint**, not a bigger penalty.

**Resilient mode** = the principled expected-disruption-loss surcharge (betweenness ×
recourse cost, Snyder–Daskin 2005) **plus a mandated second source**: for any BOM the
cost-optimizer consolidated onto one hub, cap the lines any single distributor may
serve (`≤ ⌈n/2⌉`), forcing the plan across ≥2 suppliers. It fires *only* on
single-hub BOMs — already-diversified plans are left untouched (no reshuffle, no
cost, no regression).

**Real numbers (run_id=4, all 9 BOMs benchmarked, blind → resilient):**

| BOM | suppliers | targeted cascade risk | cost premium |
|-----|:---------:|:---------------------:|:------------:|
| smart_meter | 1 → **2** | **1.00 → 0.00** (eliminated) | +25.4% |
| pcb_power_supply | 1 → **2** | **1.00 → 0.25** | +81.1% |
| iot_sensor_node | 1 → **2** | **1.00 → 0.50** | +84.5% |
| robotics_servo_driver | 1 → **2** | **1.00 → 0.50** | +5.6% |
| industrial_motor_driver | 1 → **2** | **1.00 → 0.75** | +16.6% |
| automotive / rf / drone / medical | already ≥2 | unchanged | +0.0% |

**The headline you can defend:** *"For the 5 BOMs the optimizer had put on a single
hub, mandating a second source cuts the targeted-outage cascade risk from 100% — on
`smart_meter`, to zero — for a cost premium of 5–85%, and that premium is exactly the
value of the fixed-charge consolidation you're giving up. The tool prices resilience
per BOM so procurement can decide which single points of failure are worth paying to
remove."*

**Honest caveats to volunteer:**
- The premium is steep where the single hub was much cheaper (iot +84.5%, pcb +81.1%)
  and cheap where it wasn't (robotics +5.6%) — that spread *is* the finding.
- Broad *stress* (every distributor degraded at once) isn't helped by 2-sourcing
  within a stressed pool — dual-sourcing hedges *idiosyncratic* single-node failure,
  not correlated system-wide shocks. Say so.
- Next step for the truly-textbook version: a scenario-based CVaR term in the objective
  (two-stage stochastic program) instead of a hard cap — scoped, not faked.

*Why this reads as senior:* you show the cost-vs-resilience tension, price it, and are
candid about exactly what dual-sourcing does and doesn't protect against.
