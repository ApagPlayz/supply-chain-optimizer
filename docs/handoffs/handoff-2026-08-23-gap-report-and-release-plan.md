# Handoff — Full Gap Report & Sunday Release Plan (2026-08-23)

> **SUPERSEDED by `handoff-2026-08-24-release-tonight-status.md` (2026-08-24)** — read that file instead for current
> state; this one is kept for history and REMAINS THE MASTER GAP LIST (scores, evidence, pending ≤85 items).

**Goal:** release this project Sunday 2026-08-24 as a portfolio piece for AI/ML-in-operations/logistics
applications. Three parallel audits ran 2026-08-23 (live UI click-through with Playwright — first time the
rendered UI was ever actually driven — plus backend/ML/CI verification, plus a recruiter's-eye pass).
This file is the complete rated gap list. **Score = usefulness to the portfolio × ease of fixing in ~1 day.**

**Owner decision 2026-08-23:** execute a research→plan→execute→test loop with Opus agents on every gap
scored **above 85**. Everything ≤85 stays pending unless separately approved.

**Overall verdict:** the science is strong (CVaR/stochastic OR, leakage self-audit, model-CI gates, live API
healthy — all endpoints spot-checked returned real populated data). The public *surface* is what loses
interviews: no live link in the README, a failing CI badge on line 3, headline numbers better than the
artifacts, best OR work unreachable from the app, flagship Optimize page stamped "TIED" everywhere.

---

## IN SCOPE NOW (scored >85) — agent run of 2026-08-23 — ALL SIX SHIPPED LIVE 2026-08-24 (build 7b80715, verify_backend 42/42)

| Score | Gap | Fix | Status |
|---|---|---|---|
| 96 | README has **no live demo URL** (Quick Start shows localhost only) | Add https://supply-chain-ui-bhwz.onrender.com near top + cold-start warning + API /docs link | DONE 08-23 — live-demo callout at top of README, verified |
| 94 | **CI red since 2026-08-18** (Model CI: 46/49 gates, 3 fail; CI: 3 fail/728 pass) and `deploy-render.yml` deploys regardless of CI | Retrain artifact so schema matches (recomputed design has 11 extra one-hot cols, `c=packaging=*` family the model was never fitted on); make deploy `needs:` CI green | DONE 08-24 — root cause was CI pointing tests at an EMPTY DB (11 phantom packaging cols); CI+Model CI green since 7b80715; deploy gated via workflow_run AND Render autoDeploy turned OFF (was silently bypassing the gate) |
| 92 | **README headline numbers overstate the artifacts**: README.md:127 says Prophet 2.5% vs naive 4.4%, +42.7% skill, 197 obs; docs/forecast_backtest.json says 3.13% vs 4.80%, +34.8%, 198 (honest vintage-pinned real-time: 4.13%, +29.6%). Also "817 lead times, two snapshots" vs served panel 1,180 rows/3 snapshots. IMPACT_FRAMING.md still quotes the stale 2.5%/4.4% | Correct all numbers to match committed artifacts; sync IMPACT_FRAMING | DONE 08-23 — all numbers now match artifacts; stale figures kept only as honest history (IMPACT_FRAMING §3d, README leakage note) |
| 90 | **Dead Market Intelligence panel** full-width mid-dashboard (`Dashboard.tsx:644-704`) — tells visitors "add a SUPPLYMAVEN_API_KEY and it works", which is false: `supplymaven_client.py:29,164` posts to `supplymaven.com/api/v1/tools` → 404 (real interface is MCP at /api/mcp → 405 on POST) | **Delete the panel** (owner-approved via the >85 directive; rebuild-via-MCP rejected for now) | DONE 08-23 — panel + 358 lines of orphaned frontend code removed, tsc clean; backend /market/* + supplymaven_client left (no callers) |
| 88 | **Server-path / identity leak**: public `GET /ml/model-info` returns `training_data_path: <home>/...`; also in docs/BENCHMARK_RESULTS.md:135, docs/benchmark_results.json:40, inside metrics.joblib; model_version `3958e87-dirty` advertises an uncommitted-tree build. Model Card page shows a raw MLflow error dump exposing `/opt/render/project/src/backend/mlruns/mlflow.db` | Relativize paths at capture (retrain from clean tree → clean version) + sanitize at serve layer + scrub docs + collapse error dump behind a disclosure | DONE 08-23 — serve-layer sanitizer in ml.py, docs scrubbed, error dump collapsed behind disclosure; capture-time fix rides with the 94 retrain |
| 88 | **Model Card regime section headlines the zero-skill metric**: tile "ACCURACY VS PERSISTENCE 72.9%" (baseline 72.9%, delta 0.0 — live /ml/stress confirms) at `ModelCardPage.tsx:429-442`, while **Brier — the actual ship gate it wins (0.394 vs 0.541) — has no tile** | Swap Brier into the headline tile; demote accuracy with honest zero-skill caption | DONE 08-23 — Brier headlines the regime tiles, accuracy demoted with zero-skill caption, tsc clean |

## Evening batch 2026-08-24 (owner-directed)

- **Demo Login was genuinely broken cold** (owner report, confirmed): global 30s axios timeout vs ~100s free-tier
  cold start — first click always failed; token stored only in a cookie silently bounced cookie-blocking browsers.
  FIXED: 150s auth timeout + cookie→localStorage→memory token chain + honest "waking up ~2 min" notice; verified
  in chromium+webkit incl. cookies-blocked and 45s-cold-start scenarios. NOT a cross-site-cookie issue (no
  Set-Cookie exists; Bearer auth was already the mechanism).

## PENDING — not approved for the agent run (score ≤85)

| Score | Gap | Effort |
|---|---|---|
| 85 DONE 08-24 | Optimize page: **16 "TIED" badges** incl. on the uniquely-cheapest card — `TIE_REL_EPS = 0.005` at `CheckoutPage.tsx:28` swallows a real $41 win (0.5% of $25.6k = $128). Add absolute floor + "BEST" badge | 2–3h |
| 82 DONE 08-24 (except benchmark timestamp — re-run proven pointless: CLI can never see live feeds, ships static_fallback by construction; kept as-is) | Polish batch: cart money `$25,119.8` (`CartPage.tsx:132,168` — no minimumFractionDigits); "Factory (Depot) ," orphan comma (`CheckoutPage.tsx:805`); "1 offers" (`SchedulerPage.tsx:496`); truncated chart labels (`Dashboard.tsx:81-82` truncateLabel, used :264/281/298); stale "Jul 6" benchmark timestamp on live Benchmark page; no 404 page (`App.tsx` wildcard → /dashboard silently) | 2–3h |
| 80 | **PostgreSQL claim vs SQLite reality**: render.yaml:11-12 `sqlite:///./supply_chain.db`, 2.2MB .db committed; CLAUDE.md:3 + README.md:223 claim Postgres | 15 min doc fix (or ~4h Neon free Postgres) |
| 78 DONE 08-24 (new /frontier page, live-verified contract, 90s client; also real 404 page) | **CVaR frontier has no UI** — zero frontend callers of `/stochastic/frontier` (grep + live drive confirmed). Needs: chart page, per-request 60s timeout (`services/api.ts:9` global is 30s, cold solve ~45s), loading state, warm cache | 4–8h — strongest substantive add; planned for Mon/Tue |
| 74 | Architecture diagram (image), demo GIF, **LICENSE file** (README claims MIT, file missing), GitHub description/topics/homepage (all blank) | 1.5–2h |
| 72 | Docs sprawl: 37 docs, no index. Write docs/README.md; archive ~12 internal docs (handoffs, loop-brief, AUTONOMOUS-LOOP, ML_API_PUSH_PLAN, DASHBOARD-CONTRACT, FRONTEND_VERIFICATION, SCENARIO_API, BENCHMARK_RESULTS, history/) | 1–2h |
| 70 | **Resilience page self-contradiction**: after simulating, tiles say "Baseline 101.4 USD" while the table says $25,119.80 for the same BOM — backend `procurement_spend_at_risk_usd` values BOM at **unit prices ignoring quantity** (CVaR-95 $7.54 = $100.48×0.075); "0 component(s) affected" (`BOMImpactTable.tsx:44`) above a table showing 1 re-source; page lands nearly blank (auto-run default scenario on mount) | 4–6h |
| 68 | **Git authorship**: 244/290 commits by `Supply Chain Developer <student@logistics.local>` (unlinked grey avatar — zero GitHub credit to owner); 128 commits carry Claude co-author trailers; 8 `claude-*.yml` workflows + LEARNINGS.md + LOOP-DASHBOARD.md advertise the agent farm publicly. Fix identity going forward + README "how this was built" note; history rewrite (`git filter-repo --mailmap`) is owner's call — risky day-of-release | 1h + decision |
| 62 | Leakage docs describe an undeployed model: leakage_progression.json = random_forest/810 rows/R² −0.550; served = gradient_boosting/1143 rows/−0.35 (live /ml/model-comparison). PROJECT_OVERVIEW.md:69-71, ML_API_PUSH_PLAN.md:30, LEAKAGE_PROGRESSION.md all stale. Add artifact↔served gate | 3h |
| 60 | **Python 3.13.5 local venv vs 3.11 in CI/Render** (ci.yml:20,49; model-ci.yml:73; render.yaml:19) — artifacts pickled on 3.13, unpickled on 3.11; third instance of the env-drift bug class | 1–2h |
| 55 | **Shared stateful demo account**: /auth/demo returns user id:1 for everyone — visitors share one cart; anyone can wipe it | 3–5h |
| 50 | **Mobile unusable**: every page scrollWidth 1219px at 390px viewport; NavBar.tsx:38 non-wrapping 8-button row, no hamburger | 4–6h |
| 48 | Fulfillment P10/P50/P90 chart renders as solid teal blocks, no visible lines | 1–2h |
| 45 | Tests overwrite committed training data: `fetch_regime_feature_frame()` (fred_client.py:335-356) unconditionally `to_csv` on read, no ALFRED vintage pin — FRED already revised 5 months in place (2026-05 ip_semis 180.92→183.80). Revision leakage; Render container rewrites its own copy on first request | 3h |
| 40 | Zero frontend tests; verify_backend.py uses `always_ok` (any 200 passes) for 17/33 checks; mypy without --check-untyped-defs partly vacuous | 4h+ |
| 30 | Alembic decorative (0001–0008 never run; create_all does the work); real Postgres migration | 3h+ / $7/mo decision |
| 25 | **No inventory/reorder decision layer** (newsvendor, safety stock, service levels) — biggest substantive gap for SCOT-type roles; RESEARCH_TECHNIQUES.md §3.4 scopes it 3–4 days | 24–32h — NOT feasible by Sunday; state honestly in Limitations/Roadmap |

## Other findings worth keeping (from the audits)

- Live deploy is current (`fed1bb6` = HEAD); cold start 122s, warm ~80ms; all spot-checked endpoints
  return real populated bodies. `/ml/lead-time` also has **zero frontend callers** (mlAPI.leadTime defined
  services/api.ts:596, never invoked).
- Hidden gem nobody surfaces: `/benchmark/fiedler-curve` — removing DigiKey moves connectivity 0.0%, removing
  Newark (5th distributor) collapses it −53%.
- Checkout four strategies: only 2 genuinely distinct plans (honest banner exists); other three byte-identical.
- Login page: Demo Login is the de-emphasised grey secondary button; ~100s "Loading…" on cold start, no warning.
- Map: "Routes" tab default shows zero routes; legend mismatches Network Risk overlay colors; stray line artifact.
- `docs/screenshots/current/` = 24 tracked QA debug files, should be gitignored. One stale sc-benchmark.png (Jun 9).
- No secrets in repo history (verified). Recruiter audit's resume bullets + LinkedIn blurb: in the 2026-08-23
  recruiter audit output (4 XYZ bullets — CVaR frontier, leakage/49 gates, vintage-pinning, CRPS re-scoring).
- 67 UI screenshots from the audit in session scratchpad `audit/shots/` (ephemeral — may be gone after reset).
- claude-* loop workflows currently `disabled_manually`; loop bot last committed 2026-08-18.

## Sunday plan (agreed order)

1. Agent run on the six >85 items (in flight) → 2. verify (full local gates + fresh model-CI strict + tsc/build)
→ 3. commit + `./launch --anyway` (push = deploy) → 4. confirm live: green badge, README correct, panel gone,
Model Card clean, no path leak → 5. if time: TIED-badge fix (85) and polish batch (82) with approval.
Monday/Tuesday: CVaR UI (78), LICENSE/diagram/topics (74), docs index (72).

## Open decisions for the owner

1. Authorship: README note only, or also git history rewrite? (agents will NOT touch history)
2. PostgreSQL: correct the docs, or pay for real Postgres?
3. Rotate DigiKey/Nexar keys (open since the cleartext incident)?
4. ≤85 items above: which to approve next?

## Key commands / gotchas (from 2026-08-19 handoff — still valid)

```bash
cd backend && source venv/bin/activate
rm -f test_hardening.db && python -m pytest tests/ -q -p no:cacheprovider     # was 732 passed / 2 skipped
MODEL_CI_STRICT=1 python -m pytest tests/ -q -m model_ci -p no:cacheprovider  # was 49 gates (3 now fail in CI on py3.11)
python ../scripts/verify_backend.py     # against live
git checkout -- backend/seeds/data/regime_features_monthly.csv                # after ANY pytest run
./launch --anyway                       # deploy + verify build hash (use --anyway; agent-memory files are dirty)
```
Never kill pytest mid-flight (poisons test_hardening.db). CP-SAT needs num_search_workers=1 on macOS (already set).
Cart add returns 201. Tail metric is `cvar_95`, never `evar`. Benchmark retraction is intentional — do not "fix".
Live: UI https://supply-chain-ui-bhwz.onrender.com · API https://supply-chain-api-qy8x.onrender.com
Render backend srv-d98ru31o3t8c73ed9dig. CI/Render run **Python 3.11** — local venv is 3.13; test on 3.11 claims accordingly.
