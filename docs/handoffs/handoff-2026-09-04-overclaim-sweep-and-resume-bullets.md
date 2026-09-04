# Handoff — 2026-09-04 — overclaim sweep, and the résumé bullets that came out of it

## TL;DR

`56f439e` is **live and verified** on both Render services; tree clean, in sync with origin.
An audit found **eleven published claims the code contradicted** — all closed, and every
number moved **down**, not up. The headline benchmark is now **18.79%**, not 47.25%.
Suite 1173 passed; **UI gate 239/239 against the deployed site**.
Next action: re-capture `docs/screenshots/optimize-four-strategies.png` (it still shows
pre-fix carbon numbers under a caption claiming every figure came from a real API response).
Nothing is blocked on the owner.

## Goal

This repo is a job-search portfolio piece for OR / forecasting / supply-chain-DS roles.
The owner directs the work and is **not** an engineer. This session's arc was a question,
not a feature: *"what's incomplete or overcomplicated here, and is this too advanced for
the jobs I'm going for?"* — which turned into fixing what the audit found, and then into
producing résumé bullets whose every figure traces to a committed artifact.

**The verdict on the framing question** (worth not re-deriving): the project is *above*
the bar for those roles, and "too advanced" carries no real hiring risk. The actual risk
was a headline number an OR interviewer would dismantle in ten minutes. That is now gone.
AI-authorship is moot and undeniable — 158 commits are publicly stamped `Co-Authored-By:
Claude` and the Actions tab lists workflows named "Claude — Builder". Disclosure is the
only viable posture; every 2026 source checked says it is neutral-to-expected.

## State

Branch `main`, clean, `0 0` against origin. Five commits shipped today — read
`git log --oneline -6` for the list; the commit messages carry the full detail and are
deliberately long so this document does not have to repeat them.

Nothing is mid-edit. `git status --porcelain backend/seeds/data/` is empty.

## Verified vs assumed

**Verified against the live deployment** (not against a document, per the standing bar):
- Both services serve `56f439e` — `/version` + `/version.json` + local HEAD agree.
- `/api/v1/graph/metrics` returns 7,363 edges · 34 components · 847-node giant · λ₂ 0.2788,
  and `n_holdout_offer_rows` is **absent** (field removed).
- `/api/v1/benchmark/summary` returns `savings_pct_matched_pool: 18.79`, arm
  `greedy_add_dom`, `pool_asymmetry.matched: true`, all four baselines with pool
  descriptions.
- UI gate **239 passed, 0 failed** against `https://supply-chain-ui-bhwz.onrender.com`.

**Verified locally:**
- Full suite 1173 passed / 1 skipped. Both previously-standing failures are **gone**: the
  data-vintage tripwire cleared via retrain, and the MLflow identity check now passes for
  the right reason (see Dead ends).
- CVaR and leakage artifacts regenerated from a **clean tree**, both stamping
  `dirty: false`. Neither moved a number — that reproduction *is* the determinism proof.
- The re-armed quality gate was proven able to fail: a constant predictor was substituted
  and it fired at 9.1% vs the 10% floor, then the artifact was restored byte-identical.

**Assumed / NOT verified — treat with suspicion:**
- **The cold-start fix has never been measured on Render.** Import time 32–43s → 1.0s was
  measured locally only. Free-tier sleep still applies; a cold first request was measured
  at **80–90s** earlier today. Nobody has timed it post-deploy.
- **`docs/screenshots/optimize-four-strategies.png` is known-stale** — shows 1.5/0.8 kg
  where the corrected values are 1.65/0.936. A note was added marking it pre-fix, but the
  image itself is wrong and its caption claims otherwise.
- The **18.79%** figure comes from pipeline run 9 in the tracked DB. It reproduced a scratch
  prediction exactly, but has only ever been computed on these 9 BOMs.
- **`docs/RESILIENCE_INTERVIEW_GUIDE.md` scenario results** (DigiKey failure → 0 orphaned,
  risk 0.106; GPR 0.106 → 0.188) were computed on the **80% graph** and were not re-run.
  Orphan counts can only improve with more edges, so "0 orphaned" is directionally safe,
  but the risk scores lean on betweenness, which moved. **Owed a re-run before any demo.**
- Several `docs/` files were edited by concurrent agents and only their own sections were
  re-read. No full proofread of the docs tree happened.

## Dead ends — do not repeat these

1. **"The 47% gap is a shipping-policy artifact on the MILP side" is FALSE.** It was the
   leading hypothesis and it was tested and disproved: re-solving the MILP on greedy's full
   global pool gives **$3,315.07, identical to the cent**, same distributors on every BOM.
   The domestic restriction is **non-binding** — the optimizer declines international offers
   on its own because air freight doesn't pay back at these quantities. The real asymmetry
   was entirely on the *greedy* side, plus a weak baseline. Decomposition of the old 47.25:
   **10.15 pts** weaker heuristic + **18.31 pts** wider catalogue + **18.79 pts** optimizer.
2. **Fixing the tiny-text elements the UI gate *prints* does not work.** `ui-gate.cjs:456`
   asserts `tiny.length === 0` but prints `tiny.slice(0,4)`. Fixing the four shown leaves
   the count unchanged and four more appear. Cost one wasted 26-minute deploy. The rule is
   at `scripts/ui-gate.cjs:99`: fail below 11px outright, and below 12px when the element's
   own text exceeds 60 chars. **Read the rule, fix the class of problem.**
3. **Do not run the suite with `MLFLOW_SERVING=off DISABLE_MLFLOW=1`** as a convenience. It
   masks real failures *and* causes three different ones in `test_model_serving.py` that
   pass without it. It produced a misleading 10-failure run today.
4. **The MLflow champion alias could not be repointed without a retrain**, and an agent
   correctly refused to write a `training_data_sha256` no run had recorded — that would be
   doctoring the record to make a test pass. Current state is *intentional*: selection
   promotes nothing, startup refuses the mismatched champion, the correct 324-feature
   joblib serves, and `/ml/model-info` publishes `fallback_reason`. The owed retrain will
   restore a real champion.
5. **Background `Bash run_in_background` jobs were killed three times** in this session
   (UI gate twice, a CI watcher once), each time with little or no output. Long Playwright
   runs and long polls should use the **`Monitor` tool** or run in the **foreground**.

## Running & resumable

- **Playwright MCP Chrome is still alive**: PIDs `886`, `957` (npx/playwright-mcp) and
  `4303`+ (Chrome, `--user-data-dir=…/ms-playwright-mcp/mcp-chrome-22defb2`). Harmless but
  leaking memory; `kill 886 957` and the Chrome tree if the machine feels slow.
- No background jobs, agents, or workflow runs are outstanding. No scheduled task is
  imminent **except** the weekly lead-time collector cron (`collect-lead-times.yml`,
  Mondays 06:00 UTC) — the next snapshot will re-open the data-vintage tripwire and oblige
  another retrain + `run_leakage_progression` (~337s).
- `.playwright-mcp/` on disk is ~1.0 GB (gitignored).

## Next steps

1. **Re-capture `docs/screenshots/optimize-four-strategies.png`** from the live site. Its
   caption claims every figure is a real API response; it currently shows pre-fix carbon.
   Also `docs/archive/screenshots/README.md:10` repeats the stale `1.49 kg`.
2. **Re-run the resilience scenarios** in `docs/RESILIENCE_INTERVIEW_GUIDE.md` on the
   corrected graph (see Verified vs assumed) — this is interview material the owner studies.
3. **Split CI** so pushes stop costing ~26 minutes. Fast checks (ruff, mypy, `tsc -b`, unit
   tests) can gate the deploy in ~4 min with slow artifact-reproduction tests running
   separately. The owner explicitly asked for this. **Related gotcha worth keeping:** the UI
   gate runs against a local `vite preview` build (it defaults to `localhost:4173`), which
   verifies UI fixes in ~4 min instead of a deploy cycle. That is how 239/239 was confirmed
   before the last push.
4. **Decide whether the benchmark generators should load live ML state.** They run at
   `macro_stress = 0` while production serves `0.8284`. The artifacts agree today and still
   agreed after the risk-premium fix — but that is luck, not a guarantee, and the margin
   shrank. Owner decision.
5. Optional, flagged by the job-fit audit as the biggest gap for demand-planning roles:
   add **ADI/CV² classification** to the demand benchmark (~15 lines).

## Key context

- Read `CLAUDE.md` and `LEARNINGS.md` first — do **not** restate or edit them.
- Gates and the DB-churn ritual are in `CLAUDE.md`. `backend/supply_chain.db` is tracked
  and is what production serves; it now carries benchmark runs 8 and 9 (alembic `0009`,
  791/92/8,176, integrity ok).
- Two provenance decisions the owner made today, already implemented: the truck CO₂ factor
  (161.8 g) is relabelled to its true source — **2013 SmartWay technical documentation via
  EDF's 2014 handbook**, per *short* ton-mile — value kept; and the air factor is relabelled
  from ICAO to **GLEC v3.2**, with the range disclosed so the 4.51× air:truck ratio is
  stated as a lower bound.
- **The résumé bullets** (this session's other deliverable). Every figure verified today:

  > Formulated a two-stage stochastic sourcing program to minimize mean-CVaR under a
  > Rockafellar-Uryasev linearization, enumerating scenarios rather than SAA sampling across
  > **387** optimal CP-SAT solves — finding the point where one extra dollar removes **$4.27**
  > of worst-case cost.

  > Trained a macro regime classifier validated across **219** walk-forward folds (Brier
  > **0.393** vs. 0.539 persistence, 0.673 climatology), feeding its risk signal into a
  > CP-SAT sourcing MILP as a per-unit stock-out premium that shifts orders away from
  > thinly-stocked suppliers.

  > Benchmarked six intermittent-demand forecasters across **2,646** real spare-parts series
  > under both point and proper scoring rules — MASE ranked a degenerate all-zero forecast
  > **1st** (Friedman rank 1.66, p < 1e-300) while CRPS and pinball loss placed it **4th and
  > 5th**, with TSB winning both.

  **Gotcha: "349 CP-SAT solves" is wrong** and appears nowhere in the artifact — the real
  figure is **387** λ-solves (347 converged). The owner's older drafts carry 349.
  Also retired: the leakage bullet's old `+0.80 → −0.78 / 1,879 rows` (now **+0.83 → −0.70**,
  28 manufacturers, **2,615 rows**), and **never cite 47%**.

## Open questions

1. Should the benchmark generators run with live macro stress (next step 4)? — yes/no.
2. Keep the MASE bullet in slot 3, or swap for the ALFRED vintage-controlled backtest? The
   owner settled on MASE, having rejected two earlier candidates for reading as
   "correcting my own errors". Worth honouring that preference in any future rewrite.
