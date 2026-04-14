"""
Joblib-based model persistence.

Models are saved to backend/data/ml_models/ as .joblib files.
This directory is gitignored (large binary files); models are regenerated
by running: python -m seeds.train_ml_models
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import joblib

logger = logging.getLogger(__name__)

# Relative to backend/ root
_MODEL_DIR = Path(__file__).parent.parent.parent / "data" / "ml_models"


def _path(name: str) -> Path:
    return _MODEL_DIR / f"{name}.joblib"


def save(name: str, obj: Any) -> None:
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(obj, _path(name))
    logger.info("saved ml model: %s", name)


def load(name: str) -> Optional[Any]:
    p = _path(name)
    if not p.exists():
        return None
    return joblib.load(p)


def models_exist() -> bool:
    # regime.joblib is optional (skipped when FRED is unavailable); lead_time is always required
    return _path("lead_time").exists()
