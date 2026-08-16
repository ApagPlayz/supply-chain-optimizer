"""Regression test for the ``GET /ml/lead-time`` 422 contract (audit item 8).

The bug: the endpoint declared ``required_inputs: [dk_category, parameter_count,
unit_price]`` and everything else as ``optional_inputs``, but supplying exactly
those three fields 422'd on ``dk_subcategory``, then ``category``, then
``manufacturer`` — one field at a time. The root cause was in the serving
record, not the declared list: ``optional_record_keys`` correctly names the
categoricals whose ``unseen_policy`` is "other" (they safely fold a missing
value into the model's own trained Unknown / ``__other__`` level), but the
endpoint never actually put those keys into the record it fed the model, so
the feature-filling code (``_fill`` in ``app/ml/lead_time_model.py``) saw an
ABSENT key — which it treats as fatal — rather than a present-but-None one,
which it treats as "fall back to Unknown".

This file is written so that gap can never silently reopen. The key test below
does not hardcode the required-field list: it reads it straight from the
endpoint's own declared ``required_inputs`` (via a live 422) and posts exactly
those fields. If a future schema change adds a required field without the
endpoint's record-building keeping up, this test fails on real data instead of
a caller discovering it one 422 at a time.
"""
from __future__ import annotations

import pytest

from app.ml import model_store, set_ml_state
from app.ml.lead_time_model import (
    known_categories,
    optional_record_keys,
    primary_category_feature,
    required_record_keys,
)
from app.ml.serving import get_serving_model, load_ml_state

pytestmark = pytest.mark.model_ci

#: Realistic stand-ins for each possible required/optional field, keyed by the
#: record key the endpoint's query parameters use. ``dk_category`` is filled in
#: per-test from the served schema's own trained vocabulary (its unseen_policy
#: is "refuse", so it cannot be an arbitrary string).
_SAMPLE_VALUES = {
    "dk_subcategory": "Diode Arrays",
    "category": "Semiconductors",
    "manufacturer": "Texas Instruments",
    "lifecycle_status": "Active",
    "package_case": "SOT-23",
    "htsus_code": "8541.10.0060",
    "rohs_status": "ROHS3 Compliant",
    "is_normally_stocked": True,
    "parameter_count": 5,
    "unit_price": 1.23,
    "moq": 1.0,
    "max_break_qty": 100,
    "price_break_count": 3,
}


@pytest.fixture(scope="module")
def served():
    """The real MLState, exactly as the API process loads it at startup."""
    if not model_store.models_exist():
        pytest.skip("no ML artifacts — run `python -m seeds.train_ml_models`")
    state = load_ml_state()
    if state is None or get_serving_model(state) is None:
        pytest.skip("no serving model resolved")
    return state


def _sample_params(feature_cols) -> dict:
    """Build a full, valid parameter set for the CURRENT served schema."""
    params = dict(_SAMPLE_VALUES)
    feature = primary_category_feature(feature_cols)
    if feature is not None:
        levels = sorted(known_categories(feature_cols))
        if not levels:
            pytest.skip("served schema has no trained dk_category vocabulary")
        params["dk_category"] = levels[0]
    return params


def test_endpoint_declared_contract_matches_the_schema(served, client):
    """The 422's declared lists must literally equal the schema helpers' output.

    If someone ever hand-edits the endpoint's ``required_inputs`` /
    ``optional_inputs`` instead of deriving them from
    ``required_record_keys`` / ``optional_record_keys``, this catches the drift
    immediately rather than waiting for a caller to hit a false 422.
    """
    set_ml_state(served)
    resp = client.get("/api/v1/ml/lead-time")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["required_inputs"] == required_record_keys(served.feature_columns)
    assert detail["optional_inputs"] == optional_record_keys(served.feature_columns)


def test_endpoint_accepts_exactly_its_own_declared_required_fields(served, client):
    """Self-updating: posting EXACTLY the endpoint's declared-required fields
    (nothing from ``optional_inputs``) must succeed. This is the literal
    reproduction of audit item 8 — it fails on the pre-fix code because
    ``dk_subcategory`` (declared optional) was actually mandatory.
    """
    set_ml_state(served)

    declared = client.get("/api/v1/ml/lead-time").json()["detail"]["required_inputs"]
    assert declared, "schema currently has no required fields — nothing to prove here"

    sample = _sample_params(served.feature_columns)
    params = {k: sample[k] for k in declared}

    resp = client.get("/api/v1/ml/lead-time", params=params)
    assert resp.status_code == 200, (
        f"posting exactly the declared required_inputs {sorted(params)} must succeed "
        f"(nothing from optional_inputs was supplied); got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["predicted_factory_lead_time_days"] > 0
    for key, value in params.items():
        assert body["inputs_used"].get(key) == value


def test_endpoint_omitting_optional_fields_still_predicts(served, client):
    """Every declared-optional field, one at a time omitted, must still 200 —
    proving each one is genuinely optional and not merely mislabeled.
    """
    set_ml_state(served)

    declared_required = client.get("/api/v1/ml/lead-time").json()["detail"]["required_inputs"]
    declared_optional = client.get("/api/v1/ml/lead-time").json()["detail"]["optional_inputs"]
    sample = _sample_params(served.feature_columns)

    base = {k: sample[k] for k in declared_required}
    base.update({k: sample[k] for k in declared_optional if k in sample})

    resp = client.get("/api/v1/ml/lead-time", params=base)
    assert resp.status_code == 200, resp.text

    for key in declared_optional:
        params = {k: v for k, v in base.items() if k != key}
        resp = client.get("/api/v1/ml/lead-time", params=params)
        assert resp.status_code == 200, (
            f"omitting declared-optional field {key!r} must still predict; "
            f"got {resp.status_code}: {resp.text}"
        )


def test_missing_required_fields_are_aggregated_not_one_at_a_time(served, client):
    """422 must name every missing required field in one response, not dole
    them out one per request (the original failure mode this bug produced).
    """
    set_ml_state(served)
    declared = client.get("/api/v1/ml/lead-time").json()["detail"]["required_inputs"]
    if len(declared) < 2:
        pytest.skip("fewer than 2 required fields in the current schema")

    resp = client.get("/api/v1/ml/lead-time")
    assert resp.status_code == 422
    missing = resp.json()["detail"]["missing"]
    assert set(missing) == set(declared), (
        f"expected all {len(declared)} required fields named at once, got {missing}"
    )


def test_default_response_omits_the_one_hot_feature_list(served, client):
    """``features_used`` (100+ one-hot column names) must not ride along on
    every prediction by default — it is already published in full by
    ``GET /ml/model-comparison``. Opting in with ``include_feature_names=true``
    must still return the exact served schema.
    """
    set_ml_state(served)
    declared = client.get("/api/v1/ml/lead-time").json()["detail"]["required_inputs"]
    sample = _sample_params(served.feature_columns)
    params = {k: sample[k] for k in declared}

    resp = client.get("/api/v1/ml/lead-time", params=params)
    assert resp.status_code == 200, resp.text
    assert resp.json()["features_used"] == []

    resp2 = client.get(
        "/api/v1/ml/lead-time", params={**params, "include_feature_names": "true"}
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["features_used"] == list(served.feature_columns)
