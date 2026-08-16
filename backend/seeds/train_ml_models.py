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
    from app.ml.lead_time_model import evaluate_lead_time_ship_gate, retrain_lead_time
    from app.ml.regime_model import retrain_regime_model

    # ── 1. Regime model — real GSCPI target, lagged real FRED features ────────
    #
    # Evaluated by expanding-window walk-forward over ALL history, with BOTH
    # baselines (persistence-as-degenerate-probability and climatology) scored on
    # the same folds and hyperparameters frozen from a calibration window.
    #
    # HARD SHIP GATE, on a PROPER SCORING RULE: the model is persisted only if it
    # beats both baselines on Brier and is adequately calibrated. Accuracy is not
    # the gate — the optimizer consumes P(stress), not a class label, and on
    # accuracy this model merely ties persistence. See app/ml/regime_model.py.
    logger.info("Retraining regime model (GSCPI target, lagged FRED features)...")
    regime = retrain_regime_model()
    regime_pipe = regime["pipe"]
    features_df = regime["features"]
    regime_metrics = regime["metrics"]
    regime_gate = regime["ship_gate"]
    current_stress = regime["current_stress_prob"]

    _cal = regime_metrics.get("calibration") or {}
    logger.info(
        "Regime PROPER SCORING RULE (the ship gate) over %s folds — "
        "Brier: model=%s persistence=%s climatology=%s | "
        "LogLoss: model=%s persistence=%s climatology=%s | "
        "calibration slope=%s ECE=%s",
        regime_metrics.get("n_folds"),
        regime_metrics.get("brier"), regime_metrics.get("baseline_brier"),
        regime_metrics.get("climatology_brier"),
        regime_metrics.get("log_loss"), regime_metrics.get("baseline_log_loss"),
        regime_metrics.get("climatology_log_loss"),
        _cal.get("calibration_slope"), _cal.get("expected_calibration_error"),
    )
    for _bl, _pb in (regime_metrics.get("paired_brier") or {}).items():
        logger.info(
            "  paired Brier %s: reduction %s, 95%% CI [%s, %s], significant=%s, wins %s of folds",
            _bl, _pb.get("mean_brier_reduction"), _pb.get("ci95_low"),
            _pb.get("ci95_high"), _pb.get("significant"), _pb.get("fold_win_rate"),
        )
    logger.info(
        "Regime accuracy (REPORTED, not the gate) — acc=%s  persistence=%s  delta=%s  "
        "McNemar p=%s  macro_f1=%s (persistence %s)",
        regime_metrics.get("walk_forward_accuracy"),
        regime_metrics.get("baseline_accuracy"),
        regime_metrics.get("accuracy_delta_vs_baseline"),
        regime_metrics.get("mcnemar_p_value"),
        regime_metrics.get("macro_f1"),
        regime_metrics.get("baseline_macro_f1"),
    )
    if regime_metrics.get("recent_era_accuracy") is not None:
        logger.info(
            "Regime 2019+ slice — acc=%s  persistence=%s  (n=%s)",
            regime_metrics.get("recent_era_accuracy"),
            regime_metrics.get("recent_era_baseline_accuracy"),
            regime_metrics.get("recent_era_n"),
        )
    if regime_gate["passed"] and regime_pipe is not None:
        logger.info("Regime SHIP GATE PASSED (%s) — persisting; current_stress=%.4f",
                    regime_gate["reason"], current_stress)
        model_store.save("regime", regime_pipe)
        model_store.save("regime_features", features_df)
    else:
        logger.warning("Regime SHIP GATE FAILED — model NOT persisted, NOT served. %s",
                       regime_gate["reason"])
        # Remove any previously-persisted regime artifact so a stale, failing
        # model cannot keep answering after a retrain says it should not.
        for name in ("regime", "regime_features"):
            stale = model_store.path(name)
            if stale.exists():
                stale.unlink()
                logger.warning("removed stale artifact %s (failed ship gate)", stale)

    # ── 2. Lead-time models — real observed panel only (no synthetic fallback) ─
    logger.info("Retraining lead-time models on real observed panel...")
    lt = retrain_lead_time()

    lt_results = None
    lt_baselines = None
    feature_cols = None
    best_name = None

    lt_gate = evaluate_lead_time_ship_gate(lt)

    if lt["status"] == "trained":
        lt_results = lt["models"]
        lt_baselines = lt["baselines"]
        feature_cols = lt["feature_cols"]
        best_name = lt["best"]
        logger.info(
            "Lead-time model comparison (%d real observations, %d features, schema v%d).",
            lt["n_samples"], lt["n_features"], lt["feature_schema_version"],
        )
        logger.info("Resolved feature columns: %s", feature_cols)
        for exc in lt.get("feature_exclusions", []):
            logger.info("  DECLARED BUT EXCLUDED  %-20s %s", exc["feature"], exc["reason"])
        logger.info(
            "Quote the CV columns — splits are GROUPED BY PART FAMILY (base_product), "
            "because base_product alone explains R2~0.95 of the target and an ungrouped "
            "split would score memorisation of a part family."
        )
        logger.info("  %-20s %8s %8s %9s | %14s %14s",
                    "model", "RMSE", "MAE", "R2", "cv_RMSE(±sd)", "cv_R2(±sd)")
        for name, info in lt_results.items():
            marker = " <- best" if name == best_name else ""
            logger.info(
                "  %-20s %8.2f %8.2f %9.4f | %6.2f±%-6.2f %6.4f±%-6.4f%s",
                name, info["rmse"], info["mae"], info["r2"],
                info["cv_rmse_mean"], info["cv_rmse_std"],
                info["cv_r2_mean"], info["cv_r2_std"], marker,
            )
        for name, info in lt_baselines.items():
            logger.info(
                "  %-20s %8.2f %8.2f %9.4f | %6.2f±%-6.2f %6.4f±%-6.4f  (naive baseline, beaten=%s)",
                name, info["rmse"], info["mae"], info["r2"],
                info["cv_rmse_mean"], info["cv_rmse_std"],
                info["cv_r2_mean"], info["cv_r2_std"], lt["baselines_beaten"][name],
            )
        if not lt["beats_baselines"]:
            logger.warning(
                "Lead-time champion %s does NOT beat every naive baseline on mean CV RMSE "
                "— report that, do not bury it.", best_name,
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

        # HARD SHIP GATE, mirroring the regime model: a lead-time model that does
        # not beat its own naive baselines by a margin separated from zero does
        # not get persisted. Computing baselines and then shipping regardless is
        # exactly the inconsistent rigor this project keeps finding and removing.
        if lt_gate["passed"]:
            logger.info("Lead-time SHIP GATE PASSED (%s) — persisting.", lt_gate["reason"])
            model_store.save("lead_time", {k: v for k, v in lt_results.items()})
            model_store.save("feature_cols", feature_cols)
        else:
            logger.warning(
                "Lead-time SHIP GATE FAILED — model NOT persisted, NOT served. %s",
                lt_gate["reason"],
            )
            for _name in ("lead_time", "feature_cols"):
                _stale = model_store.path(_name)
                if _stale.exists():
                    _stale.unlink()
                    logger.warning("removed stale artifact %s (failed ship gate)", _stale)
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
    from app.ml.lead_time_collector import PANEL_PATH

    model_store.save("metrics", {
        # WHEN, from WHAT data, at WHICH commit. Without this you cannot tell
        # which panel produced which artifact, so no staleness or reproducibility
        # claim is possible.
        "provenance": model_store.build_provenance(
            training_data_path=PANEL_PATH,
            n_training_rows=lt.get("n_samples"),
            n_panel_rows=(lt.get("panel_rows") or {}).get("rows_in"),
            n_distinct_families=(lt.get("panel_rows") or {}).get("distinct_families_trained"),
            n_snapshot_dates=(lt.get("panel_rows") or {}).get("distinct_snapshot_dates"),
            lead_time_status=lt.get("status"),
        ),
        "lead_time_ship_gate": lt_gate,
        "regime": regime_metrics,
        # The gate decision travels with the metrics so app/ml/serving.py can
        # refuse a failing model even if someone leaves a regime.joblib on disk.
        "regime_ship_gate": regime_gate,
        "lead_time": (
            {k: {kk: vv for kk, vv in v.items() if kk != "model"} for k, v in lt_results.items()}
            if lt_results else {"status": lt["status"], "reason": lt.get("reason")}
        ),
        "lead_time_baselines": lt_baselines,
        "lead_time_beats_baselines": lt.get("beats_baselines"),
        "lead_time_toughest_baseline": lt.get("toughest_baseline"),
        "lead_time_skill_vs_toughest_baseline": lt.get("skill_vs_toughest_baseline"),
        # PAIRED per-fold comparison against the toughest baseline on the
        # identical grouped folds — the statistic to quote, not the marginal sds.
        "lead_time_paired_vs_toughest_baseline": lt.get("paired_vs_toughest_baseline"),
        # The three-number leakage progression. Recorded on every retrain because
        # it is worth more than any model metric here: it is the measurement of
        # how much independent information the panel actually contains.
        "lead_time_leakage_audit": lt.get("leakage_audit"),
        "lead_time_n_manufacturers": lt.get("n_manufacturers"),
        "lead_time_panel_rows": lt.get("panel_rows"),
        "lead_time_aggregate_backtest": lead_time_backtest_metrics,
        "best_lead_time_model": best_name,
        "feature_cols": feature_cols,
        "feature_schema_version": lt.get("feature_schema_version"),
        # Every declared candidate that did NOT make the cut, and why. Published
        # by /ml/model-comparison so a dropped feature is never silent.
        "feature_exclusions": lt.get("feature_exclusions"),
        # NOTE: `current_stress_prob` is deliberately NOT stored here any more.
        # It used to be replayed at serve time months after it was computed
        # (0.9967, baked 2026-07-10) as if it were live model output. The regime
        # signal is now resolved at load time by app/ml/serving.resolve_regime_signal.
        # REAL fit-time shape — /ml/model-comparison reports this instead of a
        # hardcoded number (it used to claim 8731, the offer count, not the panel size).
        "n_training_samples": lt.get("n_samples") if lt["status"] == "trained" else None,
        "n_features": lt.get("n_features") if lt["status"] == "trained" else None,
    })

    if not lt_gate["passed"]:
        lt_results = None
        feature_cols = None
        best_name = None

    set_ml_state(MLState(
        regime_model=regime_pipe if regime_gate["passed"] else None,
        regime_features=features_df if regime_gate["passed"] else None,
        lead_time_models=lt_results,
        best_lead_time_model=best_name,
        current_stress_prob=current_stress,
        feature_columns=feature_cols,
        regime_status={
            "available": bool(regime_gate["passed"]),
            "source": "model" if regime_gate["passed"] else "unavailable_failed_ship_gate",
            "reason": regime_gate["reason"],
            "ship_gate": regime_gate,
            "metrics": regime_metrics,
        },
    ))
    logger.info("ML models trained and loaded. Run complete.")


if __name__ == "__main__":
    main()
