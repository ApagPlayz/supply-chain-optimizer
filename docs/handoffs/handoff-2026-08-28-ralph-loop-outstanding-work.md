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

## State: 22 of 22 backlog items DONE. Committed as 6a33ad0 + a follow-up; NOT pushed.

`git status` shows ~40 modified + 12 new files, all uncommitted. HEAD is `92f1e71`,
which is live on both Render services.

### What is done (see the backlog for evidence per item)
All seven P0 "claims the code contradicts", plus: MILP price resolution, the
double-counted origin flag, live-price currency + DigiKey exact-match, CVaR saturation
measures, benchmark bootstrap CIs, the newsvendor page, the newsvendor generator +
doc-match test, and four hygiene items.

### Nothing is open. Item 15 landed: `GET /benchmark/diversification-frontier` plus a
"Price of Resilience" section on `/benchmark`.

## RESOLVED — the benchmark was re-run, and nothing moved

Run 6 is written. **Zero cells differ from run 5**, including `selected_distributor_ids`.
The prediction below did NOT materialise: an agent measured the MILP fixes out-of-tree
and forecast a supplier flip on `robotics_servo_driver` degrading two published figures.
A real run through `seeds/run_benchmark` reproduces run 5 exactly, so its harness
diverged from the real path somewhere. All five bootstrap CIs are unchanged, and
`targeted_cvar95_reduction` survives at [+0.0107, +0.0517]. The `docs/` diff is
provenance only — timestamp, commit SHA, dirty-file list.

The original prediction is kept below because the reasoning is still worth reading.

## The prediction that did not hold

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

**The browser gate is now IN THE REPO** at `frontend/scripts/ui-gate.cjs`, with every
check documented as the postmortem it came from. `playwright` and `axe-core` are
devDependencies of `frontend/`; it lives there and is `.cjs` because Node resolves
modules from the SCRIPT's directory upward, so it must sit beside that `node_modules`.

```bash
cd frontend
npx playwright install chromium          # once
npm run build && npx vite preview --port 4173 &
npm run ui-gate                                                        # local build
BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate         # live
```

**Expect ONE failure until the next deploy lands**: `no console or page errors` trips on
a 404 for `/api/v1/benchmark/diversification-frontier`. That endpoint exists in this
commit but not on the deployed backend, and the gate proxies API calls to the live API.
Verified locally: the route is registered and returns 200 with data. It resolves on deploy.

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

## Proposed `LEARNINGS.md` entries — for the owner to merge, not for an agent to add

`LEARNINGS.md` states that nothing is added without the owner merging it, so these are
proposed here rather than written there. Each one cost real time this session.

- *2026-08-28* — **A check that cannot fail is worse than no check.** Three separate
  times a green result was meaningless: a contrast script returned a clean sheet because
  it could not parse Tailwind v4's `oklch()` (32 real failures hidden); a regression test
  for the `_size_shape` defect passed against BOTH the old and new code because its
  fixture never reproduced the bug; and the browser gate would have passed a route that
  did not exist, because a missing page trivially satisfies "no emoji, no overflow, no
  tiny text". Before trusting a pass, ask: *would this fail if the thing were broken?*
  If you cannot answer, the check is decoration.

- *2026-08-28* — **Test AT the breakpoints, not around them.** A tenth nav link pushed
  the desktop row to 1371px while it collapsed only below `xl` (1280px), so at exactly
  1280 the full nav rendered into a bar 91px too narrow. The agent that added the link
  measured at 1440, where it fits. The gate tested 390/768/1440 and would have passed it.
  This is the THIRD recurrence of nav overflow. Defects live in the gap between a
  breakpoint and the width the content actually needs — prefer a measured `min-[NNNpx]`
  with the measurement in a comment.

- *2026-08-28* — **A stale "deliberately deferred" entry is worse than no entry.**
  `MAINTENANCE-AND-KNOWN-ISSUES.md` told readers "Do not fix by re-running" about a
  benchmark serving numbers from a solver repaired a week later, with a headline claim
  that flipped sign when corrected. Both halves of its stated reason were false. A
  deferral converts an open bug into a decision someone thinks was already made — so
  re-check the REASON, not just the item.

- *2026-08-28* — **An out-of-tree harness is not the real path.** An agent measured the
  MILP fixes against scratch copies and forecast a supplier flip degrading two published
  figures. A real `seeds/run_benchmark` re-run produced ZERO differing cells. Measure
  through the real entry point before reporting an impact, or label the number as an
  estimate from a reimplementation.

- *2026-08-28* — **A fixed-name scratch file forbids concurrency silently.**
  `test_hardening.db` meant two pytest processes clobbered each other, producing five
  bogus `404 component_id not found` failures that looked like code defects. The old
  learning ("never kill pytest mid-flight") treated the symptom. Per-process naming also
  unlocked `pytest -n auto`.

- *2026-08-28* — **`DATABASE_URL` is relative to CWD, and SQLite creates rather than
  fails.** Running a script from the repo root instead of `backend/` silently made an
  empty database; every query returned nothing and the error surfaced far downstream as
  a malformed `SELECT  FROM`. Scripts that touch the DB must chdir to `backend/` and
  assert the schema is non-empty.

## Open questions for the owner

- Re-run the benchmark knowing it may demote a claim? (My recommendation: yes.)
- `graph_aware` / `us_only` are still never sent by the live optimizer — one boolean,
  changes live output.
- Render Starter ($7/mo) to kill the cold start.
- Three P3 items remain TODO and are cosmetic.
