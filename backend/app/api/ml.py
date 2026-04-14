"""
ML Intelligence API endpoints.

GET /ml/stress             — current macro stress probability + FRED indicator snapshot
GET /ml/model-comparison   — lead time model RMSE/MAE/R² table
GET /ml/lead-time          — predict lead time for a (category, distance, tier) query
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ml import get_ml_state
from app.ml.lead_time_model import build_feature_row, predict_lead_time
from app.ml.lead_time_labels import get_base_days, DEFAULT_LEAD_DAYS

router = APIRouter(prefix="/ml", tags=["ml"])


class StressResponse(BaseModel):
    stress_probability: float
    stress_level: str           # "low" | "moderate" | "high"
    regime_active: bool
    val_accuracy: Optional[float]
    shortage_recall: Optional[float]
    interpretation: str


class ModelMetrics(BaseModel):
    name: str
    rmse: float
    mae: float
    r2: float
    is_best: bool


class ModelComparisonResponse(BaseModel):
    models: List[ModelMetrics]
    best_model: str
    training_samples: int


class LeadTimePrediction(BaseModel):
    category: str
    is_domestic: bool
    dist_km: float
    tier: str
    macro_stress: float
    base_days: int
    predicted_days: float
    model_used: str


@router.get("/stress", response_model=StressResponse)
def get_macro_stress():
    """
    Returns the current semiconductor supply chain macro stress probability.
    Derived from 6 FRED time series via logistic regression.
    0.0 = no stress; 1.0 = full shortage regime.
    """
    state = get_ml_state()
    if state is None or state.regime_model is None:
        return StressResponse(
            stress_probability=0.0,
            stress_level="unknown",
            regime_active=False,
            val_accuracy=None,
            shortage_recall=None,
            interpretation="ML models not loaded. Run: python -m seeds.train_ml_models",
        )

    prob = state.current_stress_prob
    if prob >= 0.70:
        level, active = "high", True
    elif prob >= 0.35:
        level, active = "moderate", False
    else:
        level, active = "low", False

    return StressResponse(
        stress_probability=round(prob, 4),
        stress_level=level,
        regime_active=active,
        val_accuracy=None,  # available in metrics.joblib if needed
        shortage_recall=None,
        interpretation=(
            f"Semiconductor shortage stress is {level} ({prob:.0%}). "
            + (
                "Current macro conditions match historical shortage regimes — "
                "expect extended lead times and availability risk premiums in the optimizer."
                if active else
                "Normal supply conditions — lead time estimates reflect baseline category averages."
            )
        ),
    )


@router.get("/model-comparison", response_model=ModelComparisonResponse)
def get_model_comparison():
    """
    Returns held-out test set metrics for all 4 lead time models.
    Ridge Regression (baseline), Random Forest, Gradient Boosting, MLP Neural Net.
    """
    state = get_ml_state()
    if state is None or not state.lead_time_models:
        raise HTTPException(
            status_code=503,
            detail="ML models not loaded. Run: python -m seeds.train_ml_models",
        )

    models_out = [
        ModelMetrics(
            name=name,
            rmse=info["rmse"],
            mae=info["mae"],
            r2=info["r2"],
            is_best=(name == state.best_lead_time_model),
        )
        for name, info in state.lead_time_models.items()
    ]
    models_out.sort(key=lambda m: m.rmse)

    return ModelComparisonResponse(
        models=models_out,
        best_model=state.best_lead_time_model,
        training_samples=8731,  # total offers in DB
    )


@router.get("/lead-time", response_model=LeadTimePrediction)
def predict_lead_time_endpoint(
    category: str = "Microcontrollers",
    is_domestic: bool = True,
    dist_km: float = 500.0,
    tier: str = "major",
):
    """
    Predict component lead time for a given (category, distance, tier) combination.
    Uses the best-performing lead time model and current macro stress probability.
    """
    state = get_ml_state()
    if state is None or not state.lead_time_models:
        raise HTTPException(
            status_code=503,
            detail="ML models not loaded. Run: python -m seeds.train_ml_models",
        )

    if tier not in ("major", "mid", "broker"):
        raise HTTPException(status_code=422, detail="tier must be 'major', 'mid', or 'broker'")

    macro_stress = state.current_stress_prob
    best_model_info = state.lead_time_models[state.best_lead_time_model]

    row = build_feature_row(
        category=category,
        is_domestic=is_domestic,
        dist_km=dist_km,
        tier=tier,
        macro_stress=macro_stress,
        risk_score=0.5,       # neutral default for endpoint query
        stock_coverage=10.0,  # neutral default
        is_chinese_origin=False,
    )

    predicted = predict_lead_time(
        best_model_info["model"], row, state.feature_columns
    )

    return LeadTimePrediction(
        category=category,
        is_domestic=is_domestic,
        dist_km=round(dist_km, 1),
        tier=tier,
        macro_stress=round(macro_stress, 4),
        base_days=get_base_days(category),
        predicted_days=round(predicted, 1),
        model_used=state.best_lead_time_model,
    )
