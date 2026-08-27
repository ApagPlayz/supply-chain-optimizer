# Process errors — 2026-08-26 release session

Not code mistakes. Mistakes in how the work was *sequenced*, which cost the owner
roughly an hour of wall-clock on a day he needed the project finished. Written down
because every one of them is cheap to avoid and I made all of them in one session.

## The governing fact I failed to state

**Every push costs ~26 minutes** (CI ~18 min, Render deploy ~8 min). Deploys are gated
on green CI, so a red build costs the whole cycle and ships nothing.

I never told the owner this. He therefore could not weigh "is this fix worth 26 minutes."
I pushed four times in one afternoon; two of those cycles were avoidable.

**Rule: state the cycle cost before the first push of a session, and batch work into as
few cycles as possible.**

## Error 1 — verified after deploying instead of before

Found *after* pushing, each costing a full cycle:

- The demo cart shipped empty (`seeds/seed_demo_cart.py` is a "run once" script that had
  never been run against the tracked DB). Every visitor landed on empty pages.
- Three cache tests asserted a <10 ms wall clock and failed only on a loaded CI runner.

Both were findable locally, before the push.

**Rule: drive the real user flow — actual login button, actual pages — against a local
production build BEFORE pushing. API-level curl checks are not a substitute; they pass
while the UI is broken.**

## Error 2 — trusted a green checkmark instead of the system of record

GitHub's `Deploy to Render: success` means the deploy was **triggered**, not finished.
I tested against a stale build, concluded the cart-cloning code was broken, and told the
owner so. It was fine — the code had not shipped yet.

**Rule: confirm what is actually running via the Render API
(`/v1/services/<id>/deploys` → `status: live` + the commit SHA), never via the GitHub
workflow result. Never diagnose a bug against a build you have not confirmed is live.**

## Error 3 — wrong assumption about auth in a verification script

A Playwright check injected a token under `localStorage['token']`; the app uses
`access_token` (`frontend/src/services/api.ts`). Every route silently redirected to
`/login`, so a "9 routes, zero overflow" pass was really the login page measured nine
times. It looked like a clean result.

**Rule: verification must assert it reached the thing it claims to test — check the
landed URL and that expected content rendered. A check that cannot fail is not a check.
Prefer driving the real UI (click the actual login button) over synthesising auth state.**

## Error 4 — no triage; everything treated as a blocker

Nine findings from the ML audit were all fixed at equal priority. Only three actually
blocked publishing (retired model numbers on the live Model Card). The rest — a `%` sign
on a centrality score, the hero-tile framing — were polish folded in silently.

**Rule: present findings as "blocks publishing" vs "can wait", with the cycle cost
attached, and let the owner choose. Do not silently expand scope.**

## Error 5 — "handled" quietly became "not mentioned"

The free-tier cold start (50–100 s for the first visitor) was mitigated months ago with a
150 s timeout and a "waking up" notice, so it fell off the reported list entirely. The
owner discovered it himself and reasonably asked what else had been filed away.

Same pattern: `graph_aware` never sent on the live optimiser (resilient sourcing is
offline-benchmark only), the Benchmark page serving Jul 6 `run_id=4`, a FRED read path
rewriting a git-tracked CSV.

**Rule: mitigated is not closed. Keep one durable list of known-open items and surface it
whenever the owner asks "what's left" — including things previously judged acceptable.**

## Error 6 — the status answer changed every time it was asked

The remaining-work list genuinely changed as verification found real problems, but from
the owner's side that reads as going in circles.

**Rule: maintain one list with a stable shape — Done / In flight / Found today (new) /
Deliberately deferred. Add to it, never re-derive it.**

## What went right, and is worth repeating

- **Verify live, not locally.** Every genuinely serious find this session — empty cart,
  retired-model numbers, stale claims — came from checking the deployed system and the
  built artifacts rather than reading code.
- **Mutation-test a gate before trusting it.** After making the `run_benchmark` gate
  AST-precise and rewriting the cache tests, both were proven by deliberately breaking the
  thing they guard and confirming they failed. A gate nobody has seen fail is not a gate.
- **Fix drift at the source.** The leakage sentence now interpolates from the artifact
  instead of quoting a literal, so it cannot rot again. A re-typed number would have
  rotted on the next retrain, exactly as the previous one did.
- **Check gates when correcting docs.** Two doc-parity guards were pinned to the stale
  wording and went red when the docs were made honest — the same mechanism that let the
  numbers rot in the first place.
