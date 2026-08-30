# Outstanding work

Live backlog. Every item was found by a verification pass against the deployed
site and the artifacts, not from a wishlist. Ordered by **interview damage**:
a false published claim outranks a correctness bug, which outranks polish.

Status: `TODO` · `WIP` · `DONE` · `DEFERRED (owner)`

Live: 5a97482 · updated 2026-08-30 (verified: `/version` and `/version.json` both return 5a97482)

## What is actually still open

**Items 1–40 below are all `DONE`.** Of the four `ml-pipeline-verifier` findings in
**[`handoffs/handoff-2026-08-30-vintage-saturation-gates.md`](handoffs/handoff-2026-08-30-vintage-saturation-gates.md)**,
**all four are now `DONE`** (2026-08-28/29), as is the lower-priority `recommended_k`
item. What follows is the record of each:

1. ~~`/ml/stress` publishes a probability computed from a **2026-07-01** frame with no as-of
   field~~ — **DONE** (2026-08-29). The response now carries `observation_date`,
   `observation_frequency`, `observation_age_days`, `observation_age_months`,
   `vintage_is_stale`, `max_observation_age_days` and a composed `vintage_label`, all derived
   from the same `tail(1)` row that is scored — never a fabricated date (the unavailable branch
   reports "no data vintage" rather than a guess). `/model-card` prints `Jul 2026` beside the
   82.8% at equal type size; `/optimize` tags the claim and renders the vintage and an amber
   note *larger* than the claim they qualify. 9 tests in `test_stress_vintage.py`, each proven
   red. **Optimizer behaviour is deliberately unchanged** — a stale frame still prices the full
   surcharge (owner decision, 2026-08-29); `sourcing.py:686-697` records where to gate it if
   that is ever revisited. `STRESS_FRAME_MAX_AGE_DAYS = 120` turns the suite red on
   **2026-10-29** if nobody retrains; the fix is to retrain, not to raise the constant.
2. ~~`p_shortfall` / `p_total_shortfall` / `cvar_95_saturated` are computed in
   `graph/simulation.py` and served nowhere~~ — **DONE** (2026-08-28). Migration `0009` adds
   `mc_p_shortfall`, `mc_p_total_shortfall`, `mc_cvar_95_ceiling` and `mc_cvar_95_saturated` to
   `optimization_runs`; `seeds/run_benchmark.py` fills them; `/benchmark/summary` serves
   `cvar95_ceiling`, `*_cvar95_saturated`, `*_cvar95_ceiling_tied_boms`,
   `*_p_total_shortfall_reduction` (with its own paired bootstrap interval) and a composed
   `saturation_note`; the `/benchmark` CVaR tiles print the flag, name the ceiling-tied BOMs and
   show the measure that still resolves. The real re-run (run 7) changed **0 of 72 cells** against
   run 6. On the published 18: **10 cells are ceiling-tied and `p_total_shortfall` breaks 8 of
   them** — and under broad stress it removes **0.197** (95% CI 0.118 to 0.259, significant) where
   both published stress deltas cover zero.
3. ~~`README.md:196-214` publishes the retired 810-row / 27-manufacturer / `random_forest`
   vintage~~ — **DONE**. The grouped-split study had already been re-run and committed
   (`docs/leakage_progression.json`, generated 2026-08-26) but the README table was never synced
   to it; README now quotes the current figures (1,879 rows / 472 family grouping keys / 28
   manufacturers,
   `+0.804 → +0.084 → −0.784`, plus the served `metrics.joblib` audit `+0.8084 → +0.1169 →
   −0.3895`) with the retired 810-row/27-manufacturer numbers labelled and dated as superseded.
   Same stale panel size (817 rows / 2 snapshots / 56 features) also found and corrected in
   `PROJECT_OVERVIEW.md`, `RESEARCH_TECHNIQUES.md` and `RESILIENCE_INTERVIEW_GUIDE.md`.
   `python_version` provenance stamping (3.13 local vs 3.11 CI) remains unresolved — see "Owner
   decisions" below.

   **Correction, 2026-08-30 — this entry's own claim was false until today.** It said README
   quoted "472 family keys", and the string `472` appeared **zero** times in `README.md`. Both
   numbers are real and they count different things: `docs/leakage_progression.json`
   (`counts.n_family_group_keys` = **472**, `identity_column_in_sample_r2.base_product.n_levels`
   = **361**) and the served `metrics.joblib['lead_time_leakage_audit']['n_families']` = **472**.
   361 is the raw `base_product` level count, used only for the in-sample R²=0.848 identity
   check; 472 is the `_group_key` fold-group count (`base_product`, falling back to MPN then
   row — `app/ml/lead_time_model.py:1644`) that the GroupKFold split and every published family
   R² are actually grouped on. README quoted 361 correctly for the identity check but labelled
   its GroupKFold row `(base_product)`, implying the split had 361 groups when it has 472.
   **Fixed in README, not in this backlog note:** the table row now reads
   `GroupKFold by part family (**472 family grouping keys**)` and the prose beneath names both
   numbers, what each counts, and the artifact field each comes from. The claim above is now
   true. (Also noticed, not fixed — not my file: `seeds/run_leakage_progression.py:54,612`
   carry stale `467` comments where the computed value is 472.)
4. ~~**UNVERIFIED** — FRED write-on-read in `fred_client.py:307,355`~~ — **VERIFIED LIVE, then
   FIXED** (2026-08-29). Both writes were unconditional and both endpoints are *keyless*
   (`fredgraph.csv` / NY Fed `.xlsx`), so no missing API key made it latent. Production serving
   never reaches the path (`serving.py::resolve_regime_signal` loads artifacts), but the two
   `@pytest.mark.integration` tests do — meaning **the documented `pytest tests/ -q` gate could
   rewrite `backend/seeds/data/`**. Commit `035ae78` (2026-08-16, a lead-time bug-fix) had
   already swept 685 lines of `gscpi_monthly.csv` along this way. Fix: `refresh_cache=False`
   default on `fetch_gscpi()` / `fetch_regime_feature_frame()`; only
   `seeds/train_ml_models.py:46` passes `True` — deliberately at the *call site*, because the
   integration test calls `retrain_regime_model()` directly and a flag inside the function body
   would have left the exposure intact. ALFRED `vintage_date` is now threaded through to all
   four `REGIME_FEATURE_SERIES` (default `None` = latest = unchanged). GSCPI gets no pin — it is
   a NY Fed proprietary single-`.xlsx`, revised in place, with no archival endpoint; documented
   at `fred_client.py:293-300`. 10 mutations, 10 reds. Proven: the two integration tests now run
   live against FRED and the seed CSVs stay byte-identical.

   The recommendation to *exclude* `integration` from CI was **rejected** — it removes coverage
   to solve a problem the guard already fixes. The marker is now registered in `pytest.ini`
   (filterable, no longer warning-noise) and still runs everywhere.

Plus, lower priority: ~~`/benchmark` anchors `k === 2` as a bare numeral~~ — **DONE**
(2026-08-28). The API serves `recommended_k` + `recommended_k_basis` from `_recommended_k()`,
the one place the rule lives, and `_frontier_finding()` composes its sentence from the same call;
the page consumes the field in all three places and labels the row "recommended" in words.
Published sentence and verdict are byte-identical. The rule is **the cheapest priced step**, not
"the largest significant k" — the latter returns k=3 on this frontier and would have flipped the
published verdict.


## Found 2026-08-29 — three gates that could not go red

None of these was on any backlog. Each is the same class of defect: a check that passed
because it was incapable of failing. `LEARNINGS.md`: *a check that cannot fail is worse than
no check.*

**41. The standing TypeScript gate typechecked nothing.** `DONE`. `frontend/tsconfig.json` is
a solution file (`"files": []` + `references`), so `npx tsc --noEmit` — the gate written in
`CLAUDE.md` — resolves no source files and exits 0 on any error. Proven by planting
`const x: number = "definitely not a number"` in `services/api.ts`: `--noEmit` passed,
`tsc -b --force` reported it. It had already waved through two real type errors in this
session's own work. Gate corrected to `npx tsc -b --force` (what `npm run build` already
runs, so CI was never affected) with a "Never do this" entry recording the evidence.

**42. `docs/volume_sweep.json` was generated by a pre-fix optimizer.** `DONE`. Commit
`6a33ad0` changed `sourcing.py` (milli-cent quantisation, risk surcharges, an
`is_chinese_origin` double-count) and hand-edited only the artifact's `meta` prose without
re-running the generator. `test_volume_curve_pooled_table_matches_sweep_json` compares the
**doc to the artifact** — both were stale together, so it stayed green while both disagreed
with the code. Verbatim the failure mode `CLAUDE.md` opens with. Regenerated via the real
`python -m seeds.run_volume_sweep` (1.0 s): the published **2.6-8.0%** range *reproduces*
(2.61%-7.97%), 12 of 13 rows bit-identical; one genuine cell moved
(`pcb_power_supply` @10,000x, $181,919.39 → $181,908.01, 5 → 6 suppliers, pooled 7.96% →
7.97%). **A scratch reimplementation had claimed the whole curve was near-zero/negative. It
was wrong.** `LEARNINGS.md`'s rule held: only the real generator settles a number.

**43. Only two artifact-vs-code pins existed in the whole suite.** `DONE`. Everything else
that looked like one was doc-to-artifact, artifact-to-artifact, schema, or API-to-artifact —
none of which goes red when *code* moves and the artifact is not regenerated.
`backend/tests/test_artifacts_pinned_to_code.py` adds 5 pins in 5.0 s, each re-solving through
the generator's own function (never a reimplementation): all 80 points of `volume_sweep.json`,
the full k-sweep of `diversification_frontier.json`, the `primary` block of `newsvendor.json`,
the frontend fallback table, and a shared constant. Anti-vacuity guards included: a DB
row-count assertion (791/92/8,176 — catches the CWD-relative-SQLite trap), a floor on points
actually re-solved, a wall-clock ceiling, and a distinct message when CP-SAT returns
`FEASIBLE` so "solver truncated" is never misread as "artifact stale". Proven red by moving
`LTL_BASE_FEE_USD` 75.0 → 76.0 (1,003 differing values) and `EXPEDITE_PREMIUM` 0.15 → 0.16
(104 differing values).

Related, fixed with 42: `frontend/src/lib/volumeDecayCurveData.ts` holds a hardcoded copy of
the volume curve, rendered on `/benchmark` whenever the API is unreachable, pinned by nothing.
It had drifted (10,000x row still 7.96), and a separate pre-existing drift in its
`greedy_fixed_share_of_cost_pct` column disagreed with the code's own arithmetic on 9 rows.
Both corrected and now pinned. It is the only such hardcoded table in `frontend/src/`.

~~**Left unpinned, deliberately, with sizing:** `cvar_frontier.json` (~1,316 s),
`leakage_progression.json` (~215 s nested CV), `chronos_benchmark.json` (torch + HF weights +
network), `forecast_backtest.json` (Prophet per rolling origin), `backend_verification.json`
(42 live HTTPS calls). **Open decision:** whether to add them.~~ — **RESOLVED 2026-08-30, see
item 44.** Four of the five are now pinned behind `-m slow`. **The sizing above was the cost of
REGENERATING each artifact, not of re-solving a canonical slice of it** — and that mistake is
why five artifacts went a day and a half unguarded. Measured truth: the whole `-m slow` block
costs **~50 s**.

**44. `docs/cvar_frontier.json` was stale, and four heavy artifacts are now pinned.** `DONE`
(2026-08-30). `backend/tests/test_artifacts_pinned_to_code.py` gains four `@pytest.mark.slow`
pins, each re-solving through the generator's own function:

| Artifact | What is re-solved | Cost | Proven red by |
|---|---|---|---|
| `cvar_frontier.json` | the whole PRIMARY arm via `_run_primary` — 3 volumes × 9 λ, both baselines, the VSS | ~45 s | `LTL_BASE_FEE_USD` 75.0 → 76.0 |
| `leakage_progression.json` | panel + row accounting + feature columns + the identity-R² table in full, then **fold 0 of each of the 3 regimes** via `score_regime` (24 fits, not 1,200) | ~5 s | `Ridge(alpha=1.0 → 1.1)` |
| `forecast_backtest.json` | all three arms, whole — **since 2026-08-30 split into a deterministic `seasonal_naive` pin (CI) and a `slow` Prophet pin, see item 54** | ~0.7 s | `SEASONAL_PERIOD` 12 → 11 |
| `chronos_benchmark.json` | classical arms unconditionally (**likewise split by determinism, item 54**); the zero-shot arm + cold-start table from the **locally cached** weights under `HF_HUB_OFFLINE` | ~4 s | `quantile_levels` 0.5 → 0.55 |

**46. The forecast pin is promoted out of `slow`, so CI gets a pin on a demand-series artifact.**
**DONE** (2026-08-30) — **but only the deterministic half survived CI; superseded in detail by
item 54, read that first.** CI's backend job runs `pytest tests/ -q --tb=short -m "not slow"`
(`.github/workflows/ci.yml:63`) and installs `requirements.txt` only (line 26) — so the five
`slow` pins above were invisible to CI.

**A CORRECTION TO THIS ENTRY'S ORIGINAL FRAMING (2026-08-30).** It said CI had "no
artifact-vs-code coverage at all". **That was wrong.** Sections 1-4 of
`test_artifacts_pinned_to_code.py` (volume sweep, the frontend fallback table, the production
floor, the diversification frontier, newsvendor) are *unmarked* and were already running on CI:
`backend/supply_chain.db` is committed — `.gitignore:40` un-ignores it explicitly — so the
optimizer pins do not skip there. CI run `33318131193` reported **1,114 passed and exactly ONE
skip** across the whole suite, which it could not have done had five pins been skipping. The
real gap was narrower and should have been stated that way: **neither DEMAND-SERIES artifact
(`forecast_backtest.json`, `chronos_benchmark.json`) had any CI pin**, both being `slow` in
full. That is what items 46 and 54 actually closed. The
`forecast_backtest.json` pin needs no database, no network (the series loads offline from the
committed ALFRED vintage pin) and no `requirements-ml.txt` dependency, so it was unmarked.

**What this entry got wrong:** it promoted ALL THREE arms, having reasoned only about *cost* and
*dependencies* and never about *reproducibility*. The Prophet arms are not bit-reproducible off
the machine that writes the artifact, and CI went red on them. Only the `seasonal_naive` arm is
in CI now; the Prophet arms are back behind `slow`. The right question for a pin is not "is it
cheap and dependency-free here?" but **"does it produce the same bytes on the machine that will
run it?"**

The red proof below still stands and is the one CI now relies on: **proven red**, per the
standing rule, by `SEASONAL_PERIOD` 12 → 11 in `seeds/run_forecast_backtest.py:77`, which fails
the deterministic pin with *"69 differing values"* across the `seasonal_naive.*` fields (and the
chronos deterministic pin with 61); restored and verified byte-identical
(`git status --porcelain` on that path empty).

The other four stay `slow`, and the reasons were re-checked rather than assumed:
`cvar_frontier.json` opens a seeded `SessionLocal` (`_assert_row_counts`, `build_graph_state`,
`_load_offers_for_bom`) and takes **42.7–43.4 s**; both `chronos_benchmark.json` pins need
`torch==2.12.1` / `chronos-forecasting==2.3.0` from `requirements-ml.txt`, which CI never
installs; `leakage_progression.json` takes 4.6–4.7 s (no DB — reads `PANEL_PATH` directly),
which is a judgement call, not a hard constraint.

**The chronos classical-arms promotion proposed here was taken, and was half wrong.** This entry
argued the pin needs no torch and no network and so was promotable on the same argument as the
forecast pin. True as far as it went — and still an incomplete argument, because dependencies are
not the only thing that has to hold on CI. Its Prophet half is not reproducible there and turned
CI red with 61 differing values. The arm is now split: `seasonal_naive` runs in CI, `prophet`
is back behind `slow`. See item 54.

**What the cvar pin caught on the day it was written.** `6a33ad0` changed `sourcing.py`;
`volume_sweep.json` was regenerated for it on 2026-08-29 and **`cvar_frontier.json` was not**,
though it carries the same deterministic MILP as a baseline. It published
`first_stage_cost_usd: 181919.39` / 5 suppliers where the optimizer returns `181908.01` / 6 —
*the identical cell that moved in the volume sweep* — and `CVAR_EFFICIENT_FRONTIER.md:534-535`
showed a reader the derived **$183,171 / $219,128 / 5**. `test_cvar_doc_matches_artifact.py` was
green throughout: it compares the doc to the artifact, and both were stale together. **Third
recurrence of the failure mode `CLAUDE.md` opens with.** It also invented a difference that does
not exist: the doc showed the shipped MILP at $183,171 / 5 suppliers *beside* the mean-value EEV
baseline at $182,932 / 6, as though the two were different plans. They are the same plan —
`solve_sourcing` with disruptions assumed away IS the mean-value solve — and after the fix the
two rows agree, which is the honest reading of a VSS of 0.37%.

Fixed by a real `python -m seeds.run_cvar_frontier` (1,331 s, no `--quick`): **10 fields moved,
all of them inside the two `shipped_milp_graph_aware=*` baselines at ×10,000** — 6 dollar
figures, 2 supplier counts, 2 supplier lists. No other published cost or CVaR figure in the
artifact changed. (The solve-quality churn that came with the re-run is item 45, not drift.)

**`backend_verification.json` is honestly UNPINNABLE, and the test file says so.** No generator
for it exists in this repo — it is a hand-run snapshot from the 2026-08-19 production repair —
so a pin would have to be the reimplementation `LEARNINGS.md` forbids. Its content is 42 live
HTTPS responses with a per-check `seconds` field that cannot reproduce; a test re-issuing them
would go red on a Render cold start and green on a broken build.

**45. `cvar_frontier.json` cannot be regenerated reproducibly, and its doc does not say so.**
**DONE** (2026-08-30) — see the resolution at the end of this item. The breadth and sensitivity
arms solve under a 15 s CP-SAT budget, and the committed
artifact's own `solve_quality.by_arm` records **46 of the breadth arm's 150 solves hitting that
limit**, 38 of them left unconverged, worst gap **92.69%**. (`primary`, at a 60 s budget, is
27 solves / 27 converged / 0 hits / 0.00% worst gap — which is why it is the arm that is
pinned.) Two honest back-to-back runs of the same generator on the same machine therefore
disagree. **Measured over two full 22-minute regenerations on 2026-08-30:**

* **Under CPU load**, the headline counters moved (349 → 347 converged, 48 → 52 non-`OPTIMAL`,
  MIP-gap p90 3.79% → 6.07%) and **`smart_meter` dropped out of the breadth table entirely** —
  a published row became `excluded / —` purely because one λ ran out of clock.
* **On a quiet machine**, the headline counters landed back on 349/38/48 exactly — but their
  *composition* did not. 16 `worst_mip_gap_pct` values moved (`audio_dsp_board ×1`
  84.69% → 88.82%, `industrial_motor_driver ×1` 9.28% → 10.06%), `automotive_ecu ×10` closed
  one λ MORE (3 → 4 converged) and `audio_dsp_board ×1` one FEWER (2 → 1), and the
  `not_converged` list reordered.

No breadth cost or CVaR figure moved in either run — the *plans* are stable. What is unstable is
every number the document publishes ABOUT the solve, and `CVAR_EFFICIENT_FRONTIER.md` presented
those as findings (its solve-time spotlight table reshuffles with them too).

**Owner decision (2026-08-30): relabel, do not regenerate.** Raising the time limit costs a
22-minute regeneration and would leave the figures machine-dependent *less often* rather than
reproducible; relabelling is truthful immediately and cannot rot. The artifact was **not**
regenerated for this item.

**Resolution — what was labelled, and what was deliberately left alone.**
`docs/CVAR_EFFICIENT_FRONTIER.md` now carries the machine-and-load-dependence notice in the
same `###`-heading weight as the claims it qualifies (never smaller — the mistake made once
already), in six places, all *outside* the `GENERATED:` markers so a re-render cannot wipe them:

* a document-header callout above §"What this replaces", stating the boundary in one line;
* §0, retitled *"Solve quality — a run log of one machine's time budget, not a property of the
  problem"*, carrying the full notice: the 15 s / 60 s budgets, `num_search_workers = 1`, the
  hardware from `Provenance`, and the two-regeneration evidence table (349 → 347, p90 3.787% →
  6.07%, `smart_meter` dropped; then 349/38/48 back but 16 gap values moved);
* a `###` run-log banner immediately above the generated `solve_quality` block;
* §4 (`Status` / `Gap` / `Solve` columns and the per-sweep solve-quality line), §6 (`all λ
  converged`, the "36 of 36" line), §7 (`Wall`, `all λ converged`), §8 (`Worst gap`, `all λ
  converged`, the `excluded` markings, **and which rows appear at all**), §9 (`λ-sweep wall
  time`, `Worst gap`, `λ not converged` — the whole table);
* the three §9 "measured" bullets, the 60-draw/200-draw sizing measurement, and the §1
  RU-reformulation timing, each marked as this machine's seconds with the *ordering* named as
  the part that transfers.

**Deliberately NOT caveated, because over-caveating real results is its own dishonesty:** every
cost, plan, supplier set, CVaR value, tail decomposition, knee, VSS, SAA bound and frontier
point. None of them moved in either regeneration, and each caveat above says so explicitly so a
reader cannot spread the doubt onto the economics.

**Also fixed while here — the same figures were stale on the live site.**
`frontend/src/pages/FrontierPage.tsx` hard-coded *"330 converged / 57 did not"* and a primary-arm
*"worst MIP gap 0.082%"* for an artifact that says **349 / 38** and **0.000%** — a superseded
vintage published as current. Corrected against `docs/cvar_frontier.json`, and the page now
carries the same machine-dependence caveat at the same type size as the counts, with the
"no cost, plan or CVaR value moved" boundary stated on screen
(`data-testid="frontier-solve-quality-caveat"`). `npx tsc --noEmit` clean;
`test_cvar_doc_matches_artifact.py` 25 passed.

**Out of scope but found:** `docs/BENCHMARK_VOLUME_CURVE.md:385` publishes the same class of
figure for a different artifact — *"of 326 MILP solve attempts, 296 were feasible and all 296
returned `OPTIMAL` — none hit the 5s time limit"*. That is a 5-second-budget measurement on one
machine, presented as a property. Not touched here; it belongs to `volume_sweep.json`.


## Found 2026-08-30 — the live-site sweep

The owner asked for every remaining error. These were found by calling the deployed API and
driving the deployed UI, not by reading code. **Four were user-facing failures on the live site.**

**46. `POST /optimize/vrp` returned HTTP 500 on ordinary carts.** `DONE`. The pre-flight checked
only that an offer ROW existed, never that it carried stock, so a zero-stock row passed and then
pinned every `q` below a demand equality — CP-SAT returned INFEASIBLE and the API reported
`"Solver failed: Sourcing MILP infeasible"`, which `CheckoutPage.tsx` renders verbatim. The server
had not failed; the catalogue was out of stock. **Reproduced live on `5a97482`**: component 24
(100 units in China, 3 domestically) with quantity 4 → 500. Blast radius, counted in the served DB:
**18 components have zero stock across every offer; 31 have a priced domestic offer with zero
domestic stock** — and three of the four strategies hard-code `us_only_sourcing=True`, so it fired
even for requests sent with `us_only=false`. Now a `ValueError` → **400** naming the part, the
quantity needed and the stock available. 4 tests; 3 proven red with the guard disabled (the 4th is
the feasible-side boundary and correctly stays green).

**47. `GET /newsvendor/evaluation` took 259.9 s and starved the entire API.** `DONE`. Render runs
**one uvicorn worker on 0.5 CPU**, so one CPU-bound request blocks everything, and abandoning it
does not stop the computation. Steady-state recompute measured at ~107 s; a source comment claimed
"~4 s", which was a dev-machine number (profiled locally at 3.4 s — production was ~30×). This was
also the true cause of the UI gate's random aborts: each abandoned run left the server saturated
for the next. Now served from `docs/newsvendor.json` — **~30 ms**, and all **72** reachable
configurations precomputed (255 s of generator time, artifact 65 KB → 0.98 MB). Served latency
median **0.7 ms**, max 3.7 ms. Every named block proved bit-for-bit identical (0 differences); all
72 recomputed the slow way and compared leaf-by-leaf.

**48. `review_period_months` 7–12 returned HTTP 500, and the dropdown offered "12 months".**
`DONE`. `run_panel_evaluation` splits a 6-month held-out horizon into `floor(horizon/L)` blocks and
raises when that is zero, so the advertised range was one click from a traceback. These could not
be precomputed without fabricating, so the range is now bounded to the horizon (**422**, derived
from `PANEL_HORIZON` rather than restated) with a `ValueError → 422` guard behind it, and the
frontend offers only 1–6.

**49. `/market/*` published fabricated constants.** `DONE`. When the upstream was unavailable the
routes returned `risk_weight_multiplier: 1.0`, `tariff_multiplier: 1.0`, `alerts_count: 0` and
`critical_alerts: 0` as bare values beside seven nulls — a reader could not distinguish "we checked
and the world is calm" from "we never fetched anything". This project forbids synthetic data
absolutely. Those fields are now `Optional` and `None` on every unavailable path, each response
carries an `unavailable_reason`, and `MarketSummaryResponse` gained the `available` flag it never
had. 33 tests, 10 mutations each proven red — **plus four mirror tests pinning the AVAILABLE path**,
so "null everything" cannot pass either. Also established by probing the vendor: the client POSTs
to `https://supplymaven.com/api/v1/tools`, which **404s with or without a token**, so it has never
once succeeded and adding a key would change nothing. Repointing it at the documented MCP endpoint
is unverified work and was deliberately NOT attempted.

**50. `/frontier` rendered a retired vintage.** `DONE`. `FrontierPage.tsx` hard-coded
"330 converged / 57 did not" and a primary-arm worst gap of "0.082%"; the artifact says **349 / 38**
and **0.000%**. Pinned by nothing. Corrected against `docs/cvar_frontier.json`.

**51. `docs/cvar_frontier.json` was stale — the third recurrence.** `DONE`. Commit `6a33ad0` moved
`sourcing.py`; `volume_sweep.json` was regenerated for it and this one was not. It published
`first_stage_cost_usd: 181919.39` / 5 suppliers where the optimizer returns `181908.01` / 6 — the
same cell that moved in the volume sweep — and the doc showed a reader **$183,171**. It also
presented the shipped MILP beside the mean-value EEV baseline as if they were different plans; they
are the same plan. `test_cvar_doc_matches_artifact.py` was green throughout, because it compares
the doc to the artifact and both were stale together. Fixed by a real 1,331 s regeneration; exactly
10 fields moved, all inside the ×10,000 baselines. **Caught by the new artifact-vs-code pin on the
day it was written.**

**52. Solve-quality figures were published as findings.** `DONE`. The CVaR breadth arm runs CP-SAT
on a 15 s budget with 46/150 solves hitting it, and two full regenerations disagreed: 349→347
converged, p90 gap 3.787%→6.07%, `smart_meter` dropped from the table entirely; on a quiet machine
the counters returned but 16 gap values moved and two BOMs swapped a converged λ. **No plan and no
cost moved** — only the numbers describing the solve. Owner chose relabelling over raising the time
limit (which costs a 22-minute regeneration and would still be machine-dependent). Every
solve-quality figure is now labelled a one-machine run log, at heading weight and outside the
`GENERATED:` markers so `render_doc()` cannot wipe it. Costs, plans, supplier sets, CVaR values and
the frontier itself are deliberately **not** caveated — over-caveating real results is its own
dishonesty. The identical claim in `BENCHMARK_VOLUME_CURVE.md` ("all 296 returned OPTIMAL — none
hit the 5s limit") is caveated the same way.

**53. The UI gate could never finish.** `DONE`. `waitUntil:'networkidle'` was **unsatisfiable** on
two routes — `/frontier` holds `stochastic/frontier` open, `/newsvendor` fired the 260 s solver —
so the gate threw FATAL rather than FAIL, at a different route each run. Navigation and readiness
are now decoupled: `domcontentloaded` + `#root > *`, then a bounded, *reported* readiness wait
(no first-party request in flight, no `.animate-spin`, held 500 ms, per-route caps sized from
measurement). Bounded retry around **navigation only** — never around an assertion. Third-party
basemap tiles excluded and the ignored hosts printed. **Nothing was weakened and it is checkable:**
the diff removes 8 lines, all navigation plumbing; `git diff | grep -c "^-.*ok("` returns **0**; no
threshold and no route×viewport matrix entry changed; 41 assertions were ADDED. Result:
**239 passed, 0 failed**. Proven still red four ways — hung endpoint, nonexistent route, absent
element, unreachable BASE. The `/newsvendor` settle cap was 300 s for the old recompute; now 30 s,
so a regression back to recomputing fails instead of hiding inside a five-minute budget.

**54. The two demand-series artifacts now have CI pins — but only their DETERMINISTIC arms.** `DONE`.

The first attempt promoted the WHOLE forecast pin and the WHOLE chronos classical-arms pin into
CI's default suite. Both passed locally and **both went red on CI** (run `33318131193`, commit
`16d3714`): 135 differing values in `forecast_backtest.json`, 61 in `chronos_benchmark.json`. Every
one of the 160 was a `prophet.*` key and none was a `seasonal_naive.*` key — at ~0.2–0.3 %
relative (`prophet.overall.wape` 0.0313 vs 0.0312, `prophet.overall.rmse` 1413.3469 vs 1410.4055).
**The artifacts were current; the pin's scope was wrong**, and its message ("The ARTIFACT is stale,
not this test") was flatly false — a check that misdiagnoses is its own defect.

The arms are now split by **determinism, not by cost**:

| Arm | Runs in CI (`-m "not slow"`) | Why |
|---|---|---|
| `seasonal_naive` (both artifacts) | **yes** — 0.01 s / <0.01 s | No arithmetic of its own: it copies observations out of a SHA-256-pinned series, and every metric is `round(x, 4)`-ed before it is written |
| `prophet`, `prophet_served_config` | no — `slow`, local-only, ~0.5 s | Prophet fits via Stan (L-BFGS): **not bit-reproducible** across platform / interpreter / BLAS |
| `chronos` zero-shot | no — `slow` | torch + chronos-forecasting live in `requirements-ml.txt`, which CI never installs, so this arm was never compared on a second platform at all. Its determinism is **unproven**, not disproven — and an arm whose determinism cannot be shown is left `slow`, the safe side |
| `cvar_frontier` | no — `slow` | Opens a seeded `SessionLocal` CI does not have; ~43 s |
| `leakage_progression` | no — `slow` | ~5 s, reads `PANEL_PATH` directly (no DB) — a judgement call, not a hard constraint |

**KNOWN CONSTRAINT — Prophet cannot be pinned on CI.** The committed artifacts are generated on one
machine (macOS/arm64, Python 3.13); CI is Linux/x86_64, Python 3.11. Stan's optimiser gives
platform-dependent results and no seed or flag changes that. The two honest options were (a) run
the Prophet pin only where the artifact is written, or (b) widen the tolerance until a
non-deterministic fit passes anywhere — and (b) is a check that cannot reliably fail, which
`LEARNINGS.md` (2026-08-28) forbids. **(a) was taken: both halves keep the same strict
`STAT_ABS_TOL`/`STAT_REL_TOL` of 1e-9.** The local standing gate (`pytest tests/ -q`, no `-m`
filter) still runs the Prophet pins on every push, on the only machine where those artifacts can
actually go stale. `slow` in this block means LOCAL-ONLY, not expensive.

**Evidence the classification is measured, not assumed.** Both artifacts' arms were re-scored
inside a `linux/amd64` container on CI's exact stack (Python 3.11.16, numpy 2.4.4, pandas 2.3.3,
prophet 1.3.0) under literal `!=` equality: `seasonal_naive` **0** differing leaves in both;
`prophet` 61 + `prophet_served_config` 74 = **135**, and chronos `prophet` **61** — reproducing
CI's failure counts exactly.

**Proven red.** `SEASONAL_PERIOD` 12→11 in `seeds/run_forecast_backtest.py:77` (a constant the
chronos generator imports rather than restates, so it moves both) fails the forecast pin with 69
differing values and the chronos pin with 61, while both Prophet pins stay green. Generator then
restored and confirmed byte-identical by sha256. The Prophet pins were separately shown red on
genuine drift (`weekly_seasonality` True) with the new, non-misdiagnosing message.

**Failure messages now match what a mismatch can mean.** A deterministic-arm mismatch still says
the artifact is stale, and says why that inference is safe. A Prophet-arm mismatch says
`THIS IS NOT NECESSARILY A STALE ARTIFACT` and walks the reader through ruling out platform
non-reproducibility first — OS/arch, interpreter, BLAS build, prophet/cmdstanpy/numpy/pandas
versions — then points at the deterministic pin as the test that actually answers "is it stale",
and only then at regeneration.

**Not pinnable, honestly:** `docs/backend_verification.json` has no generator — it is a hand-run
snapshot from the 2026-08-19 repair, and its content is 42 live HTTPS responses with a per-check
`seconds` field, so a pin would go red on a Render cold start and green on a broken build. Recorded
in the test file's docstring rather than faked.

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
| 13 | CVaR-95 under stress **saturates at a 1.15 ceiling** on 8 of 9 BOMs (`1 + (4/4)·0.15`), so the metric is structurally incapable of discriminating in the scenario designed to create saturation. The probability that *would* discriminate (`n_scenarios_with_shortfall / n`) is computed and never persisted. | `graph/simulation.py`, `models/optimization_run.py`, `migrations/0009`, `seeds/run_benchmark.py`, `api/benchmark.py`, `BenchmarkPage.tsx` | **DONE** — `p_shortfall` / `p_total_shortfall` / `cvar_95_ceiling` / `cvar_95_saturated` computed, **persisted** (migration 0009 → `mc_*` columns), **served** (`/benchmark/summary` saturation block + `p_total_shortfall_intervals`) and **shown** (the `/benchmark` CVaR tiles flag a ceiling tie and name the tied BOMs). **16/18 published rows are at the ceiling; 10/18 are bit-identical ties; `p_total_shortfall` breaks 8 of 10.** Proved re-basing CVaR would not help (exact affine map, 0/36 deviate) with a test to stop it being tried. Also corrected `CVAR_EFFICIENT_FRONTIER.md`, which claimed this was fixed on 2026-08-16. |

| 21 | **The test suite cannot be run concurrently.** Fixtures build a fixed-name `backend/test_hardening.db`, so two pytest processes clobber each other's data — observed live on 2026-08-28: a targeted run returned `component_id 5 not found` / `404` on 5 stochastic tests purely because a sibling process was mid-fixture. `LEARNINGS.md` warns "never kill pytest mid-flight — it poisons test_hardening.db" but the fixed filename is the actual defect. Give the DB a per-process unique name (PID or `tmp_path_factory`), which also makes `pytest -n auto` possible and would cut the 10-minute suite substantially. **Discovered by the loop, 2026-08-28.** | `backend/tests/conftest.py` | **DONE** — per-process name + session teardown; proved with 3 concurrent runs (24+34+45 passing) |

| 22 | **Nav overflowed at 1280px — the third recurrence of this defect.** Adding a tenth link (`/newsvendor`) pushed the desktop row to **1371px** while it collapsed to a hamburger only *below* Tailwind's `xl` (1280px), so at exactly 1280 the full nav rendered into a bar 91px too narrow. The agent that added the link measured at 1440, where it fits, and concluded it was safe. **The gate would have missed it too** — it tested 390/768/1440, and the bug lived in the gap between a breakpoint and the width the content needs. **Discovered by the loop, 2026-08-28.** | `NavBar.tsx`, `gate.js` | **DONE** — breakpoint moved to a measured `min-[1400px]`; verified collapsing at 1399 and fitting at 1440/1536; **1280 added as a fourth gate viewport** |

## P0 — found 2026-08-28 by the post-sweep verification pass

| # | Item | Where | Status |
|---|---|---|---|
| 23 | **The resilience summary published a claim its own adjacent field refuted.** `/benchmark/summary` served "the graph-aware arm **lowered** both plan cascade risk and the CVaR-95 tail" while returning `stress_cascade_risk_reduction = -0.0833` — the arm had **raised** it — and `intervals.stress_cascade_risk_reduction.significant = False` in the same response object. The branch tested only whether a reduction was *exactly* `0.0` and never looked at sign, so every negative value fell through to a hardcoded "lowered". At HEAD, on public Swagger, in the endpoint the honesty sweep had just rewritten. | `api/benchmark.py` | **DONE** — interpretation is now COMPOSED from `reductions` + `intervals`, moved after the bootstrap so it can consult significance; names wrong-way metrics as WRONG WAY and marks any interval covering zero "not quotable as a result". 9 tests, all verified RED against the old code. |
| 24 | **Public Swagger advertised a retired series count.** `api/newsvendor.py:11,422` said "2,643 held-out series"; the endpoint returns **2,646**. Item 16 built a doc-vs-artifact gate for `RESEARCH_TECHNIQUES.md` §3.4 but nothing guarded the docstrings, which are the copy a reader meets first. | `api/newsvendor.py` | **DONE** — corrected, plus 2 guards reading `docs/newsvendor.json`; verified RED on the stale number. |
| 25 | **Three docs quoted a retired leakage vintage with no caveat**, including the guide read before interviews. Old 810-row / 27-manufacturer / `random_forest` figures (R² +0.638→+0.082→−0.550) against a deployed artifact of 1,879 rows / 28 manufacturers / 472 families, champion **`gradient_boosting`** (`metrics.joblib['best_lead_time_model']`). | `RESILIENCE_INTERVIEW_GUIDE.md`, `PROJECT_OVERVIEW.md`, `RESEARCH_TECHNIQUES.md` | **DONE** — all figures traced to `leakage_progression.json` / `metrics.joblib` and corrected; the retired vintage is kept, dated and labelled as superseded. |
| 26 | **`/ml` labelled a GSCPI regime probability "Semiconductor shortage stress".** The served signal is `RegimeModel.stress_proba` = P(GSCPI z > band-hi), a general pressure regime; the semiconductor-specific `compute_stress_label` is marked legacy and is not wired to it. | `api/ml.py:441` | **DONE** — relabelled "Global supply-chain pressure (NY Fed GSCPI regime)". |
| 27 | **A served caveat no reader could see.** `docs/diversification_frontier.json` carries "these figures reproduce against the pre-fix solver only"; `benchmark.py` passed `caveats` through and `BenchmarkPage.tsx` rendered only 5 hand-picked fields, dropping 3 including that one. | `BenchmarkPage.tsx` | **DONE** — the full served caveat array is rendered. |
| 28 | **The frontier generator would have reintroduced a retired claim.** The artifact was hand-corrected after the `to_obj_units()` fix; `run_diversification_sweep.py` still held the present-tense "quantises unit prices to whole cents" text, so regenerating would undo the correction. | `seeds/run_diversification_sweep.py` | **DONE** — generator's 8 caveats now match the artifact byte-for-byte. |
| 29 | **Two tests could only ever fail on CI.** `test_cvar_saturation.py` compared an accumulated float mean to the closed-form `1.15` ceiling with `==`; exact locally, `1.149999999999999` on CI. Broke the build and blocked the deploy of `1536742`. Production was never affected — `simulation.py:327` already uses `>= ceiling - 1e-9`. | `tests/test_cvar_saturation.py` | **DONE** — the arm-vs-arm tie stays exact (that is the claim); the ceiling comparison uses the same `1e-9` the served flag uses. |
| 30 | **`graph_aware` / `us_only` never reached the live optimizer** — `api.ts` posted no body, so the page always ran both flags off. **Owner approved wiring, 2026-08-28.** | `api.ts`, `CheckoutPage.tsx` | **DONE** — two toggles, both defaulting off so the standard view is unchanged. Honest labels: `us_only` moves only Lowest Cost (3 of 4 strategies are already domestic-only), and `graph_aware` returns an identical plan on the demo cart, which the page states rather than hides. 7 solver-level tests + a gate interaction check. |

| 31 | **The CI caveat was set in smaller type than the claim it qualifies** — 11px prose against the significant branch's 12px, on `/benchmark`. The gate's rule is that sub-12px BODY text is the anti-pattern, and this text is prose, not a caption. **It could not be caught before the deploy:** the gate proxies API calls to the LIVE API, and the old deployed API returned no `intervals`, so the element never rendered and the check passed vacuously. A local build is only as good as the API it is pointed at. | `BenchmarkPage.tsx:402` | **DONE** — `text-xs`, matching its sibling branch; live gate 138/138. |

| 32 | **`/frontier` printed the literal string `undefined` to the reader** — "4 suppliers [9, 70, 81, 85] instead of the risk-neutral **undefined**". `${riskNeutral?.n_suppliers}` in a template literal renders the STRING when optional chaining short-circuits. Root cause was deeper than the interpolation: the backend measures `cvar_reduction_*` against the cheapest **non-dominated solved** point, not λ=0, so λ=0 was never the right denominator to name — and on a partial sweep it is absent entirely. | `FrontierPage.tsx:363-384,660-679` | **DONE** — the page now derives the baseline the same way the server does and names it, with a footnote when λ=0 is not on the frontier. |
| 33 | **No gate check looked at rendered WORDS.** 10 routes × 4 viewports of green said nothing about item 32, which was live in production. | `ui-gate.cjs` | **DONE** — a leaked-placeholder check (`undefined`/`NaN`/`null`/`[object Object]` in own text nodes, word-bounded) at every route and viewport. Verified RED against the real unfixed build: 4 failures, one per viewport. |
| 34 | **`fmtUsd` dropped cents and sign site-wide** — `$643.1` in a column of `$368.34`. No `minimumFractionDigits`, and `Math.abs` discarded the sign. | `BenchmarkPage.tsx:432-449` | **DONE** — all 21 call sites audited so restoring the sign does not double up. |
| 35 | **A chart's x-axis label sat on top of its own legend** at all four viewports (286×15px of overlap). Margin could not fix it: the label is positioned off the axis and recharts stacks the legend off the same axis, so they move together. | `BenchmarkPage.tsx:1792-1805` | **DONE** — legend moved above the plot. Gate now measures label-vs-legend-ITEM boxes at every viewport; verified RED. |
| 36 | **Chart legend contrast below AA** — measured against the real composited background, 3.34:1 and 3.55:1 against a 4.5:1 requirement. axe reports these "incomplete", not violations, so it never surfaced. | `BenchmarkPage.tsx:294-298` | **DONE** — 10.7:1 and 5.3:1, differing in lightness not only hue, plus a P10/P50/P90 text table so nothing depends on telling two colours apart. Gate check added, resolving colours through a canvas rather than parsing (the `oklch()` trap). |
| 37 | **Markdown backticks rendered literally** — 24 on screen in the caveat list. The split must be NESTED, not alternated: two caveats open with a bold title whose first word is itself a code span. | `BenchmarkPage.tsx:470-503` | **DONE** |
| 38 | **`frontier.verdict` was served but never rendered**, beneath a footer claiming "nothing on this page is a hardcoded copy of it". The text matched, so nothing on screen was false — but the claim about itself was. | `BenchmarkPage.tsx:508-539,1715` | **DONE** — the served string is rendered; the footer claim is now true. |
| 39 | **A cost-multiplier delta described as "percentage points"** — the tile said `-0.0309× change in cost multiplier`, the prose beside it said "3.09 pp of CVaR-95". | `BenchmarkPage.tsx:1563-1572` | **DONE** |
| 40 | **Volume-curve axis label clipped at 390** — ran to x=441 in a 390px viewport with no genuinely scrollable ancestor (the wrapper had `overflow-x: auto` but `scrollWidth === clientWidth`, so a naive ancestor check called it clean). | `VolumeDecayCurve.tsx:99-115` | **DONE** — the Price-of-Resilience scroll pattern. |


## P2 — surface work that is already built and invisible

| # | Item | Status |
|---|---|---|
| 14 | **Newsvendor has no UI.** | **DONE** — `/newsvendor` route: decision (τ, q*, quantile ladder, naive rules), evidence (CIs drawn as intervals against a zero rule, not colour alone), and the MASE-vs-decision-cost argument as its own section. Every figure read live, nothing hardcoded from docs. |
| 15 | **Price-of-resilience frontier has no UI.** "The second supplier removes 0.44 of targeted cascade risk for $58.88 (CI 0.22–0.67); the third costs 6.8× more and its CI covers zero." Exists only in `docs/DIVERSIFICATION_FRONTIER.md`. | **DONE** — `GET /benchmark/diversification-frontier` + a "Price of Resilience" section on /benchmark: chart with unit-labelled axes and dash-patterned series (nothing by colour alone), two tables with CI bars on one shared zero-containing domain, and the headline sentence COMPOSED BACKEND-SIDE from the fields it quotes — it returns empty if the first step covers zero. 23 tests. |
| 16 | No `seeds/run_newsvendor.py` + doc-match test, so the published newsvendor numbers are **not auto-checked** like every other artifact. **Now urgent and proven:** §3.4 says 2,643 series / 47,574 decisions; the live API returns **2,646 / 47,628** because the `_size_shape` Poisson-limit clamp (fixed 2026-08-28) means 3 previously-dropped series now survive. The doc drifted within a day of being written. | **DONE** — `seeds/run_newsvendor.py` + `docs/newsvendor.json` + a 17-test doc-vs-ARTIFACT match (never doc-vs-doc). Confirmed the drift independently and rewrote §3.4: the defect paragraph claimed the `_size_shape` fix "has not been made" when it landed in the same commit. |

## P3 — hygiene

| # | Item | Status |
|---|---|---|
| 17 | `MAINTENANCE-AND-KNOWN-ISSUES.md` carried two deferrals that were no longer true, one of which told a future reader NOT to re-run the benchmark — the exact fix that was needed. | **DONE** — both retired to a new "Resolved — do not re-open" section with what actually happened; the doc now points at this backlog as the live list |
| 18 | `serving.py` docstring said the regime artifacts are not git-tracked and absent in prod. They **are** tracked (`.gitignore` un-ignores both with `!`) and **are** what prod serves. | **DONE** |
| 19 | `stress_level` cutoffs were bare literals with no constant or comment, so "why those numbers?" had no answer. | **DONE** — named constants, documented as a display convention (the optimizer reads the probability, never the label), grounded against a measured base rate of **0.1681** (57/339 months): HIGH ≈ 4.2× base rate, MODERATE ≈ 2.1× |
| 20 | `api/stochastic.py` published a retired defect in the PRESENT tense on the public Swagger surface, telling readers a fixed bug was still live. | **DONE** — moved to past tense, kept as "what it replaced" |

## Owner decisions — not mine to take

- ~~`graph_aware` / `us_only` never sent by the live optimizer~~ — **RESOLVED 2026-08-28**, owner approved; see item 30. Both are now toggles on `/optimize`, defaulting off.
- Render Starter ($7/mo) to kill the 50–120 s cold start. **Owner said leave it on free, 2026-08-28.**
- ~~FRED write-on-read into a tracked CSV (~2 h).~~ **RESOLVED 2026-08-29** — this entry was
  stale: item 4 above records the same defect as VERIFIED LIVE, then FIXED, and the code agrees
  (`refresh_cache: bool = False` by default in `app/ml/fred_client.py` and `app/ml/regime_model.py`;
  only `seeds/train_ml_models.py:46` passes `True`). The document was listing it as both fixed and
  pending at the same time.
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
4. **Frontend.** `cd frontend && npx tsc -b --force && npm run build` both clean.
   **NOT `tsc --noEmit`** — item 41 above proves that invocation typechecks nothing and exits 0
   on any error. This criterion prescribed it until 2026-08-30.
5. **Browser gate against the LIVE site**, not a local build:
   `cd frontend && BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate`
   → **188 passed, 0 failed** across the 10 routes in `scripts/ui-gate.cjs` x 4 viewports
   (1440/1280/768/390), plus head/meta checks on `/login`. Covers overflow, emoji, type
   size, leaked placeholders in rendered words, clipped chart labels, chart geometry,
   legend overlap and contrast, touch targets, axe serious/critical, head tags, console errors.
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

- `cd backend && ./venv/bin/python -m pytest tests/ -q` → expect **0 failures except** the one
  documented local-only MLflow identity check (`test_the_served_estimator_is_the_one_the_metrics_describe`),
  which is green in CI. An absolute pass count is deliberately not written here: it was stated as
  **997** while the suite actually collected **1,121** (2026-08-30), and it moves with every test added.
  The gate is "nothing red but that one", not a number.
- `./venv/bin/ruff check app` and `./venv/bin/mypy app` clean.
- `cd frontend && npx tsc -b --force && npm run build`. **Never `tsc --noEmit`** — see item 41.
- Browser gate: `cd frontend && npm run ui-gate` over **10 routes × 4 viewports** → **188 passed, 0 failed**.
  (The routes array in `frontend/scripts/ui-gate.cjs:66` holds 10 entries; `/login` is additionally
  checked for head/meta. "11 routes" written elsewhere is wrong — 188 is a check count, not routes×viewports.)
  The gate proxies API calls to the LIVE API, so a check can pass vacuously when the deployed
  API does not yet return the data the element needs. A green local gate is only as good as the
  API it is pointed at.
- `git status --porcelain backend/seeds/data/` empty — never let a seed CSV drift.
