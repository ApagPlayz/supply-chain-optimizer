# Frontend Verification Checklist

**Purpose.** The backend has an automated checker (`scripts/verify_backend.py`) that
exercises all 47 endpoints and asserts on response *bodies*. There is no equivalent for
the UI — the frontend has **no automated test suite at all**. This document is the manual
substitute: what to click, what you should see, and what "broken" looks like.

**Why it exists.** On 2026-08-18 a dead panel sat in the middle of the main dashboard
advertising its own brokenness, and three separate automated audits missed it, because
every one of them read code and screenshots rather than opening the app. Backend-green
does not mean the product works.

> **Status of this document:** the *backend* column of every row below was verified
> programmatically on 2026-08-19 against the live deployment. The *frontend* expectations
> were derived from the page components, **not from looking at the rendered pages**. Treat
> unticked rows as unverified, not as passing.

---

## Before you start

**Live URL:** https://supply-chain-ui-bhwz.onrender.com
**API:** https://supply-chain-api-qy8x.onrender.com (`/docs` for Swagger)

1. The API is on Render's **free plan** and sleeps. The first request takes **~100 seconds**.
   A blank or spinning page on first load is usually a cold start, not a bug — reload after
   two minutes before reporting anything.
2. Click **Demo Login** on the landing page. No credentials needed. It calls
   `POST /api/v1/auth/demo`, which returns a JWT stored in a cookie named `access_token`,
   and logs you in as "Greenville Advanced Manufacturing".
3. **Check the build hash** in the top-right of the nav bar. It must match:
   ```bash
   git rev-parse --short HEAD
   ```
   If it doesn't, you are testing a stale deploy and everything below is meaningless.
4. Open the browser devtools **Console** and **Network** tabs and leave them open. Most
   real failures here are silent in the UI and loud in the console.

**Run the backend checker first.** If a row fails here, the UI cannot possibly work, and
you'll waste time hunting a frontend bug that isn't one:
```bash
source backend/venv/bin/activate
python scripts/verify_backend.py                     # live deployment
python scripts/verify_backend.py --json report.json  # machine-readable
```

---

## The database resets on every deploy

Production runs **SQLite on an ephemeral filesystem** (`DATABASE_URL=sqlite:///./supply_chain.db`,
free plan, no persistent disk). The `.db` file is committed to the repo and restored on each
deploy.

Consequences when testing:
- Anything you add to a cart, and any account you register, **disappears on the next deploy**.
- If a cart looks empty when you expect items, check whether a deploy happened in between.
- This is deliberate — see the comments in `render.yaml` — but it means the app is not a
  durable multi-session demo.

---

## Page-by-page checks

### 1. Dashboard — `/dashboard`

| What | Expect | Red flag |
|---|---|---|
| KPI tiles | Real numbers: 55 categories, component/distributor counts | Zeroes, `—`, `NaN` |
| Category chart | **Full** category labels | Labels clipped mid-word (`"Analog to"`, `"NFC /"`) — a bug that was fixed once already |
| Live Feeds | GPR shows a value and a fetch timestamp | All four feeds "Unavailable" |
| Market Intelligence | **See known issue #1 below** | — |
| High-risk items | A count, currently 1 | — |

**Live Feeds nuance.** ACLED and any other keyless feed correctly show `inactive` with an
explanatory message. That is honest degradation, not a fault. What *is* a fault is all four
being unavailable at once, or a feed showing `live` with no value.

### 2. Components / Scheduler — `/components`, `/scheduler`

- The catalogue table populates (backend confirms 791 parts, 8,731 offers).
- Search and category filter change the result set.
- Clicking a part opens detail with real offers, prices and stock.
- **Red flag:** an empty table, or prices rendering as `$0.00` / `null`.

### 3. Cart — `/cart`

- Add a part from the catalogue; it appears here with a real unit price.
- Quantity edits recalculate the total.
- Live pricing shows per-distributor offers.
- **Red flag:** items add but the total stays `$0`, or a 500 in the console on add.
- Backend note: `POST /cart` correctly returns **201 Created**, not 200. If you write a
  checker, don't treat 201 as failure — that mistake was made once already.

### 4. Checkout / Optimize — `/checkout`, `/optimize`

- **The cart must be non-empty.** `POST /optimize/vrp` returns `400 "Cart is empty"`
  otherwise, and that is correct behaviour, not a bug.
- Run each of the four strategies; results should **differ** between them.
- A route map renders with real distributor locations.
- **Red flag:** all four strategies returning identical cost — that regression has happened
  before. With a very small cart they may legitimately not differentiate, and the UI says so
  in a banner; verify with a larger BOM before reporting it.

### 5. Resilience — `/resilience` (`/digital-twin` redirects here)

- Simulate a distributor failure: expect a cost delta, a fulfilment chart, and a
  line-by-line impact table.
- Monte Carlo results appear with a `cvar_95` tail metric.
- Criticality sweep, dual-sourcing plan and sensitivity all return populated tables.
- **Red flag:** an empty results form with no output — the *old* screenshot of this page
  showed exactly that.
- **Honesty check:** the Monte Carlo delay parameters are **assumed, not fitted**
  (`calibrated: false`). The UI should not present those probabilities as measured.

### 6. Map — `/map`

- Routes and the network-risk overlay both render.
- Nodes are positioned at real distributor coordinates.
- **Red flag:** a blank map pane, or all nodes stacked at (0,0).

### 7. Benchmark — `/benchmark`

- Leads with the **retraction** of the original savings claim. This is intended — it is the
  most credible thing on the page. Do not "fix" it.
- The methodology line should read **"All N reference BOMs · seed=42"**.
  - **Red flag:** any mention of a "holdout" split. `seeds/run_benchmark.py` states plainly
    that no holdout filter is applied; a holdout badge is a false methodology claim. This was
    removed on 2026-08-18 — if it reappears, something was reverted.
- The run ID and timestamp come live from the API, so they should not be stale.
- An amber "Static Feeds" banner is expected when serving a fallback run.

### 8. Model Card — `/model-card`

This is the most resume-relevant page in the app. Check it hardest.

| Tile | Expect | Red flag |
|---|---|---|
| Model source | `local_joblib` | **`none`** — means no model is being served at all |
| Model name | `gradient_boosting` | blank |
| Version | a short git sha, e.g. `3958e87-dirty` | a bare `—` |
| Shortage recall | `0.7018` | a bare `—` |
| Feature exclusions | six reasons, **fully readable** | text clipped mid-sentence with `…` |

**Known wording problem (not yet fixed):** a tile titled *"Accuracy vs persistence"* leads the
regime-model section, but that model has **no accuracy skill** — McNemar p = 1.0, macro-F1
slightly *worse* than baseline. It ships legitimately on Brier score (0.3944 vs 0.5413). The
tile should lead with Brier, not accuracy.

### 9. Error states and routing

- Visit a nonsense path such as `/does-not-exist` — it silently redirects to `/dashboard`.
  **There is no 404 page.** Recorded in `docs/screenshots/current/_problems.json`.
- Kill the network in devtools and reload: error states should be readable, not a white screen.

### 10. Mobile

Check at 390×844 (iPhone-class). Dashboard, checkout and resilience all have mobile captures
in `docs/screenshots/current/`. Look for horizontal scroll, clipped tables, and unreachable
buttons.

---

## Known issues — do not re-report these

1. **Market Intelligence panel is dead** (`Dashboard.tsx:644-704`). A full-width panel
   mid-dashboard whose entire content is a notice that the feature is inactive, plus a link
   out to `supplymaven.com/developers`.
   - SupplyMaven **is a real company** — this is not a fabricated vendor.
   - But the client posts to `https://supplymaven.com/api/v1/tools`, which **404s**. The real
     interface is MCP at `https://supplymaven.com/api/mcp`. **Adding an API key would not fix
     it.** The panel's claim that "the moment a key is added, real GDI scores appear here — no
     code changes needed" is false.
   - There are **zero tests** referencing SupplyMaven; every response shape in the client was
     inferred from prose docs and never verified against a real payload.
   - Decision pending: delete the panel, or rewrite `_call()` to speak MCP JSON-RPC and
     capture a fixture.
2. **The CVaR frontier has no UI at all.** `POST /stochastic/frontier` works (verified 200,
   45.4s cold) but **nothing in `frontend/src` calls it** — `DigitalTwinPage.tsx` was its only
   consumer and was deleted in `241ae9e`. The two-stage stochastic programme is the most
   technically substantial work in the project and a visitor cannot reach it. This is a
   missing feature, not a bug, but it is the biggest gap between what the repo contains and
   what the demo shows.
   - **Landmine for whoever wires it up:** `services/api.ts:9` sets a **global 30s axios
     timeout** with no per-request override. A cold frontier call takes ~45s, so it will fail
     client-side with `ECONNABORTED` while the server succeeds. Give this one call its own
     ~60s timeout.
   - Results **are** cached (deterministic key over items/params/strategy/depot, 1h TTL), so
     a warm call returns instantly with `cached: true`. Pre-warming the demo BOM on startup
     would make the first visitor's call effectively free.
   - The cost knobs (7-point lambda grid, 200 draws, 12s per-solve cap) are fixed server-side
     on purpose as DoS posture — there is no `--quick` mode to expose.
3. **No 404 page** (see §9).
4. **"Accuracy vs persistence" tile** on the Model Card (see §8).

---

## When something is broken

1. **Console and Network tabs first.** A dead panel is almost always a failed XHR, and the
   status code tells you whether it's frontend or backend in one glance.
2. **Then `scripts/verify_backend.py`.** If the endpoint fails there too, it's not a UI bug.
3. **Then the Render logs** — this is where both of the silent production failures were
   actually diagnosed, and neither was visible from the outside:
   ```bash
   # RENDER_API_KEY is in the gitignored backend/.env
   # backend service id: srv-d98ru31o3t8c73ed9dig
   curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
     "https://api.render.com/v1/logs?ownerId=<owner>&resource=srv-d98ru31o3t8c73ed9dig&limit=100"
   ```

**Two production bugs found this way, both green in CI and invisible in the UI:**
- `ML model load skipped: No module named '_loss'` — scikit-learn pinned 1.3.2, artifacts
  pickled by 1.8.0. `/ml/model-info` reported `model_source: "none"` for weeks.
- `AttributeError: 'CpModel' object has no attribute 'new_bool_var'` — ortools pinned
  9.7.2996, code uses the snake_case CP-SAT API from 9.9+. `/stochastic/frontier` 500'd.

Both are now caught generically by `backend/tests/test_dependency_pins.py`, which asserts
every installed version equals its pin. **If that gate ever fails, do not loosen the pin.**

---

## Filling the gap properly

This checklist is a stopgap. The durable fix is a script that logs in via
`POST /api/v1/auth/demo`, injects the `access_token` cookie, walks every route at desktop and
mobile widths, screenshots each to `docs/screenshots/current/`, and dumps console errors and
failed requests to JSON.

Auth is trivial to automate precisely because the demo endpoint needs no credentials and the
token lives in a cookie rather than localStorage — `context.addCookies([...])` and navigate.

Recommended tooling, researched 2026-08-19:
- **Playwright agent CLI** (`npx @playwright/cli`) — writes snapshots to disk instead of into
  the model's context; roughly 4x cheaper than the equivalent MCP for the same flow.
- **Claude in Chrome** (`claude --chrome` or `/chrome`) — first-party, interactive, best when
  you need to poke at *why* something is empty rather than capture that it is.
- **Avoid** the Playwright MCP for bulk screenshotting (context blowout) and Puppeteer MCP
  entirely (deprecated and archived).

Chromium binaries are already cached at `~/Library/Caches/ms-playwright`, so setup is minimal.

---

*Routes covered: `/dashboard`, `/map`, `/components`, `/scheduler`, `/cart`, `/optimize`,
`/checkout`, `/benchmark`, `/resilience`, `/model-card`, `/login`, `/register`.*
