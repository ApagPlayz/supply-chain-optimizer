# Route A Build Plan — Real Observed Data Overhaul (started 2026-07-01)

**Decision (2026-07-01):** Route A ("make it real"). Replace the three synthetic/leaked
ML targets with genuinely observed data. User confirmed: get DigiKey + Mouser keys, build
all three tracks in parallel. This supersedes the earlier Route-B lean in
`docs/GAP_AUDIT_2026-07-01.md`.

## The core problem being fixed
Three models don't actually learn — their targets are functions of their own inputs:
1. **Lead-time model** — target = a formula (`base_days × macro × distance`), not observed.
2. **Demand forecaster** — one FRED macro curve × per-part scalar; per-part magnitude is fake.
3. **Regime classifier** — label = threshold on its own feature series (tautology).

## What research (4 parallel scouts, 2026-07-01) proved is obtainable — all real
- **Lead-time:** DigiKey `ManufacturerLeadWeeks` + Mouser `LeadTime` = real per-part lead
  times, free, 1000 calls/day each. No free *historical* per-part series exists → build a
  weekly snapshot collector (own panel = data moat) + reconstruct 2021–23 Susquehanna
  aggregate for a historical backtest.
- **Demand:** Census M3 `A34SNO` (New Orders, Computers & Electronic Products, $, monthly
  1992→now, keyless FRED CSV) = real macro target. WSTS billings (free Excel) = corroboration.
  Per-SKU demo: Monash Car Parts (2,600+ real intermittent series, CC-BY). **No public
  per-SKU electronic-component demand dataset exists — document this honestly.**
- **Regime:** NY Fed **GSCPI** = independent externally-published target; predict from lagged
  real FRED series (`CAPUTLG3344S`, `U34SIS`, `IPG3344S`, `MNFCTRIRSA`). Keyless. ~30 yrs.
  PortWatch (keyless ArcGIS) = v2 observed shipping-stress enrichment.

## Fetch endpoints (verified live 2026-07-01)
- FRED keyless CSV: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`
- Census M3 direct: `https://api.census.gov/data/timeseries/eits/advm3`
- GSCPI: `https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx`
  (⚠ legacy OLE2 .xls — read with `pandas.read_excel`, sheet "GSCPI Monthly Data", NOT openpyxl)
- WSTS Historical Billings Report: free Excel at wsts.org/67/Historical-Billings-Report
- Monash Car Parts: Zenodo record 3994911 (CC-BY 4.0), also HF `Monash-University/monash_tsf`
- PortWatch: `https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Ports_Data/FeatureServer/0/query`
- DigiKey dev portal: developer.digikey.com (Product Info V4 + Supply Chain). Mouser: mouser.com/api-hub

## Existing repo plumbing (from codebase-map scout)
- `backend/app/core/clients/` — real `DigiKeyClient` (returns `lead_time_weeks`), `NexarClient`,
  `OEMSecretsClient`, `TrustedPartsClient`, all wired into `app/api/live_prices.py`. Need keys.
- `backend/app/ml/fred_client.py` — keyed + keyless FRED paths already exist.
- `backend/seeds/train_forecasts.py` — Prophet per-part; keyless IPG3344S shape (real) × synthetic magnitude.
- `backend/seeds/train_ml_models.py` — trains lead-time + regime (ORCHESTRATOR — reserved for main).
- `backend/app/ml/lead_time_model.py`, `lead_time_labels.py`, `regime_model.py` — model defs.
- DB: `component_demand_history`, `component_forecasts` tables; no lead-time table yet.

## Track ownership (parallel build — strict file boundaries to avoid conflicts)
- **Track D — Demand** (owns): `seeds/train_forecasts.py`, new Monash loader, `ml/backtest.py`,
  demand-related DB seed. Deliver: real Census M3 target + Monash per-SKU backtest.
- **Track R — Regime** (owns): `ml/regime_model.py`, GSCPI additions to `ml/fred_client.py`,
  new regime-retrain function. Deliver: GSCPI target, lagged real features, honest metrics.
- **Track L — Lead-time** (owns): `ml/lead_time_model.py`, `ml/lead_time_labels.py`, new
  `collector` module, DigiKey/Mouser training-data prep, reconstructed SIG aggregate + backtest.
- **RESERVED for main loop (do NOT let agents touch):** `seeds/train_ml_models.py` orchestration,
  `app/core/config.py` (new keys), Alembic migrations, `render.yaml`, README/docs de-bannering,
  MLflow champion wiring, final integration.

## Integration contract
Each track exposes a clean retrain/backtest function returning real metrics + persisted artifacts;
main loop wires them into `train_ml_models.py`, adds config keys, DB migrations, and rewrites all
"demand is REAL / nothing fabricated" claims to honest scoping language.

## Status (updated 2026-07-01 — all built + integrated + verified)
- [x] Track D — demand: Census M3 A34SNO backtest (Prophet +39–43% WAPE vs naive) +
      Monash per-SKU intermittent backtest (TSB beats Prophet & naive). Honest labels.
- [x] Track R — regime: GSCPI target, lagged FRED features. Non-tautological (max
      feat↔label corr 0.43). Honest metrics: model 0.73 vs persistence 0.83; FRED-only
      0.45 → real finding that US-semi indicators don't predict global GSCPI.
- [x] Track L — lead-time: Mouser client + weekly snapshot collector (75 REAL DigiKey
      rows pulled) + retrain on observed panel (RF R²=0.93 on real obs, no formula) +
      reconstructed Susquehanna aggregate backtest (R²=0.75, 60% skill vs mean).
- [x] Integration: rewired train_ml_models.py to the 3 real retrain fns; dropped synthetic
      compute_target path; added MOUSER_API_KEY + xlrd; fixed lead_time_backtest to fetch
      IPG3344S live; de-bannered RESILIENCE_INTERVIEW_GUIDE.md.
- [x] Verified: `python -m seeds.train_ml_models` runs clean end-to-end; **243 tests pass**
      (conftest imports fine in the real venv — agents' "conftest break" was env-transient).
- [~] User: DigiKey keys ALREADY live in env (collector works). **Mouser key still pending.**

## Remaining (next session / polish)
- Wire the collector to run weekly (APScheduler like the feeds scheduler, or a cron) so the
  per-part panel grows past 75 rows → stronger real lead-time model over time.
- Add MOUSER_API_KEY to render.yaml / prod env once the user provides it.
- Consider committing trained models or building at deploy (audit 2.1) — decide DB/model
  git-blob strategy.
- Reframe the regime model's "matches persistence" result as the sharper finding
  (domestic semi indicators ≠ global supply-chain stress predictor) in the interview guide.
- Broader de-banner pass across README/frontend for any remaining "all real" overclaims.
