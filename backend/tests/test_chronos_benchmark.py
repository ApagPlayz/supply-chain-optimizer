"""
Guards on the Chronos benchmark's HONESTY, not its score.

Three things went wrong in the published version and each has a test here:
  1. timings were a single un-warmed wall-clock with no hardware and no per-call
     detail -> unfalsifiable ("0.01 s inference" could have meant nothing ran);
  2. the doc header claimed FRED IPG3344S while the harness had been repointed at
     Census M3 A34SNO -> the series in the title was not the series scored;
  3. the cold-start table only compared Chronos against a Prophet deliberately
     misconfigured (yearly seasonality on 6 monthly points).

These run WITHOUT torch/chronos installed — they exercise the measurement and
rendering scaffolding, which is where the dishonesty lived.
"""
from __future__ import annotations

import time

import seeds.run_chronos_benchmark as rcb
from seeds.train_forecasts import FRED_DEMAND_SERIES


# ── 1. timing instrumentation is real ────────────────────────────────────────

def test_timed_fit_predict_records_every_call():
    tfp = rcb.TimedFitPredict(lambda train: [0.0] * rcb.HORIZON, "fake")
    tfp([1.0] * 50)
    tfp([1.0] * 60)
    st = tfp.stats()
    assert st["n_calls"] == 2
    assert st["context_min"] == 50 and st["context_max"] == 60
    assert st["prediction_length"] == rcb.HORIZON
    assert st["median_ms"] >= 0.0


def test_timed_fit_predict_stats_none_before_any_call():
    assert rcb.TimedFitPredict(lambda t: [], "fake").stats() is None


def test_warmup_is_not_counted_in_steady_state():
    tfp = rcb.TimedFitPredict(lambda train: [0.0], "fake")
    tfp.warmup([1.0, 2.0])
    assert tfp.stats() is None, "the warm-up call must be excluded from the timings"


def test_repeat_bench_measures_real_elapsed_time():
    calls = []

    def slow(ctx):
        calls.append(1)
        time.sleep(0.002)
        return [0.0]

    out = rcb._repeat_bench(slow, [1.0] * 10, repeats=5)
    assert out["n_repeats"] == 5
    assert len(calls) == 6, "one discarded warm-up + 5 timed repeats"
    assert out["median_ms"] >= 2.0, "must reflect actual wall-clock, not a constant"
    assert out["min_ms"] <= out["median_ms"] <= out["max_ms"]
    assert out["context_len"] == 10


def test_hardware_block_is_populated():
    hw = rcb._hardware()
    assert hw["device"] == "cpu"
    assert hw["machine"] and hw["python"]


# ── 2. the doc must name the series that was actually scored ─────────────────

def test_benchmark_series_matches_the_loaded_series():
    """Regression: the doc said IPG3344S while the harness loaded A34SNO."""
    import inspect

    src = inspect.getsource(rcb.main)
    assert '"series_id": FRED_DEMAND_SERIES' in src
    assert "IPG3344S" not in src, "series id must not be hardcoded — it drifted once already"
    assert FRED_DEMAND_SERIES == "A34SNO"


# ── 3. no Chronos => no numbers (never fabricate) ────────────────────────────

def _fake_report(wape: float) -> dict:
    return {
        "overall": {"wape": wape, "mape": wape, "rmse": 1.0, "bias": 0.0},
        "by_horizon": [{"horizon": h, "wape": wape} for h in range(1, rcb.HORIZON + 1)],
    }


def test_markdown_marks_chronos_pending_when_it_did_not_run():
    payload = {
        "meta": {
            "series_id": FRED_DEMAND_SERIES,
            "series_name": "Manufacturers' New Orders",
            "n_obs": 197, "start": "2010-01-01", "end": "2026-05-01",
            "horizon": rcb.HORIZON, "n_windows": rcb.N_WINDOWS,
            "chronos_blocker": "ModuleNotFoundError: chronos",
            "run_at": "2026-07-12T00:00:00+00:00",
        },
        "hardware": rcb._hardware(),
        "timing": {},
        "prophet": _fake_report(0.05),
        "seasonal_naive": _fake_report(0.09),
        "chronos": None,
        "cold_start": {},
    }
    md = rcb._render_markdown(payload)
    assert "_pending_" in md
    assert "NOT RUN" in md
    assert "ModuleNotFoundError" in md
    assert "Verdict: PENDING" in md


def test_cold_start_table_carries_the_fair_prophet_comparator():
    """A Chronos cold-start win may only be claimed against trend-only Prophet."""
    payload = {
        "meta": {
            "series_id": FRED_DEMAND_SERIES,
            "series_name": "Manufacturers' New Orders",
            "n_obs": 197, "start": "2010-01-01", "end": "2026-05-01",
            "horizon": rcb.HORIZON, "n_windows": rcb.N_WINDOWS,
            "run_at": "2026-07-12T00:00:00+00:00",
        },
        "hardware": rcb._hardware(),
        "timing": {},
        "prophet": _fake_report(0.05),
        "seasonal_naive": _fake_report(0.09),
        "chronos": {**_fake_report(0.03), "model": "amazon/chronos-bolt-tiny", "n_parameters": 8652672},
        "cold_start": {
            "context_len": rcb.COLD_START_CONTEXT,
            "prophet": {"wape": 4.5, "rmse": 9.0, "bias": -1.0},              # misconfigured
            "prophet_trend_only": {"wape": 0.02, "rmse": 1.0, "bias": -0.1},  # fair, and it WINS
            "seasonal_naive": {"wape": 0.06, "rmse": 2.0, "bias": -0.5},
            "chronos": {"wape": 0.05, "rmse": 1.8, "bias": -0.4},
        },
    }
    md = rcb._render_markdown(payload)
    assert "the fair comparator" in md
    assert "MISCONFIGURED" in md
    # Chronos (0.05) loses to fair Prophet (0.02) -> the doc must say the win disappears
    assert "cold-start win **disappears**" in md
    assert "NOT established" in md
