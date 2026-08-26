# Handoff — Remaining Work After the Aug 24 Release

## TL;DR

The project is **released and verified live** at build `9722b93` — CI green, gated deploys,
working cold-start demo login, CVaR frontier visible, honest numbers throughout. `main` is
in sync with origin, tree clean. **Next action: the "application-ready" batch below (~4–6h)
— LICENSE + repo metadata + authorship note + docs index — which is what stands between
"released" and "safe to link on job applications".** Blocked on owner: four decisions at
the bottom.

## Goal

Portfolio piece for applications to AI/ML-in-operations/logistics companies. The owner is
applying NOW; every remaining hour should maximize what a reviewer sees in their first
5 minutes and first technical conversation. Master gap list with scores/evidence:
`docs/archive/handoffs/handoff-2026-08-23-gap-report-and-release-plan.md` (statuses current).

## State

- Live: https://supply-chain-ui-bhwz.onrender.com (build `9722b93`, both services verified;
  `scripts/verify_backend.py` 42/42). CI + Model CI + gated Deploy all green.
- Shipped 2026-08-24 (two batches): all six >85 gaps; demo-login cold-start fix (150s auth
  timeout + token cookie→localStorage→memory + waking-up notice, verified chromium+webkit);
  new `/frontier` page (CVaR efficient frontier, live-verified contract); BEST/TIED badge
  fix; money/plural/label polish; real 404 page; same-day model retrain on the cron-grown
  1,922-row panel with a clean provenance SHA.
- Everything committed and pushed; only `.claude/agent-memory/**` is dirty (never commit).

## Remaining tasks, in recommended order

**Batch A — application-ready (~4–6h, mostly presentation, do FIRST):**
1. **LICENSE file** — README claims MIT, no file exists. 5 min, glaring.
2. **GitHub repo metadata** — description, topics, homepage URL all blank (`gh repo edit`).
3. **Authorship note (gap 68, README part)** — a short honest "How this was built" section:
   the owner's role (direction, decisions, verification) vs. AI-agent-executed
   implementation; the 8 `claude-*.yml` workflows + LEARNINGS.md + LOOP-DASHBOARD.md are
   publicly visible and a reviewer WILL ask. Also set git identity for future commits
   (244/290 commits are `student@logistics.local`, unlinked). History rewrite = owner
   decision (see below), do NOT do it unprompted.
4. **Architecture diagram + demo GIF** for the README (gap 74 rest).
5. **Docs index + archive (gap 72)** — `docs/README.md` with a 5-doc reading path
   (PROJECT_OVERVIEW, MODEL_CI, CVAR_EFFICIENT_FRONTIER, DATA_PROVENANCE, README);
   `git mv` ~12 internal docs (handoffs/, loop-brief, AUTONOMOUS-LOOP, ML_API_PUSH_PLAN,
   DASHBOARD-CONTRACT, FRONTEND_VERIFICATION, SCENARIO_API, BENCHMARK_RESULTS, history/)
   into `docs/archive/`.
6. **Visual QA of the new pages** — nobody has eyeballed the rendered `/frontier` page,
   the new 404, or the BEST/TIED cards. Playwright click-through (auth cookie/localStorage
   token via `POST /auth/demo`; routes list in archived FRONTEND_VERIFICATION.md), or the
   owner clicks through personally.

**Batch B — visible-defect fixes (each independent):**
7. **Resilience page (gap 70, 4–6h)** — worst remaining on-screen defect: backend
   `procurement_spend_at_risk_usd` values the BOM at UNIT prices ignoring quantity
   ($101.4 tiles vs $25,119.80 table for the same BOM); `BOMImpactTable.tsx` says
   "0 components affected" above a 1-row re-source table; page lands blank (auto-run the
   default scenario on mount — the new FrontierPage does exactly this, copy the pattern).
8. **Python venv → 3.11 (gap 60, 1–2h)** — local is 3.13, CI/prod are 3.11; rebuild venv,
   re-pickle nothing (artifacts load fine), add an interpreter assert to the pin test.
9. **Shared demo cart (gap 55, 3–5h)** — everyone is user id:1; per-session demo user or
   session-scoped cart.
10. **Mobile nav (gap 50, 4–6h)** — every page 1219px wide at 390px; NavBar needs
    wrap/hamburger.
11. **Leakage-doc drift (gap 62, 3h)** + **FRED vintage pin for regime (gap 45, 3h)** +
    fulfillment P10/50/90 chart (gap 48, 1–2h) + delete caller-less backend `/market/*` +
    `supplymaven_client.py`.

**Batch C — the big one (gap 25, 24–32h, NOT a quick win):** newsvendor/inventory decision
layer (safety stock, reorder points, service levels) — the concept Amazon SCOT-type
reviewers live on, currently absent and honestly scoped in RESEARCH_TECHNIQUES.md §3.4.
This is the difference between "solid portfolio" and "role-matched work sample".

## Verified vs assumed

- Everything in "State" is verified against the live deployment today (bundle greps
  confirmed the 30s timeout is gone and frontier/waking-up code is present).
- **Assumed:** the frontier page renders correctly (data contract live-verified; pixels
  never seen). The owner's own-browser cold-start login test was requested but not yet
  confirmed — ask before declaring the login bug dead.
- The Jul 6 benchmark timestamp on the live Benchmark page is a KNOWN KEEP: a CLI re-run
  can only produce another `static_fallback` (feed check reads app-process cache a CLI
  never has) and would desync curated docs. Don't "fix" by re-running.

## Dead ends & gotchas (this session's additions)

- Demo-login root cause was NOT cookies/Safari — no `Set-Cookie` exists; it was the 30s
  global axios timeout vs ~100s cold start, plus token-only-in-cookie for blocked-cookie
  browsers. Both fixed.
- `python -m seeds.train_ml_models` ignores argv (a `--help` starts a real retrain); a
  killed run half-writes artifacts (restore with `git checkout -- backend/data/ml_models
  backend/seeds/data`). Clean provenance SHA requires: commit, then retrain again
  (trainer rewrites two seed CSVs mid-run; same-day rerun is byte-identical + clean tag).
- Local strict gates fail exactly one test (`test_the_served_estimator_is_the_one_the_
  metrics_describe`) whenever the gitignored local MLflow store holds a loadable champion
  — local-only; CI/prod unaffected; don't delete the store.
- Render `autoDeploy` was silently ON and bypassing the CI gate — now OFF on both
  services; if deploys ever fire instantly on push again, check it first.
- Older gotchas: 2026-08-23 gap-report handoff "Key commands / gotchas" section.

## Running & resumable

Nothing running. No pending crons until the lead-time collector Mon 2026-08-31 06:00 UTC
(it commits new panel rows — after it, the model-CI staleness gate may require a retrain;
the two-step retrain dance above applies). Loop workflows still disabled.

## Open questions (a word each)

1. Git history rewrite to fix authorship, or README note only? (rewrite = `git filter-repo
   --mailmap`, do on a quiet day, force-push)
2. Real Postgres (Neon free / $7 Render) or keep honest SQLite docs?
3. Rotate DigiKey/Nexar keys (open since the cleartext incident)?
4. Green-light Batch A now? Batch C (newsvendor) this week or after applications go out?
