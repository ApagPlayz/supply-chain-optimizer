# Handoff — Production Repair & Verification

**Date:** 2026-08-19 · **Branch:** `main`, in sync with origin, no open PRs

---

## TL;DR

Two silent production outages found and fixed, both caused by the same thing: **pinned
library versions the test suite had never run against**. The live API now passes **42/42**
endpoint checks for the first time (`scripts/verify_backend.py`). ML serves a real model;
the CVaR frontier returns 200 instead of 500. **Next action: wire the CVaR frontier into
the UI — nothing calls it.** Blocked on the owner: three decisions listed at the bottom.

---

## Goal

Make this repo a resume-grade portfolio project for **ML/Data-Science** and **big-tech ops**
(Amazon SCOT / Apple Ops) roles. Owner is job-hunting. Governing principle, set 2026-08-15:

> **Fixing means making it work.** Not deleting the feature and documenting that it doesn't.
> Honesty is satisfied by making claims TRUE, not by lowering claims until the broken thing
> is technically disclosed.

Strategy: `docs/ML_API_PUSH_PLAN.md`. Interview reference: `docs/PROJECT_OVERVIEW.md`.
Career strengths/gaps assessment is in memory as `strengths-and-gaps-aug2026`.

---

## State

**Working and verified live:** all 47 API endpoints. ML serves `gradient_boosting`
(`model_source: local_joblib`, version `3958e87-dirty`, shortage_recall 0.7018).
`/stochastic/frontier` solves. Live feeds report GPR as `live`. Local: 732 passed /
2 skipped, 49/49 model-CI gates strict, ruff + mypy clean, frontend `tsc` + build clean.

**Broken / missing:**
- **The CVaR frontier has no UI consumer.** `DigitalTwinPage.tsx` was its only caller and
  was deleted in `241ae9e`. The most substantial work in the project is unreachable from
  the app. Details and the timeout trap: `docs/FRONTEND_VERIFICATION.md` known issue #2.
- **Market Intelligence panel is dead** (`Dashboard.tsx:644-704`), full-width, mid-dashboard.
  SupplyMaven is a real company, but the client posts to `supplymaven.com/api/v1/tools`
  which **404s** — the real interface is MCP at `/api/mcp`. Adding a key would NOT fix it,
  contrary to what the panel tells the visitor.
- **Production DB is SQLite, not Postgres.** `DATABASE_URL=sqlite:///./supply_chain.db`,
  free plan, `disk: None`, `.db` committed to the repo. It resets on every deploy. README
  and CLAUDE.md both claim PostgreSQL — a live claim-vs-reality gap.
- No 404 page; `/does-not-exist` silently redirects to `/dashboard`.
- Model Card leads with an "Accuracy vs persistence" tile for a model with **no accuracy
  skill** (McNemar p=1.0). It ships legitimately on Brier; the tile should say so.
- Zero frontend tests. Alembic still decorative (0001–0003 build the pre-pivot schema).

**Uncommitted:** only `.claude/agent-memory/**` (deliberate — tooling state, keep out of the
repo) and `backend/seeds/data/regime_features_monthly.csv` — see Dead ends #3, **revert it**.

---

## Verified vs assumed

**Verified against the live deployment** (not just locally): every claim in the "working"
list above. `python scripts/verify_backend.py` was run after the final deploy and reported
42/42 with populated bodies, not just 200s. Record committed at `docs/backend_verification.json`.

**Verified locally only:** the full test suite and gates. Note this distinction is exactly
what failed last time — see Dead ends #1.

**NOT VERIFIED AT ALL — the important one:**
> **Nobody has looked at the rendered UI.** Not this session, not the previous one. Every
> frontend claim in `docs/FRONTEND_VERIFICATION.md` was derived from reading page components,
> not from opening the app. The Market Intelligence panel sat dead mid-dashboard for months
> while three separate automated audits missed it, because all three read code and static
> screenshots. Treat every frontend row as unverified until someone actually clicks it.

Also unverified: whether the `model-ci` GitHub Action currently passes (it installs the same
`requirements.txt` and should be fixed by `f964da7`, but no run has been checked); and whether
the four strategies on the Checkout page still produce differing results.

---

## Dead ends

1. **"The deployed site has no ML — fixed by pushing."** The previous handoff asserted this.
   It was wrong. Pushing 25 commits deployed correctly and ML still reported
   `model_source: "none"`. Real cause: `requirements.txt` pinned scikit-learn 1.3.2 while the
   artifacts were pickled by 1.8.0, so `joblib` raised `ModuleNotFoundError: No module named
   '_loss'` and `main.py` swallowed it as a one-line warning. **Do not diagnose this class of
   bug from the outside — read the Render logs.**
2. **Assuming a green suite means production works.** It does not. Twelve pins had drifted
   from the venv the tests run in (fastapi 0.104.1→0.135.3, pydantic 2.5.0→2.12.5, ortools
   9.7.2996→9.15.6755, …). `backend/tests/test_dependency_pins.py` now gates this. **If it
   fails, re-pin — never loosen it to a range.**
3. **Running the test suite mutates tracked data.** `backend/seeds/data/regime_features_monthly.csv`
   goes dirty after a full `pytest` run — the suite hits the live FRED API and overwrites
   committed training data. It is dirty right now for that reason. `git checkout --` it. This
   is a real defect: test runs are non-deterministic and can silently change the vintage the
   regime model was trained against.
4. **Suspecting SupplyMaven was a hallucinated vendor.** It is a real company with a real
   developer portal. The bug is the endpoint path, not the vendor.
5. **`./launch` refuses to run** while `.claude/agent-memory/**` is dirty. Use `./launch --anyway`
   — everything relevant is committed; only tooling state is dirty.
6. **Scrapling's screenshot tool cannot get past the login.** It renders a URL but cannot
   click "Demo Login", so it only ever captures the login screen. Not a substitute for a
   browser that can interact.

---

## Running & resumable

- **No background agents or jobs from this session are still running.** The Scrapling browser
  session `scdash` was closed.
- PID 753 (`kokoro-fastapi`) belongs to **another project** — leave it.
- A `playwright-mcp` process (PIDs 54593/54593-ish) is running from a **different session**;
  the Playwright MCP is disabled for *this* project in `.claude/settings.local.json`.
- **Crons that will fire without you:** the lead-time collector runs **Mondays 06:00 UTC —
  next fire 2026-08-24**; `loop-metrics.yml` commits a dashboard daily at 11:00 UTC; a push
  to `main` triggers both Render deploys.
- The autonomous **Loop** bot commits to `main` regularly (three commits landed mid-session
  and forced a merge before push). Expect to `git fetch && git merge origin/main` before
  pushing. It recently began modifying `.github/workflows/claude-scout.yml` — it previously
  only touched its own dashboard files, so this is new and worth an eye.
- Credentials in gitignored `backend/.env`: DigiKey, Nexar, OEMsecrets, EasyPost,
  RENDER_API_KEY (all working). **Absent:** Mouser, ACLED, SupplyMaven, TrustedParts, FRED key.
- Render backend service id: `srv-d98ru31o3t8c73ed9dig`. Rotation of DigiKey/Nexar keys after
  an earlier cleartext-print incident is **still an open decision**.

---

## Next steps

1. **Wire the CVaR frontier into the UI (~1 day).** Highest ROI — the work is done and
   verified, it just has no button, and it is the strongest OR asset in the project. Needs
   three things *together*: a per-request **60s timeout** (`services/api.ts:9` sets a global
   30s and a cold call takes ~45s, so it will fail with `ECONNABORTED` while the server
   succeeds), a loading state with honest "up to 45 seconds" copy plus a disabled button, and
   ideally a startup cache pre-warm for the demo BOM (results cache with a 1h TTL, so warm
   calls are instant).
2. **Decide the Market Intelligence panel** — delete (minutes) or rewrite `_call()` to speak
   MCP JSON-RPC against `https://supplymaven.com/api/mcp` and capture a fixture (~half a day).
3. **Fix the PostgreSQL claim** in README + CLAUDE.md, or move to a real Postgres (~$7/mo
   Render Basic, or Neon free). Minutes for the doc fix.
4. **Actually look at the UI.** Build a Playwright script (auth is trivial: `POST /auth/demo`
   needs no credentials and the token is a **cookie** named `access_token`, so
   `context.addCookies([...])` and navigate). Recommended tooling and the routes list are at
   the bottom of `docs/FRONTEND_VERIFICATION.md`. `claude --chrome` is the interactive
   alternative. Chromium binaries are already cached.
5. **Newsvendor link** (`ML_API_PUSH_PLAN.md` Move 1.4, ~2 days) — the highest-value *new*
   work and the entry ticket for SCOT.
6. **Alembic squash** — needs owner approval; structural.

---

## Key context

```bash
cd backend && source venv/bin/activate
rm -f test_hardening.db && python -m pytest tests/ -q -p no:cacheprovider   # 732 passed
MODEL_CI_STRICT=1 python -m pytest tests/ -q -m model_ci -p no:cacheprovider # 49 gates
ruff check app && mypy app
python ../scripts/verify_backend.py            # 42/42 against live
./launch --anyway                              # deploy + verify build hash
git checkout -- backend/seeds/data/regime_features_monthly.csv   # after any test run
```

**Read first:** `docs/FRONTEND_VERIFICATION.md` (page-by-page checks + known issues),
`docs/ML_API_PUSH_PLAN.md`, `docs/PROJECT_OVERVIEW.md`, `LEARNINGS.md`.

**Gotchas:** OR-Tools CP-SAT hangs at 0% CPU on macOS without `num_search_workers=1` (already
set — do not "fix"). Never kill a pytest run mid-flight; it poisons `test_hardening.db`. Cart
add returns **201**, not 200. `POST /optimize/vrp` legitimately 400s on an empty cart. Feeds
reporting `inactive` without a key is honest degradation, not a fault. The Benchmark page's
retraction is intentional — do not "fix" it. The tail metric is `cvar_95` everywhere; never
reintroduce `evar`.

**Live:** UI https://supply-chain-ui-bhwz.onrender.com · API
https://supply-chain-api-qy8x.onrender.com (`/docs`). Free tier, ~100s cold start.

---

## Open questions

1. **CVaR UI, Market Intelligence, or newsvendor first?** (recommended: CVaR UI)
2. **Market Intelligence panel — delete or rebuild?**
3. **PostgreSQL — correct the docs, or pay for a real database?**
4. **Rotate DigiKey/Nexar keys** after the earlier cleartext incident? (yes/no)
5. **The Loop automation** — it now edits workflow files. Leave, disable, or relocate?
