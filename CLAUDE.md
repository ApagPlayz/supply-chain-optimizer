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
2. **`docs/handoffs/handoff-2026-08-30-visual-test-prep.md`** — the live handoff and the **next
   objective**. A SessionStart hook points at it. `docs/handoffs/` holds exactly one file, the
   current one; everything superseded is in `docs/archive/handoffs/` with a banner.
3. **`docs/OUTSTANDING_WORK.md`** — the live backlog and the source of truth for item status.
   It also carries the completion criteria and the standing gates.

`docs/archive/AUTONOMOUS-LOOP.md` describes how the loop works.

## Standing gates — every change must pass

```bash
cd backend && ./venv/bin/python -m pytest tests/ -q   # 1120 passed, 1 failed (see below), 2 skipped, ~12.5 min
cd backend && ./venv/bin/ruff check app && ./venv/bin/mypy app
cd frontend && npx tsc -b --force && npm run build   # NOT `tsc --noEmit`: see below
cd frontend && BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate   # 188 passed, 0 failed
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
  local-only MLflow identity check and it passes in CI. It is the one permitted failure.
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
