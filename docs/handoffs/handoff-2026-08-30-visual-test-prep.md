# Handoff — ready for the owner's visual test (2026-08-30)

> ### 📌 Correction appended 2026-09-01 — two figures below were overtaken by events.
>
> This document is a point-in-time record of 2026-08-30 and is left as written. But
> `CLAUDE.md` points every fresh session here, so two passages that a later session would
> act on are corrected in place, each marked **`[corrected 2026-09-01]`**: the `/frontier`
> solve-quality counts in *Next steps 1*, and the whole premise of *Next steps 4*.
>
> **What happened:** `docs/cvar_frontier.json` **was** regenerated on 2026-09-01, under a
> `max_deterministic_time` (work) budget instead of a wall clock. Its solve-quality counters
> now reproduce under any CPU load. Item 45 in `docs/OUTSTANDING_WORK.md` carries the full
> record under *"What actually fixed it"*.

## TL;DR

`646bb66` is live on both Render services (API `/version`, UI `/version.json` and local `HEAD`
all agree) and CI, Model CI and Deploy are all green on it. Today closed backlog items 44–54:
**four user-facing failures that were live on the site** (a 500 on `/optimize`, a 260-second
`/newsvendor`, a 500 behind the "12 months" dropdown, and `/market/*` publishing fabricated
constants), plus three stale artifacts and four gates that were incapable of failing.
**Next action: the owner does a human visual pass — no machine has judged how this LOOKS.**
Nothing is blocked on code; everything below is optional.

---

## Goal

Portfolio piece for OR / forecasting / supply-chain-DS roles. Audience is a recruiter who spends
2–5 minutes clicking, and a technical interviewer who may open the repo and probe one claim.
The standing bar (see `CLAUDE.md`): **nothing the site publishes may be contradicted by the code
or the artifacts.**

---

## State

Branch `main`, **0 ahead / 0 behind origin**, CI + Model CI + Deploy all green on `646bb66`.

Uncommitted, and each should **stay** that way:

- `.claude/**` — agent memory and agent definitions. **Never commit** (project rule; it has
  reached the staging area before). Always stage by explicit path, never `git add -A`.
- `backend/supply_chain.db` — **verified page churn today**, not a schema change: alembic `0009`
  and 791/92/8,176/450 identical on both sides. Leave it. *But read the gotcha below before
  ever excluding it again.*
- `docs/screenshots/current/*.png` — 17 untracked from earlier UI passes; 30 already tracked.
  Owner's call whether they belong in the repo.

**Also uncommitted: this handoff rotation itself.** `git status` will show the previous handoff
as deleted from `docs/handoffs/` and untracked under `docs/archive/handoffs/`, plus edits to
`CLAUDE.md`, `docs/README.md` and `docs/OUTSTANDING_WORK.md` repointing at this file. That is a
*move plus repoint*, not lost work — the old handoff is intact in `docs/archive/handoffs/` with a
superseded banner. Verified: `docs/handoffs/` holds exactly one file (the project rule) and there
are zero broken internal `.md` links. Commit it or not; nothing depends on it being committed.

---

## Verified vs assumed

**Verified by calling the deployed API directly** (not by matching version hashes — hashes agreed
while the site was broken earlier today):

| Check | Result |
|---|---|
| `POST /optimize/vrp`, out-of-stock cart | **400** "Insufficient stock … needs 4 but only 3 in stock" (was 500 "Solver failed") |
| `GET /newsvendor/evaluation` | **0.18 s** default, **0.06 s** on a former cache miss (was 259.9 s) |
| `?review_period_months=12` | **422** naming the bound (was a 500 traceback) |
| Full UI gate vs the live site | **239 passed, 0 failed, 0 fatal** |

Also verified locally: suite **1120 passed / 1 permitted failure / 2 skipped**; ruff, mypy,
`tsc -b --force`, `npm run build` all clean.

**NOT VERIFIED — this is the whole point of the next step:**

- **No human has looked at the site.** The 239 gate checks cover contrast, overflow, clipped
  text, type size, units, and leaked `undefined`/`NaN`. They cannot judge whether it looks
  *good*, whether the narrative reads well, or whether a chart is confusing. Treat "gate green"
  and "looks right" as unrelated claims.
- ~~**The `/market/*` routes are still on public Swagger**~~ — **RESOLVED 2026-09-01, owner chose
  removal.** All six are gone from the API surface, along with the router, the SupplyMaven client
  that fed them and their tests. Reason: the upstream REST path 404s with or without a token
  (probed 2026-08-30), so they had never once returned data, and nothing in `frontend/src`
  consumed them. OpenAPI went 51 paths → 45. See `docs/OUTSTANDING_WORK.md` item 55.
- **Chronos cross-platform determinism is unknown, not disproven** — torch never installs on CI,
  so it has never been exercised there. Its artifact pin stays `slow` for that reason.
- **The resume/LinkedIn bullets** produced this session trace every number to an artifact or a
  live endpoint, but the *ranking* of "strongest claims" is judgment, not measurement.

---

## Dead ends — do not repeat these

1. **Excluding `backend/supply_chain.db` as "page churn" when it carried migration `0009`.**
   That shipped code querying columns production did not have and **500'd `/benchmark` live**,
   behind three green workflows and three agreeing version hashes. **CI structurally cannot catch
   this** — it builds a fresh schema from the models and never sees the tracked DB.
2. **Promoting the Prophet artifact pins into CI's default suite.** They pass locally and fail on
   CI: all 160 differing values were `prophet.*`, magnitudes 0.2–0.3%. Prophet fits via Stan and
   is **not bit-reproducible across platform/interpreter/BLAS** (local macOS/Py3.13 vs CI
   Linux/Py3.11). Confirmed by re-scoring in a `linux/amd64` container on CI's exact stack,
   reproducing CI's 135 and 61 counts digit for digit. **Do not "fix" this by loosening a
   tolerance** — that makes the check unable to fail. Only the deterministic seasonal-naive arms
   run in CI now.
3. **Trusting a scratch reimplementation.** One claimed the entire volume-decay curve was
   near-zero; running the real `seeds.run_volume_sweep` showed the published 2.6–8.0% was
   correct all along. This has now happened twice. Only the real generator settles a number.
4. **`curl`-ing the UI to prove it is healthy.** 12/12 fast 200s from `/cart` were **Cloudflare
   cache hits** (`cf-cache-status: HIT`) that never reached the API. It measured nothing.
5. **Assuming the UI gate's aborts were Render throttling.** Disproven by measurement: static
   navigation was 87–262 ms on every route with zero 429s. The real cause was `networkidle` being
   *unsatisfiable* on two routes plus the 260 s endpoint starving the single 0.5-CPU worker.
6. **Letting an interrupted agent's edits stand unread.** One died mid-task (machine slept) after
   rewriting a module docstring to describe a fix **it never implemented**. Always diff an
   interrupted agent's files before trusting them.

---

## Running & resumable

- **Two `@playwright/mcp` server processes** are alive (PIDs ~30158/30236 and ~35946/36022) plus a
  headless Chrome (~26688). Harmless; `pkill -f playwright-mcp` if they get in the way.
- A `kokoro-fastapi` uvicorn on port **8880** is running — **unrelated to this project**, do not kill.
- **No background jobs, agents, or workflows from this session are still running.** Everything
  completed.
- **Render free tier**: first request after idle takes **50–120 s**. That is a cold start, not an
  outage — warm with `/version` and retry before concluding anything.

---

## Next steps, ordered

1. **Owner does the visual pass.** Site: https://supply-chain-ui-bhwz.onrender.com — warm it
   first. The three pages that changed most: **`/optimize`** (add a cart item and run it — this
   is the flow that returned "Solver failed"), **`/newsvendor`** (was a four-minute spinner),
   **`/frontier`** (its solver-quality numbers were stale — 330/57 against an artifact that
   then said 349/38). **`[corrected 2026-09-01]`** After the deterministic-budget regeneration
   the artifact says **351 converged / 36 not**, worst gap **94.955%**, and the page was
   re-typed to those values. The on-screen caveat was also inverted: it no longer calls the
   counts "a run log of one machine" — they reproduce now — but it does still say that
   *elapsed time* never will. Every one of those literals is pinned by
   `backend/tests/test_frontier_page_matches_cvar_artifact.py`. Collect what looks wrong; fix
   from that list.
2. ~~**Decide the six `/market/*` routes**~~ — **DONE 2026-09-01: removed.** Not yet pushed;
   the removal is in the working tree. See `docs/OUTSTANDING_WORK.md` item 55.
3. **`STRESS_FRAME_MAX_AGE_DAYS = 120` turns the suite red on 2026-10-29** unless someone
   retrains. Deliberate tripwire. The fix is `seeds/train_ml_models.py` + commit new artifacts —
   **not** raising the constant. That retrain also starts populating `python_version` provenance.
4. ~~**`docs/cvar_frontier.json` cannot be regenerated reproducibly** (item 45)~~ —
   **`[corrected 2026-09-01]` DONE. It can now.** As written on 2026-08-30 this said the
   breadth arm ran a 15 s wall-clock CP-SAT budget with 46/150 solves hitting it, and that
   relabelling had been chosen over regenerating. That premise no longer holds, and the fix
   was not the one anticipated here: **not a bigger clock, a different KIND of budget.**

   The sweep now runs on `max_deterministic_time` — a *work* budget — at **15 units per solve
   in `breadth`, 80 in `primary`**, `num_search_workers = 1`, `relative_gap_limit = 0.0`, with
   the wall clock demoted to a runaway guard twenty times clear of it (300 s / 1,600 s). Proven
   before the regeneration on a 15-solve verification sweep: identical `OVERALL_SHA256`
   (`10d34ccfae6868c0…`) at load averages 2.45, 43.47 and 2.64, where the wall-clock control
   produced two different digests. Regenerated 2026-09-01 (1,600.1 s): **387 solves, 351
   converged, 36 not**, worst gap **94.955%**, `n_wall_clock_bound: 0`.

   **Do not re-plan this item.** What remains open is only the residual noted in
   `docs/OUTSTANDING_WORK.md` item 45 — two `excluded_reason` strings baked wrong into the
   committed JSON, which the next regeneration clears.

---

## Key context

Read `CLAUDE.md` and `docs/OUTSTANDING_WORK.md` (items 44–54 record today with per-item
provenance). `LEARNINGS.md` is owner-merged — **never edit it**.

```bash
cd backend && ./venv/bin/python -m pytest tests/ -q     # 1120 pass, 1 permitted failure, ~12.5 min
cd backend && ./venv/bin/ruff check app && ./venv/bin/mypy app
cd frontend && npx tsc -b --force && npm run build      # NOT tsc --noEmit — it typechecks NOTHING
cd frontend && BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate   # 239 pass, ~20 min
git status --porcelain backend/seeds/data/              # must be empty
```

Gotchas that each cost an hour:

- **`npx tsc --noEmit` typechecks nothing** — the root tsconfig is a solution file (`"files": []`).
  Proven with a planted error. Use `tsc -b --force`.
- **A doc-vs-artifact test proves nothing about the code.** Both can be stale together and green;
  that happened three times. Artifacts are now pinned by re-solving through the generator's own
  function (`backend/tests/test_artifacts_pinned_to_code.py`).
- **`DATABASE_URL` is CWD-relative and SQLite creates rather than fails.** Run from `backend/`;
  sanity-check 791 / 92 / 8,176 before trusting any result.
- **Before excluding `backend/supply_chain.db`**, compare `alembic_version` against
  `git show HEAD:backend/supply_chain.db`. Same → churn. Different → it is part of the change.
- **Each push costs ~26 minutes** (CI 18–20, then the gated deploy). Batch the work.
- **A green "Deploy to Render" means *triggered*, not live** — and as today proved, even three
  agreeing version hashes do not mean the page works. Exercise the endpoint.

---

## Open questions for the owner

1. ~~Remove the six caller-less `/market/*` routes from public Swagger, or leave them?~~ — **ANSWERED 2026-09-01: remove. Done (item 55), unpushed.**
2. Commit the 17 untracked screenshots under `docs/screenshots/current/`, or discard?
3. Want the CVaR breadth-arm counters made stable (~50 min) rather than caveated?
4. `LEARNINGS.md` is 87 lines against its own stated 50-line cap. Compress, or leave?
