# Handoff — Ralph loop, outstanding-work sweep, 2026-08-28

## Read this first

**A Ralph loop is ACTIVE with no completion promise and no max-iterations.** It feeds the
same prompt back forever and cannot stop itself. Cancel it with `/ralph-loop:cancel-ralph`,
or restart it with an exit condition:

```
/ralph-loop:ralph-loop --completion-promise 'ALL GREEN' <task text>
```

The eight falsifiable criteria for `ALL GREEN` are written into
`docs/OUTSTANDING_WORK.md` — including *"if a check cannot be run, the promise is false;
'not checked' is a failure, not a pass."*

## Goal

Close every open item in `docs/OUTSTANDING_WORK.md` — the live backlog created this
session. It supersedes the "Deliberately unfinished" table in
`docs/archive/MAINTENANCE-AND-KNOWN-ISSUES.md`, which now only holds owner-decision items.

## State: 21 of 22 backlog items DONE. Nothing is committed.

`git status` shows ~40 modified + 12 new files, all uncommitted. HEAD is `92f1e71`,
which is live on both Render services.

### What is done (see the backlog for evidence per item)
All seven P0 "claims the code contradicts", plus: MILP price resolution, the
double-counted origin flag, live-price currency + DigiKey exact-match, CVaR saturation
measures, benchmark bootstrap CIs, the newsvendor page, the newsvendor generator +
doc-match test, and four hygiene items.

### The ONE item still open
**Item 15 — price-of-resilience frontier UI.** An agent (`a6d59c1509578512d`) was still
running when this handoff was written: it adds an endpoint serving
`docs/diversification_frontier.json` and a section on `/benchmark`. Check
`git status` for changes to `backend/app/api/benchmark.py` and
`frontend/src/pages/BenchmarkPage.tsx`; if they look half-finished, either finish or
`git checkout --` those two files and re-run the work.

## THE IMPORTANT PENDING DECISION — a benchmark re-run that makes a number worse

The MILP fixes change optimizer output on **exactly 1 of 80** cells:
`robotics_servo_driver`, `milp_graph`, global scope — suppliers `[81,85] → [41,81]`,
cost `675.83 → 674.81` (−$1.02). The cheaper plan is **worse** on resilience:

| | run 5 (published) | after the fix |
|---|---|---|
| targeted cascade risk reduction | +0.7500 | +0.5000 |
| targeted cvar_95 reduction | +0.0615 | 0.0000 |
| `cvar_95_improved` counter | 6 | 5 |

**So one published row describes a plan the code no longer produces.** That is the exact
defect that started this whole audit, so it should be re-run:

```bash
cd backend && ./venv/bin/python -m seeds.run_benchmark      # ~2 min
git status --porcelain backend/seeds/data/                  # MUST be empty
```

**Risk you must check afterwards:** `targeted_cvar95_reduction` currently has a bootstrap
CI of `[+0.0107, +0.0517]` — one of only **three** claims that survive significance. That
BOM contributes +0.0615 of it. Removing that contribution drops the mean to ~0.024 and
**may push the interval across zero**, demoting a defensible claim to "no measurable
effect". The page handles that correctly on its own (colour neutralises, an amber CI note
appears), but you should *know* whether it happened and say so.

`optimization_runs` is **append-only**, so run 5's rows survive the re-run and can be
snapshotted before OR after it:

```bash
cd backend && ./venv/bin/python ../scripts/snapshot_run.py 5 > /tmp/run5.json
```

## Verification — all of it passes right now

| Gate | Result |
|---|---|
| `cd backend && ./venv/bin/python -m pytest tests/ -q` | **956 passed, 1 failed** — the failure is the documented local-only MLflow identity check, green in CI. Do NOT "fix" it. |
| `./venv/bin/ruff check app` / `./venv/bin/mypy app` | clean (9 pre-existing ruff errors in `seeds/` are not linted by CI) |
| `cd frontend && npx tsc --noEmit && npm run build` | clean |
| Browser gate, 10 routes x 4 viewports | **130 passed, 0 failed** (last run against a local build) |

**The browser gate is now IN THE REPO** at `scripts/ui-gate.mjs`, with every check
documented as the postmortem it came from. It needs `playwright` + `axe-core`:

```bash
npm i -D playwright axe-core && npx playwright install chromium
cd frontend && npm run build && npx vite preview --port 4173
node scripts/ui-gate.mjs                                              # local
BASE=https://supply-chain-ui-bhwz.onrender.com node scripts/ui-gate.mjs   # live
```

It checks overflow, emoji, type size, clipped SVG chart labels, chart geometry, touch
targets, axe serious/critical, head tags, console errors — and fails on a route that
renders the 404 page. **It exits non-zero on any failure.** Screenshots land in
`gate-shots/`.

## Gotchas that will cost you an hour

- **`npm run build` writes to a shared `dist/`.** Never run it while agents work; build to
  `--outDir dist-somename` and DELETE it afterwards (`dist-navcheck` is not gitignored;
  `*.db-journal` now is).
- **Never commit anything under `.claude/**`.** An agent wrote memory into
  `frontend/.claude/` this session and it reached the staging area; it was caught and moved.
- The test DB is now **per-process** (`test_hardening_<pid>.db`) with session teardown, so
  concurrent pytest runs are safe. This was item 21, discovered when a shared file produced
  five bogus `404 component_id not found` failures.
- **Each push costs ~26 min** (CI ~18 + gated deploy ~8). Batch.
- A green GitHub "Deploy to Render" step means **triggered**, not live. Confirm with the
  Render API (`status: live`) AND `/version` + `/version.json` + `git rev-parse HEAD`
  all agreeing. `RENDER_API_KEY` is in the gitignored `backend/.env`.
- Free-tier cold start is 50–120 s. Not an outage.

## Next steps, in order

1. Land or revert item 15 (frontier UI).
2. Re-run the benchmark; diff against `run5_snapshot.json`; report whether
   `targeted_cvar95_reduction` survives.
3. Full suite, `tsc`, build, browser gate — all four.
4. Commit and push everything (one push).
5. Re-run the gate against the **live** site once the deploy reports `live`.
6. Cancel the Ralph loop, or restart it with `--completion-promise 'ALL GREEN'`.

## Open questions for the owner

- Re-run the benchmark knowing it may demote a claim? (My recommendation: yes.)
- `graph_aware` / `us_only` are still never sent by the live optimizer — one boolean,
  changes live output.
- Render Starter ($7/mo) to kill the cold start.
- Three P3 items remain TODO and are cosmetic.
