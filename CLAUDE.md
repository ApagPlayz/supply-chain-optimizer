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
2. **`docs/handoffs/handoff-2026-08-28-ml-verifier-tail.md`** — the live handoff and the **next
   objective**. A SessionStart hook points at it. `docs/handoffs/` holds exactly one file, the
   current one; everything superseded is in `docs/archive/handoffs/` with a banner.
3. **`docs/OUTSTANDING_WORK.md`** — the live backlog and the source of truth for item status.
   It also carries the completion criteria and the standing gates.

`docs/archive/AUTONOMOUS-LOOP.md` describes how the loop works.

## Standing gates — every change must pass

```bash
cd backend && ./venv/bin/python -m pytest tests/ -q   # 997 passed, 1 failed (see below), ~10 min
cd backend && ./venv/bin/ruff check app && ./venv/bin/mypy app
cd frontend && npx tsc --noEmit && npm run build
cd frontend && BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate   # 188 passed, 0 failed
git status --porcelain backend/seeds/data/   # must be empty
```

## Never do these

- **Never edit `LEARNINGS.md`.**
- **Never commit anything under `.claude/`** — agent memory has reached the staging area before.
- **Never "fix" `test_the_served_estimator_is_the_one_the_metrics_describe`.** It is a documented
  local-only MLflow identity check and it passes in CI. It is the one permitted failure.
- **Never show the owner work through a localhost dev server.** Push, wait for the deploy, hand
  over the live URL. A green "Deploy to Render" step means *triggered*, not live — only
  `/version` + `/version.json` + `git rev-parse HEAD` all agreeing proves a deploy.
- **Never let a seed CSV drift**, and never use synthetic data for prices, suppliers or metrics.
  When real data does not exist for something, say so — do not fill the gap.
- **Never trust a green check you have not seen go red.** A check that cannot fail is worse than
  no check.
- **Each push costs ~26 minutes** (CI 18–20 min, then the gated deploy). Say that cost out loud
  and batch the work.
