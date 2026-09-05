# Supply Chain Optimization Project

A deployed portfolio piece for **operations-research / forecasting / supply-chain-data-science**
roles. FastAPI + SQLite backend, React 19 frontend, OR-Tools CP-SAT, NetworkX, Prophet, on Render.

Live: https://supply-chain-ui-bhwz.onrender.com · API: https://supply-chain-api-qy8x.onrender.com

## The standing bar

**Nothing the site publishes may be contradicted by the code or the artifacts.** Every number on
screen must trace to a field in a real backend response or a committed artifact.

This repo has twice shipped figures that two documents agreed on while both disagreed with the
code. So: **check a claim against `metrics.joblib`, the JSON artifact, or the live endpoint —
never against another document.**

## Read these first, in this order

1. **`LEARNINGS.md`** — mistakes the autonomous loop has already made here. Read before you start.
   **Never edit it**; the owner merges it personally, and it is intentionally over its own
   50-line cap.
2. **`docs/handoffs/handoff-2026-09-04-overclaim-sweep-and-resume-bullets.md`** — the live handoff and the **next
   objective**. A SessionStart hook points at it. `docs/handoffs/` holds exactly one file, the
   current one; everything superseded is in `docs/archive/handoffs/` with a banner.
3. **`docs/OUTSTANDING_WORK.md`** — the live backlog and the source of truth for item status.
   It also carries the completion criteria and the standing gates.

`docs/archive/AUTONOMOUS-LOOP.md` describes how the loop works.

## Standing gates — every change must pass

```bash
cd backend && ./venv/bin/python -m pytest tests/ -q -n auto --dist loadfile   # ALL GREEN, ~3.5 min
# The 2026-09-03 retrain cleared the last permitted failure; a red suite is now a real regression.
# The two flags change the SELECTION not at all — drop them to run serially when you are chasing an
# ordering question. Measured 2026-09-05 on a 10-core laptop from a clean worktree at HEAD: serial
# 616.5 s -> parallel 210.9 s (2.9x), both 1,180 passed / 2 skipped out of the same 1,182 collected.
# The two runs' JUnit XML were compared node id by node id: 0 missing, 0 extra, 0 outcome mismatches.
# Parallelism is safe because tests/conftest.py names the scratch DB per process; `--dist loadfile`
# (not the default `--dist load`) keeps each file's module-scoped fixtures — the real retrain in
# test_lead_time_schema_contract.py — built once instead of once per worker.
cd backend && ./venv/bin/ruff check app && ./venv/bin/mypy app
cd frontend && npx tsc -b --force && npm run build   # NOT `tsc --noEmit`: see below
cd frontend && BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate   # 256 passed, 0 failed
git status --porcelain backend/seeds/data/   # must be empty
```

## `backend/supply_chain.db` is TRACKED and it is what production serves

The deployed API reads the committed `backend/supply_chain.db`. It is not a local scratch file.

`git status` shows it modified after almost any pytest run, and that is usually harmless SQLite
page churn — but **"usually" is how a schema change gets left behind**. On 2026-08-29 migration
`0009` was applied locally, the code that queries the new columns was pushed, and the DB was
excluded from the commit as churn. CI was green (it builds its own DB), the deploy succeeded,
and `/api/v1/benchmark/summary` returned **500 in production** because the served DB was still
at `0008`.

Before excluding it, check which it is:

```bash
sqlite3 backend/supply_chain.db "SELECT version_num FROM alembic_version;"
git show HEAD:backend/supply_chain.db > /tmp/head.db && \
  sqlite3 /tmp/head.db "SELECT version_num FROM alembic_version;"
```

Same version -> churn, safe to leave. Different -> **the DB is part of the change and must be
committed**, or production ships code that queries columns it does not have. Verify row counts
(791 / 92 / 8,176) and `PRAGMA integrity_check` before committing it.

**A green CI cannot catch this.** CI builds a fresh schema from the models; only the deployed
artifact carries the old one.

## Never do these

- **Never edit `LEARNINGS.md`.**
- **Never commit `.claude/agent-memory/`** — agents rewrite it on every run, it has reached the
  staging area before, and while it sat tracked-and-modified `git status --porcelain` was never
  empty, so **every generated artifact stamped `provenance.git.dirty = true`** and that flag
  became unfalsifiable noise (six artifacts carried it). Untracked and gitignored 2026-09-01.
  `.claude/agents/*.md` **are** tracked on purpose — they are hand-written source, not state,
  and `ui-verifier.md` previously existed on one laptop only. Stage by explicit path; never
  `git add -A` without excluding `.claude/`.
- **Never "fix" `test_the_served_estimator_is_the_one_the_metrics_describe`.** It is a documented
  MLflow identity check. It was long the one permitted failure (local-only; green in CI), but the
  2026-09-03 retrain cleared it: **verified passing locally 2026-09-04** (`1 passed`, 4.96 s). So
  there is no longer a standing permitted failure — **a red suite now means a real regression.**
  If it goes red again, clear it with a retrain; never by writing a `training_data_sha256` no run
  recorded, which would be doctoring the record to make a test pass.
- **The 2026-08-31 vintage failure is CLEARED (2026-09-03).**
  `test_leakage_progression_reproduces_from_the_live_lead_time_model` was red because the weekly
  collector cron committed the 2026-08-31 snapshot (panel 1,922 -> 2,664 rows). It was cleared the
  way the tripwire intends — `seeds.train_ml_models` then `seeds.run_leakage_progression` (337 s),
  never by editing an artifact. The served artifact is now 2,615 rows / 5 snapshots / 324 features,
  trained 2026-09-03, panel sha `c68e2891...`, and `/ml/model-info` reports `stale: false`.
  **The standing gate is now "nothing red but the MLflow check."** The same tripwire will fire
  again on the next Monday-06:00-UTC collector commit; clear it the same way, and never by editing
  an artifact.
- **The clean-tree regeneration is DONE (2026-09-04 verified).** Both artifacts now stamp
  `provenance.git.dirty = false` — `docs/leakage_progression.json` at commit `549b0e17b0`
  (`ffc9014`) and `docs/cvar_frontier.json` at `ffc9014ea8` (`cff1cf0`). Read the flag out of the
  JSON before believing any prose about it; this bullet previously described the opposite state
  for a day after the condition had been cleared. The rule that stands: when an artifact is
  regenerated, do it from a clean tree, and **never hand-edit the stamp.**
- **Never show the owner work through a localhost dev server.** Push, wait for the deploy, hand
  over the live URL. A green "Deploy to Render" step means *triggered*, not live — only
  `/version` + `/version.json` + `git rev-parse HEAD` all agreeing proves a deploy.
- **Never let a seed CSV drift**, and never use synthetic data for prices, suppliers or metrics.
  When real data does not exist for something, say so — do not fill the gap.
- **Never trust a green check you have not seen go red.** A check that cannot fail is worse than
  no check.
- **Never use `npx tsc --noEmit` as the TypeScript gate.** The root `tsconfig.json` is a
  solution file (`"files": []` + `references`), so `tsc --noEmit` typechecks NOTHING and exits 0
  on any error. Verified 2026-08-28 by introducing a deliberate typo: `tsc --noEmit` passed,
  `tsc -b` reported it. Use `npx tsc -b --force` — the same invocation `npm run build` uses.
- **Each push costs ~26 minutes** (CI 18–20 min, then the gated deploy). Say that cost out loud
  and batch the work.
