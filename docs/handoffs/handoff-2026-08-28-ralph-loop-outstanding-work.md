# Handoff — Ralph loop, outstanding-work sweep, 2026-08-28

## TL;DR

All 22 items in `docs/OUTSTANDING_WORK.md` are **DONE**; that file is the live backlog and
is accurate. Work is pushed through `1536742`; `df30bcb` (this doc) is committed but
**unpushed on purpose**. **A Ralph loop is still running with no exit condition** — cancel
it with `/ralph-loop:cancel-ralph`. **Next action:** wait for CI on `1536742`, confirm the
deploy is genuinely live, then run the live browser gate. Nothing is blocked on the owner
except cancelling the loop and optionally merging six proposed `LEARNINGS.md` entries.

## Goal

Portfolio piece for operations-research / forecasting / supply-chain-DS roles. This arc
closed every open item where **the code contradicted what the site published**, fixed the
correctness bugs behind them, and surfaced two results that existed but were invisible.

## State

`main`, 1 commit ahead of origin (`df30bcb`, docs-only — deliberately unpushed rather than
spend a 26-minute CI cycle on a doc; let it ride with the next real change).

Non-obvious dispositions only:
- Everything under `.claude/**` — **never commit**. An agent wrote memory into
  `frontend/.claude/` this session and it reached the staging area before being caught.
- `frontend/scripts/gate-shots/` + `gate-report.json` — gate run artifacts, now gitignored.
- Any `dist-*` build dir — not gitignored; delete after use.

Everything else `git status` explains for itself.

## Verified vs assumed

**Verified locally, this session:**
- Backend suite: **979 passed, 1 failed** — the failure is
  `test_the_served_estimator_is_the_one_the_metrics_describe`, the documented local-only
  MLflow identity check that passes in CI. **Do not "fix" it.** Up from 848.
- `ruff check app`, `mypy app`, `tsc --noEmit`, `npm run build` — all clean.
- Browser gate: **129 passed, 1 failed** against a local build, 10 routes × 4 viewports.
- Benchmark re-run wrote **run 6 with ZERO cells differing from run 5**, including
  `selected_distributor_ids`. Diffed programmatically, not eyeballed.
- `/newsvendor` was **opened and looked at** at 1440 — icons render, contrast reads, the
  limits section is real. `/benchmark`'s new "Price of Resilience" section was measured by
  the gate but **never viewed by a human**.

**Assumed / NOT verified:**
- **The deploy.** CI was still `in_progress` on `1536742` when this was written; live is
  still `92f1e71`. Nothing about the new code has run in production.
- **The gate's one failure is benign.** It is a 404 on
  `/api/v1/benchmark/diversification-frontier`, which exists in this commit but not on the
  deployed backend, and the gate proxies API calls to the live API. Verified locally that
  the route is registered and returns 200 with data — but the *"it resolves on deploy"*
  part is an inference. **If it is still failing after the deploy, the API did not ship.**
- The MILP fixes were measured as moving 0 of 80 benchmark cells; that came from the real
  `run_benchmark` path, so it is solid. But **an agent's out-of-tree harness predicted a
  change that did not occur** — see Dead ends.
- Eight of the twelve routes have never been viewed by a person at any viewport.

## Dead ends

- **An out-of-tree measurement harness disagreed with the real path.** An agent measured
  the MILP fixes against scratch DB copies and predicted `robotics_servo_driver` would flip
  suppliers `[81,85] → [41,81]`, degrading two published resilience figures and possibly
  demoting `targeted_cvar95_reduction` below significance. A real `seeds/run_benchmark`
  re-run produced **zero** differing cells. Do not trust a reimplementation's impact
  estimate; run the real entry point.
- **Re-basing CVaR onto the shortfall share does not fix its saturation.** Tested: the
  inflation map is exactly affine, so `CVaR(share) == (cvar_95−1)/premium`, 0 of 36 rows
  deviate. It buys zero resolution and would move every published figure. A test now exists
  to stop it being attempted again.
- **`noise_floor_pct` cannot be derived.** The benchmark is a single deterministic solve
  (seed 42, one search worker, no gap limit), so replicate variance is exactly 0.0% and a
  derived floor would declare every difference material. Relabelled as an assumed
  materiality threshold instead.
- **Three checks that returned green and were wrong.** A contrast script that could not
  parse Tailwind v4's `oklch()` (32 real failures hidden); a regression test that passed
  against *both* the old and new code because its fixture never reproduced the bug; a gate
  that would have passed a route that did not exist. All three were caught by asking
  *"would this fail if the thing were broken?"*

## Running & resumable

- **Ralph loop, ACTIVE, no completion promise and no max-iterations.** It re-feeds the same
  prompt forever. `/ralph-loop:cancel-ralph`, or restart with
  `--completion-promise 'ALL GREEN'` (its eight criteria are in `docs/OUTSTANDING_WORK.md`).
- **Two `watch-deploy.sh` background processes** polling for `1536742`. Harmless; they exit
  on success or after 90 minutes. `pkill -f watch-deploy` to stop.
- **CI + Model CI in progress** on `1536742`. Deploy is gated on both going green.
- A `vite preview` may still be on port 4173 — `pkill -f "vite preview"`.
- All subagents have finished. Scratchpad artifacts (`gate-final.log`, screenshots) die
  with this session; the gate and the snapshot tool are in the repo and survive.

## Next steps

1. `gh run list --limit 2` until CI and Model CI are green on `1536742`.
2. Confirm the deploy is **real** — a green GitHub "Deploy to Render" step only means
   *triggered*. Both `/version` and `/version.json` must report `1536742`, and the Render
   API must say `status: live` on both services (`RENDER_API_KEY` is in `backend/.env`).
3. `cd frontend && BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate`.
   Expect **130/130**. If the `diversification-frontier` 404 persists, the API did not ship.
4. Look at `/benchmark`'s new "Price of Resilience" section by eye — it has never been seen.
5. Cancel the Ralph loop.
6. Optional: merge the six proposed `LEARNINGS.md` entries in the section below.

## Key context

- **`docs/OUTSTANDING_WORK.md`** is the live backlog and the source of truth. It supersedes
  the "Deliberately unfinished" table in `docs/archive/MAINTENANCE-AND-KNOWN-ISSUES.md`,
  which now holds only owner-decision items.
- Commands: `cd backend && ./venv/bin/python -m pytest tests/ -q` (~10 min) ·
  `./venv/bin/ruff check app && ./venv/bin/mypy app` ·
  `cd frontend && npx tsc --noEmit && npm run build && npm run ui-gate`.
- **`frontend/scripts/ui-gate.cjs`** — the browser gate. It is `.cjs` and lives under
  `frontend/` **on purpose**: it uses `require()`, and Node resolves modules from the
  script's directory upward, so it must sit beside the `node_modules` holding `playwright`
  and `axe-core` (both devDependencies now). Run `npx playwright install chromium` once.
  Every check in it is documented as the postmortem it came from.
- **`scripts/snapshot_run.py`** — dumps any benchmark run's rows for before/after diffing.
  `optimization_runs` is append-only, so any run can be snapshotted at any time.
- Gotchas that each cost an hour: `DATABASE_URL` is relative to CWD and **SQLite creates
  rather than fails**, so running a DB script from the wrong directory silently makes an
  empty database; `npm run build` writes to a shared `dist/`, so never run it while agents
  work; each push costs ~26 minutes; free-tier cold start is 50–120 s and is not an outage.
- Read `LEARNINGS.md` and `CLAUDE.md` before ML work — both auto-load.

## Proposed `LEARNINGS.md` entries — owner merges, agents do not

`LEARNINGS.md` states nothing is added without the owner merging it, so these are proposed
here. Each cost real time.

- *2026-08-28* — **A check that cannot fail is worse than no check.** Three green results
  this session were meaningless (see Dead ends). Before trusting a pass, ask: *would this
  fail if the thing were broken?*
- *2026-08-28* — **Test AT the breakpoints, not around them.** A tenth nav link pushed the
  row to 1371px while it collapsed only below `xl` (1280px). Measured at 1440, it fit. The
  gate tested 390/768/1440 and would have passed it. Third recurrence of nav overflow.
- *2026-08-28* — **A stale "deliberately deferred" entry is worse than none.** The
  maintenance doc said "do not fix by re-running" about a benchmark whose headline claim
  flipped sign when corrected. Re-check the *reason*, not just the item.
- *2026-08-28* — **An out-of-tree harness is not the real path.** See Dead ends.
- *2026-08-28* — **A fixed-name scratch file forbids concurrency silently.**
  `test_hardening.db` made two pytest runs clobber each other, producing bogus 404s that
  looked like code defects. Per-process naming also unlocked `pytest -n auto`.
- *2026-08-28* — **`DATABASE_URL` is CWD-relative and SQLite creates rather than fails.**

## Open questions

1. Cancel the loop, or restart with `--completion-promise 'ALL GREEN'`?
2. Merge the six `LEARNINGS.md` entries above? (yes/no)
3. Still open, owner's call: wire `graph_aware`/`us_only` into the live optimizer (one
   boolean, changes live output); Render Starter at $7/mo to kill the cold start.
