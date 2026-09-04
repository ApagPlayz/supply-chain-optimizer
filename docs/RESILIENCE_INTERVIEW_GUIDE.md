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

- **The graph fragments into 34 disconnected components — but that number is far
  less alarming than it sounds, and saying why is the point.** Whole-graph
  algebraic connectivity is **exactly 0.0** — mathematically correct, not a solver
  failure, and not by itself informative (a disconnected graph always has λ₂ = 0
  no matter how tightly-knit the pieces are). The API and UI report that number
  *and* a second one that actually says something: **λ₂ of the giant (largest)
  connected component is 0.279**, computed on **847 of 883** total nodes
  (**95.9%** of the graph). *"A count of 34 components sounds like a shattered
  network. It isn't. One component holds 847 of 883 nodes; the other 33 hold
  **36 nodes between them** — so none of them can be larger than four nodes, and
  at least 30 are single isolated nodes. This isn't a network split into 34 rival
  sub-networks; it's one network plus a fringe of orphans. The whole-graph λ₂ of
  0.0 is a floor by construction — the number that means something is the giant
  component's own connectivity, 0.279, which is moderate, not fragile: it would
  take removing several well-placed distributors, not just one, to fracture it
  further. The real single-point risk is that 4% fringe — 36 nodes with no path
  into the main network at all — which is exactly what the single-source list
  below enumerates."*
- **Concentration is real but modest:** DigiKey is the single largest distributor
  at **11.2% of all offers** (918 of 8,176); the top 5 (DigiKey, Verical, Mouser,
  Arrow, Newark) together are **~34%**. *"There's no single point that owns half
  the supply — concentration is moderate, which the HHI confirms."*

**Why this framing wins:** the tempting story is "one distributor owns 40%, the
network is one failure from collapse." The data doesn't support that, and an
interviewer who pokes it would catch a fabrication. The real story — *technically
disconnected, but 95.9% of it is one piece with genuine per-line redundancy, and
the fragility is a short, nameable list of 36 orphan nodes* — is more nuanced and
more credible. **Do not lean on the component count as a fragility claim.** If you
say "34 components" and stop, an interviewer will reasonably assume a shattered
supply base and then be unimpressed when the resilience scenarios show nothing
breaking. Say the size distribution instead: one giant component, 33 fringe
components holding 36 nodes total.

### The self-audit: "tell me about a bug you found in your own work"

This is a real finding from this project and it is one of the strongest answers in
the guide, because it is a *measurement* bug — the kind that quietly invalidates
published numbers without ever throwing an error.

**What happened.** Every graph figure above was, until **2026-09-03**, computed on
only **80% of the supplier–part links**. The builder carved out a random 20%
holdout *before* constructing the graph, so **1,574 of 8,176 offers** never entered
any topology calculation. Nothing failed; the API returned plausible numbers; the
UI rendered them; two documents agreed with each other. It just wasn't the whole
graph.

**Why the carve existed — and this is the part that makes it a good story.** It was
not sloppiness. Git history (commit `da16157`, 2026-04-16) shows it was a
**deliberate leakage guard** — the commit adds `_HOLDOUT_FRACTION = 0.20`,
`_HOLDOUT_SEED = 42` and a comment reading *"Holdout partition — carve before graph
construction"*, so a planned benchmark phase could not evaluate on links the graph
had already seen. That is the correct instinct. But **four days later**, when the
benchmark actually landed (commit `885f436`, 2026-04-20), it explicitly declined to
use it. Its own header says so:

> *"HOLDOUT SEMANTICS (BENCH-06): run_benchmark.py uses ALL offers because the
> benchmark IS the holdout evaluation. The Phase 2 holdout partition existed to
> keep strategy-tuning honest; no tuning happens here, so no filter is applied."*

The guard was now guarding nothing, and no one removed it. It sat inert for about
**4.5 months**, silently shrinking every published topology figure.

**The one-line framing to say out loud:** *"A leakage guard for an evaluation step
that was later designed not to need it."*

**What it changed** (and note the direction — the correction made the network look
*better*, which is why nothing about it was self-serving to find):

| Metric | Reported (80% of links) | Correct (all links) |
|---|---|---|
| Edges | 5,789 | **7,363** |
| Connected components | 43 | **34** |
| Giant component | 839 nodes (95.0%) | **847 nodes (95.9%)** |
| λ₂ of giant component | 0.238 | **0.279** |
| Max k-core | 23 | **30** |
| Max betweenness | 0.2458 | **0.2915** |
| Single-source components | 38 | **38 (unchanged)** |

**The two follow-up questions you should be ready for:**

- *"How do you know it's right now?"* — because there is now an exact arithmetic
  invariant that has to hold: every offer row is either an edge or a duplicate of
  one, so **`n_edges + n_duplicate_offer_rows == n_offer_rows`** — 7,363 + 813 =
  8,176. The old code could not satisfy that identity; the missing 1,574 rows had
  nowhere to be accounted for. An invariant that must balance is what turns a
  silent omission into a loud failure.
- *"Did any conclusion flip?"* — no, and say so plainly. The single-source count is
  **38 either way**, the whole graph is still disconnected (λ₂ = 0.0), and the
  qualitative reading — moderate concentration, real per-line redundancy — held.
  What changed is that the network is measurably **less** fragmented than I had
  been publishing. The honest summary is: *I was overstating fragility by about a
  quarter, and I found it by auditing my own inputs rather than by something
  breaking.*

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
  (lead time derived from real distributor geography, not a constant). Baseline ETA
  **26.6 days → 9.2 days (−17.4 d)** for a cost delta of **+94.7%**.
- **Honest nuance:** *"The cost-optimal plan lands in 26.6 days because four of five
  lines buy from Singapore. A 14-day window pulls that to 9.2 days and costs 94.7%
  more. That is the trade — and it is only visible because the ETA is computed over
  the suppliers the plan actually buys from."*
- **The bug worth telling them about:** this page used to publish a baseline ETA of
  **2.8 days**, a 9.4× understatement, because `_bom_eta_days` took the *fastest*
  supplier per line while `_price_bom` bought the *cheapest*. Cost and ETA described
  two different plans. The tell was on the page the whole time — the line-by-line
  table named Singapore as the baseline supplier for four lines. Fixed 2026-08-28;
  a regression test now re-derives the argmin-price supplier from raw offer rows and
  asserts the published ETA covers it.
- **The counter-intuitive result it unlocked:** losing the cheapest distributor makes
  the BOM arrive **3.2 days sooner** and cost **28.5% more**. A cheap distant supplier
  is also your slow one. The old code reported that delta as exactly 0.0.

**Key metrics:** suppliers capable vs. cannot-meet (real lists), cost delta, ETA,
risk delta.

## The Interview Hook

After running 2–3 scenarios:

*"The real power is that these are honest trade-offs, not a dashboard that always
screams red. When your CFO asks 'are we exposed to DigiKey?' I can show them: on
this BOM, no — you're hedged. When they ask 'what would a 2-week delivery floor
cost?' I can show the real supplier split and premium. And where the topology
genuinely *is* thin, I can name it rather than gesture at it: 36 of 883 nodes —
about 4% — sit outside the main network entirely, and 38 components are
single-sourced. That's a short list procurement can actually act on. The flip side
is the part I have to be equally willing to say: the other 95.9% is one connected
piece whose own algebraic connectivity is 0.279 — moderate, not on the verge of
collapse. The tool's job is to tell you which of those two things you're looking
at. That's supply chain optimization you can defend line by line."*

## Technical Depth (If Asked)

- **Graph metrics:** algebraic connectivity (Fiedler), betweenness centrality,
  PageRank, k-core decomposition, HHI. Computed with NetworkX; the API reports
  BOTH whole-graph λ₂ (exactly 0.0 — the graph is disconnected, 34 components)
  AND λ₂ of the giant connected component (0.279, on the unweighted Laplacian —
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
  baselines through one shared cost function — freight modelled as a true fixed charge
  (per-visit fee) **plus** a per-unit rate on units actually shipped, so both arms are
  scored identically and splitting an order is not penalised (the "44.7% / 33.9%
  cheaper" headline is a fixed-fee artifact — see the benchmark section below before
  quoting it).
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
   buyer' was a fixed-fee artifact of 5-unit BOMs. Auditing it turned up a real freight
   bug — the model charged every supplier a full BOM's freight instead of allocating it
   — and fixing that cut *against* my retraction: the corrected edge at production
   volume is 3–8%, earned by routing volume on price + freight, not by dodging fees.
   I reported the correction that helped me for the same reason I reported the one that
   hurt." *(See the benchmark section — this is the strongest story here, precisely
   because it's the one where I caught myself.)*
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
configured, so it is not what produced this data.) See `docs/DATA_PROVENANCE.md`. **Lead times** are real observed DigiKey values — never a
synthetic formula — but be precise about how many and when.

> **Two different numbers, and conflating them is the mistake to avoid.** The *panel on
> disk* and the *model being served* drift apart between retrains, because the collector
> runs weekly and the model is retrained by hand. They are the same vintage right now
> (retrained 2026-09-03); they will diverge again on the next Monday collector run. Both
> numbers below are true; they are answers to different questions.
>
> | Question | Answer | Where it comes from |
> |---|---|---|
> | How much lead-time data have we collected? | **2,664 rows across five snapshot dates** | `seeds/data/lead_time_panel/observed_lead_times.csv` on disk, sha256 `c68e2891…` |
> | What was the served model trained on? | **2,615 rows** (of the 2,664 in the panel; 49 dropped for a missing label or a bad match), 5 snapshots, 324 features | `metrics.joblib['provenance']`, trained 2026-09-03, panel sha256 `c68e2891…` |

The panel (`seeds/data/lead_time_panel/observed_lead_times.csv`) is **2,664 rows across
five snapshot dates — 75 on 2026-07-01, 742 on 2026-08-15, 363 on 2026-08-17, 742 on
2026-08-24 and 742 on 2026-08-31 — all from DigiKey**. The 2026-08-15 run polled all 791
parts in the DB with a 6.2% miss rate (43 absent from DigiKey's catalog, 6 with no
published lead time); every attempt, hit or miss, is logged in `collection_log.csv`.

**Say this:** *"We have collected 2,664 real DigiKey lead-time observations across five
snapshot dates between 2026-07-01 and 2026-08-31, one distributor. The model currently
deployed was retrained on 2026-09-03 against that whole panel — 2,615 of the 2,664 rows
survive the label and match-quality drops — so the artifact and the panel are the same
vintage today, and they will diverge again the moment the next Monday snapshot lands."*
Never say
"continuously collected", and never call the five dates "weekly": the Monday-06:00-UTC cron
in `collect-lead-times.yml` accounts for 2026-08-17, 08-24 and 08-31 only — 2026-07-01 is a
Wednesday and 2026-08-15 a Saturday, both off-cadence runs. Periodic snapshots are not yet a
time series.

> **⚠ Re-check the two counts before the interview — the collector adds a snapshot every
> Monday 06:00 UTC**, so the panel figure above goes stale on its own without anyone
> touching a document. Thirty seconds, from the repo root:
>
> ```bash
> # panel on disk: rows, then rows per snapshot date
> tail -n +2 backend/seeds/data/lead_time_panel/observed_lead_times.csv | wc -l
> tail -n +2 backend/seeds/data/lead_time_panel/observed_lead_times.csv | cut -d, -f1 | sort | uniq -c
> # what the served model was actually trained on
> cd backend && ./venv/bin/python -c "import joblib; print(joblib.load('data/ml_models/metrics.joblib')['provenance'])"
> ```
>
> If the two disagree, that is normal and it is the answer above. If they *agree*, the
> retrain has landed — then say the single current number and drop the gap framing.

**If they push on the gap, that is the good outcome — it is a feature.** The repo has a
data-vintage tripwire: the artifact records the sha256 of the CSV it was fitted on, and
`model_store.check_training_data_staleness` compares it to the file on disk on every
`/api/v1/ml/model-info` call. It is reporting `stale: false` right now — both hashes are
`c68e2891…` — and it will flip to `stale: true`, naming both hashes and the retrain
command, the moment the next Monday collector run commits. Deliberately a warning and not a build failure, so that a
scheduled collector commit cannot turn CI red on its own. Knowing your served model is
stale — and being able to prove *how* stale — is the point.

**The best thing in this dataset is the paired change between the first two snapshots**
(2026-07-01 and 2026-08-15). Of the 75 parts observed on both of those dates, the 19 that were not at 30 weeks barely moved, while
**all 56 that quoted exactly 30 weeks in July re-quoted to 40 or 52 weeks in August** —
almost all of them STMicroelectronics. That is a real, observed lead-time extension
captured by our own collector, not a story from a news article. It is also why the panel
is worth continuing to grow.

**Do not quote a lead-time R² from a random train/test split.** The panel contains
large near-duplicate families (456 STM32F103 rows, 147 ATMEGA328, 93 TMS320), and
`base_product` alone explains **R²=0.856 of the target in sample** (361 levels over
2,615 rows — an in-sample identity-column figure, NOT a model score and NOT
cross-validated). A random split leaks siblings across the fold boundary and measures
memorization.

The measured collapse, same estimator and rows, 50 folds, only the grouping changing:
**R² +0.825 random → +0.073 grouped by part family → −0.697 holding out whole
manufacturers** (medians +0.826 / +0.140 / −0.104). Effective n for generalization is
**28 manufacturers, not 2,615 rows**. If asked what the negative number means, say it
exactly: R² is scored against the held-out fold's own mean, so a negative value means
the squared error exceeds that vendor's entire label variance — the model has no
explanatory power on a vendor it has never quoted. It still beats `train_mean`
(−2.177) on those folds, so the claim is "nothing in the set generalizes to an unseen
vendor", not "the model is uniquely bad". (Earlier revisions of this section quoted an
810-row, 27-manufacturer vintage — R² +0.638 / +0.082 / −0.550 — and then a 1,879-row,
four-snapshot one — R² +0.804 / +0.084 / −0.784. Both are superseded by the 2026-09-03
retrain; if you see either anywhere else, they are the retired figures.) Numbers and protocol:
[LEAKAGE_PROGRESSION.md](LEAKAGE_PROGRESSION.md). Group by `base_product`.
**Per-part demand magnitude is illustrative**; the real,
defensible demand signal is the Census M3 New Orders backtest
(`docs/FORECAST_BACKTEST.md`), and the per-SKU forecasting technique is validated on
the real Monash intermittent-demand dataset.

## Reproduce These Numbers

All figures above were captured on 2026-07-12 from the seeded `supply_chain.db`, **except
the graph-topology figures, which were re-measured on 2026-09-03** after the dead 20%
link holdout was removed from `graph/builder.py` (see the self-audit section above — the
2026-07-12 topology numbers were computed on 80% of the links and are superseded):
whole-graph Fiedler = 0.0 (34 graph components; mathematically exact, not a solver
fallback); giant-component Fiedler = 0.279 (847/883 nodes = 95.9% of the graph, computed
on the unweighted Laplacian — see `backend/app/graph/builder.py`); 7,363 edges, and
7,363 edges + 813 duplicate offer rows = 8,176 offer rows exactly;
DigiKey 11.2% of 8,176 offers (top-5 ≈ 34%);
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
suppliers → 1, avoids $335 of fees, and books a 72% "saving" on a **seven-dollar**
order. Aggregated across all 10 BOMs (pooled — sum of greedy costs vs sum of MILP
costs), of a $3,304 total saving: **+$3,863 is avoided fixed fees**, +$2 is variable
freight, and **−$561 is component cost** — i.e. fixed fees are **116% of the saving**,
and the MILP pays *more* for the parts. It loses on component cost in **10 of 10** BOMs
(it must — greedy is the component-cost minimum) and funds that loss entirely out of
avoided supplier fees.

**At prototype scale the saving is a constant, not a rate.** It is
`$112.50 × suppliers avoided`, so it barely moves with volume while component cost grows
linearly. Only the denominator changes:

| Volume (`iot_sensor_node`) | Saving % | Fixed-fee share of the saving |
|---|---:|---:|
| 5 units (as benchmarked) | **71.7%** | 102% |
| 50 units | 48.7% | 122% |
| 500 units | 19.1% | 36% |
| 5,000 units | 19.1% | −4% |
| 50,000 units | **7.4%** | −1% |

Aggregate across BOMs (pooled — the same definition the benchmark publishes):
**47.2% at 1× → 2.6%–8.0% between 2,500 and 60,000 units.** The 45% headline is dead.
**Do not quote it.**

*(Housekeeping, 2026-08-16: this line used to say "the same definition that produced
the published 44.66%." That 44.66% no longer exists anywhere. `BENCHMARK_RESULTS.md`
could not be regenerated for months — its generator wrote to a misspelled, CWD-relative
path — so it was still publishing a figure computed before the duplicate-offer and
variable-freight fixes landed. Regenerated on a pinned run it reproduces **−47.25%**,
which now agrees with the 47.2%-at-1× pooled figure above; the two artifacts had been
quietly disagreeing. Note the honest number is **bigger** than the retracted one — the
retraction was never about the size of the saving, it was about the saving evaporating
with volume, and that is unchanged.)*

*(Superseded framing, 2026-09-03: that −47.25% compares a greedy baseline shopping the
full international offer pool against a domestic-only MILP — the pools were never matched.
The benchmark now also solves both heuristics on the optimizer's own domestic pool, and the
like-for-like pooled figure is **−18.79%**. Quote that one; −47.25% is the contrast against a
naive, globally-shopping baseline and must be labelled as such.)*

*(Caveat worth volunteering: the stock snapshot can't support production volume for
every BOM, so the high-volume cohort is smaller than the low-volume one — 10 BOMs at
1×, 5 at 500×, 2 at 10,000×. The decay is not an artifact of that thinning: it holds
within each individual BOM too, as the `iot_sensor_node` column above shows.)*

### The audit found a real bug — and it cut against my own retraction

Chasing that decaying curve turned up a genuine defect. The freight helper computed
**one representative shipment weight for the whole BOM** and charged **every** opened
supplier that full weight regardless of how little it shipped — so splitting across 3
suppliers was billed **3× a full BOM's variable freight** instead of dividing one BOM's
freight across 3 shipments. It corrupted *both* arms (they deliberately share one cost
function), and it made distance almost free at volume.

Freight is now a proper fixed-charge model —
`fixed[d]·opened(d) + per_unit[d]·units_shipped_from(d)` — still linear, so CP-SAT
models it exactly (`greedy.py::landed_cost_breakdown` scores the identical thing, and a
test asserts the solver's objective equals the benchmark's score of the solver's own
plan).

**The fix makes the optimizer look better, and I'm reporting that too.** At ≥500× the
fixed-fee wedge goes to **zero or negative** — the MILP now opens *more* suppliers than
greedy on purpose — and the residual 3–8% edge comes from **routing volume by
price + freight** instead of by unit price alone, which greedy structurally cannot do.
That edge scales with volume and is honestly earned. (An earlier draft of my own
analysis predicted the corrected edge would collapse to 0.68%; that prediction re-scored
the *old* solver's plans under the new freight model without letting the solver
re-optimize. It was wrong, and the corrected number is higher, not lower.)

### What to say (this is the good version)

> *"My benchmark said the optimizer was 44.7% cheaper than a naive buyer. I didn't
> believe it, so I decomposed it — and at benchmark scale the entire win was the
> $75-per-supplier fixed freight fee. On a 4-part, 5-unit BOM, component cost is seven
> dollars and fixed fees are $450, so 'optimization' was really just 'don't pay the
> shipping charge three times.' The MILP even pays more for the parts. So I re-ran it as
> a function of volume — and while doing that I found a bug: the model charged every
> supplier a full BOM's freight instead of allocating freight across shipments, which
> systematically over-penalised splitting. I fixed it, and it cut against me — the
> corrected model makes the MILP look **better** at scale, because it can now optimize
> the term that actually matters at volume: routing units by price *plus* freight. The
> honest number is 47% on a 5-unit prototype, which is fee arithmetic, and 3–8% at
> production volume, which is real. I retracted the 44.7% either way."*

That answer demonstrates the thing the 44.7% never could: that you audit your own
results, you understand fixed-charge economics well enough to know *where* a win comes
from, and you report a correction whether it flatters you or not. **This is the
strongest story in the project — lead with it.**

**The mechanism, named properly:** this is the classic fixed-charge / facility-location
tradeoff (Balinski 1961). The MILP was solving it correctly; the instance was too small
for the answer to mean anything, and the freight term it was handed was wrong.

**If they ask "so is the MILP useless?"** — no, and say why precisely: a real 3–8%
landed-cost edge at production volume, *executable* plans (hard stock/MOQ constraints —
the greedy baseline happily orders 2,500 units from an offer holding 1), line-splitting
across distributors, and proven optimality. What it is not is a 45% cost machine.

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
- **These per-BOM numbers are from the offline benchmark** (`seeds/run_benchmark.py`,
  which calls the solver directly with `graph_aware=True`/`require_dual_source=True`),
  not from a live request through the deployed API. The frontend's VRP call
  (`frontend/src/services/api.ts` → `vrp: () => api.post('/optimize/vrp')`) sends no
  body, so `graph_aware` defaults to `False` on the live `/optimize/vrp` endpoint
  (`backend/app/api/optimize.py`) — a visitor running the tool on the live site today
  gets the blind (non-resilient) plan, not the resilient one tabled above. Wiring the
  flag through the UI is a scoped follow-up, not done here.

*Why this reads as senior:* you show the cost-vs-resilience tension, price it, and are
candid about exactly what dual-sourcing does and doesn't protect against.
