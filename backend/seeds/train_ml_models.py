"""
Training script for ML models.

Usage:
    cd backend
    python -m seeds.train_ml_models

Trains:
  1. Macro stress regime model (logistic regression on FRED time series)
  2. Four lead time regressors (Ridge, RF, GBM, MLP) on all DB offers

Saves models to backend/data/ml_models/ as .joblib files.
"""
from __future__ import annotations
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from app.core.config import settings
    from app.core.database import engine
    from app.ml import MLState, set_ml_state
    from app.ml import model_store
    from app.ml.fred_client import compute_stress_label, engineer_features, fetch_fred_data
    from app.ml.lead_time_model import build_feature_row, build_training_matrix, compute_target, train_all_models
    from app.ml.regime_model import get_current_stress_prob, train_regime_model
    from app.models.component import Component, DistributorOffer
    from app.models.distributor import Distributor
    from app.optimization.costs import haversine_km
    from sqlalchemy.orm import Session

    # 1. FRED pull
    logger.info("Pulling FRED macro data (api_key present: %s)...", bool(settings.FRED_API_KEY))
    fred_df = fetch_fred_data(settings.FRED_API_KEY, start="2010-01-01")

    if fred_df is not None and len(fred_df) >= 24:
        features_df = engineer_features(fred_df)
        labels = compute_stress_label(fred_df).reindex(features_df.index).fillna(0).astype(int)
        logger.info("FRED: %d monthly observations, %d stress months", len(features_df), int(labels.sum()))
        regime_pipe, regime_metrics = train_regime_model(features_df, labels)
        current_stress = get_current_stress_prob(regime_pipe, features_df)
        logger.info(
            "Regime model — val_acc=%.3f  shortage_recall=%.3f  current_stress=%.3f",
            regime_metrics.get("val_accuracy", 0),
            regime_metrics.get("shortage_recall", 0),
            current_stress,
        )
        model_store.save("regime", regime_pipe)
        model_store.save("regime_features", features_df)
    else:
        logger.warning("FRED data unavailable — using stress_prob=0.0 fallback")
        regime_pipe = None
        features_df = None
        current_stress = 0.0
        regime_metrics = {"val_accuracy": 0.0, "shortage_recall": 0.0}

    # 2. Build lead time training data from DB
    logger.info("Building lead time training dataset from DB...")
    USER_LAT, USER_LNG = 37.7749, -122.4194  # San Francisco default depot

    rows = []
    targets = []

    with Session(engine) as db:
        components = {c.id: c for c in db.query(Component).all()}
        distributors = {d.id: d for d in db.query(Distributor).all()}
        offers = db.query(DistributorOffer).all()

        for offer in offers:
            comp = components.get(offer.component_id)
            dist = distributors.get(offer.distributor_id)

            if not comp or not dist:
                continue

            # price field is 'price' (Float) per component.py
            price = offer.price
            if not price or price <= 0:
                continue

            # latitude/longitude fields per distributor.py
            dist_lat = dist.latitude
            dist_lng = dist.longitude
            if not dist_lat or not dist_lng:
                continue

            dist_km = haversine_km(USER_LAT, USER_LNG, dist_lat, dist_lng)

            # Tier based on total_offers field per distributor.py
            offer_count = dist.total_offers or 0
            tier = "major" if offer_count >= 500 else "mid" if offer_count >= 100 else "broker"

            # Chinese origin from risk_factors (JSON list) per component.py
            risk_factors = comp.risk_factors or []
            is_chinese = any("chinese" in str(f).lower() for f in risk_factors)

            # stock and moq fields per component.py
            stock = offer.stock or 0
            moq = offer.moq or 1
            stock_cov = stock / max(moq, 1)

            row = build_feature_row(
                category=comp.category or "Unknown",
                is_domestic=bool(dist.is_domestic),
                dist_km=dist_km,
                tier=tier,
                macro_stress=current_stress,
                risk_score=float(comp.risk_score or 0.5),
                stock_coverage=stock_cov,
                is_chinese_origin=is_chinese,
            )
            target = compute_target(comp.category or "Unknown", dist_km, current_stress)
            rows.append(row)
            targets.append(target)

    if not rows:
        logger.error("No valid offer rows found in DB — cannot train lead time models. Is the DB seeded?")
        sys.exit(1)

    logger.info(
        "Training on %d offer samples across %d categories",
        len(rows),
        len({r["category"] for r in rows}),
    )

    X, y, feature_cols = build_training_matrix(rows, targets)
    lt_results = train_all_models(X, y)

    best_name = min(lt_results, key=lambda k: lt_results[k]["rmse"])
    logger.info("Lead time model comparison:")
    for name, info in lt_results.items():
        marker = " <- best" if name == best_name else ""
        logger.info(
            "  %-20s RMSE=%6.1f  MAE=%6.1f  R²=%.4f%s",
            name,
            info["rmse"],
            info["mae"],
            info["r2"],
            marker,
        )

    model_store.save("lead_time", {k: v for k, v in lt_results.items()})
    model_store.save("feature_cols", feature_cols)
    model_store.save("metrics", {
        "regime": regime_metrics,
        "lead_time": {
            k: {"rmse": v["rmse"], "mae": v["mae"], "r2": v["r2"]}
            for k, v in lt_results.items()
        },
        "best_lead_time_model": best_name,
        "current_stress_prob": round(current_stress, 4),
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
