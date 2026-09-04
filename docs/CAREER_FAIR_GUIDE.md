# Career Fair Guide — how to explain this project out loud

**Written 2026-09-04 against commit `56f439e`.** Every number in this file was read from a
committed artifact, from `metrics.joblib`, or from a live API call — never from another
document. Where a figure could not be verified it says so.

This guide is for *talking*, not for building. It teaches you enough to say what a thing
is, why it was chosen, what it produced, and what it does **not** do. That is the level a
career-fair conversation actually needs.

**The one rule that makes all of this work:** you are not selling a perfect project. You
are demonstrating that you can tell the difference between a real result and a flattering
one. Every strong moment in this guide is a moment where a number went *down*.

---

## Contents

1. [Five minutes before you walk in](#1-five-minutes-before-you-walk-in)
2. [The pitch, in three lengths](#2-the-pitch-in-three-lengths)
3. [The numbers that are true](#3-the-numbers-that-are-true)
4. [Red lines — never say these](#4-red-lines--never-say-these)
5. [The five stories worth telling](#5-the-five-stories-worth-telling)
6. [The optimisation half, explained](#6-the-optimisation-half-explained)
7. [The forecasting half, explained](#7-the-forecasting-half-explained)
8. [The network half, explained](#8-the-network-half-explained)
9. [Hard questions, ranked by how likely you'll get them](#9-hard-questions-ranked-by-how-likely-youll-get-them)
10. ["Did you write this?" — the AI question](#10-did-you-write-this--the-ai-question)
11. [Weaknesses you volunteer before they're found](#11-weaknesses-you-volunteer-before-theyre-found)
12. [Glossary — terms you must be able to define](#12-glossary--terms-you-must-be-able-to-define)
13. [One-page cheat sheet](#13-one-page-cheat-sheet)

---

## 1. Five minutes before you walk in

**Warm the demo first.** Both services sleep after ~15 minutes idle, and a cold request was
measured at **over 60 seconds** on 2026-09-04. If you tap the link in front of a recruiter
cold, the page looks broken for a full minute while you stand there explaining.

Two ways to avoid it:

- **Easy:** open `https://supply-chain-ui-bhwz.onrender.com` on your phone ~3 minutes before
  you approach anyone, and re-open it every 10 minutes or so between conversations.
- **Better:** GitHub → Actions → **"Warm the demo"** → *Run workflow*. It pings both services
  every 5 minutes for as long as you ask (default 90 minutes) and fails loudly if either
  one doesn't answer. The GitHub mobile app can start it from a queue.

**Have a fallback.** If the site is down, the story still works — you are describing
*methodology*, and the numbers live in artifacts, not in the page. Say "the demo's asleep,
let me tell you what it does" and keep going. Never stand in silence waiting on a spinner.

**Know your two links:**
- Live app — `https://supply-chain-ui-bhwz.onrender.com`
- API — `https://supply-chain-api-qy8x.onrender.com`

---

## 2. The pitch, in three lengths

### 20 seconds — for a queue

> "It's a supply-chain sourcing optimiser built on real electronics distributor data — 791
> parts, 92 distributors, 8,176 real offers. It decides who to buy each part from, balancing
> cost, delivery time, carbon and supplier-failure risk, using a constraint solver and a
> stochastic risk model. It's deployed and live, and most of what I learned came from
> auditing my own results and finding them overstated."

That last sentence is bait. Most people take it.

### 90 seconds — the standard answer

> "The problem is a real one in procurement: you have a bill of materials, each part is sold
> by several distributors at different prices, lead times and stock levels, and every extra
> supplier you open costs a fixed freight minimum. Picking the cheapest offer per line is
> what most people do, and it's wrong, because it scatters your order across suppliers.
>
> So I formulate it as a mixed-integer program and solve it with CP-SAT. Then on top of that
> there's a second layer: the plan that's cheapest on average isn't the one that survives a
> supplier going down. So I built a two-stage stochastic model that minimises a blend of
> expected cost and *worst-case* cost — CVaR — and traced the whole efficient frontier
> between the two.
>
> Alongside that there's a lead-time model, a macro-regime classifier that feeds a risk
> premium into the optimiser, and a supplier-part network I use to find single points of
> failure.
>
> The part I'd actually want to talk about is that my headline number used to be 47% and it's
> now 18.79%, because I audited my own benchmark and found I'd handicapped the baseline."

### 5 minutes — when they're genuinely interested

Run the 90-second version, then pick **one** story from §5 based on who you're talking to:

| They are | Tell them |
|---|---|
| Operations research / optimisation | The baseline ladder (§5.1) |
| Data science / ML | The leakage progression (§5.3) or scoring rules (§5.4) |
| Data engineering / analytics | The graph audit (§5.2) or the stale feed (§5.5) |
| Procurement / category management | The diversification frontier (§6.6) — "buy the second supplier, not the third" |
| Generalist recruiter | The graph audit (§5.2). It needs no maths. |

---

## 3. The numbers that are true

Verified 2026-09-04. **If a number isn't here, don't say it.**

### The data
| Figure | Value | Source |
|---|---|---|
| Parts | **791** | `/api/v1/graph/metrics` → `n_components` |
| Distributors | **92** | same → `n_distributors` |
| Distributor offers | **8,176** | same → `n_offer_rows` |
| Source | Real Nexar / Octopart electronic-component data | — |

### The network
| Figure | Value |
|---|---|
| Edges (supplier–part links) | **7,363** |
| Duplicate offer rows | **813** |
| **The invariant** | **7,363 + 813 = 8,176** ✅ |
| Connected components | **34** |
| Giant component | **847 nodes (95.92%)** |
| Algebraic connectivity, whole graph | **0.0** (it's disconnected) |
| Algebraic connectivity, giant component | **0.2788** |
| Single-source components | **38** |
| Highest betweenness (one distributor) | **0.2915** |

### The optimiser benchmark — the full ladder
Pooled landed-cost advantage of the MILP over each baseline, 9 BOMs:

| Baseline | Offer pool | Saving |
|---|---|---|
| Naive greedy (cheapest per line) | International | **47.25%** ← *retracted headline* |
| ADD heuristic (Kuehn & Hamburger 1963) | International | **37.10%** |
| Naive greedy | Matched domestic | **34.99%** |
| **ADD heuristic** | **Matched domestic** | **18.79%** ← **the honest one** |

The decomposition is exact: **47.25 − 37.10 = 10.15 pts** was a weaker heuristic;
**37.10 − 18.79 = 18.31 pts** was letting the baseline shop a wider catalogue than the
optimiser was allowed. What remains, **18.79 pts**, is the optimiser optimising.

### Where the 18.79% actually comes from — you must volunteer this
| Component of the $3,303.55 saving | Amount |
|---|---|
| Avoided fixed per-supplier freight fees | **+$3,863.00** |
| Component cost | **−$561.19** (the MILP pays *more* for the parts) |
| Variable freight | +$1.76 |
| Suppliers opened | **33 → 14** |
| Mean BOM size | **6 units** (prototype scale) |
| Realistic saving at production volume | **2.61% – 7.97%** |

### The stochastic / CVaR layer
| Figure | Value |
|---|---|
| λ-solves on the frontier | **387** (347 converged) |
| Marginal dollar buys | **$4.27** of worst-case cost removed |
| Artifact | `docs/cvar_frontier.json` — **clean tree**, commit `ffc9014` |

### The lead-time model
| Figure | Value |
|---|---|
| Algorithm | Gradient boosting |
| Training rows | **2,615** |
| Source features → encoded columns | **10 → 324** |
| Snapshots | **5** |
| Grouping keys | **472** (over 361 base-product levels) |
| Trained | 2026-09-03, sklearn 1.8.0 |
| Staleness | `stale: false` |

### The macro regime classifier
| Figure | Value |
|---|---|
| Target | NY Fed GSCPI regime (calm / elevated / stress), one month ahead |
| Walk-forward folds | **219** (2008-05 → 2026-07) |
| Brier — model | **0.3926** |
| Brier — persistence | **0.5388** |
| Brier — climatology | **0.6725** |
| Fold win rate vs climatology | **74.4%** |
| Fold win rate vs persistence | **26.9%** |
| Accuracy — model vs baseline | **0.7306 vs 0.7306** — a dead tie, McNemar p = 1.0 |

### The demand benchmark
| Figure | Value |
|---|---|
| Real spare-part series | **2,646** |
| Forecasters compared | 6 |
| MASE rank of an all-zero forecast | **1st** (Friedman rank 1.66, p < 1e-300) |
| CRPS / pinball rank of the same forecast | **4th and 5th** |
| Winner under proper scoring rules | **TSB** |

### The leakage study
| Figure | Value |
|---|---|
| Correlation before → after | **+0.83 → −0.70** |
| Manufacturers | **28** |
| Rows | **2,615** |
| Artifact | `docs/leakage_progression.json` — **clean tree**, commit `549b0e1` |

### The engineering
| Figure | Value |
|---|---|
| Tests | **1,181 collected**, all green |
| UI gate checks | **256 passed, 0 failed** (all routes × 4 viewports) |
| Quality floor | 10% RMSE reduction required; real model clears at **34.8%** |
| Proof the floor works | constant predictor at 62.1085 d fires it at **9.135%** |

---

## 4. Red lines — never say these

| ❌ Never say | ✅ Say instead |
|---|---|
| "47% cheaper" | **18.79%** like-for-like, and **2.6–8%** at production volume |
| "18.79% cheaper" *with no volume qualifier* | "18.79% at prototype volume — it decays, and here's why" |
| "349 CP-SAT solves" | **387 λ-solves** — and that's the CVaR frontier |
| "387 solves" *about the benchmark* | The benchmark makes **99** solves. 387 is a different artifact. |
| "1,574 of 8,176 offer rows were excluded" | Don't quote it — links vs rows is unresolved (§5.2). Say **edges 5,789 → 7,363** and the invariant instead. |
| "Four live feeds" | **Three** are live; ACLED is inactive for want of an API key |
| "The geopolitical index is 128.8 today" | See §5.5 — that number is from **2021** |
| "We tested up to 10,000" | **10,000× the order quantity** on a 4-line BOM. Catalogue scale is untested. |
| "One test fails by design" | It passes now. **1,181 tests, all green.** |
| "The frontier re-solves live" | It's a **pre-computed artifact**. A live solve returns `partial: true`. |
| Quoting the screenshots' numbers | Two README PNGs are stale and carry disclosures saying so |

---

## 5. The five stories worth telling

Each of these is a complete narrative with a beginning, a mistake, and a correction. They
are the reason to hire you. **Lead with one; don't recite all five.**

### 5.1 The baseline ladder — "my headline was 47% and I took it down to 18.79%"

**The setup.** The benchmark compared a CP-SAT optimiser against a greedy baseline and
reported a 47.25% cost advantage.

**The problem.** Two handicaps were hiding in that comparison. The baseline was a *naive*
greedy — cheapest offer per line, no awareness of per-supplier freight minimums. And it was
allowed to shop the full international catalogue while the optimiser was restricted to
domestic suppliers only, where parts cost more.

**What I did.** I built a ladder of four baselines — a 2×2 of heuristic strength against
catalogue width — so each handicap could be removed independently and priced.

|  | International pool | Matched domestic pool |
|---|---|---|
| Naive greedy | 47.25% | 34.99% |
| ADD heuristic | 37.10% | **18.79%** |

**The result.** 10.15 points was a weaker opponent. 18.31 points was an unfair catalogue.
18.79 points was real.

**The kicker.** I also tested the leading alternative explanation — that the gap was a
shipping-policy artifact on the optimiser's side — by re-solving the MILP on the baseline's
full global pool. It returned **$3,315.07, identical to the cent**, same distributors on
every BOM. The domestic restriction isn't binding: the optimiser declines international
offers on its own, because air freight doesn't pay back at these quantities.

> **Say:** *"My headline used to be 47%. It's 18.79% now, and the difference is entirely that
> I'd been comparing my optimiser to a weak baseline shopping a wider catalogue than my
> optimiser was allowed. I built four baselines so I could price each handicap separately —
> ten points was the weak heuristic, eighteen was the unfair catalogue, and eighteen was
> real. I'd rather defend 18.79 than get caught on 47."*

**And immediately add the volume caveat before they ask:**

> *"And even that 18.79% is mostly avoided freight fees, not cheaper parts — on component
> price the optimiser actually pays $561 more. What it does is consolidate 33 suppliers into
> 14 and avoid the per-supplier minimums. Mean order size in the benchmark is 6 units, so
> that fee dominates. At production volume it's 2.6 to 8%. If anyone quotes you a flat
> double-digit procurement saving with no volume axis, ask them what order size."*

### 5.2 The graph audit — "I was overstating my own fragility by a quarter"

**No maths needed. This is the story for a generalist recruiter.**

**The setup.** I model the supply base as a network — parts and distributors as nodes, "this
distributor sells this part" as edges — and use it to find single points of failure.

**The problem.** The graph builder was silently holding out 20% of the supplier–part links.
It was a leftover train/test split from an earlier evaluation that had outlived its purpose
and stayed in the production path for about four and a half months. Every resilience number
I published was computed on a network missing a fifth of its real connections — so my supply
base looked far more fragile than it was.

**How I found it.** Not because anything broke. Nothing broke. I audited my own inputs.

**The fix, and the part that matters.** I didn't just delete the holdout. I added an
arithmetic identity that *has to balance*: every offer row is either an edge or a duplicate
of one, so

```
n_edges + n_duplicate_offer_rows == n_offer_rows
7,363   +        813             ==    8,176      ✅
```

The old code could not satisfy that — the missing rows had nowhere to be accounted for. An
invariant that must balance turns a silent omission into a loud failure.

**The result.** Edges 5,789 → 7,363. Components 43 → 34. The network is measurably *less*
fragmented than I'd been publishing.

> **Say:** *"I found a bug that had been live for four months, and it was making my project
> look better at storytelling than it deserved — my supply network looked much more fragile
> than it really was. Nothing crashed; I found it auditing my own inputs. And the fix wasn't
> deleting the bad code, it was adding an identity that has to balance — every offer is
> either a link or a duplicate of one, 7,363 plus 813 equals 8,176. Before, a missing row had
> nowhere to show up. Now it's arithmetic, so it can't hide."*

**A precision warning on this one story.** The repo's own wording (README, `builder.py`, the
commit message) says the holdout excluded *"1,574 of 8,176 offer rows."* A reconstruction of
the pre-fix carve suggests 1,574 is actually the count of distinct supplier–**part links**,
and that removing them dropped a larger number of offer **rows** — but that reconstruction
depends on the random seed and **has not been confirmed to my satisfaction.**

So **don't quote the 1,574 at all.** You don't need it, and this is the one story where
being caught imprecise would undercut the exact point you're making. Quote the two things
that are independently verified instead:

- **Edges went 5,789 → 7,363** and components **43 → 34** after the fix.
- **The invariant balances: 7,363 + 813 = 8,176.**

Those carry the whole story and neither is contested.

### 5.3 The leakage progression — "my model got worse and that's the result"

**The setup.** I predict manufacturer lead times. An early version scored beautifully.

**What target leakage is** — in plain words, it's when information about the answer sneaks
into the inputs. The model isn't predicting; it's reading the answer off the back of the
card. It looks brilliant in testing and is worthless in production.

**What I did.** I built a staged study that removes leaking features one layer at a time and
re-scores at each stage, so you can watch the score fall as the cheating is removed.

**The result.** Correlation between prediction and truth went from **+0.83 to −0.70** across
28 manufacturers and 2,615 rows. The honest model is *worse than useless* on that metric —
it's anti-correlated.

**Why that's the good outcome.** A −0.70 that you can defend is worth more than a +0.83 you
can't. Anyone can produce +0.83 by leaving the answer in the features. Knowing to go looking
for it, and publishing the collapse, is the skill.

> **Say:** *"I had a lead-time model correlating at 0.83, and I didn't trust it. So I built a
> staged study that strips out leaking features one layer at a time and re-scores. By the end
> the correlation was minus 0.70 — the honest model is worse than no model on that metric.
> That's the finding. The 0.83 was the model reading the answer off the back of the card.
> Publishing the collapse is the point; anyone can get 0.83 by leaving the label in."*

**Follow-up you'll get: "So the model is useless?"**
> "On that metric, on that slice, yes — and that's why it's published. What survives is the
> serving model with the leaking features removed, which is honest about being a much weaker
> predictor. The study exists so nobody, including me, quotes the 0.83."

**This artifact is one of only two generated from a clean tree** — commit `549b0e1`, panel
SHA recorded, with a test that fails if it's ever regenerated from a dirty one. If someone
asks "is any of this reproducible?", this is the one to point at.

### 5.4 Scoring rules — "the winning forecast was to always predict zero"

**This is the most sophisticated point you have. Deliver it slowly.**

**The setup.** Spare-parts demand is *intermittent* — most weeks are zero, then a lumpy
order arrives. Standard forecasting methods fail on it, so there's a specialist family:
Croston, SBA, TSB. I benchmarked six methods across **2,646 real spare-part series**.

**The result.** Under **MASE** — a standard, widely-used accuracy metric — the winner was a
degenerate forecaster that predicts **zero, always**. Friedman rank **1.66**, p < 1e-300.
It ranked *first*.

**Why.** MASE is a *point* error metric — it scores one number against what happened. When
most periods are genuinely zero, always guessing zero has very low average error. It is
accurate and completely useless: it will never tell you to order anything.

**The fix.** I scored the same forecasts under **CRPS** and **pinball loss** — *proper*
scoring rules, which score the whole predicted distribution rather than a single point, and
are mathematically minimised only by telling the truth about your uncertainty. Under those,
the all-zero forecaster fell to **4th and 5th**, and **TSB won both**.

> **Say:** *"I benchmarked six intermittent-demand forecasters on 2,646 real spare-parts
> series, and under MASE the winner was a model that always predicts zero. It ranked first,
> Friedman rank 1.66. That's not a bug in my code — it's what point-accuracy metrics do to
> intermittent data. Most weeks really are zero, so always saying zero has tiny average
> error and zero business value. When I scored the same forecasts with proper scoring rules
> — CRPS and pinball — the zero forecaster dropped to fourth and fifth and TSB won both.
> The lesson is that the metric chose the winner, not the model."*

**Follow-up: "What's a proper scoring rule?"**
> "One where your best strategy is to report your true beliefs. If you can improve your score
> by stating a distribution you don't believe, the rule isn't proper. MASE isn't scoring a
> distribution at all — it's scoring one number, so it can't reward getting the *uncertainty*
> right, which on intermittent demand is the whole question."

### 5.5 The stale feed — "I found this while preparing to talk to you"

**Tell this one if the conversation is going well. It is very recent and very honest.**

**The setup.** The app pulls the Caldara–Iacoviello Geopolitical Risk Index and displays it
as a live feed. `/feeds/status` reports it `"live"`, value **128.8**, fetched minutes ago.

**The problem.** The 128.8 is the **September 2021** observation. The file the app downloads
is a frozen archive — its own first sheet, headed *"November 15, 2021"*, says the methodology
was updated and *"the GPR updates will NOW be posted at"* a different URL. The authors moved
the maintained file; my URL didn't follow. The current real value is **117.9**.

**Why nothing caught it.** The status check measures *when we downloaded the file*, never the
date of the observation inside it — and the fetch code discards the date column entirely, so
the app has no way to know. The test builds a synthetic spreadsheet in memory, so it can
never go red on this.

> **Say:** *"Here's one I found this week preparing for today. I have a live connector to the
> geopolitical risk index and it fetches successfully every fifteen minutes — but the file
> I'm pointed at stopped updating in 2021. The download is live; the observation is five
> years old. The authors moved the maintained file and my URL didn't follow, so my app shows
> 128.8 when the real current value is 117.9. It's a one-line fix. The reason I caught it is
> that I checked the source rather than trusting my own status field — which said 'live',
> and was technically telling the truth about the wrong thing."*

**Why this lands:** it's the same species of bug as the graph holdout — *a label that
outlived the thing it described.* Noticing that pattern in your own work is a better answer
to "what would you do differently" than any tooling choice.

---

## 6. The optimisation half, explained

### 6.1 What a MILP is

A **mixed-integer linear program** is a way of writing down a decision problem so a solver
can find the provably best answer. You define variables (what you're choosing), constraints
(what's legal), and an objective (what "best" means). "Mixed-integer" means some variables
must be whole numbers — here, *did I open an account with this distributor: yes or no*. You
can't open 0.4 of a supplier, and that indivisibility is what makes the problem hard and
interesting.

**Analogy:** it's like packing a suitcase under a weight limit where some items can't be
split. *Where it breaks down:* a suitcase has one constraint; here there are hundreds, and
the solver proves optimality rather than just finding something that fits.

> **Say:** *"It's a mixed-integer program — I write down the decisions, the rules, and what
> I'm minimising, and the solver returns the provably cheapest legal plan. The integer part
> is the supplier open/closed decision, which is what makes it non-trivial: you can't open
> 40% of a supplier account."*

**Follow-up: "Why CP-SAT and not a normal LP solver?"**
> "Because the fixed-charge structure — a per-supplier freight minimum that only applies if
> you open that supplier at all — is a logical implication, not a linear one. CP-SAT handles
> those natively and it's very fast on this size. Median solve time in my volume sweep was
> 2 milliseconds, max 7, with zero time-limit hits."

### 6.2 What the model actually decides

- **Decision variables:** how many units of each part to buy from each distributor, plus a
  yes/no for whether each distributor is opened at all.
- **Constraints:** every BOM line must be fully filled; you can't buy more than a
  distributor has in stock; minimum order quantities; optionally a minimum number of
  distinct suppliers.
- **Objective:** minimise total landed cost — parts, plus per-supplier fixed freight, plus
  variable freight.

### 6.3 The four strategies

Lowest cost, fastest delivery, lowest carbon, balanced. They differ by **three levers**, not
three arbitrary weights — most importantly whether sourcing is restricted to domestic
suppliers. `cheapest` is the only one allowed international offers, which is why it's so
much cheaper.

Live on the demo cart: cheapest **$374.02**, fastest **$747.44**, greenest **$735.01**,
balanced **$747.44**.

**Fastest and balanced return the identical plan**, and the API labels them as an identical
group rather than manufacturing a difference.

> **Say:** *"Two of my four strategies return literally the same plan on the demo cart, and
> the API says so — it reports them as an identical group instead of inventing a distinction.
> Same with the graph-aware toggle: on this cart it's a no-op, because the centrality
> surcharge isn't big enough to change the argmin. I'd rather the toggle honestly do nothing
> than rig a cart where it does something."*

### 6.4 Two-stage stochastic programming

**"Two-stage" means: decide now, find out later, then react.** Stage one is the sourcing
plan you commit to before you know what goes wrong. Stage two is *recourse* — what it costs
to recover once a supplier fails. The model chooses a stage-one plan knowing it will have to
pay stage-two costs across many possible futures.

**Analogy:** buying travel insurance before you know if you'll need it. *Where it breaks
down:* insurance has one payout; here recourse cost varies continuously with which supplier
failed and what's left.

### 6.5 CVaR, and why it's not VaR

- **VaR** (Value at Risk) at 95% says: "95% of the time, losses won't exceed X." It tells
  you the *threshold*.
- **CVaR** (Conditional Value at Risk) says: "*given* we're in the worst 5%, the average
  loss is Y." It tells you how bad the bad case actually is.

VaR ignores everything past the threshold — two situations with identical VaR can have wildly
different disasters behind them. CVaR looks at the tail itself.

**Analogy:** VaR is the height of the flood wall; CVaR is how deep the water is when it goes
over. *Where it breaks down:* CVaR is an average of the tail, not the worst case — a truly
catastrophic outlier is still averaged in with the merely bad.

**The Rockafellar–Uryasev linearisation** is the trick that makes this tractable. CVaR is
defined by a condition on the tail, which is not something a linear solver can chew on
directly. Rockafellar and Uryasev showed it can be rewritten as a linear objective with
extra auxiliary variables — so a *risk* measure becomes something an ordinary MILP solver
handles.

> **Say:** *"I minimise a blend of expected cost and CVaR — conditional value at risk, which
> is the average cost in the worst 5% of futures, not just the threshold you cross. VaR would
> tell me where the wall is; CVaR tells me how deep the water gets. And I use the
> Rockafellar–Uryasev linearisation, which is what makes a tail-risk measure solvable by a
> linear solver at all."*

**"Enumerating scenarios rather than SAA sampling"** — Sample Average Approximation draws
random scenarios and hopes they're representative. Here the scenario space is small enough
to enumerate *exhaustively*, so there's no sampling error to argue about.

### 6.6 The efficient frontier, and the two headline results

Sweep the risk-aversion weight λ from fully risk-neutral to fully risk-averse, solve at each
setting, and plot cost against risk. **387 λ-solves; 347 converged.**

**The result: at the knee, one extra dollar of expected cost removes $4.27 of worst-case
cost.** That's the sentence — you are buying $4.27 of tail protection per dollar. Past that
point the exchange rate collapses, which is what makes it the right place to stop.

**The diversification frontier — the most procurement-relevant result you have.** I swept a
hard minimum-supplier constraint from 1 to 5 across 9 BOMs, with a 10,000-sample paired
percentile bootstrap (seed 42) on every delta:

| Min suppliers | Mean cost/BOM | Extra vs k=1 | Targeted risk removed | Stress risk delta |
|---|---|---|---|---|
| 1 | $368.34 | — | — | — |
| **2** | $427.22 | **+$58.88** [29.6, 87.8] | **0.500** [0.222, 0.778] | −0.111 — *not* significant |
| 3 | $527.57 | +$159.23 [111.2, 200.4] | 0.556 [0.222, 0.889] | −0.083 [−0.167, −0.028] — **significant** |
| 4 | $643.10 | +$274.76 [226.6, 315.7] | 0.556 [0.222, 0.889] | 0.000 — not significant |
| 5 | $769.16 | +$393.23 [340.2, 436.3] | 0.714 [0.429, 1.000] | +0.036 — not significant |

**Read this carefully, because the honest version is subtler than "buy two."** The second
supplier costs ~$59 and removes 0.500 of targeted-attack cascade risk. The third costs a
*further* ~$100 and takes you to 0.556 — a gain of 0.056 with confidence intervals that
overlap almost completely. So the third supplier is not *distinguishable* from the second on
risk, while costing nearly three times as much extra.

> **Say:** *"I swept a hard minimum-supplier constraint from one to five and bootstrapped
> every delta across nine BOMs. The second supplier costs about $59 and removes half the
> targeted-attack cascade risk. The third costs another hundred dollars on top and buys you
> 0.056 more, with confidence intervals that almost entirely overlap — so I can't
> distinguish it from the second, and I wouldn't pay for it on this evidence.
>
> And the counterintuitive bit: at three suppliers, diversification makes you significantly*
> worse *under random disruption — minus 0.083, interval excludes zero — because every extra
> supplier is another independent thing that can fail. Better against a targeted attack on
> your biggest supplier, worse against random failure. Those are different threat models, and
> a single 'resilience score' would have averaged that signal away entirely."*

**Note:** the artifact publishes no `recommended_k` field — "buy the second, not the third"
is *your reading* of the intervals, so present it as a judgement, not as a computed verdict.
The artifact's own caveats note the cost curve is close to linear in k by construction (each
supplier pays the same fixed fee), which is why the risk side is the one carrying bootstrap
intervals.

### 6.7 The trap — the frontier is NOT computed live

If asked "can I watch it solve?", the answer is **no**, and being straight about it is the
right move.

A live `POST /api/v1/stochastic/frontier` returns `partial: true` — it solves **1 of 7**
λ-points inside the 45-second web budget, with a 49% MIP gap on the one that finishes. The
published frontier comes from an **offline** run with a 1,600-second per-solve budget.

> **Say:** *"The frontier on the site is a pre-computed artifact. The live endpoint will try
> and it's honest about failing — it solves one point of seven in a 45-second web budget and
> returns `partial: true` with the reasons. A risk-averse mixed-integer program with a
> 64-scenario second stage is not a sub-second web request, and I'd rather the API say
> 'partial' than hand you a curve it didn't finish."*

### 6.8 There are two different things called CVaR-95 here

A sharp practitioner will notice. Have the answer ready.

| | Dollar CVaR | Cost-inflation CVaR |
|---|---|---|
| Where | The efficient frontier | The resilience benchmark |
| Units | US dollars | A multiplier, unitless |
| Bounded? | No | **Yes — capped at 1.15** |

> **Say:** *"Two different CVaRs and I keep them apart. The frontier one is in dollars and
> unbounded. The resilience one is a cost-inflation multiplier structurally capped at 1.15,
> because it's one plus an unfulfillable share times a 15% emergency premium. Under stress
> most plans sit on that ceiling, so a reported reduction of zero there is arithmetic, not a
> finding — and the API says so and names the tied BOMs."*

---

## 7. The forecasting half, explained

### 7.1 The lead-time model

Gradient boosting predicting manufacturer lead time in **days** (not log-transformed —
you'll be asked). **2,615 training rows**, **10 source features encoded into 324 columns**.

**Say "ten source features, 324 columns after encoding."** Saying "324 features on 2,615
rows" invites a raised eyebrow, and it isn't what's happening — 322 of those columns are
one-hot levels of 8 categorical variables (package case, category, tariff code, manufacturer,
lifecycle status, and so on). The two genuinely numeric ones are log unit price and
parameter count.

**Two things worth volunteering:**
- **It refuses rather than guesses.** An unseen DigiKey category raises an error and the API
  returns **422 with the list of known categories**, instead of quietly predicting from a
  zero-filled row.
- **There's no hyperparameter tuning.** Four hard-coded configurations, no grid search.
  Defensible: *"with 28 manufacturers as the effective sample, tuning across overlapping
  splits would fit the folds, not the problem"* — but say it's untuned rather than let them
  find it.

### 7.2 Walk-forward validation

**What it is:** train on the past, predict the next period, step forward, repeat. Never let
the model see anything from after the moment it's predicting.

**Why it matters:** a random train/test split on time-series data lets the model train on
Thursday to predict Wednesday. Scores look great and mean nothing.

**Analogy:** running a trading strategy forward through history one day at a time, versus
being shown the whole year and asked to pick winners. *Where it breaks down:* real
deployment also has data *revisions* — the value you see today isn't the value you'd have
seen then — which plain walk-forward doesn't capture.

### 7.3 The macro regime classifier

Predicts next month's NY Fed GSCPI regime — calm, elevated, or stress — across **219
walk-forward folds** from 2008 to 2026. Its probability feeds the sourcing MILP as a
per-unit stock-out premium that shifts orders away from thinly-stocked suppliers.

**Brier score** measures how good *probabilities* are, not just whether you were right. If
you say 70% and it happens 70% of the time, you score well. Guessing confidently and being
wrong is punished hard. **Lower is better.**

| | Brier | Fold win rate |
|---|---|---|
| Model | **0.3926** | — |
| Persistence (assume next month = this month) | 0.5388 | model wins **26.9%** |
| Climatology (always predict base rates) | 0.6725 | model wins **74.4%** |

**Own the weakness before they find it.** Accuracy is **0.7306 for both model and baseline** —
a dead tie, McNemar p = 1.0.

> **Say:** *"Against a climatology baseline it wins 74% of 219 folds with a clean confidence
> interval — that's the comparison I'd defend. Against persistence the mean Brier reduction
> is also significant, but it only wins 27% of folds; the average is carried by a handful
> where persistence is confidently wrong and takes a huge loss. And on plain accuracy it's a
> dead tie. So: better calibrated than both, more accurate than neither. I ship it because
> the optimiser prices a premium off a probability and persistence has no probability to
> give — but I wouldn't call it a strong forecaster."*

That paragraph, delivered calmly, is worth more than any headline number in this project.

### 7.4 Intermittent demand

Demand that is mostly zero with occasional lumpy orders — the norm for spare parts. Standard
methods assume something roughly continuous and fail badly. **Croston's method** splits the
problem in two: forecast the *size* of an order and the *interval between* orders
separately. **SBA** corrects a known bias in Croston. **TSB** replaces the interval logic
with a probability that decays when nothing is ordered, which handles parts going obsolete.

See §5.4 for the headline result — it's your best statistics story.

**Not implemented, and say so if asked:** ADI/CV² classification, the standard scheme for
bucketing series into smooth / intermittent / erratic / lumpy. It's the obvious next step.

---

## 8. The network half, explained

### 8.1 What the graph is

Nodes are parts and distributors. An edge means "this distributor sells this part." **7,363
edges over 791 parts and 92 distributors.**

**Analogy:** a map of which shops stock which items. *Where it breaks down:* a real map has
geography; this only has connections, so "distance" means "how many hops," not miles.

### 8.2 Connected components

A **connected component** is a group where you can get from any node to any other by
following edges. **34 components**, but one of them — the **giant component** — holds **847
nodes, 95.92% of the graph**. So it isn't 34 separate supply networks; it's one network plus
a fringe of small isolated pieces.

### 8.3 Betweenness centrality

Measures how often a node sits on the shortest path between other nodes. High betweenness =
a bridge. Losing a bridge disconnects things that were only connected through it. The
highest-betweenness distributor here scores **0.2915**.

**Analogy:** the one bridge between two halves of a city — not necessarily the busiest road,
but the one whose closure strands people. *Where it breaks down:* it's a *structural* score,
not a failure probability. The API says this explicitly, because a previous version rescaled
it to [0,1] and accidentally published the top distributor as having a failure probability of
1.0.

### 8.4 Algebraic connectivity (the Fiedler value)

A single number for how hard a network is to cut in two. Zero means already disconnected.
Higher means more robust.

Whole graph: **0.0** — it's disconnected, by definition, because of those 34 components.
Giant component: **0.2788**.

> **Say:** *"I report it for the giant component, not the whole graph, because the whole
> graph's value is structurally zero — it's disconnected, so the number is uninformative. The
> giant component is 96% of the network and that's where the question is real."*

### 8.5 The data, and why it's the trust question

**Real Nexar / Octopart electronic-component data.** 791 parts, 92 distributors, 8,176
offers. There is a standing rule in this project: **no synthetic data for prices, suppliers
or metrics.** Where real data doesn't exist, the project says so rather than filling the gap.

The clearest example: **ACLED is a built, working connector that is inactive because the API
key isn't provisioned.** The status endpoint says exactly that, with a registration link. It
would have been trivial to fake it.

> **Say:** *"All the prices and suppliers are real distributor offers — nothing synthetic.
> Where I don't have data, the app says so instead of filling it in. One of my four risk
> feeds is built and working but inactive because I haven't provisioned the API key, and the
> status endpoint tells you that rather than showing you a made-up number."*

### 8.6 The resilience scenarios — and the precise word to use

Three scenarios: a distributor failing, a geopolitical risk spike, a tight delivery target.

**Say "re-prices", never "re-optimises".** None of the three runs the CP-SAT solver — each
re-prices the BOM greedily against surviving offers and re-runs a 1,000-draw Monte Carlo.
The MILP lives on the `/optimize` endpoints.

Verified live on the demo cart, failing the distributor four of five lines depend on:
cost **$167.19 → $209.63 (+25.4%)**, ETA **26.6 → 23.4 days**, fulfilment **unchanged at
100%**, risk **unchanged at 0.220**, **zero lines orphaned**.

> **Say:** *"Losing the distributor this cart leans on costs 25% more and — this is the
> interesting part — actually arrives* sooner*, because the cheap supplier was the distant
> one. Nothing orphans; every line has an alternative. A tool that only ever manufactures a
> crisis isn't useful. The value is being able to tell procurement 'you're already hedged
> here, spend your redundancy budget somewhere else.'"*

**On the delivery-target scenario, know both ends** — the cost of speed depends entirely on
the BOM. On one BOM, cutting 20 days cost **+0.3%**. On the demo cart, cutting 17 days cost
**+95.2%**, because **37 of 92 distributors can hit a 14-day window and 55 cannot** — and on
that cart the cheap ones are all in the 55.

---

## 9. Hard questions, ranked by how likely you'll get them

**1. "How much of this did you actually build?"** → §10.

**2. "At what order volume is that 18.79%?"**
> "Prototype — mean six units per BOM. And most of it is avoided per-supplier freight fees,
> not cheaper parts; on component cost the optimiser actually pays $561 more. At production
> volume it's 2.6 to 8%, and the site publishes that range. The advantage amortises because
> the fee is roughly constant in volume while component cost grows."

**3. "How do you know any of these numbers are right?"**
> "Two ways. Every number on the site has to trace to a field in an actual API response or a
> committed artifact — a rule I have because I twice shipped figures that two of my own
> documents agreed on while both disagreed with the code. And the checks have to be
> falsifiable: I break them deliberately to confirm they can go red. My model quality floor,
> for instance, I proved by substituting the exact constant predictor an old bug produced —
> it fired at 9.1% against a 10% floor, and the real model clears at 34.8%."

**4. "Isn't this just a toy?"**
> "It's a portfolio project, not production software — 791 parts, nine benchmark BOMs, one
> user. What's real is the data and the methodology: real distributor offers, a real solver,
> real validation protocols, and results I've corrected downward when they didn't hold. What
> it isn't is battle-tested at enterprise scale, and I can tell you specifically what would
> break first."

**5. "What breaks if you run this on 10,000 parts?"**
> "The graph, and it breaks *quietly*, which is worse. Algebraic connectivity has an
> eight-second timeout and when it fires the code falls back to zeros and serves them —
> including 'connected components = 0', which is physically impossible for a non-empty graph.
> There's no degraded flag on the response, and zero is a legitimate value for a disconnected
> graph, so from the outside you can't tell a failure from a real answer. Betweenness is
> O(V·E) on the startup path — at 10,000 parts roughly 145× today's cost.
>
> The solver is the reassuring half: the MILP is sized by the bill of materials, not the
> catalogue, so a wider catalogue doesn't widen any single instance. Median solve 2
> milliseconds, max 7, zero time-limit hits."

**6. "Why should I believe your benchmark isn't rigged in your favour?"** — *the best question
you can get.*
> "Because it was, and I'm the one who found it. My headline was 47%; it's 18.79% now,
> because I'd been comparing against a naive baseline shopping a wider catalogue than my own
> optimiser was allowed. I built four baselines so each handicap could be priced separately.
> Every number I've corrected has moved down. I'd also point you at the tenth BOM —"

**7. "You said nine BOMs. What happened to the tenth?"** — *have this ready; it's the sharpest
factual question in the project.*
> "It's excluded because my optimiser *failed* on it. `audio_dsp_board` — the MILP is
> restricted to domestic suppliers and one flash part had zero domestic stock, so it raised
> rather than returning a plan. My harness is all-or-nothing, so the baselines' results for
> that BOM were discarded too. That's a selection effect on my headline and I don't love it.
> The artifact names the BOM and the exact part number, so it's auditable rather than hidden
> — but the honest read is that 18.79% is measured on the nine instances where my optimiser
> was able to compete."

**8. "Is it reproducible?"**
> "Two artifacts are fully reproducible from a clean tree — the CVaR frontier and the leakage
> study, both with recorded commit and data hashes, and the leakage one has a test that fails
> if it's ever regenerated from a dirty tree. Seven others were generated from working trees
> with uncommitted changes, and they stamp their own provenance saying so.
>
> But I'd separate *provenance* from *determinism*, because they're different claims. I
> re-ran the benchmark generator against current code and diffed it leaf by leaf against the
> committed artifact: **every single value matched — the only differences were the timestamp
> and the provenance block itself.** So the 18.79% does fall out of the code today. What the
> dirty stamp means is that you couldn't check out that specific commit and be *guaranteed*
> the same result, because the tree had uncommitted changes when it was generated. It's
> labelled rather than hidden, and regenerating the rest from a clean tree is on my list —
> most of them take under half a minute."

**That last answer is strong, so know why it's honest:** provenance says "can a stranger
reproduce this from a commit hash?" (partly — 2 of 9). Determinism says "does the current
code still produce this number?" (yes, verified by diff). Conflating them would be
overclaiming; separating them is the answer of someone who understands what a provenance
stamp is for.

**9. "What's the weakest part?"**
> "The MLOps. The published benchmark runs with the macro risk premium at zero and all four
> feed surcharges at zero, because my offline generators are plain CLI processes that never
> start the app's lifespan — so they don't load the ML state or the feed cache. Production
> runs with stress at 0.83 and three live feeds. I measured the impact: it happens to be zero
> to the cent today, for a structural reason. But it's a genuine train/serve gap and it being
> harmless is luck, not design."

**10. "What would you do next?"**
> "Three things, in order. Fix that train/serve gap so the benchmark runs the same optimiser
> production does. Repoint the geopolitical feed at the maintained file — mine is frozen at a
> 2021 observation and I only found it this week. And add ADI/CV² classification to the
> demand benchmark, which is the standard way to bucket intermittent series and the obvious
> gap for a demand-planning role."

---

## 10. "Did you write this?" — the AI question

**The position: full disclosure, no defensiveness, no apology.** It is undeniable and
searchable — 158+ commits are publicly stamped `Co-Authored-By: Claude` and the Actions tab
lists workflows named "Claude — Builder". Anyone who looks will know. So tell them first.

**"Did you write this?"**
> "I directed it; a lot of the code was AI-written and the commit history says so openly. What
> I did was set the standards, decide what was worth building, and audit the results — which
> is where most of the actual work went."

**"How much did AI do?"**
> "Most of the typing. None of the judgement calls. The interesting decisions in this project
> were things like refusing synthetic data, catching that my benchmark was comparing against a
> handicapped baseline, and deciding that a model which scores worse after removing leakage is
> the result worth publishing. An AI will happily generate a beautiful 0.83 correlation and
> not tell you it's leaking."

**"So what did YOU actually do?"** — *the hostile version. Answer it flat and confident.*
> "I found the errors. Every headline number in this project has moved *down* because I
> audited it — 47% to 18.79% on the benchmark, a supply network that turned out 20% more
> connected than I'd been publishing, a lead-time correlation that went from 0.83 to minus
> 0.70 once I stripped the leakage out. None of those corrections came from the code failing.
> They came from me not believing my own results and going to check.
>
> That's the same job as running a team of analysts: you're not writing the SQL, you're
> deciding what's trustworthy and what isn't. If you want to test whether I understand it,
> ask me anything in here and I'll tell you where the number comes from and what's wrong with
> it."

**Then stop talking.** Don't over-explain. The confident short answer is the credible one,
and the offer at the end reliably converts scepticism into a real conversation.

---

## 11. Weaknesses you volunteer before they're found

Volunteering these is not damage control — it is the single strongest signal available to
you, because almost no candidate does it.

| Weakness | How to say it |
|---|---|
| **Nine BOMs, and the tenth was excluded because the MILP failed** | See Q7. Say it before you're asked. |
| **The 18.79% is prototype volume and mostly freight fees** | See Q2. Always attach the volume qualifier. |
| **Benchmark runs with risk premium and all feeds at zero** | "A real train/serve gap. Measured impact today: zero to the cent — but that's luck." |
| **The geopolitical feed is frozen at a 2021 observation** | §5.5. Tell it as a story; it's a strength. |
| **Seven of nine artifacts came from a dirty tree** | "Labelled, not hidden. Two are clean and both reproduced exactly." |
| **The demo cold-starts in over a minute** | "Free tier. It sleeps after 15 minutes." Warm it beforehand. |
| **No hyperparameter tuning on the lead-time model** | "Untuned, deliberately — 28 manufacturers is too small a sample to tune on." |
| **No uncertainty quantification on lead times** | "Point predictions only. Conformal intervals are the obvious addition." |
| **ADI/CV² classification not implemented** | "The obvious gap for a demand-planning role. It's ~20 lines." |
| **Accuracy tie on the regime model** | §7.3. Lead with calibration, concede accuracy. |
| **mypy doesn't cover the optimiser** | 22 modules are excluded, including `sourcing` and `solve`. The reason is legacy SQLAlchemy style, but the gate is narrower than it sounds. |
| **Two README screenshots are stale** | Both carry disclosures saying exactly what's out of date. |
| **Python 3.13 locally vs 3.11 in CI** | A provenance skew on the model artifact. Known, logged. |
| **`ANNUAL_REORDERS = 12`** | One unmeasured integer multiplies every annualised dollar figure. Say so if annual savings come up. |

---

## 12. Glossary — terms you must be able to define

**BOM (bill of materials)** — the list of parts and quantities needed to build one unit.

**Landed cost** — total cost to get a part to your door: unit price + freight + fees. Not
just the sticker price.

**MILP** — mixed-integer linear program. See §6.1.

**CP-SAT** — Google OR-Tools' constraint solver. Good at logical/fixed-charge structures.

**Fixed charge** — a cost you pay if you use a supplier at all, regardless of quantity. The
per-supplier freight minimum here. It's what makes consolidation valuable.

**Recourse** — in stochastic programming, the corrective action (and its cost) after
uncertainty resolves.

**VaR / CVaR** — see §6.5. VaR = the threshold; CVaR = the average loss beyond it.

**Efficient frontier** — the set of plans where you can't improve cost without worsening
risk, or vice versa.

**VSS (value of the stochastic solution)** — how much you gain by modelling uncertainty
properly versus just planning against average conditions.

**Target leakage** — information about the answer sneaking into the model's inputs. See §5.3.

**Walk-forward validation** — train on past, test on future, step forward. See §7.2.

**Brier score** — accuracy of *probabilities*. Lower is better.

**Proper scoring rule** — a scoring rule where honestly reporting your true beliefs is the
optimal strategy. CRPS and pinball loss are proper; MASE is not a distributional score at all.

**MASE** — Mean Absolute Scaled Error. A point-accuracy metric. Breaks badly on intermittent
demand (§5.4).

**CRPS** — Continuous Ranked Probability Score. A proper scoring rule for full distributions.

**Intermittent demand** — mostly-zero demand with occasional lumpy orders.

**Croston / SBA / TSB** — the specialist forecasters for intermittent demand. See §7.4.

**Betweenness centrality** — how often a node lies on shortest paths between others. A
bridge score.

**Algebraic connectivity / Fiedler value** — how hard a network is to split in two.

**Connected component** — a group of nodes all mutually reachable.

**Monte Carlo simulation** — running many random scenarios to estimate a distribution of
outcomes.

**GSCPI** — the NY Fed's Global Supply Chain Pressure Index. The regime model's target.

**HHI (Herfindahl–Hirschman Index)** — a concentration measure. High = few suppliers
dominate a category.

---

## 13. One-page cheat sheet

*Skim this in the car.*

**What it is:** supply-chain sourcing optimiser on real electronics data. Deployed, live.

**Scale:** 791 parts · 92 distributors · 8,176 offers · 7,363 network edges

**The headline:** **18.79%** like-for-like vs an ADD heuristic on a matched pool.
**2.6–8%** at production volume. Mostly avoided freight fees — the optimiser pays **$561
more** for parts and consolidates **33 suppliers into 14**.

**The ladder:** 47.25 → 37.10 → 34.99 → **18.79**. Ten points was a weak heuristic, eighteen
was an unfair catalogue.

**The risk layer:** 387 λ-solves · at the knee **$1 buys $4.27** of worst-case cost removed.

**Procurement takeaway:** **buy the second supplier, not the third.** Second = +$59, removes
**0.500** of targeted risk. Third = +$100 more, reaches 0.556 — intervals overlap, not
distinguishable. At k=3, diversification is *significantly worse* under random stress.

**The ML:** lead-time GBM, 2,615 rows, 10 features → 324 columns. Regime classifier, **219
folds**, Brier **0.3926** vs 0.5388 / 0.6725 — *better calibrated, accuracy a dead tie*.

**The stats headline:** MASE ranked an **all-zero forecast first**; CRPS and pinball put it
**4th and 5th**; TSB won both.

**The honesty headline:** graph builder was silently dropping 20% of links for ~4.5 months.
Found by audit, not by failure. Fixed with an invariant: **7,363 + 813 = 8,176.**

**Never say:** 47% · "349 solves" · "387 solves" about the benchmark · four live feeds ·
"GPR is 128.8 today" · 18.79% without the volume qualifier.

**Before you walk up:** warm the demo.

**If you only remember one line:**
> *"Every headline number in this project has moved down, because I audited it myself."*
