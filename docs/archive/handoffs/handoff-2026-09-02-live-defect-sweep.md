# Handoff — the live-defect sweep shipped; one decision open (2026-09-02)

> **SUPERSEDED by `handoff-2026-09-03-cold-start-and-interrupted-agent.md` (2026-09-03)** —
> read that file instead; this one is kept for history. Its next step (the owner's visual
> pass) was overtaken: the site was audited, eight defects fixed and shipped, and the work
> moved on to the free-tier cold start.


## TL;DR

Everything from the 2026-09-01 session is **live and verified**: `85b2890` on both Render
services, `/version` + `/version.json` + local `HEAD` all agreeing, endpoints exercised.
Working tree is **clean, 0 ahead / 0 behind origin**. Eight defects that were live on the site
are fixed, four new gates exist, and the CVaR solve-quality counters are now genuinely
reproducible. **The single next action is the owner's own visual pass** at
https://supply-chain-ui-bhwz.onrender.com — no machine has judged the *new* look. **Blocked on
the owner: the retrain decision** (details in Open questions). Nothing is blocked on code.

---

## Goal

Portfolio piece for OR / forecasting / supply-chain-DS roles. Audience: a recruiter who clicks
for 2–5 minutes, and a technical interviewer who may open the repo and probe one claim. The
standing bar (`CLAUDE.md`): **nothing the site publishes may be contradicted by the code or the
artifacts.** The owner has put this project on their résumé, which raises the cost of any
published figure that a reader can falsify.

---

## State

Branch `main`, clean, level with origin. `git log --oneline -5` tells the rest.

Two dispositions that are **not** obvious from `git status`:

- `.claude/agent-memory/**` — deliberately **untracked** as of `3340fb5`. Do not re-add it.
  Agents rewrite it constantly; while it was tracked the tree was never clean, so every
  generated artifact stamped `provenance.git.dirty = true` and that flag became meaningless
  noise across six artifacts.
- `.claude/agents/*.md` — deliberately **tracked**, including `ui-verifier.md` which had existed
  on this laptop only. These are hand-written source, not state. `CLAUDE.md`'s rule was narrowed
  to match; the old blanket rule was one the repo had been contradicting since before it was
  written (nine files under `.claude/` were already tracked).
- `backend/supply_chain.db` — currently identical to HEAD. It was deliberately restored
  (`git checkout`) to get a clean tree for the artifact regeneration.

---

## Verified vs assumed

**Verified by exercising the deployed system**, not by matching version hashes (hashes agreed
while the site was broken on 2026-08-30):

| Check | Result |
|---|---|
| API `/version`, UI `/version.json`, local `HEAD` | all `85b2890` |
| `/benchmark/summary`, `/newsvendor/evaluation`, `/ml/stress`, `/benchmark/diversification-frontier` | all 200 |
| The six removed `/market/*` routes | all **404**; OpenAPI 45 paths, 0 market routes |
| Corrected `/frontier` figures present in the **served JS bundle** | `35 / 36` and `12 of 12` present; `31 / 36` and `11 of 12` absent |
| Full UI gate vs the live site (on `ed57056`) | **239 passed, 0 failed** |
| Backend suite locally | **1120 passed**, 2 failed (both known, see below) |
| CI · Model CI · Deploy | all green on `85b2890` |

**Verified by measurement, worth not re-deriving:**

- **The CVaR determinism claim.** Two independent 27-minute regenerations of the whole 387-solve
  study differ in **53 leaves: 35 wall-clock seconds inside prose, 16 `evaluate_seconds`, 2
  intended string fixes. No cost, plan, supplier set, CVaR value, gap, status, knee or frontier
  point moved.** Separately, a 15-solve sweep hashed identically at load 2.45 / 43.47 / 2.64
  (`10d34ccf…` ×3) where the wall-clock control did not (`8f6eeab5` vs `421cd46a`).
- `provenance.git.dirty` is now **false** in `docs/cvar_frontier.json` at commit `3340fb5`.

**NOT VERIFIED — say so rather than assuming:**

- **No human has looked at the NEW site.** The 239 gate checks cover contrast, overflow, clipped
  text, type size, units and leaked placeholders. They cannot judge whether it looks *good* or
  reads well. This was true before the session and is still true after it.
- **Cross-architecture determinism of the CP-SAT deterministic budget is untested.** Proven
  across CPU load on this arm64 machine with `ortools 9.15.6755` / Python 3.13.5 only. This is
  why the breadth arm must **not** be promoted into CI on that basis.
- **What a retrain would actually produce.** Directions were reasoned from the panel's structure;
  no metric value is measured, and **both ship-gate verdicts are unknown**.
- `_recourse_cost` still uses a fixed 10 s wall limit (evaluation side). It did not bind under
  43× saturation, but it is the residual load-dependence on a slower machine. Untouched.

---

## Dead ends — do not repeat these

1. **Raising the CVaR wall-clock budget to stabilise the counters.** Measured and rejected:
   `rf_transceiver_module ×1` went 92.69% → **89.12%** for **20×** the budget, and the gap is not
   even monotone in budget (`automotive_ecu ×1` λ=0.5 got *worse* at 4×, 82.19% → 88.18%, because
   a different incumbent was found). The fix was a different *kind* of budget
   (`max_deterministic_time`), not a bigger one. Do not re-plan this.
2. **A doc-vs-artifact test as a gate.** Both can be stale together and stay green — that is how
   `/frontier` published "31 / 36" for five days. `FrontierPage.tsx`'s own header sourced its
   figures "via `CVAR_EFFICIENT_FRONTIER.md`" — a document in the middle. Gates must compare the
   **page** to the **artifact**, or the **doc** to the **CSV**.
3. **Assuming a subagent's figures.** Two were wrong this session and were caught only because
   the next agent checked them against the artifact: `rf_transceiver_module ×1` is **not** one of
   the no-converged-λ BOMs post-regeneration (`drone_flight_controller ×1` and `automotive_ecu ×1`
   are), and breadth's non-`OPTIMAL` count is **44**, not 46 (46 is the run-wide total).
4. **A commit-only cache key.** The real incident was an *uncommitted* edit, which a commit-only
   key would not have caught. The key needs a source-content fingerprint.
5. **Regenerating any artifact while other agents are running.** The generating closure must be
   committed first, or the artifact records a dirty tree and can bake in half-applied fixes.

---

## Running & resumable

- **Three `@playwright/mcp` process pairs are alive** (PIDs ~886/957, ~14852/14911, ~97366/97425).
  Harmless leftovers; `pkill -f playwright-mcp` if they get in the way.
- A `kokoro-fastapi` uvicorn on port **8880** (PID 753) is **unrelated to this project — do not kill it.**
- **No agents, background jobs or workflows from the last session are still running.**
- **A bot cron (`collect-lead-time-panel`) commits new rows every Monday.** The 2026-08-31 run is
  what made the ML artifacts stale. The next one is due **2026-09-07** and *will* turn
  `test_lead_time_panel_docs_pinned_to_csv.py` red — by design; that gate was built for exactly
  this and was proven red against a simulation of that commit.
- **Render free tier**: first request after idle takes 50–120 s. Warm with `/version` and retry
  before concluding an outage.

---

## Next steps, ordered

1. **Owner does the visual pass** at https://supply-chain-ui-bhwz.onrender.com (warm it first).
   The pages that changed most: **`/optimize`** (cross-dock card now shows `+6.6% cost` with
   DIRECT favoured; also exercise the `us_only` toggle and the out-of-stock 400),
   **`/resilience`** (fulfilment drop now at headline weight; check the geopolitical tab, which
   previously rendered no statement at all), **`/dashboard`** (radar replaced by a labelled bar
   chart + data table), **`/frontier`** (numbers now match the artifact). Fix from that list.
2. **Decide the retrain** — see Open questions. If yes: `cd backend && ./venv/bin/python -m
   seeds.train_ml_models`, then `./venv/bin/python -m seeds.run_leakage_progression` (~215 s),
   two commits, second from a clean tree. **Watch the lead-time ship gate — on failure
   `train_ml_models.py` DELETES the artifacts and the site loses the model.**
3. **Only if the owner asks:** compress `LEARNINGS.md` (87 lines against its own 50-line cap).
   The honest route is *retiring* entries whose defects are now structurally impossible, not
   shortening them. **Never edit that file directly** — draft a candidate elsewhere for the owner
   to merge.

---

## Key context

Read `CLAUDE.md`, `LEARNINGS.md` (never edit) and `docs/OUTSTANDING_WORK.md` — items 44–57 carry
per-item provenance for everything above, including the four new gates and the cache-versioning
defect. `docs/archive/handoffs/` holds superseded handoffs.

```bash
cd backend && ./venv/bin/python -m pytest tests/ -q       # ~12 min; expect exactly 2 failures, both known
cd backend && ./venv/bin/ruff check app && ./venv/bin/mypy app
cd frontend && npx tsc -b --force && npm run build        # NEVER tsc --noEmit — it typechecks NOTHING
cd frontend && BASE=https://supply-chain-ui-bhwz.onrender.com npm run ui-gate   # 239 pass, ~20 min
git status --porcelain backend/seeds/data/                # must be empty
```

**The two permitted test failures**, both expected, neither to be "fixed":
`test_the_served_estimator_is_the_one_the_metrics_describe` (documented local-only MLflow check,
green in CI) and `test_leakage_progression_reproduces_from_the_live_lead_time_model` (the
2026-08-31 collector commit moved the panel SHA `0884a977…` → `c68e2891…`; cleared only by the
retrain in step 2, never by editing the artifact).

Gotchas that each cost an hour:

- **Each push costs ~26 minutes** (CI 18–20, then the gated deploy). Batch the work.
- **A green "Deploy to Render" means *triggered*, not live** — and even three agreeing version
  hashes do not mean the page works. Exercise the endpoints.
- **Before excluding `backend/supply_chain.db`**, compare `alembic_version` against
  `git show HEAD:backend/supply_chain.db`. Same → churn. Different → it is part of the change.
- **`DATABASE_URL` is CWD-relative and SQLite creates rather than fails.** Run from `backend/`;
  sanity-check 791 / 92 / 8,176.
- **`curl`-ing the UI proves nothing** — fast 200s are Cloudflare cache hits that never reach the API.

---

## Open questions for the owner

1. **Retrain now, or wait?** It clears the red test and refreshes the vintage, and the headline
   argument should get *stronger* (same 28 manufacturer clusters at a 93:1 row ratio, CI expected
   to tighten 15–20%). Against: ~1 hour, two commits, and a real risk the ship gate fails and
   deletes the artifacts. It does **not** clear the 2026-10-29 `STRESS_FRAME_MAX_AGE_DAYS`
   tripwire — upstream GSCPI still ends 2026-07-01 (verified read-only), so that needs the August
   reading. **Standing recommendation: wait, so one retrain closes both.**
2. Compress `LEARNINGS.md`, or leave it at 87 lines?
3. Anything from the visual pass that should be fixed before the link is shared further?
