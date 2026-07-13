# Data Provenance

Every external data source this project depends on, where it actually comes
from, and how confident we are in that provenance. Project rule: **real data
only, honest provenance** — no synthetic data, and no data whose origin we
can't name. This doc is the source of truth for that rule; if a source isn't
listed here, treat its provenance as unverified.

Each entry lists: what it is, where it's used, license/terms, and how it was
verified.

---

## 1. Electronic components + distributor pricing (`backend/seeds/seed_db.py`)

**Status: verified real, but a static 2024 snapshot, not a live feed.**

- **Dataset:** `mdnh/electronic-components-supply-chain`
- **URL:** https://huggingface.co/datasets/mdnh/electronic-components-supply-chain
- **License:** CC-BY-4.0 (attribution required; commercial/derivative use permitted)
- **Uploader:** HuggingFace user `mdnh` — an independent individual, **not**
  Nexar or Octopart. The dataset is a third-party redistribution, not a
  first-party feed.
- **Original source (per the dataset's own README):** collected via the
  **Nexar API**, which itself aggregates **Octopart** data. Datasheet links
  are Octopart URLs.
- **Collection date:** 2024 (404 general components + 387 telecom-focused
  components, per the dataset card).
- **Published to HuggingFace:** 2026-01-01 (`createdAt` timestamp from the
  HuggingFace API).
- **Row count:** 791 components, CC-BY-4.0, `size_categories: n<1K`.
- **Verified how:** fetched `https://huggingface.co/api/datasets/mdnh/electronic-components-supply-chain`
  and the dataset's `README.md` directly on 2026-07-12 and confirmed the
  above against the dataset card text (license, source, collection
  methodology, row counts, top manufacturers).
- **Populates:** `components`, `distributors`, `distributor_offers` tables
  (via `Component`, `Distributor`, `DistributorOffer` models).
- **Used by:** this is the DB the live app actually runs on (it's what
  `backend/manage.py seed` / `python -m seeds.seed_db` loads). The
  alternative live-fetch path, `backend/seeds/seed_live.py`, queries the real
  Nexar API directly — but the deployment has no `NEXAR_CLIENT_ID` /
  `NEXAR_CLIENT_SECRET` configured (checked `backend/app/core/config.py`,
  `.env.example`, `render.yaml`), so that path has never actually run in
  production. `seed_db.py` is therefore the load-bearing seeder, not a
  fallback.
- **Honest framing for README/UI copy:** say "791 real components, sourced
  from Nexar/Octopart via a 2024 static snapshot (CC-BY-4.0)" — **not** "live
  Nexar/Octopart API," which overstates freshness. Prices, MPNs, and
  suppliers are real; they are not live/current.
- **Known limitations (carried over from the 2026-07-01 gap audit,
  `docs/GAP_AUDIT_2026-07-01.md` §1.6):**
  - MOQ is uniformly 1 in the seeded data (no price breaks).
  - ~40 Asian distributors in `DISTRIBUTOR_LOCATIONS` share one hardcoded
    Shenzhen coordinate (real city, but not each distributor's actual
    address) — a resolution shortcut, not fabricated data.
  - ~~Any place in the app claiming "8,731 offers" should be reconciled against
    the actual live row count.~~ **RESOLVED 2026-07-13:** the live row count is
    **8,176** (`SELECT COUNT(*) FROM distributor_offers`), and every user-facing
    claim (README, QUICK_START, `docs/PROJECT.md`, the dashboard) now says 8,176.
    Note the count is not a constant: offers with `price <= 0` are dropped at seed
    time, so it can shift by seed run / dataset revision. Re-check it after any
    reseed rather than treating 8,176 as permanent.

## 2. Distributor warehouse/HQ coordinates (`backend/seeds/seed_db.py::DISTRIBUTOR_LOCATIONS`)

- **Source:** manually compiled from company websites, SEC filings, and
  public press releases (see in-code comment above the dict).
- **Status:** real locations for named companies; not independently
  re-verified as part of this audit. Where multiple distributors share a
  hub city (e.g. Shenzhen), that's a deliberate simplification, not
  fabricated precision.

## 3. Lead-time, demand, and regime data (Route A build)

Documented separately in `docs/ROUTE_A_BUILD_PLAN.md`, owned by the
forecasting/ML tracks, not `seed_db.py`:

- **Demand:** Census M3 `A34SNO` (New Orders, Computers & Electronic
  Products) — `https://api.census.gov/data/timeseries/eits/advm3`
- **Regime:** NY Fed GSCPI —
  `https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx`
- **Lead time:** DigiKey `ManufacturerLeadWeeks` + Mouser `LeadTime` (real
  keys; see `backend/app/core/clients/`)

See `docs/ROUTE_A_BUILD_PLAN.md` for verification status and current build
progress on those tracks.

## 4. Emission factors (`backend/app/core/constants.py`)

Cited real sources per the improvement plan: EPA SmartWay, ICAO, IATA. Not
re-verified in this pass (out of scope — no changes made in this area).

---

## Outstanding provenance gaps (owner should know)

- **README/UI copy overstatement:** `README.md`, `QUICK_START.md`, and
  `frontend/src/pages/Dashboard.tsx` reference "791 parts from Nexar/Octopart
  APIs" in a way that reads as a live API integration. That copy is outside
  `backend/seeds/` and was **not** changed as part of this pass (scoped to
  `seed_db.py`) — flagging for whoever owns those files to reword per the
  "honest framing" note in §1 above.
- ~~**`backend/manage.py` bug (unrelated to provenance, found incidentally):**
  `cmd_seed()` imports `run_seed` from `seeds.seed_db`, but `seed_db.py` only
  defines a function named `seed()` — `python manage.py seed` will raise
  `ImportError`.~~ **FIXED 2026-07-13.** `cmd_seed()` now calls `seed()`. The
  vestigial `--reset` flag was also removed: `seed()` unconditionally clears
  components, distributors, offers, orders and cart items before reloading, so
  the flag was a silent no-op while the CLI help promised it dropped data.
  Seeding is *always* destructive, and the docstring now says so.
- ~~**Offer count drift:** README says 8,731 offers vs. 8,176 actually in the
  DB.~~ **RESOLVED 2026-07-13** — see §1. Live count is **8,176**; all
  user-facing copy now matches.
