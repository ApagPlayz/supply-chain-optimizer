"""
Two correctness defects in the sourcing MILP, pinned so they cannot come back.

1. PRICE RESOLUTION (OUTSTANDING_WORK item 8). The objective is denominated in
   milli-cents (`OBJ_SCALE = 100_000`) and depends on that resolution for its
   per-unit freight term, but unit prices used to be rounded to WHOLE CENTS
   first and multiplied up afterwards:

       int(round(price_usd * PRICE_SCALE)) * OBJ_SUBSCALE

   Three digits were discarded before CP-SAT saw them. MLG0603P43NHT000, a real
   part in this catalogue at $0.0031/unit, entered the objective at exactly 0 —
   free in unlimited quantity — and the 15 components with sub-$0.10 offers
   carried a quantisation error of up to ~6%. Meanwhile the greedy baselines in
   `greedy.py` price on full floats, so the two arms of the published benchmark
   were not optimising at the same price resolution.

2. VULNERABILITY DOUBLE COUNT (item 9). The stock-out premium weighted
   `is_chinese_origin` at 0.3 AND `risk_score` at 0.5, but `risk_score` is
   itself `0.60·chinese_origin + 0.25·critical_category + 0.10·limited_suppliers`
   — so the same binary flag arrived twice for 0.60 of the maximum.

Both tests below were confirmed RED against the pre-fix code and GREEN after.
"""
from __future__ import annotations

import os

import pytest

from app.optimization.greedy import landed_cost_breakdown, solve_sourcing_greedy
from app.optimization.sourcing import (
    MAX_OBJ_COEFF,
    OBJ_SCALE,
    PRICE_SCALE,
    RISK_PREMIUM_RATE,
    VULN_W_CHINESE_ORIGIN,
    VULN_W_STOCK_COVERAGE,
    BomLine,
    Offer,
    _stockout_risk_premium_obj_units,
    solve_sourcing,
    to_obj_units,
)
from app.optimization.strategies import get_strategy

# The real price of MLG0603P43NHT000 in backend/supply_chain.db — the offer that
# used to be free to the solver. Not a made-up number.
SUB_CENT_PRICE = 0.0031

CHEAPEST = get_strategy("cheapest")


@pytest.fixture(autouse=True)
def _no_optional_surcharges(monkeypatch):
    """
    Neutralise the ML regime premium and the live-feed surcharge.

    Both are real objective terms, but neither is modelled by
    `greedy.landed_cost_breakdown`, and the regime signal is read off a
    checked-in artifact whose value would make these assertions depend on when
    the model was last trained. Same technique `test_greedy.py` uses for the
    anti-rigging invariant.
    """
    import app.feeds
    import app.ml
    monkeypatch.setattr(app.ml, "get_ml_state", lambda: None)
    monkeypatch.setattr(app.feeds, "get_live_data_cache", lambda: None)


def _offer(price: float, did: int = 1, stock: int = 100_000, km: float = 0.0) -> Offer:
    return Offer(
        component_id=1,
        distributor_id=did,
        distributor_name=f"D{did}",
        price_usd=price,
        stock=stock,
        moq=1,
        is_domestic=True,
        dist_km_from_depot=km,
    )


# ── 1. A sub-cent part is not free to the objective ──────────────────────────

def test_a_sub_cent_part_is_not_free_to_the_objective():
    """
    Buying 1000x more of a $0.0031 part must cost the solver 1000x more.

    The distributor sits at 0 km from the depot, so its per-unit freight rate is
    exactly zero and the ONLY term in the objective that scales with quantity is
    the unit price. Under whole-cent rounding that term was 0, so this delta was
    identically zero no matter how many units the plan bought — the solver would
    happily take any quantity for nothing.
    """
    offers = [_offer(SUB_CENT_PRICE)]

    def obj(qty: int) -> float:
        bom = [BomLine(component_id=1, mpn="MLG0603P43NHT000", quantity=qty)]
        res = solve_sourcing(bom, offers, CHEAPEST, us_only=True)
        assert res.objective_usd is not None
        return res.objective_usd

    delta = obj(1000) - obj(1)

    assert delta == pytest.approx(999 * SUB_CENT_PRICE, abs=0.01), (
        f"999 extra units of a ${SUB_CENT_PRICE} part moved the objective by "
        f"${delta:.4f}, expected ${999 * SUB_CENT_PRICE:.4f} — the price term is "
        "being quantised away"
    )
    assert delta > 0.0, "a priced part is free to the objective"


def test_the_conversion_that_used_to_zero_it_out_is_gone():
    """`to_obj_units` keeps the price; the old two-step conversion destroyed it."""
    old_two_step = int(round(SUB_CENT_PRICE * PRICE_SCALE)) * (OBJ_SCALE // PRICE_SCALE)
    assert old_two_step == 0, "this test no longer reproduces the original defect"
    assert to_obj_units(SUB_CENT_PRICE) == 310


@pytest.mark.parametrize("price", [0.0031, 0.0095, 0.021, 0.055, 0.099])
def test_sub_dime_prices_keep_their_value_through_the_objective(price):
    """
    The 15 components with sub-$0.10 offers carried up to ~6% quantisation
    error on whole cents. At milli-cent resolution the relative error must be
    negligible, and it must beat the whole-cent grid on every one of them.
    """
    milli = to_obj_units(price) / OBJ_SCALE
    cents = int(round(price * PRICE_SCALE)) / PRICE_SCALE

    assert abs(milli - price) <= 0.5 / OBJ_SCALE
    assert abs(milli - price) / price < 1e-3
    assert abs(cents - price) > abs(milli - price)


# ── 2. Both benchmark arms price at the same resolution ──────────────────────

def test_both_arms_price_at_the_same_resolution():
    """
    The MILP prices on the `to_obj_units` grid; the greedy baselines price on
    full floats. Pin the gap between those two yardsticks to at most half a
    milli-cent per unit, and show the whole-cent grid the MILP used to sit on
    does NOT clear that bar for real catalogue prices.
    """
    catalogue_prices = [SUB_CENT_PRICE, 0.0095, 0.099, 2.86, 3500.0]

    for p in catalogue_prices:
        milp_unit_price = to_obj_units(p) / OBJ_SCALE   # what the MILP charges
        greedy_unit_price = p                           # what greedy charges
        assert abs(milp_unit_price - greedy_unit_price) <= 0.5 / OBJ_SCALE, (
            f"${p}: MILP prices at ${milp_unit_price}, greedy at ${greedy_unit_price}"
        )

    # The grid the MILP used to sit on fails the same check on the cheap end.
    old_grid = int(round(SUB_CENT_PRICE * PRICE_SCALE)) / PRICE_SCALE
    assert abs(old_grid - SUB_CENT_PRICE) > 0.5 / OBJ_SCALE


def test_milp_objective_matches_the_greedy_scorer_on_a_sub_cent_bom():
    """
    The benchmark's anti-rigging invariant, exercised on a BOM that contains the
    sub-cent part rather than only on well-priced ones.

    `greedy.landed_cost_breakdown` scores a plan with the same cost model the
    MILP minimises. If the two arms price at different resolutions, the solver's
    own objective and the benchmark's score of the solver's own plan disagree —
    by the full component cost of the sub-cent line, which is exactly what used
    to happen.
    """
    bom = [
        BomLine(component_id=1, mpn="MLG0603P43NHT000", quantity=5000),
        BomLine(component_id=2, mpn="STM32F103C8T6", quantity=10),
    ]
    offers = [
        _offer(SUB_CENT_PRICE, did=1, km=120.0),
        Offer(component_id=1, distributor_id=2, distributor_name="D2",
              price_usd=0.0095, stock=50_000, moq=1, is_domestic=True,
              dist_km_from_depot=300.0),
        Offer(component_id=2, distributor_id=1, distributor_name="D1",
              price_usd=2.86, stock=500, moq=1, is_domestic=True,
              dist_km_from_depot=120.0),
        Offer(component_id=2, distributor_id=2, distributor_name="D2",
              price_usd=3.10, stock=500, moq=1, is_domestic=True,
              dist_km_from_depot=300.0),
    ]

    res = solve_sourcing(bom, offers, CHEAPEST, us_only=True)
    assert res.objective_usd is not None
    scored = landed_cost_breakdown(res.assignments, offers, bom, CHEAPEST)

    # The only legitimate gap between the integer objective and the float scorer
    # is half a unit of rounding on each per-unit coefficient, times the units
    # bought. Two coefficients scale with quantity (unit price and the freight
    # rate), plus one fixed term per opened distributor. Derived, not guessed —
    # a hardcoded tolerance would hide exactly the defect this test exists for.
    units = sum(b.quantity for b in bom)
    n_open = len(res.selected_distributor_ids)
    tol = (2 * units + n_open + 1) * (0.5 / OBJ_SCALE)

    assert scored["total_cost"] == pytest.approx(res.objective_usd, abs=tol), (
        f"solver minimised {res.objective_usd} but the benchmark scores the same "
        f"plan at {scored['total_cost']} — the arms use different price grids"
    )

    # That bound is tiny in absolute terms and would NOT have covered the defect:
    # whole-cent pricing put the sub-cent line's entire $15.50 component cost
    # outside it.
    assert tol < 0.06
    assert 5000 * SUB_CENT_PRICE > 100 * tol

    # And the greedy arm, scored by the same helper, sees the sub-cent line too.
    g = solve_sourcing_greedy(bom, offers, CHEAPEST, us_only=True)
    g_scored = landed_cost_breakdown(g.assignments, offers, bom, CHEAPEST)
    assert g_scored["component_cost"] > 0


# ── 3. Objective coefficients still fit CP-SAT's integer ceiling ─────────────

def test_objective_coefficients_stay_under_the_int64_safety_ceiling():
    """
    Carrying prices at OBJ_SCALE multiplies every price coefficient by 1000.
    Verify — not assume — that the result still clears the same ceiling
    `stochastic.py` holds its own model to.

    Extremes measured from backend/supply_chain.db on 2026-08-28:
      max unit price  $3,500.00
      max offer stock  2,111,292 units
    A single q variable is bounded by min(stock, demand), so the largest
    possible price coefficient x domain product is the two together.
    """
    max_price_usd = 3500.0
    max_units = 2_111_292

    worst_coeff = to_obj_units(max_price_usd)
    worst_term = worst_coeff * max_units

    assert worst_coeff == 350_000_000
    assert worst_term < MAX_OBJ_COEFF, (
        f"worst single objective term {worst_term:.3e} exceeds the ceiling "
        f"{MAX_OBJ_COEFF:.3e}"
    )
    # Headroom is not marginal: at least two orders of magnitude.
    assert worst_term * 100 < MAX_OBJ_COEFF
    assert MAX_OBJ_COEFF < 2**63 - 1


@pytest.mark.skipif(
    not os.path.exists(
        os.path.join(os.path.dirname(__file__), "..", "supply_chain.db")
    ),
    reason="needs the seeded catalogue",
)
def test_the_real_catalogue_has_no_offer_that_prices_to_zero():
    """Every priced offer in the shipped catalogue survives the conversion."""
    import sqlite3
    db = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "supply_chain.db")
    )
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        prices = [r[0] for r in con.execute(
            "SELECT price FROM distributor_offers WHERE price > 0"
        )]
    finally:
        con.close()

    zeroed = [p for p in prices if to_obj_units(p) == 0]
    assert not zeroed, f"{len(zeroed)} priced offers still round to 0: {zeroed[:5]}"

    # The same catalogue under the old whole-cent grid: at least one did.
    assert any(int(round(p * PRICE_SCALE)) == 0 for p in prices), (
        "the catalogue no longer contains the sub-cent offer this guards"
    )

    assert max(to_obj_units(p) for p in prices) < MAX_OBJ_COEFF


# ── 4. The vulnerability index counts each attribute once ────────────────────

def _premium(price=10.0, chinese=False, risk_score=0.5, stock=100_000, moq=1,
             stress=1.0) -> int:
    o = Offer(
        component_id=1, distributor_id=1, distributor_name="D",
        price_usd=price, stock=stock, moq=moq, is_domestic=True,
        risk_score=risk_score, is_chinese_origin=chinese,
    )
    b = BomLine(component_id=1, mpn="X", quantity=1)
    return _stockout_risk_premium_obj_units(o, b, stress)


def test_risk_score_no_longer_enters_the_vulnerability_index():
    """
    `risk_score` is `0.60·chinese_origin + 0.25·critical_category +
    0.10·limited_suppliers`, and on this catalogue risk_score >= 0.6 is exactly
    the set of Chinese-origin parts. Weighting both it and `is_chinese_origin`
    counted one flag twice. The premium must now be invariant to risk_score.
    """
    for chinese in (False, True):
        vals = {_premium(chinese=chinese, risk_score=rs)
                for rs in (0.0, 0.10, 0.20, 0.25, 0.60, 0.70, 1.0)}
        assert len(vals) == 1, (
            f"is_chinese_origin={chinese}: premium still varies with risk_score "
            f"({sorted(vals)}) — the opaque index is back in the formula"
        )


def test_a_flagless_fully_stocked_offer_pays_nothing():
    """
    387 of 791 components (48.9%) carry a flat risk_score of 0.20 with an EMPTY
    risk_factors list — a placeholder, not a measurement. Under the old formula
    that placeholder charged half the catalogue 0.5 x 0.20 = 0.10 of maximum
    vulnerability on no evidence at all. It must charge nothing now.
    """
    assert _premium(chinese=False, risk_score=0.20, stock=100_000, moq=1) == 0


def test_the_chinese_flag_is_counted_exactly_once_at_its_stated_weight():
    """
    Effective weight on the flag was 0.3 direct + 0.5 x 0.6 via risk_score = 0.60.
    It stays 0.60 — the double count is removed, not the signal.
    """
    price, stress = 10.0, 1.0
    domestic = _premium(price=price, chinese=False, stock=100_000, moq=1, stress=stress)
    chinese = _premium(price=price, chinese=True, stock=100_000, moq=1, stress=stress)

    expected = to_obj_units(price * stress * VULN_W_CHINESE_ORIGIN * RISK_PREMIUM_RATE)
    assert chinese - domestic == expected
    assert VULN_W_CHINESE_ORIGIN == 0.6


def test_vulnerability_is_bounded_by_one_so_the_rate_means_what_it_says():
    """
    RISK_PREMIUM_RATE is documented as the surcharge at maximum stress AND
    maximum vulnerability. That is only true if the weights sum to 1 over terms
    that are each in [0, 1]. The old formula's did not: at max it reached
    0.3 + 0.2 + 0.5 x 1.0 = 1.0 only for a risk_score of 1.0, which does not
    exist in the catalogue (max is 0.70).
    """
    assert VULN_W_CHINESE_ORIGIN + VULN_W_STOCK_COVERAGE == pytest.approx(1.0)

    price = 100.0
    worst = _premium(price=price, chinese=True, stock=0, moq=1, stress=1.0)
    assert worst == to_obj_units(price * RISK_PREMIUM_RATE)

    best = _premium(price=price, chinese=False, stock=100_000, moq=1, stress=1.0)
    assert best == 0

    # And nothing in between can exceed the ceiling.
    for chinese in (False, True):
        for stock in (0, 1, 25, 50, 1000):
            assert 0 <= _premium(price=price, chinese=chinese, stock=stock,
                                 moq=1, stress=1.0) <= worst


def test_thin_stock_still_raises_the_premium_monotonically():
    """The surviving second attribute has to keep working."""
    price = 100.0
    premiums = [
        _premium(price=price, stock=s, moq=1, stress=1.0)
        for s in (0, 5, 10, 25, 50, 100)
    ]
    assert premiums == sorted(premiums, reverse=True)
    assert premiums[0] > premiums[-1]
    assert premiums[-1] == 0  # coverage >= 50 x MOQ is fully covered


def test_no_stress_means_no_premium():
    """macro_stress multiplies the whole index; zero stress must zero it out."""
    assert _premium(chinese=True, stock=0, moq=1, stress=0.0) == 0
