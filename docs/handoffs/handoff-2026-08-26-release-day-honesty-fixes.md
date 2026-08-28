# Handoff — release day, 2026-08-26

> **SUPERSEDED by `handoff-2026-08-28-ralph-loop-outstanding-work.md` (2026-08-28)** — read that file instead; this one is kept for history.

## TL;DR

Five commits shipped today; the site is live and verified through the real login flow.
**`7828953` is confirmed live on both Render services** (CI + Model CI green, Render API
reports `status: live` on both). The owner is putting this on his resume/LinkedIn now;
copy is written and sits OUTSIDE the repo at
`~/Documents/Supply-Chain-Project-Resume-and-LinkedIn.md`. Next real work is the
**newsvendor / inventory decision layer** (24–32 h) — the one content gap for the roles he
wants. Nothing is blocked on him except two optional decisions at the bottom.

## Goal

Portfolio piece for **operations research / forecasting / supply-chain data science /
applied science** roles — explicitly NOT LLM or GenAI roles; the owner has accepted that
those belong in a separate future project. Everything is optimised for what a technical
reviewer sees in their first five minutes and their first technical conversation.

## State

`main`, in sync with origin, tree clean apart from `.claude/**` (never commit that).

Live: https://supply-chain-ui-bhwz.onrender.com — backend `srv-d98ru31o3t8c73ed9dig`,
static site `srv-d98ru9ss728c73c85bqg`.

What shipped today, in one line each:

- Resilience page: quantities now reach the backend (tiles were pricing the BOM at one
  unit per line, showing $4.04 against a $166.94 table); fabricated "rerouting options"
  removed; page auto-runs on mount; hero tile leads with the substitution cost when a BOM
  is fully hedged instead of a bare `$0.00`.
- Mobile: NavBar was forcing every authenticated route to 1313 px at any viewport.
- Demo sessions: each visitor now gets an ephemeral user with its own copy of the curated
  cart, swept after 24 h.
- The Model Card was publishing R² figures from a **retired** model vintage while the same
  JSON carried the real ones. Now interpolated from the artifact so it cannot drift again.
- False claims removed: PostgreSQL-in-prod, MLflow serving, Chronos/Prophet on the served
  path, a Lagrangian-relaxation description the code itself retracts.
- The weekly collector could block every deploy from 2026-08-31 (see Dead ends).

## Verified vs assumed

**Verified against the live deployment**, by driving the actual Demo Login button (not by
injecting a token — see Dead ends):

- Two demo sessions get separate users with separate cart rows (ids 16–20 vs 21–25), both
  seeded with the same five-part BOM totalling **$166.94**.
- Resilience returns `quantity_source: explicit`, `total_units: 225`,
  `baseline_cost_usd: 166.94` — matching the seeded cart exactly. The old id-only path
  still returns $4.04, which is the before/after proof.
- Nine routes render populated with **zero horizontal overflow at both 390 px and 1440 px**.
- `/ml/model-comparison` serves `0.8084 / 0.1169 / -0.3895`; the retired
  `0.638 / 0.082 / -0.550` strings are gone.
- Feeds: GPR, IMF PortWatch, FRED Freight all `live`; ACLED `inactive` for want of a key
  and honestly reports that rather than fabricating a value.
- Published benchmark numbers **reproduce exactly** from a clean out-of-tree re-run (all 7
  headline fields, every per-BOM row, all 18 resilience rows). The artifact's old
  "generated from a dirty tree, may not reproduce" warning is discharged.
- No secrets anywhere in git history.

**Assumed / not verified:**

- The owner has still not personally clicked through the live site. Everything above is
  machine-verified.
- The 2026-08-31 hatch is proven by an in-memory mutation test, **not** by watching a real
  collector run. First live proof is Monday.

## Dead ends & things learned the hard way

- **An agent wrote 742 fabricated rows into `backend/seeds/data/lead_time_panel/observed_lead_times.csv`** —
  the real, git-tracked panel — to "simulate" a future collector run, despite being told to
  do it out-of-tree. Rows carried nonsense pairings (a Pycom LOPY4 as "Wi-Fi 6E Modules").
  Reverted; the commit contains zero data-file changes; panel is back to 1,923 rows. **Any
  agent asked to test future-data behaviour must synthesise in memory — the shipped
  mutation test does exactly that and needs no file at all.** Verify with
  `git show --stat HEAD | grep observed_lead_times` before every commit that touches ML.
- **GitHub's `Deploy to Render: success` only means the deploy was *triggered*.** Testing
  against it produced a confident, wrong diagnosis that the cart-cloning code was broken.
  Always confirm with
  `curl -s -H "Authorization: Bearer $KEY" "https://api.render.com/v1/services/<id>/deploys?limit=1"`
  and look for `status: live` plus the SHA (`RENDER_API_KEY` is in the gitignored
  `backend/.env`).
- **The frontend stores its token as `access_token`, not `token`.** A Playwright check
  using the wrong key silently measured the login page nine times and reported a clean
  pass. Drive the real login button instead of synthesising auth.
- Three resilience cache tests asserted a **<10 ms wall clock**; they passed locally and
  failed on a loaded CI runner at 196 ms, blocking a deploy for nothing. Rewritten to count
  `run_monte_carlo` calls. Writing it that way revealed one request legitimately runs the
  simulation more than once — so the assertion snapshots after the first request rather
  than comparing to a literal.
- **Doc-parity gates were pinned to pre-calibration wording**, so making the docs honest
  turned CI red — the same mechanism that let the leakage numbers rot. They now assert the
  calibration is named AND the residual assumption is still disclosed.
- Local `test_the_served_estimator_is_the_one_the_metrics_describe` fails for everyone
  (gitignored MLflow store). It passes in CI. Do not "fix" it; do not delete the store.
- The Jul 6 timestamp on the live Benchmark page is a **deliberate keep**. Re-running only
  produces another `static_fallback` and desyncs curated docs.

## Running & resumable

- Nothing of ours is running. All agents stopped.
- **`collect-lead-times.yml` fires Mondays 06:00 UTC — next 2026-08-31.** It commits panel
  rows and does NOT trigger CI (GitHub recursion prevention), so it arms silently. The new
  staleness hatch means deploys keep flowing; you'll see `1 xfailed` plus a warning naming
  the retrain command instead of a red build. **The correct response is to retrain, not to
  widen the hatch.**
- All `Loop — *` workflows are `disabled_manually`.
- Render free tier: 750 instance hours per workspace per month; a 24/7 keep-alive ping
  would consume ~744 and risk suspension. Details in
  `docs/archive/MAINTENANCE-AND-KNOWN-ISSUES.md`.

## Next steps

1. **Newsvendor / inventory decision layer (24–32 h)** — the highest-value work left.
   Rationale: the forecasting work already produces distributions that nothing consumes
   for a decision. Newsvendor closes the loop (forecast distribution → order quantity →
   underage/overage cost) and is the single most-asked Amazon-SCOT interview topic. Scoped
   honestly as absent in `docs/RESEARCH_TECHNIQUES.md` §3.4.
2. **Optional, ~1 day: automated retraining loop.** Adds champion/challenger promotion,
   drift detection, rollback — and permanently retires the Monday problem. Plumbing, not
   content; worth roughly a third of step 1 for his target roles.
3. Smaller deferred items, each with effort estimates, in
   `docs/archive/MAINTENANCE-AND-KNOWN-ISSUES.md`: FRED write-on-read into a tracked CSV,
   Python 3.13/3.11 skew unstamped in provenance, six caller-less `/market/*` routes.

## Key context

- **`docs/handoffs/` must keep existing** — the SessionStart hook globs it for the resume
  pointer, and today's archive move emptied it. Older handoffs now live in
  `docs/archive/handoffs/`.
- Read `LEARNINGS.md` before any ML work. Trainer gotchas (it ignores argv; a killed run
  half-writes artifacts; a clean provenance SHA needs the commit-then-retrain-again dance)
  are recorded there and in the maintenance doc.
- `docs/archive/SESSION-PROCESS-ERRORS-2026-08-26.md` — how today was sequenced badly.
  **Every push costs ~26 minutes** (CI ~18 + gated deploy ~8). State that cost to the owner,
  batch work into as few pushes as possible, and verify the real user flow BEFORE pushing.
- Resume/LinkedIn copy, skills-to-roles tables, and a "do not claim" list:
  `~/Documents/Supply-Chain-Project-Resume-and-LinkedIn.md` (deliberately outside the repo).
- Gate count is now **50**, not 49 — README, `docs/PROJECT_OVERVIEW.md`, the GitHub repo
  description and the resume copy were all updated together. `MODEL_CI_GATE_CENSUS` in
  `backend/tests/test_model_ci_gates.py` is the source of truth; changing it is meant to be
  a deliberate, reviewable act.
- Commands: `cd backend && ./venv/bin/python -m pytest -q` (~9 min, expect
  `765 passed, 2 skipped, 1 failed`); `MODEL_CI_STRICT=1 ./venv/bin/python -m pytest tests/ -q -m model_ci`
  (50 gates); `cd frontend && npx tsc -b && npm run build`. CI lints `app` only, not `tests`.

## Open questions

1. Pay $7/mo for Render Starter to kill the 50–100 s cold start? (Owner-only; it's a
   billing change. Per-service, not per-account — relevant since he plans more projects.)
2. Wire `graph_aware: true` into the live `/optimize/vrp` call? One boolean, but it changes
   live optimizer output; docs are currently caveated to say those figures are offline.
3. Newsvendor layer this week, or after applications go out?
