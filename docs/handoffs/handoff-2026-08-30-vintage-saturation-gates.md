# Handoff — vintage, saturation, and three gates that could not fail (2026-08-30)

## Read this first: verify, don't trust

This document was written by the session that did the work. **Do not take any claim in it on
faith.** Every factual claim is followed by the command that checks it. If a command disagrees
with what is written here, believe the command and fix this document.

The rule that mattered most this session, from `LEARNINGS.md`: *a check that cannot fail is
worse than no check.* Three of this repo's standing checks turned out to be incapable of
failing. Assume there are more.

---

## Goal

Portfolio piece for operations-research / forecasting / supply-chain-DS roles. The standing bar:
**nothing the site publishes may be contradicted by the code or the artifacts.**

---

## Verify the starting state

```bash
cd "/Users/alessiopagliarulo/Documents/Claude Projects/Logisitics Project"

git log --oneline -1                      # expect f380b1c
git rev-list --count origin/main..main    # expect 0
git status --porcelain backend/seeds/data/   # expect empty

curl -s https://supply-chain-api-qy8x.onrender.com/version      # expect f380b1c...
curl -s https://supply-chain-ui-bhwz.onrender.com/version.json  # expect f380b1c...
```

The API is Render free tier: **the first request after idle takes 50–120 s and can time out.
That is a cold start, not an outage — retry before concluding anything.**

---

## What this session did

Two pushes, both live and verified.

### `612e238` — the four open findings, plus three unfalsifiable gates

All four `ml-pipeline-verifier` findings from the previous handoff are **DONE**. Details and
provenance are recorded per-item in `docs/OUTSTANDING_WORK.md`; the short version:

1. **`/ml/stress` published a July frame as current.** Now carries `observation_date`,
   `observation_age_days/months`, `vintage_is_stale`, `max_observation_age_days` and
   `vintage_label`, all read off the same `tail(1)` row that is scored. `/model-card` and
   `/optimize` render it at type ≥ the claim it qualifies. **Optimizer behaviour deliberately
   unchanged** — a stale frame still prices the full surcharge (owner decision, 2026-08-29).
2. **CVaR saturation measures were computed and discarded.** Migration `0009` persists them,
   `/benchmark/summary` serves them, the page flags saturated rows.
3. **README published a retired lead-time vintage.** Synced; old numbers dated as superseded.
4. **FRED write-on-read — verified LIVE, then fixed.** See below.

The three gates that could not go red are recorded as items **41–43** in
`docs/OUTSTANDING_WORK.md`. Read them; they are the most transferable thing here.

### `f380b1c` — the migrated DB, after a live 500

**This is the mistake worth learning from.** `612e238` shipped code querying the `0009` columns
but excluded `backend/supply_chain.db` as "SQLite page churn". The deployed API reads that
tracked file. Production served the new code against a schema still at `0008`, and
`/api/v1/benchmark/summary` returned **500**.

**Every gate was green.** CI builds a fresh schema from the models, so it structurally cannot
see this. Model CI green. Deploy green. All three version hashes agreed. The only thing that
caught it was the UI gate's console-error check run against the live site.

`CLAUDE.md` now carries a section on telling page churn from a real schema change, with the
two-command check. **Read it before excluding that file again.**

---

## Current state

- **Live and verified on `f380b1c`**: API `/version`, UI `/version.json` and local `HEAD` all
  agree. `/api/v1/benchmark/summary` returns **200** with `cvar95_ceiling: 1.15`,
  `cvar95_saturated_rows: 26`, `cvar95_rows_measured: 36`.
- **`/api/v1/ml/stress` live** returns `observation_date: "2026-07-01"`,
  `observation_age_days: 60`, `vintage_label: "Macro data as of Jul 2026 — 60 days old"`.
- **Full backend suite: 1118 passed, 1 failed, 2 skipped** (`755 s`). The one failure is
  `test_the_served_estimator_is_the_one_the_metrics_describe` — the documented, permitted,
  local-only MLflow identity check that passes in CI. **Do not "fix" it.**
- **ruff / mypy clean** (78 source files). **`npx tsc -b --force` clean.** `npm run build` OK.

### The one thing NOT fully verified — pick this up first

**The live UI gate has not completed a clean full run since the `f380b1c` deploy.**

What *is* known:
- The gate's **new vintage checks passed against the live site** — `/model-card` reported
  `claimPx 20 / vintagePx 20`, i.e. the vintage renders at the same size as the 82.8%.
- The run immediately before the DB fix was **187 passed / 2 failed**, both failures caused by
  the `/benchmark/summary` 500 that `f380b1c` fixed.
- Since the fix, **four runs produced zero assertion failures**, but each aborted with a
  Playwright `page.goto` / `waitForURL` timeout on `networkidle` — at a *different* route each
  time (dashboard, map, cart), always immediately *after* that route's own assertions passed.
  The abort point moved earlier each run (15 passes → 3).
- The site itself is healthy: 12/12 sequential `curl` fetches of `/cart` returned 200 in
  0.06–0.44 s.

Best explanation: Render free-tier throttling after four full Playwright sweeps in ~40 minutes,
or local network instability (one abort was `net::ERR_NETWORK_CHANGED`). **It is not evidence of
a site defect, but it is also not a green gate.** Re-run it cold:

```bash
cd frontend && BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate
# expect ~189 passed, 0 failed
```

If it aborts again at a varying route with zero `FAIL` lines, it is environmental. If a specific
route fails an *assertion*, that is a real finding.

---

## Standing gates — every change must pass

```bash
cd backend && ./venv/bin/python -m pytest tests/ -q
#   expect 1118 passed, 1 failed, 2 skipped. ~12 min. The ONE permitted failure is
#   test_the_served_estimator_is_the_one_the_metrics_describe. DO NOT "fix" it.

cd backend && ./venv/bin/ruff check app && ./venv/bin/mypy app     # both clean

cd frontend && npx tsc -b --force && npm run build
#   NOT `tsc --noEmit` -- it typechecks NOTHING. See CLAUDE.md.

cd frontend && BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate

git status --porcelain backend/seeds/data/    # must be empty
```

---

## Next steps, ordered

1. **Re-run the live UI gate cold** and confirm a clean full pass (above).
2. **Decide whether the four heavy artifacts get `-m slow` pins.** Only three cheap artifacts
   are pinned to code. Unpinned, with measured sizing: `cvar_frontier.json` (~1,316 s — the
   committed artifact asserts `quick_mode=False`), `leakage_progression.json` (~215 s nested
   CV), `chronos_benchmark.json` (torch + HF weights + network), `forecast_backtest.json`
   (Prophet per rolling origin), `backend_verification.json` (42 live HTTPS calls). Without
   pins, each can drift from the code exactly as `volume_sweep.json` did.
3. **`STRESS_FRAME_MAX_AGE_DAYS = 120` turns the suite red on 2026-10-29** if nobody retrains.
   That is deliberate. The fix is to rerun `seeds/train_ml_models.py` and commit new artifacts —
   **not** to raise the constant.
4. **`python_version` provenance is stamped but not populated.** `build_provenance()` now
   records it; the committed `metrics.joblib` predates the field, so it appears on the next
   retrain. It is deliberately not in `REQUIRED_PROVENANCE_FIELDS` and nothing gates on it.

---

## Gotchas that each cost an hour

- **`backend/supply_chain.db` is TRACKED and is what production serves.** It shows modified
  after almost any pytest run (usually harmless page churn) — but a schema change hides in the
  same signal. Check `alembic_version` against `git show HEAD:` before excluding it. CI cannot
  catch this. See `CLAUDE.md`.
- **`npx tsc --noEmit` typechecks nothing.** Use `npx tsc -b --force`.
- **A doc-vs-artifact test proves nothing about the code.** Both can be stale together and
  green. Pin artifacts to a re-solve through the generator's own function.
- **Never estimate a change with a scratch reimplementation.** A scratch harness claimed the
  entire volume-decay curve was near-zero; the real `seeds.run_volume_sweep` showed the
  published 2.6–8.0% was correct. This has now happened twice.
- **`DATABASE_URL` is CWD-relative and SQLite creates rather than fails.** Run scripts from
  `backend/`, and sanity-check 791 / 92 / 8,176 before trusting any result.
- **`npm run build` writes to a shared `dist/`.** Never run it while an agent is working.
- **Never commit anything under `.claude/`.** It is dirty right now. Stage by explicit path;
  never `git add -A`.
- **Each push costs ~26 minutes** (CI 18–20 min, then the gated deploy). Batch the work.
- **A green "Deploy to Render" step means *triggered*, not live.** Only `/version` +
  `/version.json` + `git rev-parse HEAD` all agreeing proves a deploy — and as `612e238`
  showed, even that does not prove the page works.

---

## Open questions for the owner

1. Do the four heavy artifacts get `-m slow` code pins? (Next step 2.)
2. `LEARNINGS.md` still breaks its own stated 50-line cap (87 lines). Owner-merged; left alone.
3. Still standing: Render Starter at $7/mo to kill the 50–120 s cold start (owner said leave on
   free, 2026-08-28); six caller-less `/market/*` routes on public Swagger.
