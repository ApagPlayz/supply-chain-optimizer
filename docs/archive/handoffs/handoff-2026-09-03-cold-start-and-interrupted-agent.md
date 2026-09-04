# Handoff — cold-start work uncommitted, one agent interrupted mid-task (2026-09-03)

> **SUPERSEDED by `handoff-2026-09-04-overclaim-sweep-and-resume-bullets.md` (2026-09-04)** — read that file instead; this one is kept for history.


## TL;DR

`247cd34` is live and verified on both Render services; branch is clean against origin.
**There is substantial UNCOMMITTED work in the tree from two agents, one of which was killed
mid-task by a rate limit** (session limit, resets 23:10 America/New_York on 2026-09-02). The
prize: **`import app.main` went from 32–43 s to 1.0 s**, and the FastAPI lifespan's two expensive
steps moved to a background thread — that attacks ~70 of the ~75-second cold start. **Next action:
confirm the full backend suite is green on the interrupted tree, then commit and push.** A full
suite run was started at 11:35 and its result is NOT in this document — re-run it. Blocked on the
owner: the $7/month Render decision, and four other open items listed at the end.

---

## Goal

Portfolio piece for OR / forecasting / supply-chain-DS roles, aimed at a recruiter who clicks for
2–5 minutes and a technical interviewer who may probe one claim. Standing bar (`CLAUDE.md`):
nothing the site publishes may be contradicted by the code or the artifacts.

The 2026-09-02/03 arc was: audit the owner's résumé claims against reality, assess what the project
still lacks, build him an interview-prep guide, and **kill the free-tier cold start** — a recruiter
was waiting up to two minutes on first click.

---

## State

Branch `main`, 0 ahead / 0 behind origin. Everything below is uncommitted; `git status` lists it.

Two independent, unrelated bodies of work are interleaved in the tree — **do not assume one commit**:

1. **Frontend warm-up (COMPLETE, verified).** `frontend/src/services/warmup.ts`,
   `components/WakeNotice.tsx` (both new) plus `main.tsx`, `App.tsx`, `Login.tsx`, `services/api.ts`.
   Fires one `GET /health` before React renders so the backend wakes while the visitor reads.
   Verified with Playwright including a falsification run.
2. **Backend cold-start (INTERRUPTED).** `backend/app/startup.py` and
   `backend/tests/test_startup_warmup.py` (both new) plus 15 modified backend files including
   `main.py`, `sourcing.py`, `stochastic.py` and the `ml/` modules. **The agent that wrote this
   died mid-sentence** — its last message was *"Both new race tests failed to reproduce the bug —
   the mutation samples the epoch before my stub lands. Restructuring them to gate on the earlier
   step."* So its own test-hardening was in flight when it stopped.

`backend/supply_chain.db` is modified — verify it is churn (`alembic_version` vs
`git show HEAD:backend/supply_chain.db`) before excluding it, per `CLAUDE.md`.

---

## Verified vs assumed

**Verified by me directly after the agent died** (`LEARNINGS.md` requires diffing an interrupted
agent's work rather than trusting it):

| Check | Result |
|---|---|
| `import app.main` | **1.0 s** (was 32.3–42.7 s measured on Render) |
| `ruff check app` | All checks passed |
| `mypy app` | Success, 78 source files |
| `tests/test_startup_warmup.py` | **15 passed** |

**Verified by measurement earlier in the session:**

- The cold start is **our own Python startup, not Render**. From Render's platform logs across
  **8 independent real cold starts**: import 32.3–42.7 s, lifespan 30.2–33.7 s, total to first HTTP
  response 70.2–80.0 s. Warm responses are fine (`/health` 0.064 s).
- `startup.py`'s own docstring records the local lifespan breakdown: `load_ml_state()` **2.37 s**
  (the biggest item — *not* the graph), `build_graph_state()` 1.06 s, fiedler 0.20 s.
- Live at `247cd34`: `/optimize/vrp` **0.59–0.67 s** (was 9.9–10.2 s), UI gate **239 passed**.

**NOT VERIFIED — the reason this handoff exists:**

- **The full backend suite has not been confirmed green on the interrupted tree.** A run was started
  at 11:35 on 2026-09-03; its result is not in this file. **Re-run it before committing.** Expect
  exactly two failures, both named in `CLAUDE.md`.
- **The graph-cache landmine fix is unproven.** `api/resilience.py:297` and `api/stochastic.py:229`
  now carry comments saying they store what they build (the old code called `build_graph_state(db)`
  without `set_graph_state`, so deferring the build naively would make every request rebuild the
  graph — a self-inflicted DoS on a 0.5-CPU worker). **The comments are present; the behaviour is
  not proven.** This is precisely the failure mode `LEARNINGS.md` records — an interrupted agent
  rewrote a docstring to describe a fix it never implemented. Test it under concurrency.
- **No endpoint response has been diffed before/after.** The change was supposed to be startup-only.
  Capture the main endpoints on `247cd34` and on the new tree and compare byte-for-byte.
- **The cold-start improvement has never been observed end to end.** 1.0 s import is measured; the
  full boot on Render is not. It also could not be measured locally — see below.
- **The frontend warm-up has not run against the live site** (it is not deployed).

---

## Dead ends — do not repeat these

1. **A cron pinging the free service to keep it awake.** Researched properly and rejected on two
   independent grounds. (a) Render's Acceptable Use Policy bans imposing load *"especially for the
   purpose of evading payment"* and *"bypassing usage restrictions"* — spin-down is a documented
   free-plan restriction whose only documented removal is paying. (b) Free hours are **750 per
   workspace per month**; 24/7 uptime costs **744 h in a 31-day month**, clearing it by 0.8%, and
   overrun **suspends every free web service until the 1st**.
2. **GitHub Actions as the pinger** — measured against this repo's own history:
   `claude-builder.yml` (`*/30`) delivered **60 of 84 runs (71%), max gap 91.8 min**; hourly
   `claude-scout` had a **48-minute median delay**. Against a 15-minute idle timeout it cannot work.
3. **Pointing an uptime monitor at `/robots.txt`.** Render answers that path *itself* while a
   service is spun down, so the monitor reports 100% green while the API sleeps. A check that cannot
   fail.
4. **Migrating to a "free always-on" host.** All checked with fetched sources: Oracle Always Free
   reclaims idle instances (exactly this workload); Vercel caps Python bundles at 500 MB vs our
   1.6 GB and has no always-on mode; Netlify has no Python runtime; Hugging Face now requires a paid
   plan for Docker Spaces; Deta is dead (no DNS); Railway's $1 credit runs out ~day 6. Only
   **Northflank's Developer Sandbox** ("always-on compute – no sleeping") is unexplored — its free
   per-service RAM cap is not published anywhere fetchable.
5. **Trying to observe a cold start locally.** Impossible right now: a device on the owner's home
   network has the deployed Dashboard open, and `Dashboard.tsx` polls `/api/v1/feeds/status` every
   60 s, resetting Render's idle timer permanently. Two full 17–18 minute idle windows produced no
   spin-down. A Render API restart does not help either — Render brings the replacement up before
   cutting over, so the client never sees a boot.
6. **Raising the CVaR wall-clock budget** (from the previous arc, still true): 20× the budget moved
   the worst gap only 92.69% → 89.12%. The fix was a *different kind* of budget
   (`max_deterministic_time`), not a bigger one.

---

## Running & resumable

- **A full backend suite run** was started 2026-09-03 11:35 in the background. If this session is
  gone, just re-run it: `cd backend && ./venv/bin/python -m pytest tests/ -q` (~12 min).
- **The cold-start agent can be resumed** — it failed on a *session* rate limit that resets
  **23:10 America/New_York, 2026-09-02** (now past). Its unfinished work is the two race tests.
- **`ScraplingServer` MCP is disconnected** (`CONNECTION_CLOSED` at session start). **It is not
  broken** — I sent it a real MCP handshake and it answered correctly (v0.4.15). Reconnect with
  `/mcp` or restart Claude Code.
- **Something on the owner's home network keeps the production API awake 24/7** and is burning
  ~730 of the 750 free instance-hours per month. He has been told to close that tab.
- **A weekly bot cron (`collect-lead-time-panel`) fires Mondays** — next 2026-09-07. It *will* turn
  `test_lead_time_panel_docs_pinned_to_csv.py` red, by design.
- Several `playwright-mcp` process pairs may still be alive; `pkill -f playwright-mcp` if they get
  in the way. A `kokoro-fastapi` uvicorn on port 8880 is **unrelated — do not kill it**.

---

## Next steps, ordered

1. **Re-run the full backend suite** on the current tree. Expect exactly two failures, both named
   in `CLAUDE.md`. Anything else is from the interrupted agent.
2. **Prove the graph-cache fix**, don't trust the comment. Force `_graph_state` to `None`, fire
   concurrent requests at `/resilience/*` and `/stochastic/*`, and assert exactly one build happens
   and the result is stored.
3. **Diff endpoint responses** against `247cd34` — this was meant to be startup-only.
4. **Commit as two separate commits** (frontend warm-up; backend cold-start) and push. ~26 min.
5. **After the deploy, measure the real cold start** — but only after the owner closes the tab that
   is keeping the API awake, or it cannot be observed.

---

## Key context

Read `CLAUDE.md`, `LEARNINGS.md` (never edit) and `docs/OUTSTANDING_WORK.md` (items 44–57).
Interview-prep material the owner asked for lives **outside the repo** at
`~/Documents/Claude Projects/Interview Prep/` — `STUDY-GUIDE-3-hours.md` (14,107 words),
`ROADMAP-what-to-learn.md`, `REFERENCE-deep-dive.md` (27,540 words).

```bash
cd backend && ./venv/bin/python -m pytest tests/ -q     # ~12 min; exactly 2 known failures
cd backend && ./venv/bin/ruff check app && ./venv/bin/mypy app
cd frontend && npx tsc -b --force && npm run build      # NEVER tsc --noEmit — it checks NOTHING
cd frontend && BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate   # 239 pass, ~20 min
git status --porcelain backend/seeds/data/              # must be empty
```

Gotchas: each push costs ~26 min (CI 19.5–25 min measured, then the gated deploy); a green
"Deploy to Render" means *triggered*, not live; `DATABASE_URL` is CWD-relative and SQLite creates
rather than fails, so run generators from `backend/` and sanity-check 791 / 92 / 8,176.

**Two audit findings not yet acted on**, both from 2026-09-02 and both verified:
- **The 20% graph holdout is dead code that corrupts published figures.** `builder.py` carves 1,574
  offer rows and `holdout_offer_pairs` is read by nothing. Published: 43 components, λ₂ 0.2377, max
  betweenness 0.2458. Truth with all edges: **34, 0.2788, 0.2914851** — the site overstates its own
  network's fragility by ~26%.
- **The risk premium attaches to the wrong variable.** `sourcing.py:902` uses `premium * x[key]`
  (binary selection) where cost uses `q` (quantity), so it is a fixed charge worth one unit. Proven
  by sweeping `macro_stress` across all four strategies: **plans byte-identical at every value.**
  The résumé claim "plans automatically shift toward safer suppliers" is therefore false.

---

## Open questions for the owner

1. **Pay $7/month for Render's `0.5c-512mb` plan?** It removes spin-down entirely. Everything free
   was researched and rejected (see Dead ends). Caveat: it is the *same* 512 MB, and the service
   peaks at 413 MB (81%) — it buys no headroom.
2. Fix the 20% graph holdout? (Only place the live site still contradicts its own code.)
3. Fix `premium * x` → `premium * q`? Changes every published benchmark/frontier/CVaR figure.
4. Un-gate `/benchmark`, `/frontier`, `/model-card`? Their APIs already answer without auth.
5. Rewrite the résumé bullets against the audit? The must-fix list is led by deleting the "plans
   shift" claim, correcting "classifier" (it is a `GradientBoostingRegressor`), and removing the
   bootstrap-CI and ECE claims from the ship-gate bullet — the code enforces neither.
6. Retrain (`seeds.train_ml_models` + `run_leakage_progression`)? Clears the second test failure.
   Risk: if the ship gate fails it **deletes the artifacts**.
