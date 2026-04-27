"""TDD RED phase tests for Task 1: ORM models and prophet pin.

These tests MUST fail before implementation (Task 1 RED phase).
They pass after forecast.py is created (Task 1 GREEN phase).
"""
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-characters-long-for-testing")
os.environ.setdefault("DEBUG", "true")


def test_forecast_models_import():
    """FORE-01: Importing forecast models raises no errors."""
    from app.models.forecast import ComponentDemandHistory, ComponentForecast
    assert ComponentDemandHistory.__tablename__ == "component_demand_history"
    assert ComponentForecast.__tablename__ == "component_forecasts"


def test_forecast_models_in_metadata():
    """FORE-01: Both tables registered in Base.metadata."""
    import app.models  # noqa: F401 — triggers registration via package __init__
    from app.core.database import Base
    assert "component_demand_history" in Base.metadata.tables
    assert "component_forecasts" in Base.metadata.tables


def test_forecast_columns():
    """FORE-01: ComponentForecast columns match the contract in CONTEXT.md D-05."""
    from app.models.forecast import ComponentForecast
    cols = [c.name for c in ComponentForecast.__table__.columns]
    assert cols == [
        "id", "component_id", "forecast_date",
        "predicted_demand", "lower_bound", "upper_bound", "created_at",
    ], cols


def test_demand_history_columns():
    """FORE-01: ComponentDemandHistory columns match the contract."""
    from app.models.forecast import ComponentDemandHistory
    cols = [c.name for c in ComponentDemandHistory.__table__.columns]
    assert cols == ["id", "component_id", "week_date", "demand_units"], cols


def test_requirements_pins_prophet_1_3_0():
    """FORE-01: requirements.txt pins prophet==1.3.0 and does not pin prophet==1.1.4."""
    req_path = Path(__file__).resolve().parent.parent / "requirements.txt"
    content = req_path.read_text()
    assert "prophet==1.3.0" in content, "requirements.txt must pin prophet==1.3.0"
    assert "prophet==1.1.4" not in content, "requirements.txt must NOT pin prophet==1.1.4"
