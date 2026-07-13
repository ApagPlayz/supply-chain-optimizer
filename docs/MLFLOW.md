# MLflow Experiment Tracking + Model Registry (P5)

Every ML training run in this project is tracked with [MLflow](https://mlflow.org):
parameters, the **real backtest metrics** (no fabricated numbers), and the fitted
model artifact. The lowest-RMSE model in each experiment is automatically promoted
to **champion** in the MLflow Model Registry.

Core module: [`backend/app/ml/mlflow_tracking.py`](../backend/app/ml/mlflow_tracking.py).

## What gets logged

### Experiment `lead_time_models` (registered model `lead_time_predictor`)
One parent run (`lead_time_training`) with four nested runs — Ridge, RandomForest,
GradientBoosting, MLP. For each:

- **Params:** estimator class + its hyperparameters (`hp_alpha`, `hp_n_estimators`,
  `hp_max_depth`, `hp_hidden_layer_sizes`, …), plus dataset size and the 0.2 test split.
- **Metrics:** `rmse`, `mae`, `r2` — the holdout numbers computed by
  `lead_time_model.train_all_models` (the existing evaluation, reused verbatim).
- **Artifact:** the fitted sklearn estimator (`mlflow.sklearn`).

### Experiment `demand_forecast` (registered model `prophet_demand_forecast`)
One run (`prophet_backtest`):

- **Params:** seasonality config (yearly on, weekly/daily off), `horizon`,
  `n_windows`, `seasonal_period`, `series_id` (Census M3 / FRED **A34SNO** —
  Manufacturers' New Orders: Computers & Electronic Products).
- **Metrics:** `wape`, `mape`, `rmse`, `bias`, `tracking_signal`, plus the
  seasonal-naive baseline (`naive_wape`, `naive_rmse`) and `skill_score` — all from
  the real rolling-origin walk-forward backtest over A34SNO.
- **Artifact:** a Prophet model fit on the full real series (`mlflow.prophet`).

## Champion selection

`select_champion(experiment, registered_model, metric="rmse")` queries every run in
an experiment that logged the metric, picks the **lowest RMSE**, registers that run's
model in the registry, and points the `champion` alias at the new version (with
`selection_metric` / `selection_value` / `source_run_id` provenance tags).

## Serving: which model actually answers a request

> Until 2026-07-12 the registry was **decorative with respect to serving** — training
> set the `champion` alias, but the API loaded `data/ml_models/lead_time.joblib` at
> startup and never resolved it. That is fixed; the resolution order below is what the
> process really does ([`app/ml/serving.py`](../backend/app/ml/serving.py)).

At startup (`app.main:lifespan` → `app.ml.serving.load_ml_state`):

1. **MLflow registry** — if a store is reachable (`MLFLOW_TRACKING_URI` set, or the
   local `backend/mlruns/mlflow.db` exists), load `models:/lead_time_predictor@champion`
   and serve that exact model version. `/ml/lead-time` and the optimizer's ML lead-time
   estimator (`app/optimization/costs.py`) both use it.
2. **On-disk joblib fallback** — otherwise serve `backend/data/ml_models/lead_time.joblib`
   (committed on purpose). **This is the live path on Render:** the free tier runs no
   MLflow server, so `model_source` there is `local_joblib`, and the API says so rather
   than pretending otherwise.

Check which one is live:

```bash
curl -s localhost:8000/api/v1/ml/model-info | jq
# { "model_source": "local_joblib" | "mlflow_registry",
#   "model_name": "random_forest", "model_version": null,
#   "fallback_reason": "no MLflow store: MLFLOW_TRACKING_URI unset and .../mlruns/mlflow.db does not exist ...",
#   "detail": "..." }
```

`GET /ml/lead-time` also carries `model_source` / `model_version` on every prediction.
Set `MLFLOW_SERVING=off` to skip the registry probe entirely (deploy image).

## Storage

Local and infra-free. Defaults to a SQLite tracking + registry store at
`backend/mlruns/mlflow.db` (MLflow 3 put the bare filesystem store in maintenance
mode, so SQLite is the supported local backend). Override the location with the
`MLFLOW_TRACKING_URI` environment variable. The store is gitignored.

## Run training with tracking

```bash
cd backend
source venv/bin/activate

# Lead-time models (logs 4 runs + selects champion by RMSE)
python -m seeds.train_ml_models

# Prophet demand forecast (logs the real backtest run + selects champion)
python -m seeds.run_forecast_backtest

# Re-select champions from already-logged runs, no retraining:
python -m seeds.select_champion            # both experiments
python -m seeds.select_champion lead_time  # or: forecast
```

Set `DISABLE_MLFLOW=1` to skip tracking (training still runs and saves models).

## View the MLflow UI

```bash
cd backend
mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db
# open http://127.0.0.1:5000
```

The **Experiments** tab compares the four lead-time runs side by side (sort by RMSE);
the **Models** tab shows `lead_time_predictor` / `prophet_demand_forecast` with the
`champion` alias on the winning version.
