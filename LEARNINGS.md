# Learnings

Every agent working on this repo reads this file before it starts.

It records **mistakes the loop has already made**, so it stops making them. Only failures
and corrections go here — never successes. A file of self-congratulation would just dilute
the context that every future agent has to load.

Rules: max 50 lines. Dated entries. The weekly retro proposes additions via pull request;
nothing is added here without the owner merging it.

---

- *2026-07-14* — Seeded from `content-generation-platform`, where this loop was first built. The
  three entries below are scars from that repo. They are about the loop's own machinery, so they
  apply here too. No lessons about *this* codebase yet.
- *2026-07-14* — **A green Actions run does not mean the agent did its job.** The first Scout run
  there finished `success` in 6 minutes, having done all its research, and filed **zero** issues:
  Bash was never granted, so every `gh issue create` was silently denied
  (`permission_denials_count: 20` in the run log, the only place it surfaces). Rule: verify the
  *outcome* on GitHub — the issue, the PR, the comment must exist. Never trust the green tick.
- *2026-07-14* — **`--allowedTools` REPLACES the default toolset; it does not extend it.** Passing
  only `--allowedTools "Bash(gh:*)"` granted Bash and silently revoked `Read`/`Grep`/`Task`/
  `WebSearch` — denials went UP and the run collapsed from 46 turns to 21. An allowlist must name
  EVERY tool the agent needs. Also: `Bash(gh:*)` prefix patterns do NOT match commands containing
  `$(...)`, heredocs or pipes — and that is exactly how an agent writes a multi-paragraph issue
  body. In an ephemeral CI container, plain `Bash` is the right call.
- *2026-07-14* — **GitHub Actions expressions have no arithmetic.** `${{ 8 - fromJSON(x) }}` is not
  valid; GitHub rejects the whole workflow file, the run shows up under its raw filename instead of
  its name, and the workflow never executes. Do the maths in bash and pass it as a step output.
  Run `actionlint` on every workflow before committing it.
