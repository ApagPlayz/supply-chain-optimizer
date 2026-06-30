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
  `n_windows`, `seasonal_period`, FRED `series_id` (IPG3344S).
- **Metrics:** `wape`, `mape`, `rmse`, `bias`, `tracking_signal`, plus the
  seasonal-naive baseline (`naive_wape`, `naive_rmse`) and `skill_score` — all from
  the real rolling-origin walk-forward backtest over FRED IPG3344S.
- **Artifact:** a Prophet model fit on the full real series (`mlflow.prophet`).

## Champion selection

`select_champion(experiment, registered_model, metric="rmse")` queries every run in
an experiment that logged the metric, picks the **lowest RMSE**, registers that run's
model in the registry, and points the `champion` alias at the new version (with
`selection_metric` / `selection_value` / `source_run_id` provenance tags). Resolve it
later with `MlflowClient().get_model_version_by_alias("lead_time_predictor", "champion")`.

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
