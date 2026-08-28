# Outstanding work

Live backlog. Every item was found by a verification pass against the deployed
site and the artifacts, not from a wishlist. Ordered by **interview damage**:
a false published claim outranks a correctness bug, which outranks polish.

Status: `TODO` · `WIP` · `DONE` · `DEFERRED (owner)`

Live: 92f1e71 · updated 2026-08-28

---

## P0 — claims the code contradicts

| # | Item | Where | Status |
|---|---|---|---|
| 1 | `risk_score` published as a **percentage**. It is a verbatim passthrough of a HuggingFace column (`seed_db.py:248`), an additive hand-weighted flag sum on a **6-value support**, and **48.9% of the catalogue carries a flat 0.20 placeholder**. The `0.4/0.7` bands sit inside a gap in the support (nothing exists between 0.25 and 0.60) so both thresholds are unfalsifiable; `SchedulerPage` uses a *different* set (0.3/0.6), so the same 13 ESP8266 parts render **red on /components and amber on /dashboard**. `models/component.py:17` claims it comes from "Nexar analysis"; `nexar_client.py:418` hardcodes 0.0. | `Dashboard.tsx`, `SchedulerPage.tsx`, `lib/risk.ts`, `models/component.py` | **DONE** — no `%` anywhere; one flag-based tier shared by both pages; 12 tests |
| 2 | `/resilience` baseline **ETA describes a different plan from the baseline cost**. `_bom_eta_days` is max-over-lines of **min**-over-suppliers (the fastest supplier in the catalogue); `_price_bom` buys the **cheapest**. On the demo cart 4 of 5 lines price to Weyland (Singapore, 26.6 d), so the true ETA of the $166.94 plan is **26.6 days, not 2.8** — a 9.4× understatement. The honest story is better: losing Weyland *improves* delivery ~3 days while raising cost 25.2%. | `api/resilience.py` | **DONE** — ETA now computed over the plan's own suppliers; baseline 2.8 → **26.6 d**; distributor-failure delta flipped 0.0 → **−3.2 d at +28.5% cost**; 4 tests, RED/GREEN verified |
| 3 | `/map` **Network Risk colour channel is dead**. `MapPage.tsx:566` feeds raw betweenness into `riskLabel()`, whose thresholds are 0.4/0.7 — but max betweenness across all 92 distributors is **0.2458**, so every marker is always green/"low" and no data could change that. Size channel uses 24.6% of its range. Calibrated for a min-max-normalised score later removed from the builder. | `MapPage.tsx` | **DONE** — percentile bands over the live distribution (max 0.2458); legend says "top 10% by betweenness", not "high risk" |
| 4 | `noise_floor_pct` is a **hardcoded 2.0** rendered as "well above **this run's** 2.0% noise floor". The schema comment literally says `# hardcoded 2.0`. Not derived from solver tolerance or replicate variance. | `api/benchmark.py`, `BenchmarkPage.tsx` | **DONE** — could not be derived (deterministic solve, replicate variance 0), so relabelled `materiality_threshold_pct` with a served basis saying it is assumed, not measured |
| 5 | "change in **collapse probability** (0–1 scale)" — the field is `1 − median fraction of BOM lines fulfilled`, quantised to quarters on 4-line BOMs. No base rate, no exposure window: **not a probability**. | `BenchmarkPage.tsx`, `api/benchmark.py` | **DONE** — now "change in median unfulfilled-line share (0–1)", corrected at the source string too |
| 6 | Volume curve overlays the **withdrawn run-4 headline (48.09)** onto a curve whose own 1× point is **47.22**, generated post-fix with different `us_only` and 10 BOMs. The caption "Same solver, same offer pool, same objective" is false relative to that reference line, and the API's own `aggregate_definition` says so. `docs/volume_sweep.json` also ships a stale `meta.known_bug` block declaring the optimizer broken — fixed 2026-07-13. | `BenchmarkPage.tsx`, `docs/volume_sweep.json`, `seeds/run_volume_sweep.py`, `lib/volumeDecayCurveData.ts` | **DONE** — reference line is the curve's own 1× (47.22%); stale `known_bug` removed from artifact AND generator; fallback provenance date corrected |
| 7 | `collapsed_boms` is **documented but never computed** — `main.py` never writes the key, all 6 served points return `[]`, and the page invites "Click a point to see which BOMs collapse". | `api/benchmark.py`, `main.py` | **DONE** — now computed: Arrow removes `pcb_power_supply`, Newark also removes `automotive_ecu`; serves `boms_checked` + `bom_source` so an empty list can't be misread |

## P1 — correctness

| # | Item | Where | Status |
|---|---|---|---|
| 8 | MILP **quantises unit prices to whole cents** (`int(round(price*PRICE_SCALE))`) while the objective carries milli-cent resolution and uses it for freight. `MLG0603P43NHT000` at $0.0031 → **0 cents: free to the optimizer**. 15 components have sub-$0.10 offers, error up to ~6%. The greedy baseline prices on full floats, so **the two benchmark arms optimise at different price resolutions**. | `sourcing.py`, `greedy.py` | **DONE** — one `to_obj_units()` is now the sole USD→objective conversion, applied once per term. The three risk surcharges had the SAME defect and floored to zero on cheap parts. Measured impact on the benchmark: **0 of 80 cells** (no benchmark BOM holds a sub-cent part). 17 tests. |
| 9 | `is_chinese_origin` is **double-counted** in the stock-out premium: `0.3·is_chinese + 0.2·stock + 0.5·risk_score`, but `risk_score` is *itself* 0.6 exactly when that flag fires. One binary attribute contributes 0.30 directly and 0.30 again. Also uses "calibrated" for a hand-chosen weight. | `sourcing.py` | **DONE** — `risk_score` removed from the vulnerability index; confirmed `risk_score ∈ {0.60,0.70}` is *exactly* the 14 rows with `manufacturer_country == "China"`, the same predicate `is_chinese_origin` fires on. Now `0.6·is_chinese + 0.4·stock`, summing to 1.0 so `RISK_PREMIUM_RATE` means what it says. "Calibrated" removed. **Moves 1 of 80 cells** — and makes one published resilience row worse, so a re-run is owed. |
| 10 | Live-price "cheapest first" **sorts raw price with no currency normalisation**, so a "best price" pick can be a non-USD figure. | `api/live_prices.py:278,391,502` | **DONE** — no FX source exists in this repo, so ranking/best-price is scoped to USD offers only; every offer still returned, non-USD ones carry `price_comparable=false` and sort after; response states `price_comparison_basis`; sync endpoint no longer writes a non-USD price into the USD `price` column; 18 tests |
| 11 | DigiKey live lookup is a `Limit:1` keyword search with **no exact-match check** — `ESP8266EX` returned `ESP-WROOM-02U` at $3.30 and the cart printed "Live: $3.30 (+574.5%)" with no SKU shown. | `digikey_client.py:87-113`, `CartPage.tsx:158-160` | **DONE** (backend) — `search_mpn` now requires the returned MPN to equal the query after normalizing case/whitespace/separators (checks `ExactMatches` then `Products`); a non-matching hit returns `None`, an honest miss, instead of the nearest part. `CartPage.tsx` untouched (out of scope for this pass) — see report for the optional SKU-display follow-up |
| 12 | Benchmark deltas are **uninterval'd means over 9 BOMs, 4 structurally zero** (effective n = 5–7). No CI, SE or replicate anywhere; single seed 42; `−0.0072×` published to 4 dp. This contradicts the repo's own ship standard (paired bootstrap CI excluding zero) that the ML models are held to. | `api/benchmark.py`, `seeds/run_benchmark.py`, `BenchmarkPage.tsx` | **DONE** — paired bootstrap over BOM clusters, 10k resamples. **3 of 5 deltas survive; both stress deltas do NOT** (stress_cascade CI [−27.78, +5.56] pp covers zero). Page neutralises colour, prints the interval, and the Honest-finding panel now says "no measurable effect" instead of claiming −8 pp. `n_effective = 7`, BOMs named. |
| 13 | CVaR-95 under stress **saturates at a 1.15 ceiling** on 8 of 9 BOMs (`1 + (4/4)·0.15`), so the metric is structurally incapable of discriminating in the scenario designed to create saturation. The probability that *would* discriminate (`n_scenarios_with_shortfall / n`) is computed and never persisted. | `graph/simulation.py` | **DONE** — `p_shortfall` / `p_total_shortfall` / `cvar_95_ceiling` / `cvar_95_saturated` exposed. **16/18 published rows are at the ceiling; 10/18 are bit-identical ties; `p_total_shortfall` breaks 8 of 10.** Proved re-basing CVaR would not help (exact affine map, 0/36 deviate) with a test to stop it being tried. Also corrected `CVAR_EFFICIENT_FRONTIER.md`, which claimed this was fixed on 2026-08-16. |

| 21 | **The test suite cannot be run concurrently.** Fixtures build a fixed-name `backend/test_hardening.db`, so two pytest processes clobber each other's data — observed live on 2026-08-28: a targeted run returned `component_id 5 not found` / `404` on 5 stochastic tests purely because a sibling process was mid-fixture. `LEARNINGS.md` warns "never kill pytest mid-flight — it poisons test_hardening.db" but the fixed filename is the actual defect. Give the DB a per-process unique name (PID or `tmp_path_factory`), which also makes `pytest -n auto` possible and would cut the 10-minute suite substantially. **Discovered by the loop, 2026-08-28.** | `backend/tests/conftest.py` | **DONE** — per-process name + session teardown; proved with 3 concurrent runs (24+34+45 passing) |

| 22 | **Nav overflowed at 1280px — the third recurrence of this defect.** Adding a tenth link (`/newsvendor`) pushed the desktop row to **1371px** while it collapsed to a hamburger only *below* Tailwind's `xl` (1280px), so at exactly 1280 the full nav rendered into a bar 91px too narrow. The agent that added the link measured at 1440, where it fits, and concluded it was safe. **The gate would have missed it too** — it tested 390/768/1440, and the bug lived in the gap between a breakpoint and the width the content needs. **Discovered by the loop, 2026-08-28.** | `NavBar.tsx`, `gate.js` | **DONE** — breakpoint moved to a measured `min-[1400px]`; verified collapsing at 1399 and fitting at 1440/1536; **1280 added as a fourth gate viewport** |

## P2 — surface work that is already built and invisible

| # | Item | Status |
|---|---|---|
| 14 | **Newsvendor has no UI.** | **DONE** — `/newsvendor` route: decision (τ, q*, quantile ladder, naive rules), evidence (CIs drawn as intervals against a zero rule, not colour alone), and the MASE-vs-decision-cost argument as its own section. Every figure read live, nothing hardcoded from docs. |
| 15 | **Price-of-resilience frontier has no UI.** "The second supplier removes 0.44 of targeted cascade risk for $58.88 (CI 0.22–0.67); the third costs 6.8× more and its CI covers zero." Exists only in `docs/DIVERSIFICATION_FRONTIER.md`. | TODO |
| 16 | No `seeds/run_newsvendor.py` + doc-match test, so the published newsvendor numbers are **not auto-checked** like every other artifact. **Now urgent and proven:** §3.4 says 2,643 series / 47,574 decisions; the live API returns **2,646 / 47,628** because the `_size_shape` Poisson-limit clamp (fixed 2026-08-28) means 3 previously-dropped series now survive. The doc drifted within a day of being written. | **DONE** — `seeds/run_newsvendor.py` + `docs/newsvendor.json` + a 17-test doc-vs-ARTIFACT match (never doc-vs-doc). Confirmed the drift independently and rewrote §3.4: the defect paragraph claimed the `_size_shape` fix "has not been made" when it landed in the same commit. |

## P3 — hygiene

| # | Item | Status |
|---|---|---|
| 17 | `MAINTENANCE-AND-KNOWN-ISSUES.md` carried two deferrals that were no longer true, one of which told a future reader NOT to re-run the benchmark — the exact fix that was needed. | **DONE** — both retired to a new "Resolved — do not re-open" section with what actually happened; the doc now points at this backlog as the live list |
| 18 | `serving.py` docstring said the regime artifacts are not git-tracked and absent in prod. They **are** tracked (`.gitignore` un-ignores both with `!`) and **are** what prod serves. | **DONE** |
| 19 | `stress_level` cutoffs were bare literals with no constant or comment, so "why those numbers?" had no answer. | **DONE** — named constants, documented as a display convention (the optimizer reads the probability, never the label), grounded against a measured base rate of **0.1681** (57/339 months): HIGH ≈ 4.2× base rate, MODERATE ≈ 2.1× |
| 20 | `api/stochastic.py` published a retired defect in the PRESENT tense on the public Swagger surface, telling readers a fixed bug was still live. | **DONE** — moved to past tense, kept as "what it replaced" |

## Owner decisions — not mine to take

- `graph_aware` / `us_only` never sent by the live optimizer (`api.ts:181` posts no body). One boolean, changes live output.
- Render Starter ($7/mo) to kill the 50–120 s cold start.
- FRED write-on-read into a tracked CSV (~2 h).
- Python 3.13/3.11 provenance skew (~1 h + retrain).
- Six caller-less `/market/*` routes on public Swagger.

## Completion criteria — the promise `ALL GREEN` may ONLY be emitted when every line is true

This exists so the claim is falsifiable. Each line is a command with an expected
result, not a judgement call. If any one of them fails, the promise is false and
must not be said, regardless of how much work has been done.

1. **Backlog clear.** Every P0, P1 and P2 item above is marked `DONE` or
   `DEFERRED (owner)`. P3 items may remain `TODO`.
2. **Backend suite.** `cd backend && ./venv/bin/python -m pytest tests/ -q`
   → 0 failures, except the single documented local-only MLflow identity check
   (`test_the_served_estimator_is_the_one_the_metrics_describe`), which passes in CI.
3. **Lint and types.** `./venv/bin/ruff check app` and `./venv/bin/mypy app` both clean.
4. **Frontend.** `cd frontend && npx tsc --noEmit && npm run build` both clean.
5. **Browser gate against the LIVE site**, not a local build:
   `BASE=https://supply-chain-ui-bhwz.onrender.com node gate.js` → **0 failures**
   across 9 routes x 3 viewports. Covers overflow, emoji, type size, clipped chart
   labels, chart geometry, touch targets, axe serious/critical, head tags, console errors.
6. **ML verified against the deployed artifacts.** An `ml-pipeline-verifier` pass
   returns no FAIL: every published figure traces to `metrics.joblib`, no raw score
   is published as a probability, no technique is claimed that the code does not
   implement, and no endpoint described as live is unreachable.
7. **Deploy is real.** Render API reports `status: live` on BOTH services for the
   current SHA, AND `/version` + `/version.json` + `git rev-parse HEAD` all agree.
   A green GitHub "Deploy to Render" step is NOT sufficient — it only means triggered.
8. **Tree is honest.** `git status --porcelain backend/seeds/data/` empty; nothing
   under `.claude/**` staged or committed.

A green run that produced nothing is a lie. If a check cannot be run, the promise
is false — "not checked" is a failure, not a pass.

## Standing gates — every change must pass

- `cd backend && ./venv/bin/python -m pytest tests/ -q` → expect **848 passed, 1 failed** (the documented local-only MLflow identity check, green in CI).
- `./venv/bin/ruff check app` and `./venv/bin/mypy app` clean.
- `cd frontend && npx tsc --noEmit && npm run build`.
- Browser gate: `node gate.js` over 9 routes × 3 viewports → **99 passed, 0 failed**.
- `git status --porcelain backend/seeds/data/` empty — never let a seed CSV drift.
