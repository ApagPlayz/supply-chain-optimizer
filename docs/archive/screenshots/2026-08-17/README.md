# SUPERSEDED — captured 2026-08-17 against build `241ae9e`

**Do not cite any number in these images.** They are kept as a record of what the app
looked like in mid-August, not as a description of what it does now.

They sat in `docs/screenshots/current/` until 2026-09-05 — nineteen days — while the
folder's name went on claiming they were current. In that window the benchmark headline
moved from 47.25% to 18.79%, the supplier graph gained 1,574 links that a dead 20%
holdout had been silently discarding, and the carbon figures were corrected. Every one
of those changes is invisible in these files.

Their own `_problems.json` records the staleness in miniature: it states *"app has no
dedicated 404 page — catch-all route `*` redirects to /dashboard"*. `App.tsx` now routes
`*` to a real `NotFoundPage`. The note was true when written and had been false for weeks.

## Why they went stale

There was no command to regenerate them. They were produced ad hoc by the `ui-verifier`
agent, which drives the **Playwright MCP server** — and that server was later removed
from the owner's setup. The agent correctly refuses to fabricate results without it, so
the visual pass stopped silently and nobody noticed.

The fix is `npm run screenshots` (`frontend/scripts/screenshots.cjs`), which depends on
nothing but the `playwright` devDependency already in the repo, fails the run if a page
renders blank or 404s, and writes a `_manifest.json` recording the commit and base URL —
so a future reader can tell what the images depict instead of trusting a folder name.
