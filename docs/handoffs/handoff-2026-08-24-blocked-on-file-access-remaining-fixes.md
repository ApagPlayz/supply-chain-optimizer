# Handoff — Blocked on File Access; Four Fixes Queued (2026-08-24, end of session)

## TL;DR

The project **shipped and is verified live** (build `9722b93`, all three GitHub workflows green,
42/42 API checks). Four small fixes remain — doc overclaims, two live bugs, stale ML numbers,
LICENSE — **none of which could be started because macOS revoked file-read access mid-session.**
**Next action: restore file access (see below), then run the four fixes in parallel (~2h).**
Blocked on owner: the FDA grant, plus two decisions (Resilience page, authorship).

## Goal

Portfolio piece for AI/ML-in-operations/logistics applications; owner is applying now. Stated
priorities, in order: **(1) the techniques must be genuinely impressive and resume-defensible —
modest effect sizes are fine, overclaiming is not; (2) it must actually work.**

## THE BLOCKER — read this first

macOS TCC revoked read access to `~/Documents` mid-session. Symptom: `Operation not permitted` on
every `cat`/`head`/Read/`ls` and `git status` ("Unable to read current working directory"), while
**writes still succeed** and `stat` works. Not the Claude sandbox — fails identically with the
sandbox disabled. Not a repo or git problem.

**Diagnosed root cause (this is new information — do not re-diagnose):** Terminal.app **already
has** the Documents grant (`kTCCServiceSystemPolicyDocumentsFolder|com.apple.Terminal|2` in
`~/Library/Application Support/com.apple.TCC/TCC.db`). The problem is `/Applications/Claude
Launcher.app` — an AppleScript applet that runs `do shell script "open ~/claude-launch.command"`.
It is the **responsible process** for every window it spawns, so TCC checks *its* permissions, not
Terminal's. It was ad-hoc signed with **no CFBundleIdentifier at all**, so macOS could not durably
record any grant for it, and it has **no TCC entry whatsoever**. That is why "enable Documents for
Terminal" advice never worked — that box was already ticked.

**Already fixed this session:** gave the launcher a stable identity
(`com.alessiopagliarulo.claudelauncher`), re-signed it, re-registered with LaunchServices. Backup at
`~/ClaudeLauncher.backup.app`. **Grants will now persist.**

**Owner must do (cannot be scripted — TCC is deliberately unwritable without disabling SIP):**
System Settings → Privacy & Security → **Full Disk Access** → add **both**
`/Applications/Claude Launcher.app` **and** Terminal.app → **Cmd-Q Terminal** (not just close) →
relaunch. A permanent playbook for this failure mode is now in the global `~/.claude/CLAUDE.md`.

## State

Live: build `9722b93` on both Render services. All three workflows (`CI`, `Model CI`,
`Deploy to Render`) report **success**. No open PRs. GitHub repo metadata was blank and is now set
(description, homepage, 11 topics) — done via `gh`, which works because it needs no file reads
when passed `-R ApagPlayz/supply-chain-optimizer`.

**Git state could NOT be re-verified this session** (git cannot read the cwd). As of the last
successful check, `main` was in sync with origin at `9722b93`. Uncommitted/untracked docs written
blind this session — verify they exist and are well-formed once access returns:
`docs/handoffs/handoff-2026-08-24-remaining-work-after-release.md`,
`docs/handoffs/handoff-2026-08-24-addendum-technical-inventory-and-open-fixes.md`,
`docs/handoffs/BRIEF-for-ml-agent.md`, and this file. `.claude/agent-memory/**` is dirty by design —
**never commit it** (every commit this session used `git add -A ':!.claude/agent-memory'`).

## Verified vs assumed

**Verified against the live deployment today:** `/version` = `9722b93` on both services;
`scripts/verify_backend.py` 42/42 with populated bodies; the deployed JS bundle contains the 150s
auth timeout and the "waking up" copy and **zero** occurrences of the old `timeout:3e4`; the
`/stochastic/frontier` endpoint responds warm in 0.06s and validates input correctly.

**Verified via GitHub API today:** all three workflows green; zero open PRs; repo description /
homepage / topics now populated.

**RESOLVED — a contested fact from two conflicting audits:** the macro stress regime model's ship
gate **PASSES**. Live `/ml/stress` returns `ship_gate_policy: brier`, `ship_gate_passed: true`,
`brier 0.3926` vs `baseline_brier 0.5388`. It ties persistence on *accuracy* (0.7306, McNemar
p=1.00) and ships on Brier by design. **The optimizer's macro stock-out risk premium is therefore
LIVE, not inert** — an earlier audit claimed the opposite and was wrong. Do not re-open this.

**NOT verified — assume nothing:**
- **Nobody has ever visually looked at the `/frontier` page, the new 404 page, or the BEST/TIED
  badges.** Data contracts and typechecks were verified; pixels never were.
- The **cold-start Demo Login** fix has not been exercised by a human in a real browser after a
  15+ minute idle. It passed Playwright chromium+webkit tests including a simulated 45s cold
  start, but the owner's own report of failure predates the fix and has not been re-tested.
- The four fixes listed under Next steps are **identified, not applied.** The working tree is
  exactly as it was after `9722b93`.

## Dead ends

- **"Enable Documents folder for Terminal"** — the advice the owner received in multiple sessions.
  It was already enabled. Wrong diagnosis; see THE BLOCKER.
- **Four fix-agents were launched and then stopped by me** while file reads were dead. They applied
  **nothing**. Stopping them was deliberate: reads were blocked but *writes worked*, so an agent
  could have written blind and reported false success. Verify the tree rather than trusting any
  earlier "fixed it" language.
- `python -m seeds.train_ml_models` **ignores argv** — `--help` starts a real retrain. No
  lead-time-only mode. A killed run half-writes artifacts (`git checkout -- backend/data/ml_models
  backend/seeds/data`).
- A **benchmark re-run cannot refresh the stale "Jul 6" timestamp** on the live Benchmark page:
  `run_tag` is set from a feed-availability check that reads a **FastAPI process-global cache**, so
  a CLI run always sees all feeds unavailable and emits another `static_fallback`. It would also
  desync curated retraction prose that a test asserts. **Decision: ship as-is. Do not re-run.**
- **Local strict gates fail exactly one test** (`test_the_served_estimator_is_the_one_the_metrics_describe`)
  whenever the gitignored local MLflow store holds a loadable champion. Proven local-only by moving
  `backend/mlruns` aside; CI and prod never see it. **Don't delete the store; don't "fix" the test.**

## Running & resumable

Nothing is running. All background agents and jobs from this session are stopped. Next scheduled
event: the **lead-time collector cron, Mondays 06:00 UTC — next fire 2026-08-31**; it commits new
panel rows to `main`, after which the model-CI staleness signal may warrant a retrain (see the
two-step retrain dance in `BRIEF-for-ml-agent.md`). The `claude-*` loop workflows remain
`disabled_manually`. Render `autoDeploy` is deliberately **OFF** on both services so the CI gate
cannot be bypassed — if deploys ever start firing instantly on push again, check that first.

## Next steps

1. **Owner restores file access** (THE BLOCKER above), relaunches Terminal, and starts a fresh session.
2. **Verify the tree**: `git status`, and confirm the four docs listed under State exist and are intact.
3. **Run these four in parallel (~2h total), then one commit + `./launch --anyway`:**
   - **Doc overclaims (~1h)** — full detail with file:line in
     `handoff-2026-08-24-addendum-technical-inventory-and-open-fixes.md` § OPEN FIX 1. Summary:
     the "Lagrangian relaxation of the Capacitated Facility Location Problem" claim is false (no
     multipliers, no relaxation, no capacity constraints — it is exhaustive search over 10 hubs);
     "Asymmetric TSP" is false (haversine is symmetric) and `/optimize/vrp` is a single-vehicle
     uncapacitated TSP; the documented tri-objective MILP minimizes **cost only**; and the
     `GET /ml/lead-time` docstring falsely claims the UI calls it.
   - **Two live bugs (~1h)** — § OPEN FIX 2. `recommendations.py:238,264` reads raw betweenness as
     a probability (route it through `build_failure_probabilities()` in `stochastic.py:289`);
     `api/optimize.py:110-125` never sets `distributor_country`, so every ACLED lookup asks about
     the US.
   - **LICENSE (~5 min)** — README claims MIT, no file exists. Note the bundled HuggingFace dataset
     is CC-BY-4.0.
   - **`docs/README.md` index** — 37 docs, no reading path. Do **not** `git mv` anything while other
     agents edit docs.
4. **Visual UI verification** — Playwright click-through of every route, especially `/frontier`.
5. **Owner: cold-start Demo Login test** in their own browser after 15+ minutes idle.
6. **Hand `docs/handoffs/BRIEF-for-ml-agent.md` to the dedicated ML agent** — owner's explicit
   instruction: the ML workstream (stale MODEL_CI/LEAKAGE numbers, FRED vintage pinning, conformal
   prediction intervals, newsvendor layer) is **deliberately deferred** to that agent. Do not start it.

## Key context

Commands, live URLs, service IDs, and older gotchas: **§ Key context of
`handoff-2026-08-24-remaining-work-after-release.md`** and the **§ Key commands / gotchas** of
`handoff-2026-08-23-gap-report-and-release-plan.md` (which remains the **master gap list** — every
score, its evidence, and the pending ≤85 items). Full technique inventory and the exact
claim / do-not-claim lists for interviews: the **addendum** handoff. Global rules auto-load from
`~/.claude/CLAUDE.md` (now including the macOS-TCC playbook); project memory auto-loads too.

**Framing decided with the owner:** effect sizes here are modest and that is fine — lead with
method and judgment, not impact numbers. The measured leakage progression, the retracted savings
headline, proper scoring rules chosen over accuracy with a written argument, and the finding that
**tail risk is driven by concentration rather than failure probability** are the strongest material.

## Open questions

1. **Resilience page** (tiles say $101.4 while the table says $25,119.80 for the same BOM; backend
   prices the BOM at unit cost ignoring quantity) — fix (4–6h) or ship with it? *Recommendation:
   ship, fix this week.*
2. **Authorship** — 244/290 commits are attributed to an unlinked `student@logistics.local`, 128
   carry Claude co-author trailers, and eight `claude-*.yml` agent workflows are publicly visible.
   Honest "How this was built" section, move the loop infra off the default branch, or both?
   *Recommendation: own it in the README.*
3. Rotate DigiKey/Nexar keys (open since an earlier cleartext-print incident)?
4. Real Postgres, or keep the honest SQLite docs?
