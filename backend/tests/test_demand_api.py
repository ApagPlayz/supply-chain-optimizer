"""Tests for `GET /demand/benchmark`, the replacement for the retired `/forecasts/*`.

Two jobs here. First, the ordinary contract: the endpoint reads the committed
artifact and reshapes it without inventing anything, and it fails loudly rather
than serving an empty leaderboard when the artifact is absent. Second — and this
is the part worth having — a set of invariants checked against the REAL committed
artifact, so that if the backtest is ever regenerated in a way that quietly breaks
the maths, these fail.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.api import demand as demand_api

ARTIFACT = Path(__file__).resolve().parents[2] / "docs" / "intermittent_demand.json"
MIRROR = Path(__file__).resolve().parents[1] / "seeds" / "data" / "intermittent_demand.json"

pytestmark = pytest.mark.skipif(
    not ARTIFACT.is_file(),
    reason="demand benchmark artifact absent; run `python -m seeds.run_carparts_backtest`",
)


@pytest.fixture(scope="module")
def artifact() -> dict:
    return json.loads(ARTIFACT.read_text())


@pytest.fixture
def payload(client) -> dict:
    demand_api._load.cache_clear()
    response = client.get("/api/v1/demand/benchmark")
    assert response.status_code == 200, response.text
    return response.json()


# ── Contract ─────────────────────────────────────────────────────────────────

def test_endpoint_returns_the_full_contract(payload):
    for key in (
        "headline", "generated_utc", "dataset", "protocol", "scoring", "methods",
        "ranking_changed", "winner_changed", "point_winner", "distributional_winner",
        "mcb", "significance", "artifact", "reproduce_command",
    ):
        assert key in payload, f"missing {key}"
    assert payload["methods"], "leaderboard must not be empty"
    assert {m["metric"] for m in payload["mcb"]} == {"mase", "rmsse", "crps", "spl"}


def test_every_method_carries_both_a_point_and_a_proper_score(payload):
    """Nothing on this surface is published unless it is scoreable both ways —
    the failure that retired the previous endpoint was serving a forecast that
    could not be scored at all."""
    for row in payload["methods"]:
        for field in ("mase_mean", "rmsse_mean", "crps_mean", "spl_mean",
                      "rank_mase", "rank_crps", "rank_spl"):
            value = row[field]
            assert isinstance(value, (int, float)) and value == value, f"{row['name']}.{field}"
        assert row["family"] and row["assumption"], f"{row['name']} has no documented parameterisation"


def test_leaderboard_is_ordered_by_proper_scoring_rank(payload):
    ranks = [m["rank_crps"] for m in payload["methods"]]
    assert ranks == sorted(ranks)
    assert payload["methods"][0]["name"] == payload["distributional_winner"]


def test_response_matches_the_committed_artifact(payload, artifact):
    """The endpoint must reshape, not recompute — the served numbers and the
    documented numbers have to be the same bytes."""
    primary = artifact["configs"]["primary"]
    assert payload["headline"] == artifact["headline"]
    assert payload["generated_utc"] == artifact["meta"]["generated_utc"]
    assert payload["protocol"]["n_series_scored"] == primary["n_series_scored"]
    for row in payload["methods"]:
        source = primary["leaderboard"][row["name"]]
        assert row["mase_mean"] == source["mase"]["mean"]
        assert row["crps_mean"] == source["crps"]["mean"]
        assert row["rank_crps"] == primary["mcb"]["crps"]["mean_ranks"][row["name"]]


def test_missing_artifact_returns_503_not_an_empty_leaderboard(client, tmp_path, monkeypatch):
    """An empty body would read as 'no method works' — a different, false claim
    from 'this deployment has not run the measurement'."""
    monkeypatch.setattr(demand_api, "ARTIFACT_CANDIDATES", (tmp_path / "absent.json",))
    demand_api._load.cache_clear()
    response = client.get("/api/v1/demand/benchmark")
    assert response.status_code == 503
    assert "run_carparts_backtest" in response.json()["detail"]


def test_artifact_from_an_older_schema_returns_503(client, tmp_path, monkeypatch):
    stale = tmp_path / "intermittent_demand.json"
    stale.write_text(json.dumps({"headline": "x", "meta": {}, "configs": {}}))
    monkeypatch.setattr(demand_api, "ARTIFACT_CANDIDATES", (stale,))
    demand_api._load.cache_clear()
    response = client.get("/api/v1/demand/benchmark")
    assert response.status_code == 503
    assert "regenerate" in response.json()["detail"].lower()


def test_served_mirror_is_identical_to_the_documented_artifact():
    """The mirror exists only because the container build context is `backend/`.
    If the two ever diverge, the docs and the running app stop agreeing."""
    assert MIRROR.is_file(), "served mirror missing — rerun the backtest script"
    assert MIRROR.read_text() == ARTIFACT.read_text()


# ── Invariants on the real artifact ──────────────────────────────────────────

def test_degenerate_methods_have_scaled_crps_equal_to_mase(artifact):
    """CRPS of a point mass is absolute error, so with the shared MASE denominator
    a degenerate method's scaled CRPS must equal its MASE — on the real panel, not
    just in a unit test. This is what makes the two leaderboards comparable."""
    for config in artifact["configs"].values():
        for method in ("zero", "naive_last"):
            row = config["leaderboard"][method]
            assert row["crps"]["mean"] == pytest.approx(row["mase"]["mean"], abs=1e-4)
            assert row["crps"]["median"] == pytest.approx(row["mase"]["median"], abs=1e-4)


def test_non_degenerate_methods_have_scaled_crps_below_mase(artifact):
    """Hedging can only help under CRPS: spreading mass off the point estimate must
    reduce CRPS relative to the absolute error the same point forecast incurs."""
    for config in artifact["configs"].values():
        for method in ("croston", "sba", "tsb"):
            row = config["leaderboard"][method]
            assert row["crps"]["mean"] < row["mase"]["mean"]


def test_mean_ranks_are_consistent_with_the_number_of_methods(artifact):
    """Friedman mean ranks over k methods must average to (k+1)/2 — an arithmetic
    identity that catches a broken ranking. Tolerance is loose only because the
    artifact stores mean ranks rounded to four decimals."""
    for config in artifact["configs"].values():
        for block in config["mcb"].values():
            ranks = list(block["mean_ranks"].values())
            k = len(ranks)
            assert sum(ranks) / k == pytest.approx((k + 1) / 2, abs=1e-3)


def test_protocol_is_rolling_origin_with_multiple_refits(artifact):
    """Guards the fix: the car-parts protocol used to be a single split, which was
    inconsistent with every other backtest in the repo."""
    assert "rolling origin" in artifact["protocol"]["split"]
    for config in artifact["configs"].values():
        assert config["n_origins"] >= 2
        assert len(config["train_sizes"]) == config["n_origins"]
        assert config["train_sizes"] == sorted(config["train_sizes"])
        assert min(config["train_sizes"]) > config["seasonality"], (
            "every origin must train on more than one seasonal cycle or the "
            "seasonal-naive MASE denominator is degenerate"
        )


def test_artifact_records_reproducibility_metadata(artifact):
    meta = artifact["meta"]
    for field in ("generated_utc", "hardware", "python", "numpy", "scipy", "seed",
                  "script", "command", "wall_seconds"):
        assert meta.get(field) is not None, f"meta.{field} missing"


def test_the_conclusion_is_reported_not_assumed(artifact):
    """`ranking_changed` must be derived from the mean ranks actually computed, in
    both directions — a hardcoded True would be as dishonest as a hardcoded False."""
    for config in artifact["configs"].values():
        comparison = config["ranking_comparison"]
        orders = comparison["orders_by_mean_friedman_rank"]
        derived = any(orders[p] != orders[d] for p in ("mase", "rmsse") for d in ("crps", "spl"))
        assert comparison["ranking_changed"] == derived
        assert comparison["winner_changed"] == any(
            orders[p][0] != orders[d][0] for p in ("mase", "rmsse") for d in ("crps", "spl")
        )
