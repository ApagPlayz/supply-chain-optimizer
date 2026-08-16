# The part-family leakage collapse, measured

Generated `2026-08-16T21:49:00Z` by `python -m seeds.run_leakage_progression` (backend/, venv active). Machine-readable: [`leakage_progression.json`](leakage_progression.json).

**Every number below is produced by that one command.** Earlier revisions of `MODEL_CI.md` and `RESEARCH_TECHNIQUES.md` quoted two different progressions from memory; this artifact is now the only source either of them cites.

## The headline

The same estimator (`random_forest`), the same 810 rows, the same feature pipeline and the same seed. **The only thing that changes is what the fold boundary is allowed to cut through.**

| Split regime | R² mean | R² median | fold sd | p10 | p90 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| random rows (**wrong**) | +0.638 | +0.638 | 0.079 | +0.535 | +0.730 | +0.443 | +0.785 |
| grouped by part-family key | +0.082 | +0.163 | 0.242 | -0.306 | +0.307 | -0.621 | +0.435 |
| grouped by manufacturer | -0.550 | -0.166 | 0.815 | -1.938 | +0.064 | -2.741 | +0.278 |

Mean R² **+0.638 → +0.082 → -0.550**; median R² **+0.638 → +0.163 → -0.166**. 810 rows, 467 family grouping keys, 27 manufacturers.

**467 grouping keys is not 467 part families**, and the two numbers are kept apart everywhere below. The fold groups are the output of `lead_time_model._group_key`, which emits `family:{base_product}` when DigiKey returned a base product, `mpn:{mpn}` when it did not, and `row:{i}` as a last resort. A fallback can only ever split a group, never merge two real families, so the key count (467) is a strict refinement of the **360 distinct `base_product` values** in the panel. Read as "part families", the right number is **360**; read as "what the fold boundary actually respects", it is **467**.

**The effective sample size for generalisation is 27 manufacturers, not 810 rows.** Three vendors (Analog Devices, Texas Instruments, STMicroelectronics) supply 66.0% of the panel, and 15 of the 27 vendors contribute 6 rows or fewer.

## What the negative number means, precisely

Holding out whole manufacturers, mean R² is **-0.550** and 40 of 50 folds score below zero. A negative R² is not a small positive one, and it is worth stating exactly what it is: R² is measured against the **held-out fold's own mean**, so R² < 0 means the model's squared error exceeds that vendor's entire label variance. On a vendor it has never quoted, the model has **no explanatory power at all** — it does not rank that vendor's parts correctly and its predicted level is biased for them.

It does **not** mean the model is beaten by every trivial predictor, and the honest version of the claim has to say so. Scored on those same manufacturer-held-out folds, `train_mean` gets -2.464 and `manufacturer_mean` gets -2.469 — both worse than the model's -0.550. The model is still the best of the set. It is simply the best member of a set in which **nothing generalises to an unseen vendor.**

The mechanism is visible in the baseline table below: under a random split, a lookup table keyed on nothing but the manufacturer scores +0.576 — almost the whole of the full model's +0.638. Vendor identity *is* the panel's signal, and holding a vendor out is precisely the operation that removes it. This is a statement about the dataset, not a bug in the estimator: 27 vendors is a small sample no matter how many rows they generate.

As a harness sanity check, `train_mean` scores -0.006 under the random regime — R² ≈ 0 for a constant predictor, which is what it must be if the scoring is right.

### Mean vs median, and why both are quoted

R² divides by the *test fold's own* label variance. Under the manufacturer regime a fold can be dominated by one vendor whose quotes barely vary, and that fold's R² blows up negative regardless of absolute error — which is why the mean (-0.550) sits far below the median (-0.166). RMSE has no such pathology, so it is reported alongside:

| Split regime | RMSE mean (days) | RMSE median (days) | fold sd |
|---|---:|---:|---:|
| random rows (**wrong**) | 61.93 | 60.65 | 7.68 |
| grouped by part-family key | 77.42 | 62.60 | 30.60 |
| grouped by manufacturer | 83.81 | 74.52 | 33.55 |

The RMSE progression tells the same story without the ratio artefact: error grows from 61.9 d to 83.8 d as the protocol gets honest.

## Naive baselines, on the identical folds

Every baseline is scored on exactly the folds above, so the comparison is paired. They come from `lead_time_model.baseline_predictors` — the same definitions the training path gates on — not from a copy living in this script.

| Predictor | random R² | family R² | manufacturer R² |
|---|---:|---:|---:|
| `ridge` | +0.524 | -0.140 | -4.829 |
| `random_forest` *(champion)* | +0.638 | +0.082 | -0.550 |
| `gradient_boosting` | +0.650 | +0.083 | -0.741 |
| `mlp` | +0.537 | -0.262 | -4.760 |
| `train_mean` *(baseline)* | -0.006 | -0.588 | -2.464 |
| `always_210d` *(baseline)* | -0.437 | -2.018 | -6.593 |
| `category_mean` *(baseline)* | +0.185 | -0.423 | -1.336 |
| `manufacturer_mean` *(baseline)* | +0.576 | -0.096 | -2.469 |

The collapse is not an artefact of one estimator — every model in the bake-off shows it, including the two linear/neural ones whose manufacturer-regime means are dominated by a handful of catastrophic folds. And the ordering does not invert: the champion beats every naive baseline under all three regimes. What changes is that under the manufacturer regime the whole table is negative.

The headline row is `random_forest` — the served champion, read from data/ml_models/metrics.joblib. This run's own lowest family-regime RMSE belongs to `gradient_boosting`, a different estimator. They are within noise of each other on this panel, and the headline deliberately follows what production serves rather than the best number available.

## A DIFFERENT quantity: in-sample identity-column R²

**These are not model scores and not cross-validated.** Each row fits a per-level mean on all rows and scores it on those same rows (one-way ANOVA R²). It quantifies how much *redundancy* the panel contains — the reason the random split is inflated — and must never be quoted as a split-regime R². A column with one level per row would score 1.000 by construction, so the level count is shown next to every figure.

| Identity column | in-sample R² | levels | rows/level |
|---|---:|---:|---:|
| `mpn` | 0.938 | 736 | 1.1 |
| `base_product` | 0.823 | 360 | 2.25 |
| `series` | 0.640 | 92 | 8.8 |
| `manufacturer` | 0.601 | 27 | 30.0 |
| `package_case` | 0.630 | 123 | 6.59 |
| `dk_category` | 0.203 | 16 | 50.62 |
| `category` | 0.523 | 52 | 15.58 |
| `family_group_key` | 0.878 | 467 | 1.73 |

This is the table that got conflated with the progression. `base_product` explaining 0.823 in sample is why a random split leaks; it is **not** the model's random-split score, which is +0.638.

## Protocol

- **Folds:** 5-fold, 10 independent shuffles = 50 folds per regime.
- **Seed:** `random_state = 42 + repeat`, identical across all three regimes.
- **Splitters:** `KFold(shuffle=True)` for `random`; `GroupKFold(shuffle=True)` for `family` and `manufacturer`.
- **Feature pipeline:** `lead_time_model.build_training_design` + `build_design_matrix`, feature schema v3, 173 columns — the same path `retrain_lead_time` uses.
- **Panel:** `backend/seeds/data/lead_time_panel/observed_lead_times.csv`, sha256 `ac6a4802fa59334e…`
- **Nothing is persisted.** All fits are in-memory; `backend/data/ml_models/` is not written by this script.

### Row accounting

| | rows |
|---|---:|
| rows in | 817 |
| dropped no label | 0 |
| dropped bad match | 6 |
| rows used | 811 |
| distinct family grouping keys | 467 |
| distinct snapshot dates | 2 |
| static cells filled | 697 |
| parts enriched | 817 |
| dropped unfillable | 1 |
| rows trained | 810 |
| distinct family grouping keys trained | 467 |
| distinct manufacturers trained | 27 |

### Regimes

- **`random`** — KFold(shuffle=True) on rows. The naive, WRONG protocol: near-duplicate siblings of one part family straddle the fold boundary, so the score measures recognition of an already-seen family, not prediction.
- **`family`** — GroupKFold on lead_time_model._group_key — family:{base_product} where DigiKey returned one, mpn:{mpn} otherwise. This is the protocol the shipped model uses. No family can straddle a fold. Note the key count exceeds the base_product level count because the MPN fallback splits the Unknown bucket; it never merges two real families.
- **`manufacturer`** — GroupKFold on the manufacturer. Whole vendors are held out — the strictest and most honest generalisation test, and the one that matches deployment.

### Environment

- hardware `arm64 / Darwin 25.5.0`, python `3.13.5`
- scikit-learn 1.8.0, numpy 2.4.4, pandas 2.3.3, scipy 1.17.1
- wall time 118.1s

## Reproduce

```bash
cd backend && source venv/bin/activate
python -m seeds.run_leakage_progression
```

## Provenance

- **Generated:** 2026-08-16T21:50:58Z (UTC)
- **Generator:** `seeds.run_leakage_progression`
- **Commit:** `241ae9e6959c8f53558556dcaae1f4b394d0dbca` — ⚠️ **DIRTY WORKING TREE.** UNCOMMITTED CHANGES: this artifact was generated from a working tree that did not match its git commit. Checking out the recorded SHA alone will NOT reproduce these numbers. Regenerate from a clean tree before treating them as published.
- **Input `lead_time_panel`:** `backend/seeds/data/lead_time_panel/observed_lead_times.csv` · sha256 `ac6a4802fa59334e…`
- **Python:** 3.13.5 · macOS-26.5-arm64-arm-64bit-Mach-O


