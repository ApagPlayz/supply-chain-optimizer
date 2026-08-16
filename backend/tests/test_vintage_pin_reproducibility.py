"""The vintage pin is the reproducibility guarantee — these tests hold it in place.

A reproducibility audit (2026-08) found that `seeds/run_forecast_backtest.py` refetched
Census M3 `A34SNO` live from FRED on every run and overwrote its own cache. Census
revises that series in place, so the published Prophet-vs-Chronos headline silently
inverted between two runs of unchanged code. These tests make that class of failure
fail loudly instead:

  * the committed vintage pins must be present and byte-exact (hash-checked),
  * a pinned load must be reproducible and must need NO network,
  * the two published artifacts must record the vintage and the input hashes,
  * both generators must be scored on the SAME vintage bytes,
  * the doc headlines must match the JSON artifacts they claim to come from.

None of these touch the network, so they are fast and safe in CI.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from seeds.macro_demand import (
    COMMITTED_CACHE_SHA256,
    DEFAULT_VINTAGE,
    PUBLISHED_VINTAGE,
    VINTAGE_SHA256,
    CACHE_PATH,
    canonical_values_sha256,
    load_demand_series,
    vintage_cache_path,
)
from seeds.provenance import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"


# ── The pins themselves ──────────────────────────────────────────────────────


@pytest.mark.parametrize("vintage", sorted(VINTAGE_SHA256))
def test_committed_vintage_pin_is_byte_exact(vintage: str) -> None:
    """Each committed vintage file must hash to its recorded SHA-256.

    A pin whose bytes can drift is not a pin.
    """
    path = vintage_cache_path(vintage)
    assert path.is_file(), f"missing committed vintage pin: {path}"
    assert sha256_file(path) == VINTAGE_SHA256[vintage], (
        f"vintage pin {path.name} no longer matches its recorded hash — either the "
        "file was edited or the constant is stale. Both are reproducibility bugs."
    )


def test_committed_snapshot_hash_matches_constant() -> None:
    """The legacy unpinned snapshot is hash-recorded so the fallback can be honest."""
    assert sha256_file(CACHE_PATH) == COMMITTED_CACHE_SHA256


def test_default_vintage_is_pinned_and_loads_offline() -> None:
    """The published vintage must load from committed bytes with NO network."""
    load = load_demand_series(DEFAULT_VINTAGE, allow_network=False)
    assert load.reproducible is True
    assert load.vintage == DEFAULT_VINTAGE
    assert load.source == "alfred_vintage_pin_committed"
    assert not load.warnings
    assert len(load.series) > 100


def test_pinned_load_is_deterministic() -> None:
    """Two loads of the same pin must give byte-identical observations."""
    a = load_demand_series(DEFAULT_VINTAGE, allow_network=False)
    b = load_demand_series(DEFAULT_VINTAGE, allow_network=False)
    assert a.values_sha256 == b.values_sha256 == canonical_values_sha256(a.series)


def test_different_vintages_are_actually_different_data() -> None:
    """Guards the whole premise: the revision this pin protects against is real.

    If these two vintages ever hash the same, either the pins were clobbered or the
    loader is ignoring the vintage — both would make the pin decorative.
    """
    old = load_demand_series(PUBLISHED_VINTAGE, allow_network=False)
    new = load_demand_series(DEFAULT_VINTAGE, allow_network=False)
    assert old.values_sha256 != new.values_sha256
    assert len(new.series) > len(old.series)


# ── The artifacts built from the pin ─────────────────────────────────────────

ARTIFACTS = ["forecast_backtest.json", "chronos_benchmark.json"]


@pytest.mark.parametrize("name", ARTIFACTS)
def test_artifact_records_its_vintage_and_input_hash(name: str) -> None:
    """Every artifact must say which bytes produced it."""
    meta = json.loads((DOCS / name).read_text())["meta"]
    assert meta["vintage"] == DEFAULT_VINTAGE, (
        f"{name} was generated on vintage {meta.get('vintage')!r}, not the pinned "
        f"{DEFAULT_VINTAGE!r}. Regenerate it with --as-of."
    )
    assert meta["reproducible"] is True
    assert meta["vintage_file_sha256"] == VINTAGE_SHA256[DEFAULT_VINTAGE]

    prov = meta["provenance"]
    assert prov["generated_at_utc"]
    assert prov["git"]["commit"]
    assert "dirty" in prov["git"], "dirty state must be recorded explicitly, not suffixed"
    assert prov["inputs"]["demand_series"]["sha256"] == VINTAGE_SHA256[DEFAULT_VINTAGE]


def test_both_generators_scored_the_same_bytes() -> None:
    """The Prophet backtest and the Chronos benchmark must not diverge on inputs.

    They disagreed before precisely because each refetched the series independently.
    """
    metas = [json.loads((DOCS / n).read_text())["meta"] for n in ARTIFACTS]
    hashes = {m["series_values_sha256"] for m in metas}
    assert len(hashes) == 1, f"artifacts were built from different series bytes: {hashes}"
    assert len({m["n_obs"] for m in metas}) == 1


def test_seasonal_naive_agrees_across_artifacts() -> None:
    """Same series + same harness ⇒ the shared baseline must be identical.

    This is the exact check that would have caught the original 0.0438-vs-0.0437
    discrepancy on the day it appeared.
    """
    fb = json.loads((DOCS / "forecast_backtest.json").read_text())
    cb = json.loads((DOCS / "chronos_benchmark.json").read_text())
    assert fb["seasonal_naive"]["overall"] == cb["seasonal_naive"]["overall"]
    assert fb["prophet"]["overall"]["wape"] == cb["prophet"]["overall"]["wape"]


# ── The docs built from the artifacts ────────────────────────────────────────


def _numbers_after(text: str, label: str) -> list[str]:
    line = next((ln for ln in text.splitlines() if label in ln), "")
    return re.findall(r"\d+\.\d+", line)


def test_forecast_doc_headline_matches_artifact() -> None:
    art = json.loads((DOCS / "forecast_backtest.json").read_text())
    md = (DOCS / "FORECAST_BACKTEST.md").read_text()
    wape = art["prophet"]["overall"]["wape"]
    assert f"{wape:.4f}" in md, f"Prophet WAPE {wape:.4f} is not quoted in FORECAST_BACKTEST.md"
    assert art["meta"]["vintage"] in md, "the doc must state the vintage it is pinned to"
    assert str(art["meta"]["n_obs"]) in md


def test_chronos_doc_headline_matches_artifact() -> None:
    art = json.loads((DOCS / "chronos_benchmark.json").read_text())
    md = (DOCS / "CHRONOS_BENCHMARK.md").read_text()
    assert art["meta"]["vintage"] in md
    for key in ("prophet", "seasonal_naive"):
        assert f"{art[key]['overall']['wape']:.4f}" in md
    if art.get("chronos"):
        assert f"{art['chronos']['overall']['wape']:.4f}" in md


# ── The real-time protocol ───────────────────────────────────────────────────


def test_realtime_origin_vintages_are_pinned_and_sized_correctly() -> None:
    """Each origin vintage must be committed and hold exactly its origin's training set.

    162 / 174 / 186 are the training sizes the pseudo-real-time rolling origins produce
    on the reference vintage. The two protocols are only comparable because these match.
    """
    from seeds.macro_demand import REALTIME_ORIGIN_VINTAGES

    expected = [162, 174, 186]
    assert len(REALTIME_ORIGIN_VINTAGES) == len(expected)
    for vintage, n in zip(REALTIME_ORIGIN_VINTAGES, expected, strict=True):
        assert vintage in VINTAGE_SHA256, f"origin vintage {vintage} has no recorded hash"
        load = load_demand_series(vintage, allow_network=False)
        assert load.reproducible is True
        assert len(load.series) == n, (
            f"origin vintage {vintage} holds {len(load.series)} obs, expected {n} — the "
            "real-time and pseudo protocols would no longer be comparable."
        )


def test_realtime_folds_match_pseudo_targets_but_differ_in_training_data() -> None:
    """The core experimental control: same actuals, same lengths, different information.

    If the actuals ever differ, the protocols are measuring different things and the
    'revised data flatters by X%' comparison is invalid.
    """
    from app.ml.backtest import rolling_origins
    from seeds.macro_demand import load_realtime_folds

    folds, meta = load_realtime_folds(allow_network=False)
    ref = load_demand_series(DEFAULT_VINTAGE, allow_network=False)
    vals = [float(v) for v in ref.series.to_numpy()]
    cuts = rolling_origins(len(vals), horizon=12, n_windows=3)

    assert meta["reference_vintage"] == DEFAULT_VINTAGE
    assert len(folds) == len(cuts)
    for fold, cut in zip(folds, cuts, strict=True):
        assert fold.actual == vals[cut:cut + 12], "actuals must be identical across protocols"
        assert len(fold.train) == cut, "training lengths must be identical across protocols"
        assert fold.train != vals[:cut], (
            "real-time training data is identical to the revised slice — the vintage pin "
            "is not doing anything and the whole comparison is vacuous."
        )


@pytest.mark.parametrize("name", ARTIFACTS)
def test_artifact_publishes_the_real_time_protocol(name: str) -> None:
    art = json.loads((DOCS / name).read_text())
    rt = art.get("real_time")
    assert rt, f"{name} must publish the real-time protocol result"
    assert rt["meta"]["protocol"] == "real_time_vintage_per_origin"
    assert rt["meta"]["reference_vintage"] == DEFAULT_VINTAGE
    for model, rep in rt["models"].items():
        assert rep["overall"]["wape"] > 0, f"{model} produced no real-time WAPE"


def test_real_time_is_worse_than_pseudo_for_every_model() -> None:
    """Revised data flatters. If this ever inverts, the protocol wiring is wrong.

    Scoring against data that did not exist at the origin cannot legitimately make a
    model look *worse*; an inversion means the folds are misaligned.
    """
    art = json.loads((DOCS / "chronos_benchmark.json").read_text())
    rt = art["real_time"]["models"]
    pseudo = {
        "prophet": art["prophet"],
        "seasonal_naive": art["seasonal_naive"],
        "chronos": art.get("chronos"),
    }
    for model, rep in rt.items():
        ps = pseudo.get(model)
        if not ps:
            continue
        assert rep["overall"]["wape"] > ps["overall"]["wape"], (
            f"{model}: real-time WAPE {rep['overall']['wape']} is not worse than pseudo "
            f"{ps['overall']['wape']} — suspect misaligned folds."
        )


def test_chronos_doc_states_the_real_time_verdict_and_its_limits() -> None:
    """The verdict must be published WITH its sample-size and contamination caveats."""
    md = (DOCS / "CHRONOS_BENCHMARK.md").read_text()
    art = json.loads((DOCS / "chronos_benchmark.json").read_text())
    rt = art["real_time"]["models"]
    for key in rt:
        assert f"{rt[key]['overall']['wape']:.4f}" in md
    assert "real-time" in md.lower()
    # The honest framing is load-bearing: a bare "Chronos wins" would be an overclaim
    # at 3 origins with a flipping per-origin winner.
    paired = art["real_time"].get("paired_prophet_vs_chronos")
    if paired and len(set(paired["per_origin_winner"])) > 1:
        assert "not consistent" in md, "an inconsistent per-origin winner must be disclosed"
    assert "pretrain" in md.lower(), "the Chronos contamination caveat must be stated"


def test_chronos_doc_reports_vintage_sensitivity() -> None:
    """The flip must be shown in the doc, not just fixed in the code."""
    art = json.loads((DOCS / "chronos_benchmark.json").read_text())
    md = (DOCS / "CHRONOS_BENCHMARK.md").read_text()
    rows = art.get("vintage_sensitivity") or []
    assert rows, "the benchmark must publish a vintage-sensitivity comparison"
    assert PUBLISHED_VINTAGE in md, "the superseded published vintage must be disclosed"
    for row in rows:
        assert f"{row['prophet_wape']:.4f}" in md
