"""The macro stress probability may not be published without its data vintage.

The defect these tests close
----------------------------
``GET /api/v1/ml/stress`` served ``stress_probability`` / ``stress_level`` /
``regime_active`` as the CURRENT state of the world, with no date anywhere in
the payload. The number is scored from ``regime_features.tail(1)`` — ONE row of
a MONTHLY frame — and nothing refreshes that artifact on a schedule. On
2026-08-28 the served "82.84% HIGH" reading, which prices a real stock-out
surcharge into every MILP solve (``app/optimization/sourcing.py``), actually
described **July 2026**, and no field, string or pixel said so.

Two independent things are pinned here, because they fail independently:

  1. **The field exists.** Every branch of the endpoint carries the vintage
     fields, and the served branch carries a real observation date derived from
     the frame that produced the probability — not a constant, not a doc.
  2. **The frame is not ancient.** The served probability is scored from a row
     no older than ``STRESS_FRAME_MAX_AGE_DAYS``. This is a TRIPWIRE, and it is
     meant to go red: when it does, the artifact is half a year stale and the
     fix is to rerun ``seeds/train_ml_models.py`` and commit new artifacts, not
     to raise the constant.

Both were confirmed to fail against deliberately broken code before being
committed (see the notes on each test).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from app.ml import MLState, set_ml_state
from app.ml.regime_model import STRESS_FRAME_MAX_AGE_DAYS, get_feature_frame_asof

VINTAGE_FIELDS = (
    "observation_date",
    "observation_frequency",
    "observation_age_days",
    "observation_age_months",
    "vintage_is_stale",
    "max_observation_age_days",
    "vintage_label",
)


def _frame(last: str, rows: int = 3) -> pd.DataFrame:
    """A minimal feature frame whose index ends at ``last`` (month starts)."""
    idx = pd.date_range(end=pd.Timestamp(last), periods=rows, freq="MS")
    return pd.DataFrame({"gscpi_lag1": range(rows)}, index=idx)


def _state(features: pd.DataFrame | None, status_date: str | None) -> MLState:
    return MLState(
        regime_model=object(),   # only needs to be non-None — the endpoint checks that
        regime_features=features,
        lead_time_models={},
        best_lead_time_model=None,
        current_stress_prob=0.8284,
        feature_columns=[],
        regime_status={
            "available": True,
            "source": "model",
            "observation_date": status_date,
            "observation_frequency": "monthly",
            "ship_gate": {"policy": "brier", "reason": "beats persistence"},
            "metrics": {},
        },
    )


# ── the helper that recovers the date `tail(1)` throws away ──────────────────

def test_get_feature_frame_asof_returns_the_date_of_the_row_that_is_scored():
    """`get_current_stress_prob` scores `tail(1)`; this must read THAT row's date.

    Proven red: returning ``features_df.index.min()`` instead of ``max()`` gives
    2026-05-01 and this assertion fails.
    """
    df = _frame("2026-07-01", rows=3)
    assert get_feature_frame_asof(df) == pd.Timestamp("2026-07-01")


def test_get_feature_frame_asof_says_unknown_rather_than_assuming_fresh():
    """No date available must read as UNKNOWN, never as "now"."""
    assert get_feature_frame_asof(None) is None
    assert get_feature_frame_asof(pd.DataFrame()) is None
    assert get_feature_frame_asof(pd.DataFrame({"a": [1, 2]})) is None


# ── the endpoint: the field must be there, on every branch ───────────────────

def test_stress_response_always_carries_the_vintage_fields(client):
    """Whatever the branch, the payload has somewhere to put the vintage.

    Proven red: deleting ``observation_date`` from ``StressResponse`` drops it
    from the JSON and this fails on the first field.
    """
    body = client.get("/api/v1/ml/stress").json()
    missing = [f for f in VINTAGE_FIELDS if f not in body]
    assert not missing, f"/ml/stress published a stress reading with no {missing} field"


def test_a_served_probability_is_never_published_without_an_observation_date(client):
    """If a probability is being SERVED, it must say which month it describes.

    Proven red: making ``resolve_regime_signal`` omit ``observation_date`` and
    the endpoint skip its fallback leaves this null, and this fails.
    """
    body = client.get("/api/v1/ml/stress").json()
    if not body["available"]:
        pytest.skip(
            "no regime artifact is being served on this checkout, so there is no "
            "probability whose vintage could be missing — see regime_status.reason: "
            f"{body.get('ship_gate_reason')!r}"
        )
    assert body["observation_date"], (
        "a live stress_probability was published with no observation_date — the "
        "reader cannot tell whether it describes this month or last quarter"
    )
    date.fromisoformat(body["observation_date"])          # must be a real ISO date
    assert body["observation_age_days"] is not None
    assert body["vintage_label"] != "Data vintage unknown"
    # The human-readable label must actually name the month it is qualifying.
    obs = date.fromisoformat(body["observation_date"])
    assert f"{obs:%b}" in body["vintage_label"], body["vintage_label"]
    assert f"{obs:%Y}" in body["vintage_label"], body["vintage_label"]
    # And the sentence that gets quoted on its own must carry it too.
    assert f"{obs:%B %Y}" in body["interpretation"], body["interpretation"]


def test_the_published_date_is_the_frames_own_last_observation(client):
    """The vintage must be DERIVED from the frame that produced the number.

    Not from a document, not from a constant. If the two ever disagree, the
    endpoint is qualifying its figure with someone else's date.

    Proven red: hardcoding ``observation_date`` to "2026-08-01" in
    ``resolve_regime_signal`` makes this fail against the real artifact
    (2026-07-01).
    """
    body = client.get("/api/v1/ml/stress").json()
    if not body["available"]:
        pytest.skip("no regime artifact served — nothing to cross-check")
    from app.ml import get_ml_state

    state = get_ml_state()
    assert state is not None
    asof = get_feature_frame_asof(state.regime_features)
    assert asof is not None, "a probability is served from a frame with no date"
    assert body["observation_date"] == asof.date().isoformat()


# ── the tripwire: the served frame may not be arbitrarily old ────────────────

def test_the_served_probability_is_not_scored_from_an_ancient_frame(client):
    """TRIPWIRE. Goes red when nobody has retrained for `STRESS_FRAME_MAX_AGE_DAYS`.

    The correct response to this failing is to rerun
    ``python -m seeds.train_ml_models`` and commit the refreshed
    ``regime_features.joblib`` — NOT to raise the constant. The optimizer prices
    a real surcharge off this number; a frame two quarters behind is not a
    forecast of anything.

    Proven red: temporarily setting ``STRESS_FRAME_MAX_AGE_DAYS = 1`` fails with
    the real 58-day-old artifact.
    """
    body = client.get("/api/v1/ml/stress").json()
    if not body["available"]:
        pytest.skip("no regime artifact served — no stale probability is reaching anyone")
    age = body["observation_age_days"]
    assert age is not None, "cannot verify freshness: no age was published"
    assert age <= STRESS_FRAME_MAX_AGE_DAYS, (
        f"/ml/stress is serving a probability scored from the "
        f"{body['observation_date']} row — {age} days old, past the "
        f"{STRESS_FRAME_MAX_AGE_DAYS}-day tolerance. Retrain and commit new "
        f"artifacts; do not raise the tolerance."
    )
    assert body["vintage_is_stale"] is False


def test_a_frame_past_the_tolerance_is_reported_stale(client):
    """The stale flag must actually flip — otherwise it is decoration.

    This is the "would it fail if the thing were broken?" half of the tripwire:
    it drives the endpoint with a deliberately ancient frame and asserts the
    response says so.
    """
    old = date.today() - timedelta(days=STRESS_FRAME_MAX_AGE_DAYS + 40)
    old_month = old.replace(day=1)
    set_ml_state(_state(_frame(old_month.isoformat()), old_month.isoformat()))

    body = client.get("/api/v1/ml/stress").json()
    assert body["available"] is True
    assert body["observation_date"] == old_month.isoformat()
    assert body["observation_age_days"] > STRESS_FRAME_MAX_AGE_DAYS
    assert body["vintage_is_stale"] is True
    assert body["max_observation_age_days"] == STRESS_FRAME_MAX_AGE_DAYS


def test_the_endpoint_recovers_the_vintage_from_the_frame_when_status_omits_it(client):
    """An MLState built by some other path still publishes a date.

    ``regime_status`` is a free-form dict; if a caller builds one without the
    key, the endpoint re-reads the frame it is holding rather than silently
    dropping the qualifier.
    """
    set_ml_state(_state(_frame("2026-07-01"), None))
    body = client.get("/api/v1/ml/stress").json()
    assert body["observation_date"] == "2026-07-01"
    assert body["observation_age_days"] == (datetime.now(UTC).date() - date(2026, 7, 1)).days


def test_an_unserved_signal_reports_no_vintage_rather_than_a_fake_one(client):
    """The fallback 0.0 describes no month, and the label must say exactly that."""
    set_ml_state(MLState(
        regime_model=None,
        regime_features=None,
        lead_time_models={},
        best_lead_time_model=None,
        current_stress_prob=0.0,
        feature_columns=[],
        regime_status={
            "available": False,
            "source": "unavailable_no_artifact",
            "reason": "no artifact",
            "ship_gate": {},
            "metrics": {},
        },
    ))
    body = client.get("/api/v1/ml/stress").json()
    assert body["available"] is False
    assert body["observation_date"] is None
    assert body["vintage_is_stale"] is None
    assert "no data vintage" in body["vintage_label"].lower()
