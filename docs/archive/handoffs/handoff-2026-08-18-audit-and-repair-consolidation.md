# Handoff — Full Audit & Repair Consolidation

> **SUPERSEDED by `handoff-2026-08-19-production-repair-and-verification.md` (2026-08-19)** — read that file instead; this one is kept
> for history.


**Date:** 2026-08-18 · **Branch:** `main` · **Ahead of origin:** 25 commits · **Behind:** 1

---

## TL;DR

`main` is 25 commits ahead of `origin/main` and **has never been pushed**. Everything is
verified green (689 tests, 47/47 model-CI gates, ruff + mypy clean, frontend builds). A
three-day audit-and-repair arc found and fixed ~40 real defects across ML, API, frontend,
data and CI. **Next action: push** — the deployed site currently serves *no ML at all* (503s)
while the README claims it, and the weekly collector already ran once against stale remote
code. **Blocked on the user:** approval to push (it triggers a Render deploy).

---

## Goal

Make this repo a resume-grade portfolio project for **ML/Data-Science** and **big-tech ops
(Amazon SCOT / Apple Ops)** roles. Owner is job-hunting. The governing principle, set by the
owner on 2026-08-15 after a course correction:

> **Fixing means making it work.** Not deleting the feature and documenting that it doesn't.
> Honesty is satisfied by making claims TRUE, not by lowering claims until the broken thing
> is technically disclosed.

Strategy doc: `docs/archive/ML_API_PUSH_PLAN.md` (rewritten 2026-08-16 around the "decision spine").
Interview/resume reference: `docs/PROJECT_OVERVIEW.md`.

---

## Repo state

**Branch `main`**, ahead 25 / behind 1. No open PRs (`gh pr list --state open` → empty).

The 1 behind is `f6012ba` `chore(loop): update metrics dashboard` — a bot commit from the
autonomous Loop system. Harmless; it only touches `LOOP-DASHBOARD.md` and
`metrics/loop-metrics.json`. Take the remote's version on merge.

### Uncommitted files — ALL are screenshots, all safe to commit

| File | Disposition |
|---|---|
| `docs/screenshots/current/02-dashboard.png` (M) | commit — recaptured |
| `docs/screenshots/current/05b-cart-live-pricing.png` (M) | commit — recaptured |
| `docs/screenshots/current/09a-map-routes.png` (??) | commit |
| `docs/screenshots/current/09b-map-network-risk.png` (??) | commit |
| `docs/screenshots/current/10-model-card.png` (??) | commit |
| `docs/screenshots/current/11a-unknown-route-redirect.png` (??) | commit |
| `docs/screenshots/current/11b-error-state-components.png` (??) | commit |
| `docs/screenshots/current/12a-mobile-dashboard.png` (??) | commit |
| `docs/screenshots/current/12b-mobile-checkout.png` (??) | commit |
| `docs/screenshots/current/12c-mobile-resilience.png` (??) | commit |
| `docs/screenshots/current/_console_errors.json` (??) | commit — audit evidence |
| `docs/screenshots/current/_problems.json` (??) | commit — audit evidence |

`.claude/agent-memory/**` also shows dirty. **Deliberately left uncommitted** — it is agent
tooling state, and we are trying to reduce AI-tooling noise in this repo, not add to it.

**This handoff file is NOT committed.** Commit it if you want it on the remote.

---

## Done so far — the 25 commits

Newest first. Each commit message contains the full detail; this is the index.

| Commit | What |
|---|---|
| `82d7e83` | Third lead-time snapshot merged; the ST extension held |
| `3958e87` | Merge: union the cron's 2026-08-17 snapshot with the local panel rewrite |
| `449db34` | Real-time backtest — score on data that existed at the forecast origin |
| `5b0fd9b` | Close the model-CI gate holes a mutation audit proved could not fail |
| `62fd5ed` | API endpoints that returned 200 with structurally empty data |
| `42104c2` | Stochastic frontier blamed the user for our own solver budget |
| `241ae9e` | Frontend demo-breakers; Benchmark page now leads with the retraction |
| `2f0f415` | Remove dependencies that were never imported |
| `62dd0f4` | `docs/PROJECT_OVERVIEW.md` — interview/resume reference |
| `7b8500d` | Replace fabricated per-part forecasts with a scored method benchmark |
| `78f7a6d` | Rewrite the plan around the decision spine |
| `615a55a` | Persist the technique research as an actionable backlog |
| `95f1b77` | Measure the leakage progression instead of quoting it from memory |
| `e6250bc` | Model CI: gate the build on failures that actually shipped |
| `b4486fb` | Give the orphaned integrations real consumers |
| `1bf2909` | Cut stale/misleading docs; audits retained as dated history |
| `da2d6cc` | Require repo-write permission before the `@claude` workflow runs |
| `19a9a6e` | Activate dormant APIs in production; stop claiming unwired ones |
| `c2e7e9d` | Two-stage stochastic program with CVaR objective + efficient frontier |
| `32a091d` | The served lead-time model was a constant; regime signal a frozen scalar |
| `888c0a8` | Collect the full DigiKey catalogue — panel 75 → 817 rows |

### The headline results (all reproducible from a committed script)

- **Lead-time panel: 75 → 1,180 rows**, three snapshot dates (75 / 742 / 363), 56 columns.
  748 distinct MPNs; 282 in two snapshots; 75 in all three.
- **Leakage progression** (`python -m seeds.run_leakage_progression`):
  R² **+0.638** random split → **+0.082** grouped by part family → **−0.550** holding out
  whole manufacturers. 810 rows / 467 grouping keys / 360 `base_product` / **27 manufacturers**.
  Effective sample size for generalisation is the manufacturer count, not the row count.
- **Real-time backtest** (`docs/CHRONOS_BENCHMARK.md`): scoring on revised data flatters every
  model by ~20% (Prophet 24.2%, Chronos 19.5%, naive 18.2%). **No winner declared** — the
  protocol effect on Prophet (0.0100) is *twice* the Prophet–Chronos gap (0.0049).
- **Intermittent demand** (`docs/INTERMITTENT_DEMAND.md`): across 2,646 Monash series, **MASE
  ranks the degenerate `zero` forecast FIRST** (Friedman rank 1.66); under CRPS it falls to
  4th, under pinball loss 5th. Kendall τ(MASE, pinball) = **−0.20**, anti-correlated.
  Friedman p < 1e-300, Nemenyi CD 0.1466.
- **CVaR frontier** (`docs/cvar_frontier.json`, full non-quick run): knee at λ=0.30,
  **$4.266 of tail risk removed per $1 of expected cost at 60,000 units**. `knee = null` at
  100× and 1,000× — the frontier is genuinely flat there. **This now reproduces from the live
  endpoint**, not just the offline script.
- **ST lead-time event**: 56 STMicroelectronics parts quoted exactly 30 wk in July, re-quoted
  to 52 wk (42 parts) / 40 wk (14 parts) in August, and **all 56 held those figures on
  2026-08-17**. A durable state change observed at three points in time.

### Work done outside this session (NOT verified here)

- The autonomous **Loop** system (installed 2026-07-27) commits `chore(loop): update metrics
  dashboard` daily via `github-actions[bot]`. **30 of 248 commits.** It has *never* touched
  product code — verified. Its dashboard claims "Healthy / 100% merge rate" computed from 2
  self-install PRs. Scout: **252/252 runs failed**; Builder: **491/491 no-ops**.
- `claude-mention.yml` had a real security hole (any GitHub user could trigger a privileged
  agent). **Patched in `da2d6cc`** — now requires admin/maintain, matching `claude-redraft.yml`.
- The weekly collector cron fired 2026-08-17 07:04 UTC, ran 10m21s, collected 363 real rows —
  the first successful run ever. It used the OLD July collector code (9-column schema).

---

## Current state

### Working / verified (as of the last full run)

```
689 passed, 1 deselected          # pytest -m "not slow"
47 passed                          # MODEL_CI_STRICT=1 pytest -m model_ci
All checks passed!                 # ruff check app
Success: no issues found in 75 source files   # mypy app
tsc --noEmit clean, npm run build succeeds
```

- Lead-time model serves real varying predictions, **94.4%** coverage (was a constant, then 7%).
- Regime model ships on a Brier gate + calibration slope 0.625; live stress prob ~93.5%.
- `/stochastic/frontier` solves (was 422 on 6/7 BOMs).
- All 9 previously-orphaned endpoints have UI consumers.
- Migrations work from empty, from the committed DB, re-run, after `create_all`, and downgrade.
- Migration 0008 **applied** — the tracked DB no longer ships 50,624 fabricated demand rows
  (10.6 MB → 2.3 MB).

### Known-broken / open

1. **The deployed site has NO ML** — `/ml/*` returns 503, `model_source: "none"`. Every ML
   claim in the README is currently unbacked on the live URL. **Fixed by pushing.**
2. **Benchmark page shows a false badge** — "HOLDOUT · SEED 42" top-right, but
   `seeds/run_benchmark.py:33-34` says explicitly *"the benchmark IS the holdout evaluation…
   no holdout filter is applied."* Also displays a stale **"run 4 — Jul 6, 2026"** (a fresh
   run gives −47.25%, not −44.66%).
3. **Model Card blemishes** — `VERSION —` and `SHORTAGE RECALL —` render as bare em dashes
   (empty tiles read as missing data); the 6 feature-exclusion reasons are **truncated
   mid-sentence** with `...`, cutting off the most interesting text on the page.
4. **Test suite shares one SQLite file** (`backend/test_hardening.db`). Concurrent pytest runs
   corrupt each other, producing a *drifting* set of 6–11 phantom failures. **Not a product
   bug.** Delete the file and re-run serially. A per-worker DB or `drop_all` before
   `create_all` would fix it permanently.
5. **Alembic is still decorative.** The chain now *works*, but migrations 0001–0003 build the
   pre-pivot schema (`materials`, `suppliers`, `production_hubs`); every table the product uses
   comes from `create_all()`. Recommended: squash 0001–0003 into a real `Base.metadata`
   baseline, drop `create_all()` from `main.py`, `alembic stamp` the Render DB. **Needs owner
   approval** — not done silently.
6. `frontend/src/services/api.ts:75` still exports `optimizeAPI.scenario`, pointing at the
   `/optimize/scenario` endpoint that was deleted.
7. `README.md:22` still headlines "Monte Carlo simulation (1,000 scenarios)" without noting the
   delay parameters are assumed (`calibrated: false`), not fitted.
8. `docs/MODEL_CI.md` doesn't yet describe gates 7–10 (documented in
   `tests/test_model_ci_gates.py`'s module docstring, ready to lift across).
9. **README hero image** is `docs/screenshots/sc-dashboard.png` from **June 9** — two months
   stale, predates the model card, demand panel and benchmark retraction. Replace with one of
   `docs/screenshots/current/`.

---

## Running & resumable

**Kill these — leftovers from dead agents, running ~1d 16h:**

```bash
kill 99446        # uvicorn app.main:app  (project backend)
kill 99584 99603  # vite --port 5183      (project frontend)
rm -f backend/test_hardening.db   # stale shared test DB, 176KB, causes phantom failures
```

(PID 753 on :8880 is `kokoro-fastapi` — **another project**, leave it. Docker Desktop was
started by an agent on 2026-08-15 for a Redis container used in verification; that container
has exited. Quitting Docker Desktop is safe.)

**No resumable workflow run IDs** — no `Workflow` tool runs this arc; all work was via subagents.

**Scheduled / automatic:**
- `.github/workflows/collect-lead-times.yml` — Mondays 06:00 UTC. Next fire: **2026-08-24**.
  If unpushed by then it repeats the stale-code problem.
- `.github/workflows/loop-metrics.yml` — daily 11:00 UTC, commits the metrics dashboard to main.
- `.github/workflows/deploy-render.yml` — on push to main, triggers both Render deploys.

**Credentials that exist and work** (in gitignored `backend/.env`): DigiKey (also in GitHub
Actions secrets + Render), Nexar, OEMsecrets, EasyPost, RENDER_API_KEY.
**Absent / empty:** Mouser, ACLED, SupplyMaven, TrustedParts, FRED key (keyless path works).

⚠️ **Security note:** during Render env-var work on 2026-08-15 an agent briefly printed key
values in cleartext into its own local transcript. Not in the repo, not pushed. Owner was told;
rotation of DigiKey/Nexar keys is **still an open decision**.

---

## Next steps (ordered)

1. **Push.** `git push origin main` (25 commits). Triggers a Render deploy and the first real
   `model-ci` workflow run. This is the single highest-value action: it fixes the live 503s and
   stops next Monday's cron repeating the stale-code merge. **Needs owner approval.**
2. **Verify the deploy** — `./launch` per the `launch` skill (never hand over a localhost URL).
   Smoke-test `/api/v1/ml/model-info` returns a real `model_source`, and `/api/v1/demand/benchmark`.
3. **Fix the three cosmetic-but-credibility items** (~30 min total): the false "HOLDOUT · SEED 42"
   badge, the stale Jul-6 benchmark run, and the Model Card's two empty tiles + truncated
   exclusion text.
4. **Build the newsvendor link** — `docs/archive/ML_API_PUSH_PLAN.md` Move 1.4. **This is the highest-value
   remaining build and the only one that changes the project's category.** τ = Cu/(Cu+Co); because
   newsvendor cost *is* pinball loss, fitting a quantile regressor at τ is provably the
   decision-optimal predictor. Deliverable: one chart showing the method that wins on MASE is not
   the method that wins on dollar cost. It converts three separate credible pieces into one system
   that runs forecast → decision → dollars.
5. **Move 2** — conformal prediction intervals (Mondrian, grouped by part family) for lead time;
   optimizer consumes the interval; finish the SAA optimality-gap CI.
6. Replace the June-9 README hero image.
7. Optional/structural: the Alembic squash (needs approval); per-worker test DB.

---

## Key files & context

**Read first on resume:** `docs/archive/ML_API_PUSH_PLAN.md` (the plan), `docs/PROJECT_OVERVIEW.md`
(what to claim and what NOT to claim), `docs/RESEARCH_TECHNIQUES.md` (backlog + a reasoned
do-NOT-build list).

**Commands**
```bash
cd backend && source venv/bin/activate
rm -f test_hardening.db && python -m pytest tests/ -q -m "not slow" -p no:cacheprovider  # 689
MODEL_CI_STRICT=1 python -m pytest tests/ -q -m model_ci -p no:cacheprovider             # 47
ruff check app && mypy app
cd ../frontend && npx tsc --noEmit && npm run build

# reproduce headline numbers
python -m seeds.run_leakage_progression      # ~98s
python -m seeds.run_carparts_backtest        # ~17s
python -m seeds.run_volume_sweep             # ~2s
python -m seeds.run_cvar_frontier --quick    # ~5s   (full run ~21min)
python -m app.ml.lead_time_collector --sync-only   # idempotent panel→DB
```

**Gotchas (hard-won this arc)**
- OR-Tools CP-SAT **hangs at 0% CPU on macOS** unless `num_search_workers=1`. Already set. Do
  not "fix".
- **Never kill a pytest run mid-flight** — it leaves `test_hardening.db` poisoned and every
  later run fails differently.
- Running several file-editing agents on one working tree is a live hazard. Give each a disjoint
  file scope and forbid `git stash`/`reset`/`checkout`.
- **Agents spawning sub-agents multiplies cost silently.** At peak, 4 of 6 running agents were
  grandchildren the main session never spawned. Forbid sub-agents explicitly in briefs.
- Several agents **stall waiting on their own background test runs** and never report. Faster to
  run the verification yourself than to keep resuming them.
- The tail metric is `cvar_95` / `mc_cvar_95` everywhere — **never reintroduce `evar`**.

**Live URLs:** UI https://supply-chain-ui-bhwz.onrender.com · API
https://supply-chain-api-qy8x.onrender.com (docs at `/docs`). Free tier: ~100s cold start.

---

## Open questions / decisions pending

1. **Push to origin?** (yes/no) — 25 commits, triggers a Render deploy. Recommended: yes.
2. **Rotate DigiKey/Nexar keys** after the cleartext-print incident? (yes/no)
3. **Permissions allowlist** — add `pytest`/`ruff`/`mypy`/`npm run build`/`git status` to
   `.claude/settings.local.json` to cut prompts? Include `rm`? (recommended: yes to the safe
   list, no to blanket `rm`)
4. **Re-enable the Playwright MCP** for this project? Currently in `disabledMcpjsonServers`.
   Would let the main session drive the browser directly instead of via agents.
5. **The Loop automation** — owner asked to investigate, then deprioritised it. Options were:
   disable the 9 `claude-*.yml` workflows, delete the scaffolding, or relocate it to its own
   repo. Only the security patch was applied. Still undecided.
6. **Write project-specific agent definitions?** (`.claude/agents/`) — would shorten every future
   brief; only `supply-chain-research-agent.md` exists today.
7. **Alembic squash** (see Current state #5) — structural, needs explicit approval.
8. **Mouser API key** — free at mouser.com/api-hub. Still the single highest-value hour the
   owner could spend: the client and collector are already written, and it adds a *second
   measurement of the same MPN*, which is what would lift the lead-time model off its 27-manufacturer
   ceiling.
