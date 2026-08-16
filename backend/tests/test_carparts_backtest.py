"""Tests for the intermittent-demand backtest driver.

Runs entirely on a small synthetic panel — no Monash download, no Prophet — so it
exercises the harness (rolling-origin split, balanced-panel filter, leaderboard,
MCB, DM/CW wiring, artifact assembly) rather than the dataset. The dataset numbers
themselves are pinned by tests/test_demand_api.py against the committed artifact.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.ml.backtest import rolling_origins
from seeds import run_carparts_backtest as rcb

HORIZON, N_WINDOWS, MIN_TRAIN = 3, 2, 24
LENGTH = MIN_TRAIN + N_WINDOWS * HORIZON      # 30


@pytest.fixture(scope="module")
def panel() -> np.ndarray:
    """A deterministic intermittent panel: ~25% non-zero, small integer sizes."""
    rng = np.random.default_rng(1234)
    occur = rng.random((60, LENGTH)) < 0.25
    sizes = rng.integers(1, 5, size=(60, LENGTH))
    return (occur * sizes).astype(float)


# ── The rolling-origin split is genuinely shared, not re-implemented ──────────

def test_the_split_comes_from_the_shared_harness():
    """`rolling_origins` is the single source of truth for origin placement, so the
    car-parts backtest and the macro A34SNO backtest cannot drift apart."""
    assert rolling_origins(51, 6, 3, 33) == [33, 39, 45]
    assert rolling_origins(51, 12, 2, 27) == [27, 39]


def test_shipped_configs_fit_the_monash_series_length():
    """Every configured protocol must be feasible on 51 months, and must leave more
    than one seasonal cycle in the shortest training window."""
    for _, horizon, n_windows, min_train in rcb.CONFIGS:
        cuts = rolling_origins(51, horizon, n_windows, min_train)
        assert len(cuts) == n_windows
        assert min(cuts) > rcb.SEASONALITY
        assert max(cuts) + horizon == 51


# ── Scoring ──────────────────────────────────────────────────────────────────

def test_score_panel_returns_one_score_per_kept_series_per_method(panel):
    per_series, kept, squared = rcb.score_panel(
        panel, HORIZON, N_WINDOWS, MIN_TRAIN, rcb.METHODS
    )
    assert 0 < kept.size <= panel.shape[0]
    for name in rcb.METHODS:
        for metric in rcb.METRIC_KEYS:
            values = per_series[name][metric]
            assert values.shape == (kept.size,)
            assert np.all(np.isfinite(values))
        assert squared[name].shape == (kept.size,)


def test_score_panel_drops_a_series_no_method_can_score(panel):
    """A constant series has a zero seasonal-naive denominator, so every scaled
    metric is undefined. It must be excluded rather than silently counted as 0."""
    with_constant = np.vstack([panel, np.full((1, LENGTH), 7.0)])
    _, kept, _ = rcb.score_panel(with_constant, HORIZON, N_WINDOWS, MIN_TRAIN, rcb.METHODS)
    assert with_constant.shape[0] - 1 not in set(kept.tolist())


def test_kept_panel_is_balanced_across_methods(panel):
    """Every method must be scored on an IDENTICAL set of series, or the mean
    Friedman ranks are comparing different samples."""
    per_series, kept, _ = rcb.score_panel(panel, HORIZON, N_WINDOWS, MIN_TRAIN, rcb.METHODS)
    sizes = {per_series[m][k].size for m in rcb.METHODS for k in rcb.METRIC_KEYS}
    assert sizes == {kept.size}


def test_degenerate_methods_score_identically_under_mase_and_crps(panel):
    """The cross-check that ties the point and distributional leaderboards, run
    through the real driver rather than the unit-test path."""
    per_series, _, _ = rcb.score_panel(panel, HORIZON, N_WINDOWS, MIN_TRAIN, rcb.METHODS)
    for method in ("zero", "naive_last"):
        np.testing.assert_allclose(
            per_series[method]["crps"], per_series[method]["mase"], rtol=1e-9
        )


# ── The full config, end to end ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def config(panel) -> dict:
    return rcb.run_config(panel, "test", HORIZON, N_WINDOWS, MIN_TRAIN)


def test_run_config_emits_the_documented_structure(config):
    for key in ("label", "horizon", "n_origins", "train_sizes", "leaderboard", "mcb",
                "ranking_comparison", "diebold_mariano", "clark_west", "n_series_scored"):
        assert key in config
    assert set(config["mcb"]) == set(rcb.METRIC_KEYS)
    assert set(config["leaderboard"]) == set(rcb.METHODS)
    for row in config["leaderboard"].values():
        assert set(row) == set(rcb.METRIC_KEYS)


def test_every_method_has_a_documented_parameterisation():
    """A method may not appear on the leaderboard without stating what it assumes
    to become a distribution."""
    assert set(rcb.PARAMETERISATIONS) == set(rcb.METHODS)
    for entry in rcb.PARAMETERISATIONS.values():
        assert entry["family"] and entry["assumption"]


def test_clark_west_is_used_for_nested_pairs_and_dm_for_the_rest(config):
    cw_pairs = {(r["restricted_model"], r["unrestricted_model"]) for r in config["clark_west"]}
    dm_pairs = {(r["baseline"], r["candidate"]) for r in config["diebold_mariano"]}
    assert cw_pairs == {(a, b) for a, b, _, _ in rcb.NESTED_PAIRS}
    assert dm_pairs == set(rcb.DM_PAIRS)
    assert not (cw_pairs & dm_pairs), "a pair must not be tested both ways"
    for row in config["clark_west"]:
        assert row["nesting"] and row["why_not_diebold_mariano"]


def test_the_uninformative_clark_west_pairs_are_flagged(config):
    """With f1 = 0 the Clark-West adjustment collapses to 2*y*f2, which is
    non-negative by construction — rejection is automatic and means nothing. Those
    rows must be marked as such rather than presented as evidence."""
    by_pair = {(r["restricted_model"], r["unrestricted_model"]): r for r in config["clark_west"]}
    for (restricted, _), row in by_pair.items():
        assert row["informative"] is (restricted != "zero")
        if restricted == "zero":
            assert "DEGENERATE" in row["caveat"]
    assert by_pair[("croston", "sba")]["informative"] is True


def test_ranking_comparison_is_computed_from_the_mean_ranks(config):
    comparison = config["ranking_comparison"]
    orders = comparison["orders_by_mean_friedman_rank"]
    for metric, order in orders.items():
        ranks = config["mcb"][metric]["mean_ranks"]
        assert order == sorted(ranks, key=lambda m: ranks[m])
    assert comparison["ranking_changed"] == any(
        not c["identical"] for c in comparison["comparisons"]
    )


def test_headline_states_whichever_result_actually_occurred(config):
    """Both branches must be reachable — a null result has to be sayable."""
    headline = rcb._headline(config)
    if config["ranking_comparison"]["ranking_changed"]:
        assert "disagree" in headline
    else:
        assert "NULL RESULT" in headline
    assert str(config["n_series_scored"]) in headline


def test_payload_carries_provenance_and_dataset_facts(panel, config):
    from datetime import UTC, datetime

    payload = rcb.build_payload(panel, [config], None, datetime.now(UTC), 1.0)
    for field in ("generated_utc", "hardware", "python", "numpy", "scipy", "seed",
                  "script", "command", "wall_seconds"):
        assert payload["meta"].get(field) is not None
    assert payload["dataset"]["n_series"] == panel.shape[0]
    assert payload["dataset"]["nonzero_fraction"] == pytest.approx(
        float((panel > 0).mean()), abs=1e-4
    )
    assert payload["headline"]
    assert "rolling origin" in payload["protocol"]["split"]
    assert set(payload["parameterisations"]) == set(rcb.METHODS)
