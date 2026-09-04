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
  2. A PRICE IS ONLY PRINTED WHERE THE DENOMINATOR SURVIVED, AND POINTED THE
     RIGHT WAY. `usd_per_unit_*` must be None wherever the corresponding paired
     95% CI covers zero — a ratio over a denominator indistinguishable from zero
     is an artifact of division, not a price — AND wherever the change is a risk
     INCREASE, because a price of protection is only defined when protection was
     bought. Both cases carry a `_note`; the second republishes the magnitude
     under `_added`.
  3. `significant` MEANS "EXCLUDES ZERO", always, on every interval served.
  4. n AND n_effective ARE BOTH SERVED AND THEY DIFFER. Quoting only n=9 would
     inflate the panel with BOMs the constraint never touched.
  5. THE MECHANISM IS DATA-DERIVED, AND SO ARE ITS RETRACTIONS. Two claims this
     section used to publish lost their evidence when the supply graph was
     corrected to use all 8,176 supplier-part links instead of the 80% a dead
     holdout carve left behind:

       * the COLLAPSE ("the second supplier is cheap per unit of risk and the
         third is not, 6.8x") — the fuller graph leaves ONE priced step, so
         there is no second price to form a multiple against;
       * the EXPECTED-SHORTFALL counter-example — on the fuller, more redundant
         graph broad-stress expected shortfall falls at every step on every
         included BOM.

     Neither test was deleted. Each now asserts that the retraction HOLDS and
     that the payload PUBLISHES the absence — `n_priced_steps` / `price_coverage`
     and `non_monotone_status` — rather than serving a bare null the page skips
     over. Both go red the moment the underlying data changes back.
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


def test_the_collapse_is_retracted_and_the_retraction_is_published(payload):
    """
    THE COLLAPSE IS GONE, AND THE PAYLOAD SAYS SO.

    This test used to require at least two priced steps, because the section's
    claim was a collapse: "the second supplier is cheap per unit of risk and the
    third is not — 6.8x". That claim was measured on a supply graph built from
    80% of the supplier-part links. On the corrected graph exactly ONE step
    carries a price. The second supplier takes mean targeted cascade risk from
    0.556 to 0.056; every later step's interval covers zero, so there is no
    second price and no multiple. The claim is retracted.

    It is retracted, not deleted. What is asserted here is that the retraction
    HOLDS and that it is PUBLISHED — a payload that withheld every price but said
    nothing would leave the old story standing in the reader's head. This goes
    red if a second priced step reappears (the collapse is back and must be
    published as a multiple again), if the counts stop matching the served table,
    or if the payload stops explaining the absence.
    """
    priced = [
        s for s in payload["steps"]
        if s["usd_per_unit_targeted_cascade_risk"] is not None
    ]
    # The served counts are the table's own counts, not a second opinion.
    assert payload["n_steps_total"] == len(payload["steps"])
    assert payload["n_priced_steps"] == len(priced)

    assert len(priced) == 1, (
        f"{len(priced)} steps are priced — a collapse is quotable again and the "
        "retraction in price_coverage, the finding and the page must be replaced "
        "by the multiple"
    )
    only = priced[0]
    assert only["to_k"] == payload["recommended_k"]
    assert only["cost_multiple_vs_first_step"] == 1.0
    assert all(
        s["cost_multiple_vs_first_step"] is None
        for s in payload["steps"] if s["to_k"] != only["to_k"]
    ), "a multiple is served for a step that carries no price to form it from"

    # Every unpriced step says why, and the reason is the one being claimed.
    for s in payload["steps"]:
        if s["usd_per_unit_targeted_cascade_risk"] is not None:
            continue
        assert s["usd_per_unit_targeted_cascade_risk_note"]
        risk = s["marginal_targeted_cascade_risk_removed"]
        assert risk is not None and not risk["significant"], (
            f"{s['label']} withheld a price over a SIGNIFICANT denominator — "
            "that is a different failure from the one being retracted"
        )

    # The absence is published, in the payload and in the sentence.
    cov = payload["price_coverage"]
    assert cov, "every price was withheld and nothing on the payload explains it"
    assert f"ONLY 1 OF {len(payload['steps'])} STEPS" in cov
    assert "no cheap-then-expensive collapse" in cov
    assert f"${only['usd_per_unit_targeted_cascade_risk']:,.2f}" in cov
    assert "ONLY step on this frontier that carries a price" in payload["finding"]


def test_a_second_priced_step_would_still_be_published_as_a_multiple():
    """The collapse is retracted from the DATA, not deleted from the CODE.

    If the frontier ever regains a second priced step, `price_coverage` must go
    back to quoting the collapse. Proving that here is what keeps the retraction
    above a finding rather than a hardcoded "there is never a multiple".
    """
    steps = [
        benchmark_api.FrontierStep(
            label="1 → 2", from_k=1, to_k=2,
            marginal_cost_usd=benchmark_api.FrontierInterval(n=9, mean=58.88),
            marginal_targeted_cascade_risk_removed=benchmark_api.FrontierInterval(
                n=9, mean=0.44, ci95_low=0.22, ci95_high=0.67, significant=True,
            ),
            usd_per_unit_targeted_cascade_risk=132.47,
            cost_multiple_vs_first_step=1.0,
        ),
        benchmark_api.FrontierStep(
            label="2 → 3", from_k=2, to_k=3,
            marginal_cost_usd=benchmark_api.FrontierInterval(n=9, mean=100.35),
            marginal_targeted_cascade_risk_removed=benchmark_api.FrontierInterval(
                n=9, mean=0.11, ci95_low=0.03, ci95_high=0.22, significant=True,
            ),
            usd_per_unit_targeted_cascade_risk=903.14,
            cost_multiple_vs_first_step=6.8,
        ),
    ]
    cov = benchmark_api._price_coverage([], steps)
    assert "2 OF 2 STEPS CARRY A PRICE, and they collapse" in cov
    assert "$132.47" in cov and "$903.14" in cov and "6.8×" in cov


def test_no_price_of_risk_removed_is_ever_served_for_a_risk_increase(payload):
    """
    THE SIGN CONTRACT. `excludes_zero` is symmetric — `(lo > 0) or (hi < 0)` —
    so it says a change is measurable, never that it is a REDUCTION. Gating a
    "$ per unit of risk removed" on significance alone printed `$-1,910.71` in
    the doc's "$/unit cascade risk removed (stress)" column at k = 3, where
    diversification had significantly ADDED risk. No k had ever been
    significantly negative before the graph was corrected, so it never surfaced.

    A price of protection is only defined where protection was bought. Where it
    was not, the removed-price is withheld with a note and the magnitude is
    republished under `_added`.
    """
    seen_added = False
    for p in payload["points"]:
        for scen in ("targeted", "stress"):
            removed = p[f"usd_per_unit_{scen}_cascade_risk"]
            added = p[f"usd_per_unit_{scen}_cascade_risk_added"]
            ci = p[f"delta_{scen}_cascade_risk"]
            assert not (removed is not None and added is not None), (
                f"k={p['k']} {scen}: served a price of risk removed AND a price "
                "of risk added for the same change"
            )
            if removed is not None:
                assert removed > 0
                assert ci["significant"] and ci["mean"] > 0
            if added is not None:
                seen_added = True
                assert added > 0
                assert ci["significant"] and ci["mean"] < 0, (
                    f"k={p['k']} {scen}: a risk-ADDED price over a change that "
                    "is not a significant increase"
                )
                assert p[f"usd_per_unit_{scen}_cascade_risk_note"]
                assert "ADDS" in p[f"usd_per_unit_{scen}_cascade_risk_note"]

    # The artifact currently HAS such a k. If it stops having one this fails,
    # and the page's "risk ADDED" branch would be untested rather than merely
    # unused — which is exactly the state that let the defect ship.
    assert seen_added, (
        "no k on this frontier is a significant risk INCREASE any more; the "
        "sign-handling branch is no longer exercised by the published artifact"
    )
    k3 = next(p for p in payload["points"] if p["k"] == 3)
    assert k3["usd_per_unit_stress_cascade_risk"] is None
    assert k3["usd_per_unit_stress_cascade_risk_added"] == 1910.71


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

def _rises(raw: dict, measure: str) -> list[tuple[str, int, int]]:
    """Consecutive-k steps where broad-stress `measure` RISES, from the artifact."""
    out = []
    for bom in raw["boms"]:
        if not bom.get("included"):
            continue
        pts = [p for p in bom["points"] if p.get("feasible")]
        for prev, cur in zip(pts, pts[1:], strict=False):
            before = prev["scenarios"]["stress"][measure]
            after = cur["scenarios"]["stress"][measure]
            if after > before:
                out.append((bom["bom"], prev["k"], cur["k"]))
    return out


def test_the_expected_shortfall_counter_example_is_retracted_and_published(
    payload, raw
):
    """
    THE COUNTER-EXAMPLE MOVED MEASURE, AND THE PAGE SAYS WHICH.

    This test used to assert only that `non_monotone_example` was not None, and
    its own failure message said the remedy: "the mechanism section's claim must
    be removed". Half of it must be. The counter-example the section named was an
    EXPECTED SHORTFALL one, and on the corrected supply graph — fuller, and so
    more redundant — broad-stress expected shortfall falls at EVERY step on EVERY
    included BOM. That example does not exist and is withdrawn.

    The mechanism itself is not withdrawn, because it is still measured: the
    coarser p50 measure, cascade risk, still rises. Publishing a cascade-risk
    number under the old expected-shortfall wording would be the same class of
    error the retraction is fixing, so `measure` now travels with the values.

    Asserted, in both directions:
      * expected shortfall really is monotone here — recomputed from the raw
        rows, so if a rise reappears this fails and the finer measure must be
        named again;
      * the payload publishes the retraction in words rather than serving a bare
        null the page silently skips;
      * whatever example IS served is a real row of the artifact, in the measure
        it claims.
    """
    es_rises = _rises(raw, "expected_shortfall")
    assert not es_rises, (
        f"broad-stress expected shortfall rises again at {es_rises} — the finer "
        "measure has a counter-example once more and the retraction in "
        "non_monotone_status must be replaced by it"
    )

    status = payload["non_monotone_status"]
    assert status, "the scan found nothing and published nothing about it"
    assert "RETRACTED" in status
    assert "expected shortfall" in status

    ex = payload["non_monotone_example"]
    assert ex is not None, (
        "neither measure is non-monotone any more — the mechanism section's "
        "counter-example must be dropped and non_monotone_status must say the "
        "constraint merely PERMITS non-monotonicity rather than exhibiting it"
    )
    assert ex["measure"] == "cascade_risk", (
        "the surviving counter-example is not the coarse measure the retraction "
        "describes"
    )
    assert ex["measure_label"] == "cascade risk"
    assert ex["scenario"] == "stress"

    # A real row of the artifact, in the measure it names.
    bom = next(b for b in raw["boms"] if b["bom"] == ex["bom"])
    before = next(p for p in bom["points"] if p["k"] == ex["from_k"])
    after = next(p for p in bom["points"] if p["k"] == ex["to_k"])
    assert before["scenarios"]["stress"][ex["measure"]] == pytest.approx(
        ex["value_before"], abs=1e-4
    )
    assert after["scenarios"]["stress"][ex["measure"]] == pytest.approx(
        ex["value_after"], abs=1e-4
    )
    assert ex["value_after"] > ex["value_before"]
    assert ex["n_suppliers_after"] > ex["n_suppliers_before"]
    assert isinstance(ex["keeps_k1_suppliers"], bool)
    assert (ex["bom"], ex["from_k"], ex["to_k"]) in _rises(raw, "cascade_risk")


def test_the_retraction_is_corroborated_at_the_panel_level(payload):
    """A single BOM is an anecdote. The panel says the same thing.

    On the corrected graph there is a k whose broad-stress cascade risk is
    SIGNIFICANTLY worse than k = 1 — the paired interval excludes zero on the
    added side. That is stronger evidence than the retracted per-BOM
    expected-shortfall example ever was, and it is the same fact the sign
    contract above stops being mislabelled as a cheap price.
    """
    worse = [
        p for p in payload["points"]
        if p["k"] > 1
        and p["delta_stress_cascade_risk"]["significant"]
        and p["delta_stress_cascade_risk"]["mean"] < 0
    ]
    assert worse, (
        "no k is significantly MORE exposed under broad stress than k=1 any "
        "more; non_monotone_status must stop leaning on the panel result"
    )
    for p in worse:
        assert p["usd_per_unit_stress_cascade_risk"] is None
        assert p["usd_per_unit_stress_cascade_risk_added"] is not None


def test_the_finer_measure_wins_when_it_has_a_counter_example():
    """Order of preference, proved on synthetic BOMs rather than assumed.

    cascade_risk is `1 - p50(fulfillment)` over a 4-line BOM and moves only in
    quarters; expected_shortfall is `1 - mean(fulfillment)` and resolves any
    change. Where BOTH rise, the finer one must be the one reported — otherwise
    the served example would understate a real, smaller effect.
    """
    def _pt(k, es, cr, ns):
        return {
            "k": k, "feasible": True, "n_distinct_suppliers": ns,
            "keeps_k1_suppliers": False,
            "scenarios": {"stress": {"expected_shortfall": es, "cascade_risk": cr}},
        }

    boms = [{
        "bom": "both_rise", "included": True,
        "points": [_pt(1, 0.10, 0.00, 1), _pt(2, 0.30, 0.25, 2)],
    }]
    ex, status = benchmark_api._non_monotone(boms)
    assert ex is not None
    assert ex.measure == "expected_shortfall"
    assert ex.value_before == 0.10 and ex.value_after == 0.30
    assert "NOT MONOTONE in the finer measure" in status

    # Monotone in both -> no example, and the absence is stated.
    flat = [{
        "bom": "monotone", "included": True,
        "points": [_pt(1, 0.30, 0.25, 1), _pt(2, 0.10, 0.00, 2)],
    }]
    ex2, status2 = benchmark_api._non_monotone(flat)
    assert ex2 is None
    assert "RETRACTED" in status2 and "PERMITS" in status2


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
        # Both of these carry a RETRACTION on the current artifact. An empty one
        # is not a cosmetic gap — it is a claim silently disappearing off the
        # page instead of being withdrawn on it.
        "price_coverage",
        "non_monotone_status",
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


# ── 7. recommended_k: the page may not anchor on a numeral of its own ─────────
#
# `BenchmarkPage.tsx` used to highlight the recommended row with a hardcoded
# `k === 2` in three places. Nothing on screen was false — `_frontier_finding()`
# anchored on the same step — but two independent copies of a rule stay in
# agreement only by luck, and this repo has twice shipped figures that two
# documents agreed on while both disagreed with the code. `recommended_k` is now
# served, `_recommended_k()` is the only place the rule lives, and these tests
# fail if the served value and the sentence it composes ever part company.


def test_recommended_k_is_served_and_is_a_real_step(payload):
    k = payload["recommended_k"]
    assert isinstance(k, int), "recommended_k must be served as a number, not omitted"
    assert k in {s["to_k"] for s in payload["steps"]}
    assert payload["recommended_k_basis"], "a served rule with no stated basis is a magic number"


def test_the_recommended_step_is_the_cheapest_priced_step(payload):
    """The rule, recomputed from the served table rather than trusted.

    If `_recommended_k()` ever stops meaning "lowest USD per unit of targeted
    cascade risk removed among the priced steps", this recomputation and the
    served field diverge and this test goes red.
    """
    priced = [
        s for s in payload["steps"]
        if s["usd_per_unit_targeted_cascade_risk"] is not None
        and s["marginal_targeted_cascade_risk_removed"] is not None
        and s["marginal_targeted_cascade_risk_removed"]["significant"]
    ]
    assert priced, "the frontier serves no priced step at all"
    expected = min(priced, key=lambda s: (s["usd_per_unit_targeted_cascade_risk"], s["to_k"]))
    assert payload["recommended_k"] == expected["to_k"]


def test_every_priced_step_is_at_least_as_expensive_as_the_recommended_one(payload):
    """The recommendation is a minimum, so nothing priced may undercut it."""
    k = payload["recommended_k"]
    rec = next(s for s in payload["steps"] if s["to_k"] == k)
    for s in payload["steps"]:
        price = s["usd_per_unit_targeted_cascade_risk"]
        if price is None:
            continue
        assert price >= rec["usd_per_unit_targeted_cascade_risk"] - 1e-9, (
            f"step {s['label']} removes risk more cheaply than the recommended k={k}"
        )


def test_the_sentence_and_the_served_k_describe_the_same_step(payload):
    """The one that closes the loop: prose and field, or neither.

    The finding names the k-th supplier in words. Those words are generated from
    `recommended_k`, so a client highlighting `recommended_k` is highlighting the
    row the sentence is about — and if the two ever disagree, the ordinal in the
    sentence stops matching the served number and this fails.
    """
    k = payload["recommended_k"]
    ordinal = benchmark_api._ordinal(k)
    assert f"The {ordinal} supplier removes" in payload["finding"]
    assert f"Buy the {ordinal} supplier." in payload["verdict"]
    assert f"Do not buy the {benchmark_api._ordinal(k + 1)}." in payload["verdict"]
    # And the figures in the sentence are that step's figures, not a neighbour's.
    step = next(s for s in payload["steps"] if s["to_k"] == k)
    assert f"${step['marginal_cost_usd']['mean']:,.2f}" in payload["finding"]


def test_recommended_k_follows_the_frontier_instead_of_a_hardcoded_two(monkeypatch):
    """Move the cheapest step to k=3 and the recommendation must move with it.

    This is the test the hardcoded `k === 2` could never have passed. It also
    pins the rule against the tempting wrong one: step 1→2 below is SIGNIFICANT
    and still not recommended, because it removes its risk at 10x the price.
    """
    steps = [
        benchmark_api.FrontierStep(
            label="1 → 2", from_k=1, to_k=2,
            marginal_cost_usd=benchmark_api.FrontierInterval(n=9, mean=500.0),
            marginal_targeted_cascade_risk_removed=benchmark_api.FrontierInterval(
                n=9, mean=0.10, ci95_low=0.05, ci95_high=0.20, significant=True,
            ),
            usd_per_unit_targeted_cascade_risk=5000.0,
        ),
        benchmark_api.FrontierStep(
            label="2 → 3", from_k=2, to_k=3,
            marginal_cost_usd=benchmark_api.FrontierInterval(n=9, mean=50.0),
            marginal_targeted_cascade_risk_removed=benchmark_api.FrontierInterval(
                n=9, mean=0.10, ci95_low=0.05, ci95_high=0.20, significant=True,
            ),
            usd_per_unit_targeted_cascade_risk=500.0,
        ),
    ]
    points = [
        benchmark_api.FrontierPoint(
            k=3, n_boms_feasible=9, n_effective=6,
            mean_total_cost_usd=500.0, mean_suppliers=3.0,
        )
    ]
    assert benchmark_api._recommended_k(steps) == 3
    finding, verdict = benchmark_api._frontier_finding(points, steps)
    assert "The third supplier removes" in finding
    assert verdict == "Buy the third supplier. Do not buy the fourth."


def test_an_unpriced_step_can_never_be_recommended():
    """A step whose interval covers zero carries no price and is not a buy."""
    steps = [
        benchmark_api.FrontierStep(
            label="1 → 2", from_k=1, to_k=2,
            marginal_cost_usd=benchmark_api.FrontierInterval(n=9, mean=58.88),
            marginal_targeted_cascade_risk_removed=benchmark_api.FrontierInterval(
                n=9, mean=0.44, ci95_low=-0.1, ci95_high=0.9, significant=False,
            ),
            usd_per_unit_targeted_cascade_risk=None,
        )
    ]
    assert benchmark_api._recommended_k(steps) is None
    assert benchmark_api._frontier_finding([], steps) == ("", "")


def test_recommended_k_is_null_exactly_when_the_finding_is_empty(payload):
    """The two states must not disagree: a highlighted row with no sentence, or
    a sentence with no highlighted row, is the drift this field exists to stop."""
    assert (payload["recommended_k"] is None) == (payload["finding"] == "")
    assert (payload["recommended_k"] is None) == (payload["verdict"] == "")
