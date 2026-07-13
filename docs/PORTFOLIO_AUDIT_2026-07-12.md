# Portfolio Audit — "How good is this project, actually?"

**Date:** 2026-07-12 · **Scope:** read-only audit of the full repo (backend `app/`, frontend `src/`, `docs/`, tests, CI, `render.yaml`, git log) · **Audience:** the owner, a job seeker targeting consulting (McKinsey/BCG), big-tech ops (Amazon SCOT, Apple Ops), and DS/ML firms.

No flattery. Every claim below is grounded in a file I actually read.

---

## 1. Grades

| Dimension | Grade | One-line justification |
|---|---|---|
| **OVERALL** | **B−** | Real engineering, real data, unusually honest self-labeling — but the *headline numbers it leads with are the ones that break under a 2-minute interviewer poke*. |
| (a) Technical depth / modeling sophistication | **B−** | Enormous breadth (CP-SAT MILP, TSP, Monte Carlo percolation, Fiedler/betweenness/HHI/k-core, Prophet, Chronos, Croston/SBA, MLflow). Very little depth: the MILP is a small fixed-charge transportation problem; all "risk" is a heuristic price surcharge with invented constants; no stochastic/robust formulation. |
| (b) Engineering quality | **B+** | 261 real test functions incl. genuine CP-SAT solve assertions; JWT + SECRET_KEY validation + non-wildcard CORS + zero raw SQL; CI runs pytest and `tsc -b`. Undercut by: no coverage measurement, CI doesn't gate deploy, the only e2e benchmark test is `@pytest.mark.skip`'d, zero frontend tests, a 10 MB SQLite prod DB committed to git. |
| (c) Data credibility & honesty of claims | **C+** | Massively improved since the July 1 gap audit — the code is now genuinely honest (deprecation warnings on the leaky target, "ILLUSTRATIVE… NOT observed per-part demand" docstrings). But the **README still contradicts the repo on five separate numbers**, and the demand model that the UI serves is *not* the model that was backtested. |
| (d) Product / UX & demo-ability | **B** | Genuinely custom, domain-specific UI (deck.gl network-risk map, MILP-vs-greedy benchmark page, dollar-quantified tooltips, an explicit "Honest finding" callout). Undercut by `<title>frontend</title>`, emoji-as-icons, no error boundaries, and a real login bug that shows "0.00°N 0.00°W" on a non-demo login. |
| (e) Storytelling / 45-min interview | **B−** | It *has* a demo script and a "Reproduce These Numbers" section (`docs/RESILIENCE_INTERVIEW_GUIDE.md`) — rarer and better than 95% of portfolios. But the headline metric is fragile, there's no case-study one-pager, and there is no answer to "so what do I tell the CPO on Monday?" |

---

## 2. Benchmark against reality — is this an "impressive-but-generic LLM-built portfolio app"?

**No — but it has the tell.**

It is *not* generic. A generic LLM portfolio app is a CRUD dashboard with fake charts. This one has: a real CP-SAT model (`backend/app/optimization/sourcing.py`, 611 lines, genuine `cp_model` fixed-charge formulation with distributor-linking constraints and a dual-source escalation loop), a real greedy baseline scored through *the same* `landed_cost_breakdown` function so the comparison isn't rigged (`backend/app/optimization/greedy.py:122-159` — this is a deliberately honest design choice most candidates never make), a real walk-forward backtest harness with a seasonal-naive baseline and a skill score (`docs/FORECAST_BACKTEST.md`), and a benchmark page that renders an *"Honest finding"* callout that goes grey when the effect is inside the noise floor (`frontend/src/pages/BenchmarkPage.tsx:522-562`). That last one is a genuinely mature instinct and is the single best thing in the repo.

**But the tell is breadth without depth.** 203 commits, ~30k LOC, 14 subsystems in ~3 months. Every buzzword has a module — MILP, TSP, Monte Carlo, graph ML, Prophet, Chronos TSFM, MLflow registry, OpenTelemetry, "digital twin" — and *every one stops at the first level*. A human who spent three months on this alone would have gone three levels deep on one thing. An experienced interviewer recognizes this shape immediately. The remedy is not to add another subsystem; it is to take one and go deep enough that it could not have been generated.

### Where it lands by employer type

**Consulting (McKinsey / BCG) — STRONGEST. Currently a B+/A− artifact.**
They will never open `sourcing.py`. They will grade: is the problem structured, is impact quantified, is the recommendation clear, does the candidate know what they *don't* know. This project scores well on 1, 2 and 4 (`docs/IMPACT_FRAMING.md` derives its dollar figures with citations — Gartner 25%/yr holding cost, z=1.645 — which is exactly the right instinct). It fails on 3: **there is no recommendation.** The Recommendations tab produces a ranked list of dual-sourcing candidates, but nowhere does the project say *"Nexar-catalogue PCB manufacturers should qualify a second source for these 14 parts; it costs $X and removes $Y of tail exposure; do it this quarter."* That's the whole job.

**Big-tech ops (Amazon SCOT / Apple Ops) — WEAKEST. Currently a C+/B−.**
These are the people who *will* open `sourcing.py`, and it is where the project cracks hardest. The headline "MILP is 44.7% cheaper than greedy" (`docs/BENCHMARK_RESULTS.md:22`) does not survive contact with an operations-research scientist (see §3.1). Neither does using betweenness centrality as a disruption *probability* (§3.2). Neither does a risk model whose entire calibration is `RISK_PREMIUM_RATE = 0.15` (`sourcing.py:164`).

**DS / ML firms — WEAK-to-MEDIUM. Currently a C+.**
The *habits* are right — walk-forward rolling-origin backtest, WAPE over MAPE with a stated reason, an explicit seasonal-naive baseline the model must beat, skill score, MLflow champion-by-RMSE selection, Chronos zero-shot as a foundation-model comparator. Those habits are worth real credit and most candidates don't have them. The *data* is not right: the lead-time model trains on 75 rows from a single day from a single distributor (§3.4), and the demand model the UI serves is a formula, not a fit (§3.3). A DS interviewer will respect the harness and reject the substrate, and will conclude — correctly — that the candidate knows the *forms* of rigor but has not yet been forced to be rigorous by real data.

---

## 3. The five things that most undermine it

### 3.1 — The headline "44.7% cheaper than greedy" is an artifact of assumed fixed fees on toy BOMs. **This is the single biggest liability in the project.**

Three facts, each verifiable in the repo:

1. **The greedy baseline is, by construction, the component-cost minimum.** `solve_sourcing_greedy` picks the cheapest feasible offer for each BOM line independently (`backend/app/optimization/greedy.py:91-117`). The MILP's component cost therefore *can never be lower* than greedy's. Every dollar of the claimed 44.7% saving must come from somewhere else.
2. **It comes from the per-supplier fixed charge.** `landed_cost_breakdown` (`greedy.py:122-159`) = `component_cost + transport_fixed + consolidation_charge`, where `transport_fixed` is `LTL_BASE_FEE_USD = 75.0` (or `AIR_FREIGHT_BASE_USD = 150.0`) **per opened distributor** (`backend/app/optimization/constants.py:18,31`). The MILP's entire win is closing distributors: `BENCHMARK_RESULTS.md` shows exactly this in its own last column — `3→1`, `4→1`, `3→2` suppliers.
3. **The BOMs are trivially small.** The reference BOMs are **4 line items at quantities of 1–4 units** (`backend/seeds/run_benchmark.py:113-133` — e.g. `automotive_ecu` = 4 parts, 7 units total). `iot_sensor_node` "saves 71.75%" going from $466 → $131.77 — and **$75 of that final $131.77 is the LTL base fee.** The component cost is roughly $50.

**What an interviewer does with this:** "Great — now run it for a real BOM: 60 line items at 10,000 units each." At that scale, component cost dominates the fixed fee by three orders of magnitude, the per-line-cheapest greedy is near-optimal, and **the MILP's advantage collapses toward ~0–2%.** The 44.7% is not a finding about optimization; it is a restatement of the assumption "each extra supplier costs $75."

This is the crack. It is also, handled correctly, the single greatest opportunity in the project — see §4.2.

### 3.2 — Betweenness centrality is used directly as a failure probability. It is not one.

`backend/app/graph/simulation.py:155-161`:
```python
failure_probs = {did: min(betweenness.get(did, 0.0) * stress_factor, 1.0) for did in all_dist_ids}
```
`betweenness` is min-max normalized to [0,1] in `backend/app/graph/builder.py:127-133`. So **the most central distributor in the network fails with probability 1.0, every scenario.** Distributors do not go dark 100% of the time. Real supplier-disruption base rates are low single-digit percent per year. This is why `BENCHMARK_RESULTS.md` shows `cascade_risk = 1.0000` for six of nine BOMs — the simulation is not finding fragility, it is asserting it.

The same [0,1] score is reused as `p_d` inside `_graph_surcharge_cents` (`sourcing.py:206`, "p_d = betweenness_score"), citing Snyder & Daskin (2005) — but Snyder & Daskin's `q_i` is an *estimated disruption probability*, not a centrality score. The citation is doing work the math doesn't support.

Downstream, this also makes **`cvar_95` a degenerate metric**: it saturates at `1.0 + 1.0 × EMERGENCY_COST_PREMIUM = 1.15` in almost every row of `BENCHMARK_RESULTS.md`. So "procurement spend at risk" (`backend/app/api/resilience.py:263`: `spend_at_risk = component_cost * (cvar_95 - 1.0)`) is, in practice, **just 15% of spend** — an assumed constant wearing a Monte Carlo costume. The README calls this figure "fully data-derived" (`README.md:59-61`). It isn't.

### 3.3 — The demand forecast that the UI serves is not the demand forecast that was backtested.

The per-part demand series is (`backend/seeds/train_forecasts.py:138-141`):
```python
base_rate = max(total_stock / HISTORY_WEEKS, 1.0)
risk_multiplier = min(1.0 + (risk_score / RISK_SCORE_NORMALIZER), RISK_MULTIPLIER_CAP)
weekly_draw = base_rate * risk_multiplier
return np.maximum(0.0, weekly_draw * shape)   # `shape` = ONE shared macro curve
```
Three problems: (a) demand is derived from **inventory** (`total_stock/52`) — backwards; stock is a *consequence* of demand; (b) all 791 parts share **the same `index_shape`**, so every part's normalized demand curve is identical — Prophet is fitting 791 copies of one macro series; (c) demand is made *increasing* in `risk_score`, which asserts that riskier parts are more in demand, which is not a thing.

The code is now *admirably honest* about this — the docstring literally says "ILLUSTRATIVE… NOT observed per-part demand." But the backtest in `docs/FORECAST_BACKTEST.md` was run on **Census M3 `A34SNO`, a macro new-orders index** — a completely different series from the per-part sparklines the SchedulerPage shows. **The reported WAPE has no bearing on the forecasts the product displays**, and `docs/IMPACT_FRAMING.md`'s "$3.7k/yr saved per $1M of spend" is built on top of that gap.

### 3.4 — The lead-time ML model is trained on 75 rows from one day from one distributor, with a random split on time-series data.

`backend/seeds/data/lead_time_panel/observed_lead_times.csv` has **76 lines (75 rows), every row `snapshot_date = 2026-07-01`, every row `source = digikey`.** That is a single-day cross-section covering 75 of 791 parts (<10%).

Consequences, each of which an interviewer finds in under a minute:
- `train_all_models` uses `train_test_split(X, y, test_size=0.2, random_state=42)` (`backend/app/ml/lead_time_model.py:133`) — a **random** split. On temporal data, with no temporal holdout. The quoted `R²=0.93` (`docs/ROUTE_A_BUILD_PLAN.md:70`) comes from **15 test points**.
- Two of the features are **constant**: `macro_stress` is broadcast as a single scalar to every row (`lead_time_model.py:239`), and `src_digikey` is 1 for all 75 rows. They carry zero information.
- The target is the distributor's **quoted** lead time (a catalog field), not the **realized** delivery time. Predicting DigiKey's own published field from DigiKey's own published attributes is a much smaller claim than "lead-time prediction."

The honest framing (`retrain_lead_time` refuses to fall back to the old synthetic formula and skips training below `min_samples=30`) is genuinely good. But shipping the model *and quoting its R²* on n=75 undoes that honesty.

### 3.5 — The README contradicts the repository on five separate numbers.

An interviewer who opens two docs side by side catches all of these inside five minutes:

| Claim | Where | Reality |
|---|---|---|
| "8,731 price offers" | `README.md:5,105,122,171`; `docs/PROJECT.md:10` | DB has **8,176**. `docs/RESILIENCE_INTERVIEW_GUIDE.md:33` has it right — the two docs disagree with each other. |
| "DigiKey handles 40% of our component offers" | `README.md:157` (the *30-second pitch*) | **11.2%** — a figure the project's own interview guide already corrected (`RESILIENCE_INTERVIEW_GUIDE.md:35`). |
| "195 passed, 3 skipped" | `README.md:144` | A full run today gives **282 passed, 1 failed, 2 skipped** (order-dependent flake in `test_dual_sourcing_plan_endpoint`). |
| "EVaR-95" as the tail-risk metric | `README.md:38,59` | `graph/simulation.py:39,107` explicitly says **CVaR / Expected Shortfall, "NOT Entropic VaR."** The README uses the name the code was corrected away from. |
| "Prophet 4.8% vs seasonal-naive 8.7% on FRED `IPG3344S` ([docs/FORECAST_BACKTEST.md])" | `README.md:41` | That file was **regenerated onto a different series** and now says **2.5% vs 4.4% on Census `A34SNO`**. The README cites a file that does not contain the number it quotes. |

Individually, doc rot. Together, they establish a pattern: *the numbers this candidate quotes are not the numbers his own system produces.* That is a fatal impression in a data role, and it is the cheapest thing on this entire list to fix.

---

## 4. Highest-leverage improvements, ranked by (hire-ability impact ÷ effort)

### Tier 1 — "This makes it credible." Do all four. ~3 days total.

**4.1 — Sync every number in README/PROJECT/IMPACT_FRAMING to what the code actually produces. (2 hours. Ratio: enormous.)**
Fix the five contradictions in §3.5. Add a `docs/` build step or a one-command script that regenerates the stats block from the live DB so it cannot rot again. This is two hours of work standing between you and "his own docs disagree with his own repo."
*Employer:* all three. It's table stakes.

**4.2 — Re-run the benchmark at realistic BOM scale, and turn §3.1 from your biggest liability into your best story. (1 day. Ratio: highest in the document.)**
Build a 40–60-line BOM at 1,000–10,000 unit quantities from the existing catalog. Re-run `run_benchmark.py`. Publish the **MILP-savings-vs-order-volume curve** — savings will collapse from ~45% toward low single digits as the fixed fee amortizes. Then say, out loud, in the interview:

> "My first benchmark said the MILP beat greedy by 44.7%. I didn't believe it, so I decomposed it — and the entire win was the $75-per-supplier LTL base fee on a 7-unit BOM. Greedy is the component-cost minimum by construction, so the MILP can only ever win on fixed charges. I re-ran it across order volumes and found the crossover: below ~N units, consolidation is the whole game; above it, the MILP's advantage is under 2% and you shouldn't bother running it. Here's the curve."

That paragraph is an A-grade interview moment at **Amazon and McKinsey simultaneously.** It demonstrates the exact thing both actually screen for — that you interrogate your own favorable result. Right now you have the finding and are presenting it as a win. Present it as an investigation instead.

**4.3 — Ground the disruption probabilities. (1 day.)**
Replace `p = normalized_betweenness` with `p_i = base_rate × f(centrality_i)`, where `base_rate` is a cited empirical supplier-disruption frequency (BCI Supply Chain Resilience Report / Resilinc EventWatch publish annual per-supplier disruption rates), and centrality is a *multiplier*, not the probability itself. Then run the sensitivity you already have the machinery for — `compute_tornado` already exists in `backend/app/optimization/recommendations.py:306` and is not surfaced as a headline. Show the tornado. "My tail-risk number moves ±X% when I flex the disruption base rate from 2% to 8%; here's the range" is a far stronger answer than a point estimate.
*Employer:* Amazon/Apple Ops — this kills the §3.2 objection outright. Also the honest-uncertainty move consultants love.

**4.4 — Stop quoting R²=0.93 on n=75. (4 hours.)**
Either (a) do a temporal holdout and report the model with an honest confidence interval and the sample-size caveat in the same breath, or (b) pull the model from the headline and say: *"I built the collector, I have one snapshot, n=75, one source. That is not enough to train on and I'm not going to pretend it is. Here's the panel design and what 12 weekly snapshots would let me do."* **Option (b) scores higher with a DS interviewer than any R² you could report.** Knowing when your n is too small is the senior signal.

### Tier 2 — "This makes it exceptional." Pick ONE and go deep. 2–4 days.

**4.5 — Replace the heuristic risk surcharge with a two-stage stochastic program with a CVaR objective. (2–3 days. This is the highest-ceiling item in the project.)**
Right now, all resilience enters the MILP as an invented price uplift: `RISK_PREMIUM_RATE = 0.15`, `STOCKOUT_PENALTY_MULTIPLE = 3.0`, vulnerability weights `0.3/0.2/0.5` (`sourcing.py:153-186`). It is a hand-wave with a citation stapled to it, and an OR scientist will say so.

You already own both halves of the real thing. `graph/simulation.py` is a scenario generator. `sourcing.py` is a CP-SAT model. Compose them into a **sample average approximation**: sample K≈50 disruption scenarios, add recourse variables, and minimize `E[cost] + λ·CVaR_α(cost)` with the standard Rockafellar–Uryasev linearization (which is LP-representable and drops straight into CP-SAT). Sweep λ. **Plot the efficient frontier: expected cost on one axis, CVaR-95 on the other.**

That chart is the single most portfolio-defining artifact you could produce. It replaces "I added a 15% surcharge" with "here is the price of resilience, and here is the knee of the curve" — and the knee *is the recommendation* consulting keeps asking you for. It is textbook-standard (Snyder & Daskin's actual formulation, which you are already citing), it is unambiguously not LLM-boilerplate, and it converts your weakest employer (Amazon SCOT) into your strongest.

**4.6 — Validate the forecasting pipeline on a real per-SKU demand dataset. (1–2 days.)**
Public per-part electronics demand doesn't exist — that's a true and defensible statement. So say it, and then prove the *pipeline* works on data where the truth is known: you already have `backend/seeds/monash_loader.py` and `run_carparts_backtest.py`. Run the full stack (Croston/SBA for intermittent, Prophet, Chronos) on **M5 or the Monash car-parts series**, report WAPE against seasonal-naive with the same harness, and label the in-app sparklines explicitly as "illustrative — pipeline validated on M5, see docs." That is a completely honest, completely defensible position, and it's *stronger* than a fake per-part number.

### Tier 3 — Presentation. 1 day, and it's the day most candidates skip.

**4.7 — Write the 2-page case study. (4 hours.)** See §5. Nobody reads a repo. They read one page.

---

## 5. What's missing entirely that a top candidate would have

1. **A case-study one-pager.** There is no `CASE_STUDY.md`, no PDF, no artifact that a recruiter forwards. `docs/RESILIENCE_INTERVIEW_GUIDE.md` is close but it's a *technical* walkthrough. What's missing is the consulting structure: **Situation → Complication → Question → Answer → Recommendation.** Two pages: who the client is (a mid-size PCB manufacturer sourcing 60-line BOMs), what it costs them today, what you found, what you'd do about it, what you'd need to be sure.

2. **Business-scale dollars.** Every dollar figure in the repo is per-BOM and in the **hundreds** ($131.77 optimized, "~$500 spend-at-risk"). No McKinsey EM or Amazon L6 will engage with $500. You need: *"a manufacturer running 12 BOM re-orders/year at $2M annual component spend"* → savings and tail exposure in **$100k–$1M**, with the volume assumption stated on the slide. You already have `ANNUAL_REORDERS = 12` (`backend/app/api/benchmark.py:30`) — you're one assumption away, you just haven't stated it at a scale anyone cares about.

3. **The recommendation.** The whole project computes and displays. It never *decides*. Add one line to the top of the Benchmark page and to the case study: **"Qualify a second source for these 14 parts. Cost: $X/yr. Removes: $Y of tail exposure. Payback: Z months."** The `compute_dual_sourcing_plan` engine already tiers candidates into no-regret / hedge / supplier-development (`recommendations.py:199`) — that is a *recommendation engine you are not using as one.*

4. **An efficient frontier.** Cost vs tail-risk. See §4.5. Its absence is why the resilience story currently reads as "I added a surcharge" rather than "I priced insurance."

5. **Held-out evidence that the *served* models beat a baseline.** You have three backtests, and all three test something adjacent to what the product actually serves (§3.3, §3.4). Fixing this is §4.6.

6. **A stated limitations section.** Every one of the §3 findings is something *you already know* (the code's own docstrings prove it). Put them in the README under **"What this model can't do."** Counterintuitively this makes you look *stronger*, not weaker — it converts every gotcha an interviewer was going to spring on you into evidence that you saw it first. Right now the honesty is buried in docstrings where only I found it, while the README is out front making claims the code contradicts. **That is exactly backwards.**

7. **Operational hygiene an engineer will notice:** zero frontend tests and no test runner in `frontend/package.json`; no React error boundaries; `<title>frontend</title>` in `frontend/index.html:6`; the non-demo login path hardcodes a fake user (`frontend/src/pages/Login.tsx:22`) and renders "0.00°N 0.00°W"; CI does not gate `deploy-render.yml`, so a red suite still ships to production; `regime.joblib` is not committed, so the regime model **silently fails to load in production** and `models_exist()` doesn't check for it; 34 stray `.playwright-mcp/` debug artifacts are committed; and the production database is a 10 MB SQLite file in git on an ephemeral disk, so every signup and cart is destroyed on redeploy.

---

## 6. The honest bottom line

You have built something real. The CP-SAT model is real, the graph is real, the data is real, the benchmark harness is scrupulously fair, and the willingness to render an "Honest finding: no material effect" callout in your own showcase UI is a genuinely uncommon act of intellectual honesty that I would hire for.

But you are currently **marketing the weakest parts and hiding the strongest.** The README leads with a 44.7% figure that is a fixed-fee artifact, an "EVaR" that is a constant, an R² from 15 test points, and five numbers that its own repo contradicts. Meanwhile, the actual A-grade material — *"I found my own optimizer's win was an artifact and here's the volume threshold where it stops mattering"* — is sitting unexploited in your benchmark output, and the intellectual honesty that would make an interviewer trust you is buried in Python docstrings.

**Two weeks of the right work moves this from B− to A−.** Not by adding a fifteenth subsystem. By fixing the five numbers (2 hours), re-running the benchmark at realistic volume and telling the truth about what you find (1 day), grounding the disruption probabilities (1 day), building the cost-vs-CVaR efficient frontier (3 days), and writing the two-page case study that ends in an actual recommendation (4 hours).

Do that and the interview stops being *"defend your numbers"* and becomes *"here is how I found out my own numbers were wrong."* That is the interview you win.
