"""
Training script for ML models (Route A — real observed data only).

Usage:
    cd backend
    python -m seeds.train_ml_models

Trains:
  1. Macro stress-regime model — predicts the independent NY Fed GSCPI regime
     from lagged real FRED series (no tautology; see app/ml/regime_model.py).
  2. Lead-time regressors — trained ONLY on real observed lead times collected
     from DigiKey/Mouser (app/ml/lead_time_collector.py). If no observed panel
     exists yet, training is SKIPPED honestly — there is no synthetic fallback.

Saves models to backend/data/ml_models/ as .joblib files.
"""
from __future__ import annotations
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from app.ml import MLState, set_ml_state
    from app.ml import model_store
    from app.ml.lead_time_model import retrain_lead_time
    from app.ml.regime_model import retrain_regime_model

    # ── 1. Regime model — real GSCPI target, lagged real FRED features ────────
    logger.info("Retraining regime model (GSCPI target, lagged FRED features)...")
    regime = retrain_regime_model()
    regime_pipe = regime["pipe"]
    features_df = regime["features"]
    regime_metrics = regime["metrics"]
    current_stress = regime["current_stress_prob"]

    if regime_pipe is not None:
        logger.info(
            "Regime model — val_acc=%.3f  baseline_acc=%s  stress_recall=%.3f  current_stress=%.3f",
            regime_metrics.get("val_accuracy", 0),
            regime_metrics.get("baseline_accuracy"),
            regime_metrics.get("shortage_recall", 0),
            current_stress,
        )
        model_store.save("regime", regime_pipe)
        model_store.save("regime_features", features_df)
    else:
        logger.warning("Regime data unavailable — serving stress_prob=0.0 fallback")

    # ── 2. Lead-time models — real observed panel only (no synthetic fallback) ─
    logger.info("Retraining lead-time models on real observed panel...")
    lt = retrain_lead_time(macro_stress=current_stress)

    lt_results = None
    feature_cols = None
    best_name = None

    if lt["status"] == "trained":
        lt_results = lt["models"]
        feature_cols = lt["feature_cols"]
        best_name = lt["best"]
        logger.info("Lead-time model comparison (%d real observations):", lt["n_samples"])
        for name, info in lt_results.items():
            marker = " <- best" if name == best_name else ""
            logger.info(
                "  %-20s RMSE=%6.1f  MAE=%6.1f  R²=%.4f%s",
                name, info["rmse"], info["mae"], info["r2"], marker,
            )

        # MLflow tracking (best-effort; must not lose the models we just persisted).
        if os.environ.get("DISABLE_MLFLOW") != "1":
            try:
                from app.ml.mlflow_tracking import log_lead_time_models

                mlflow_out = log_lead_time_models(
                    lt_results,
                    n_samples=lt["n_samples"],
                    n_features=lt["n_features"],
                    extra_params={
                        "target": "observed_lead_time_days",
                        "current_stress_prob": round(current_stress, 4),
                        "source": "DigiKey/Mouser observed panel",
                    },
                )
                champ = mlflow_out.get("champion")
                if champ:
                    logger.info(
                        "MLflow champion: %s (RMSE=%.2f) registered as %s v%s [alias=%s]",
                        champ["model_name"], champ["value"],
                        champ["registered_model"], champ["version"], champ["alias"],
                    )
            except Exception as exc:  # noqa: BLE001 - tracking is non-critical
                logger.warning("MLflow tracking skipped (%s)", exc)

        model_store.save("lead_time", {k: v for k, v in lt_results.items()})
        model_store.save("feature_cols", feature_cols)
    else:
        logger.warning(
            "Lead-time training SKIPPED (%s, n=%d) — run the collector "
            "(`python -m app.ml.lead_time_collector`) to accumulate observed "
            "lead times, then re-run. No synthetic fallback is used.",
            lt.get("reason"), lt.get("n_samples", 0),
        )

    # ── 3. Real historical backtest: predict Susquehanna lead-time index ──────
    lead_time_backtest_metrics = None
    try:
        from app.ml.lead_time_backtest import run_backtest

        lead_time_backtest_metrics = run_backtest()
        logger.info(
            "Lead-time aggregate backtest (Susquehanna vs lagged GSCPI+IPG3344S): "
            "MAE=%.2fwk  R²=%.2f  skill_vs_mean=%.0f%%",
            lead_time_backtest_metrics.get("loo_mae_weeks", float("nan")),
            lead_time_backtest_metrics.get("loo_r2", float("nan")),
            100 * lead_time_backtest_metrics.get("skill_vs_baseline", 0),
        )
    except Exception as exc:  # noqa: BLE001 - historical backtest is non-critical
        logger.warning("Lead-time aggregate backtest skipped (%s)", exc)

    # ── 4. Persist combined metrics + load into serving state ─────────────────
    model_store.save("metrics", {
        "regime": regime_metrics,
        "lead_time": (
            {k: {"rmse": v["rmse"], "mae": v["mae"], "r2": v["r2"]}
             for k, v in lt_results.items()}
            if lt_results else {"status": lt["status"], "reason": lt.get("reason")}
        ),
        "lead_time_aggregate_backtest": lead_time_backtest_metrics,
        "best_lead_time_model": best_name,
        "current_stress_prob": round(current_stress, 4),
        # REAL fit-time shape — /ml/model-comparison reports this instead of a
        # hardcoded number (it used to claim 8731, the offer count, not the panel size).
        "n_training_samples": lt.get("n_samples") if lt["status"] == "trained" else None,
        "n_features": lt.get("n_features") if lt["status"] == "trained" else None,
    })

    set_ml_state(MLState(
        regime_model=regime_pipe,
        regime_features=features_df,
        lead_time_models=lt_results,
        best_lead_time_model=best_name,
        current_stress_prob=current_stress,
        feature_columns=feature_cols,
    ))
    logger.info("ML models trained and loaded. Run complete.")


if __name__ == "__main__":
    main()
