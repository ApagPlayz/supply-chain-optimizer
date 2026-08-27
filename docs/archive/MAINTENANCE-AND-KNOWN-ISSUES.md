# Maintenance notes & known open items

Written 2026-08-26, at the release of `c2936b2`. Operational notes for whoever maintains
this next — what will break on its own, what is deliberately unfinished, and what each
one would cost to fix. Substantive model limitations are disclosed in `README.md` and
`docs/DATA_PROVENANCE.md`; this file is about *operations*.

## Dated landmines

### 1. Weekly collector vs. the model-CI gates — armed every Monday

`.github/workflows/collect-lead-times.yml` commits new lead-time panel rows each Monday
06:00 UTC. New rows bring new `category` values, so the recomputed design matrix grows
one-hot columns: a simulated 2026-08-31 panel went from 1,922 rows / 263 columns to
2,664 rows / **324 columns**.

`test_model_ci_gates.py::test_committed_artifact_beats_a_naive_baseline_on_genuinely_held_out_data`
fails against that panel. It is marked `model_ci` but not `slow`, and `ci.yml` runs
`-m "not slow"`, so it fails in **both** required checks and blocks every deploy.

Two properties make this nastier than it sounds:

- The collector's own push does **not** trigger CI (GitHub's recursion prevention), so it
  arms silently and fires on the maintainer's next unrelated push.
- The error names a gate file that looks fine; the actual cause is data that moved.

**The established but undocumented maintenance step is a hand retrain after each collector
run** — see `f561d9f` (collector snapshot) followed by `cf00e43` ("the artifact must match
the committed panel"). Nobody performs that automatically.

A staleness escape hatch was added at release (mirroring the one
`test_lead_time_schema_contract.py` already had) so a legitimately-stale artifact produces
a loud warning rather than a hard block. **If you see this gate complain, the fix is to
retrain, not to widen the hatch.**

Retraining, if needed:

```bash
cd backend && ./venv/bin/python -m seeds.train_ml_models
```

Gotchas, both learned the hard way (see `LEARNINGS.md`):
- The trainer **ignores argv** — `--help` starts a real retrain.
- A killed run half-writes artifacts. Recover with
  `git checkout -- backend/data/ml_models backend/seeds/data`.
- The trainer rewrites two seed CSVs mid-run, so a clean provenance SHA needs: commit,
  then retrain again (the same-day rerun is byte-identical and tags clean).

### 2. Render free-tier limits

- Spins down after **15 minutes** idle; first visitor then waits **50–100 s**. Mitigated
  by a 150 s auth timeout and a "waking up" notice, but the wait is real. $7/mo Starter
  removes it entirely.
- **750 free instance hours per workspace per month**, shared across all free web
  services. Exhausting them **suspends every free service until the next month**. A 31-day
  month is 744 hours, so a 24/7 keep-alive ping is not safe on the free tier — restrict any
  ping to a daily window (≈13 h/day ≈ 53% of quota) or upgrade.
- Free services "might restart at any time" regardless.

## Deliberately unfinished

| Item | Effect | Effort |
|---|---|---|
| `graph_aware` never sent on the live optimizer | `services/api.ts` posts `/optimize/vrp` with no body, so the flag defaults false and the graph-surcharge path is dead in the live app. Resilient-sourcing figures in the docs come from the offline benchmark, which is now caveated. Wiring it on is one boolean but changes live output — **owner's decision**. | 30 min + re-verify |
| FRED regime path writes on read | `ml/fred_client.py::fetch_regime_feature_frame` unconditionally `to_csv`s into a **git-tracked** file and passes no `vintage_date`, unlike the pinned Census path in the same module. Can dirty the tree unexpectedly. | ~2 h |
| Python version skew | Artifacts pickled on 3.13.5; CI and Render run 3.11. Provenance stamps `sklearn_version` but not `python_version`. Stamping it requires a retrain to take effect. | ~1 h + retrain |
| Six `/market/*` routes live on public Swagger | No frontend consumer. Docstrings now say so honestly rather than claiming a wiring pass. | 30 min to delete |
| Benchmark page serves `run_id=4` (2026-07-06) | Docs publish `run_id=5`. **Deliberate keep** — a CLI re-run can only produce another `static_fallback` and would desync curated docs. Do not "fix" by re-running. | — |
| Newsvendor / inventory layer absent | Safety stock, reorder points, service levels — the concept Amazon-SCOT-type reviewers expect. Honestly scoped as absent in `RESEARCH_TECHNIQUES.md` §3.4. | 24–32 h |

## Verified healthy as of 2026-08-26

- Published benchmark numbers **reproduce exactly** from a clean out-of-tree re-run — all
  7 headline fields, every per-BOM row, all 18 resilience rows. The artifact's old
  "generated from a dirty tree, may not reproduce" warning is discharged.
- Live API matches `metrics.joblib` field-for-field; the panel CSV re-hashes to the
  recorded `training_data_sha256`.
- No secrets in git history (scanned); `.env` correctly ignored.
- No test fails purely because time passes — vintage pins, TTLs, timezone handling,
  month/quarter arithmetic and the 60-day horizon were all swept.
- `Loop — Metrics` and the other loop workflows are `disabled_manually`; they will not
  fire.
