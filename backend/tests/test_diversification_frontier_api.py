"""
`GET /benchmark/diversification-frontier` — the price-of-resilience endpoint.

The sweep itself is tested in `test_diversification_frontier.py`. This file tests
the thing that ships to a reader: the API that serves the committed artifact, and
specifically the honesty invariants that make the published sentence quotable.

What is proved here, in order of how much a violation would cost:

  1. NO DRIFT. Every number the endpoint serves is the artifact's number. The
     headline sentence is composed from the same fields it quotes, so it cannot
     say "$58.88" while the table says something else — the failure mode that
     produced the retracted 44.7% headline in the first place.
  2. A PRICE IS ONLY PRINTED WHERE THE DENOMINATOR SURVIVED. `usd_per_unit_*`
     must be None wherever the corresponding paired 95% CI covers zero, with a
     `_note` saying why. A ratio over a denominator indistinguishable from zero
     is an artifact of division, not a price.
  3. `significant` MEANS "EXCLUDES ZERO", always, on every interval served.
  4. n AND n_effective ARE BOTH SERVED AND THEY DIFFER. Quoting only n=9 would
     inflate the panel with BOMs the constraint never touched.
  5. THE MECHANISM IS DATA-DERIVED. The non-monotone counter-example is found by
     scanning the artifact, not asserted; if the frontier were monotone the field
     would be absent rather than wrong.
  6. A MISSING OR CORRUPT ARTIFACT DEGRADES, NEVER 500s.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault(
    "SECRET_KEY", "test-secret-key-that-is-at-least-32-characters-long-for-testing"
)
os.environ.setdefault("DEBUG", "true")

import pytest  # noqa: E402

from app.api import benchmark as benchmark_api  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "docs" / "diversification_frontier.json"


@pytest.fixture(autouse=True)
def _clear_frontier_cache():
    """The loader is `lru_cache`d for the process; tests must not leak into each other."""
    benchmark_api._load_diversification_frontier.cache_clear()
    yield
    benchmark_api._load_diversification_frontier.cache_clear()


@pytest.fixture(scope="module")
def raw() -> dict:
    assert ARTIFACT.exists(), f"missing sweep artifact: {ARTIFACT}"
    return json.loads(ARTIFACT.read_text())


@pytest.fixture
def payload() -> dict:
    return benchmark_api.get_diversification_frontier().model_dump()


# ── 1. The endpoint serves the artifact, unmodified ──────────────────────────

def test_endpoint_is_available_and_names_its_source(payload):
    assert payload["available"] is True
    assert payload["source"].endswith("diversification_frontier.json")
    assert payload["unavailable_reason"] is None


def test_every_k_row_matches_the_artifact(payload, raw):
    served = {p["k"]: p for p in payload["points"]}
    assert set(served) == {int(r["k"]) for r in raw["frontier"]}
    for row in raw["frontier"]:
        p = served[int(row["k"])]
        assert p["mean_total_cost_usd"] == row["mean_total_cost_usd"]
        assert p["mean_suppliers"] == row["mean_suppliers"]
        assert p["n_boms_feasible"] == row["n_boms_feasible"]
        assert p["n_effective"] == row["n_effective"]
        assert p["n_keeps_k1_suppliers"] == row["n_keeps_k1_suppliers"]
        assert p["mean_targeted_cascade_risk"] == row["mean_targeted_cascade_risk"]
        assert p["mean_stress_cascade_risk"] == row["mean_stress_cascade_risk"]


def test_every_interval_matches_the_artifact(payload, raw):
    """Means and both endpoints, field by field. Nothing is re-derived."""
    served = {p["k"]: p for p in payload["points"]}
    pairs = [
        ("delta_cost_usd", "delta_cost_vs_k1"),
        ("delta_targeted_cascade_risk", "delta_targeted_cascade_risk_vs_k1"),
        ("delta_stress_cascade_risk", "delta_stress_cascade_risk_vs_k1"),
        ("delta_targeted_expected_shortfall", "delta_targeted_expected_shortfall_vs_k1"),
        ("delta_stress_expected_shortfall", "delta_stress_expected_shortfall_vs_k1"),
    ]
    for row in raw["frontier"]:
        p = served[int(row["k"])]
        for api_key, art_key in pairs:
            ci = p[api_key]
            src = row[art_key]
            assert ci is not None, f"k={row['k']} dropped {api_key}"
            assert ci["mean"] == src["mean"]
            assert ci["ci95_low"] == src["ci_low"]
            assert ci["ci95_high"] == src["ci_high"]
            assert ci["n"] == src["n"]


def test_headline_quotes_the_same_numbers_it_tabulates(payload):
    """
    The sentence and the table must agree BY CONSTRUCTION.

    This is the retracted-headline failure mode: a prose claim that outlives the
    numbers it was written from. The finding is composed from the k=2 step, so
    the k=2 step's figures have to appear in it.
    """
    step = next(s for s in payload["steps"] if s["to_k"] == 2)
    k2 = next(p for p in payload["points"] if p["k"] == 2)
    risk = step["marginal_targeted_cascade_risk_removed"]
    cost = step["marginal_cost_usd"]
    finding = payload["finding"]

    assert f"{risk['mean']:.2f}" in finding
    assert f"${cost['mean']:,.2f}" in finding
    assert f"{risk['ci95_low']:.2f}" in finding
    assert f"{risk['ci95_high']:.2f}" in finding
    assert f"n={risk['n']}" in finding
    assert f"n_effective={k2['n_effective']}" in finding
    assert payload["verdict"]


def test_headline_is_withheld_when_the_first_step_is_not_significant(monkeypatch):
    """A finding is a finding only if its interval excluded zero. Otherwise: silence."""
    points = [
        benchmark_api.FrontierPoint(
            k=2, n_boms_feasible=9, n_effective=7,
            mean_total_cost_usd=427.22, mean_suppliers=2.11,
        )
    ]
    steps = [
        benchmark_api.FrontierStep(
            label="1 → 2", from_k=1, to_k=2,
            marginal_cost_usd=benchmark_api.FrontierInterval(n=9, mean=58.88),
            marginal_targeted_cascade_risk_removed=benchmark_api.FrontierInterval(
                n=9, mean=0.44, ci95_low=-0.1, ci95_high=0.9, significant=False,
            ),
        )
    ]
    finding, verdict = benchmark_api._frontier_finding(points, steps)
    assert finding == ""
    assert verdict == ""


# ── 2. A price is only printed where the denominator survived ────────────────

def test_no_price_is_quoted_over_a_denominator_that_covers_zero(payload):
    """The honesty invariant, on the marginal table."""
    for step in payload["steps"]:
        risk = step["marginal_targeted_cascade_risk_removed"]
        price = step["usd_per_unit_targeted_cascade_risk"]
        if risk is None or not risk["significant"]:
            assert price is None, f"{step['label']} priced a non-significant denominator"
            assert step["usd_per_unit_targeted_cascade_risk_note"]
        else:
            assert isinstance(price, (int, float))
            assert step["usd_per_unit_targeted_cascade_risk_note"] is None

        es = step["marginal_stress_expected_shortfall_removed"]
        es_price = step["usd_per_unit_stress_expected_shortfall"]
        if es is None or not es["significant"]:
            assert es_price is None
            assert step["usd_per_unit_stress_expected_shortfall_note"]


def test_cumulative_prices_carry_a_note_wherever_they_are_absent(payload):
    for p in payload["points"]:
        if p["usd_per_unit_targeted_cascade_risk"] is None:
            assert p["usd_per_unit_targeted_cascade_risk_note"], (
                f"k={p['k']} withheld a price without saying why"
            )
        if p["usd_per_unit_stress_cascade_risk"] is None:
            assert p["usd_per_unit_stress_cascade_risk_note"]


def test_the_collapse_is_real_and_is_reported_as_a_multiple(payload):
    """
    The whole point of the section: the second supplier is cheap per unit of risk
    and the third is not. The multiple is computed from the served ratios, so it
    cannot disagree with the column beside it.
    """
    priced = [
        s for s in payload["steps"]
        if s["usd_per_unit_targeted_cascade_risk"] is not None
    ]
    assert len(priced) >= 2, "no collapse to show"
    first, second = priced[0], priced[1]
    assert first["cost_multiple_vs_first_step"] == 1.0
    expected = round(
        second["usd_per_unit_targeted_cascade_risk"]
        / first["usd_per_unit_targeted_cascade_risk"],
        1,
    )
    assert second["cost_multiple_vs_first_step"] == expected
    assert second["cost_multiple_vs_first_step"] > 1.0

    # And past the priced steps, no price is quotable at all.
    assert any(
        s["usd_per_unit_targeted_cascade_risk"] is None for s in payload["steps"]
    ), "the artifact no longer contains a step where the CI covers zero"


# ── 3. `significant` always means "excludes zero" ────────────────────────────

def test_significant_is_exactly_excludes_zero_everywhere(payload):
    def check(ci, where):
        if ci is None:
            return
        lo, hi = ci["ci95_low"], ci["ci95_high"]
        if lo is None or hi is None:
            return
        assert ci["significant"] == (lo > 0 or hi < 0), where

    for p in payload["points"]:
        for key, ci in p.items():
            if key.startswith("delta_"):
                check(ci, f"points[k={p['k']}].{key}")
    for s in payload["steps"]:
        for key, ci in s.items():
            if key.startswith("marginal_"):
                check(ci, f"steps[{s['label']}].{key}")


# ── 4. n and n_effective are both served, and they differ ────────────────────

def test_n_effective_is_served_and_is_smaller_than_n_at_k2(payload):
    k2 = next(p for p in payload["points"] if p["k"] == 2)
    assert k2["n_effective"] < k2["n_boms_feasible"], (
        "the constraint binds on every BOM at k=2 — the honest-denominator "
        "caveat on the page would be describing nothing"
    )
    assert k2["n_effective"] == 7
    assert k2["n_boms_feasible"] == 9
    assert "n_effective" in payload["n_effective_definition"]


def test_k1_is_the_control_arm_and_contributes_no_effective_boms(payload):
    k1 = next(p for p in payload["points"] if p["k"] == 1)
    assert k1["n_effective"] == 0
    assert k1["delta_cost_usd"]["mean"] == 0.0
    assert k1["n_keeps_k1_suppliers"] == k1["n_boms_feasible"]


def test_baseline_reproduces_the_published_benchmark(payload, raw):
    check = raw["run5_reproduction_check"]
    assert payload["baseline_check_passed"] is bool(check["all_match"])
    assert f"{check['matched']} of {check['checked']}" in payload["baseline_check"]
    assert "milp_blind" in payload["baseline_check"]


# ── 5. The mechanism is derived from the artifact, not asserted ──────────────

def test_non_monotone_example_is_a_real_row_in_the_artifact(payload, raw):
    ex = payload["non_monotone_example"]
    assert ex is not None, (
        "the sweep no longer contains a BOM that gets worse under stress when "
        "forced to diversify — the mechanism section's claim must be removed"
    )
    bom = next(b for b in raw["boms"] if b["bom"] == ex["bom"])
    before = next(p for p in bom["points"] if p["k"] == ex["from_k"])
    after = next(p for p in bom["points"] if p["k"] == ex["to_k"])
    assert (
        before["scenarios"]["stress"]["expected_shortfall"]
        == pytest.approx(ex["expected_shortfall_before"], abs=1e-4)
    )
    assert (
        after["scenarios"]["stress"]["expected_shortfall"]
        == pytest.approx(ex["expected_shortfall_after"], abs=1e-4)
    )
    assert ex["expected_shortfall_after"] > ex["expected_shortfall_before"]
    assert ex["n_suppliers_after"] > ex["n_suppliers_before"]
    assert isinstance(ex["keeps_k1_suppliers"], bool)


def test_plans_are_not_nested_so_the_frontier_is_not_a_ladder(payload):
    """
    `n_keeps_k1_suppliers` is the mechanism in one column. If every plan kept its
    k=1 suppliers, the count constraint WOULD be a resilience constraint and the
    page's explanation of the benchmark's split would be wrong.
    """
    k2 = next(p for p in payload["points"] if p["k"] == 2)
    assert k2["n_keeps_k1_suppliers"] < k2["n_boms_feasible"]
    assert k2["n_keeps_k1_suppliers"] == 4


def test_every_caveat_the_page_shows_is_served_and_non_empty(payload):
    for field in (
        "cost_axis_caveat",
        "seed_caveat",
        "quantisation_caveat",
        "independence_caveat",
        "nesting_caveat",
        "aggregate_definition",
        "n_effective_definition",
    ):
        assert payload[field].strip(), f"{field} is empty — the page would render a gap"
    assert "LTL_BASE_FEE_USD" in payload["cost_axis_caveat"]
    assert "seed 42" in payload["seed_caveat"]
    assert "0.25" in payload["quantisation_caveat"]
    assert payload["caveats"], "the artifact's own caveat list was dropped"


def test_infeasible_k_publishes_its_own_smaller_panel(payload):
    """k=5 is a different comparison from the rows above it and must say so."""
    k5 = next((p for p in payload["points"] if p["k"] == 5), None)
    if k5 is None:
        pytest.skip("sweep no longer reaches k=5")
    assert k5["boms_infeasible"], "k=5 lost its infeasibility record"
    assert k5["n_boms_feasible"] < 9


def test_excluded_boms_are_named_with_a_reason(payload):
    assert payload["boms_excluded"], "the excluded BOM vanished from the payload"
    for bom, reason in payload["boms_excluded"].items():
        assert bom and reason.strip()


def test_provenance_is_served(payload):
    assert payload["mc_scenarios"] == 1000
    assert payload["mc_seed"] == 42
    assert payload["bootstrap_seed"] == 42
    assert payload["strategy"] == "balanced"
    assert payload["mean_suppliers_at_k1"] is not None


# ── 6. Degradation, not 500s ─────────────────────────────────────────────────

def test_missing_artifact_returns_unavailable_with_a_regeneration_command(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        benchmark_api, "_DIVERSIFICATION_FRONTIER_PATH", tmp_path / "nope.json"
    )
    benchmark_api._load_diversification_frontier.cache_clear()
    payload = benchmark_api.get_diversification_frontier().model_dump()
    assert payload["available"] is False
    assert payload["points"] == []
    assert payload["finding"] == ""
    assert "run_diversification_sweep" in payload["unavailable_reason"]


def test_unparseable_artifact_returns_unavailable_not_an_exception(
    monkeypatch, tmp_path
):
    bad = tmp_path / "diversification_frontier.json"
    bad.write_text("{ this is not json")
    monkeypatch.setattr(benchmark_api, "_DIVERSIFICATION_FRONTIER_PATH", bad)
    benchmark_api._load_diversification_frontier.cache_clear()
    payload = benchmark_api.get_diversification_frontier().model_dump()
    assert payload["available"] is False
    assert "could not be parsed" in payload["unavailable_reason"]


def test_empty_frontier_returns_unavailable(monkeypatch, tmp_path):
    empty = tmp_path / "diversification_frontier.json"
    empty.write_text(json.dumps({"meta": {}, "frontier": []}))
    monkeypatch.setattr(benchmark_api, "_DIVERSIFICATION_FRONTIER_PATH", empty)
    benchmark_api._load_diversification_frontier.cache_clear()
    payload = benchmark_api.get_diversification_frontier().model_dump()
    assert payload["available"] is False
    assert "no frontier rows" in payload["unavailable_reason"]


def test_loader_is_cached_so_the_artifact_is_read_once():
    first = benchmark_api._load_diversification_frontier()
    second = benchmark_api._load_diversification_frontier()
    assert first is second


def test_endpoint_is_registered_and_unauthenticated():
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import app

    with TestClient(app) as client:
        resp = client.get(f"{settings.API_V1_STR}/benchmark/diversification-frontier")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["finding"]
    assert len(body["points"]) == 5
    assert len(body["steps"]) == 4
