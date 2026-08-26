# History

This directory holds point-in-time audit and planning records, kept as
evidence of iterative rigor — not as current documentation.

- **`GAP_AUDIT_2026-07-01.md`** — the 2026-07-01 gap audit that found several
  ML models weren't actually learning (targets were functions of their own
  inputs) and that some metrics measured the wrong thing.
- **`ROUTE_A_BUILD_PLAN.md`** — the resulting build plan ("Route A: make it
  real"), replacing synthetic/leaked ML targets with genuinely observed data
  (DigiKey/Mouser lead times, Census M3 demand, GSCPI regime).
- **`PORTFOLIO_AUDIT_2026-07-12.md`** — a follow-up portfolio-wide audit after
  Route A landed.

Read these as a dated trail, not a live status report: every finding in them
reflects the state of the codebase on the date at the top of the file. Many
of the gaps and bugs identified here have since been fixed or superseded by
later work (see the main `docs/` directory and the README for current
claims). File paths quoted inside these documents — including references to
other docs that have since been deleted, renamed, or moved into this same
`history/` directory — are preserved as originally written and may no longer
resolve.

If you're evaluating the current state of the project, start with the
top-level `README.md` and the docs it links, not these files.
