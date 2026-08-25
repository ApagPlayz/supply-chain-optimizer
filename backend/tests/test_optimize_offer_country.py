"""
Regression tests for distributor-country propagation into the sourcing `Offer`.

THE BUG THESE GUARD
-------------------
`app/api/optimize.py` built every `Offer` for `POST /optimize/vrp` WITHOUT setting
`distributor_country`, so the dataclass default `"US"` applied to all 92 distributors
— including the ~31 warehoused in China. `sourcing._feed_risk_cents` reads exactly
that field to size the ACLED conflict surcharge, so the live optimizer asked ACLED
about the United States for every offer it priced and geopolitical conflict risk was
country-blind on the only path a user can actually run.

There is a second half to the bug. `feeds.fetchers.fetch_acled` aggregates its 90-day
event counts by **ISO-3166-1 alpha-3** (`{"USA": 12, "CHN": ...}` — it reads ACLED's
`iso3` field). The old default `"US"` is alpha-2 and could never have matched even for
a genuinely American distributor, and `distributors.country` stores human-readable
names ("China", "UK", "Germany"), of which only "USA" coincides with its own ISO3
code. So passing the raw column through would still have left every non-US supplier
invisible. `_acled_country_key` normalizes to ISO3.
"""
from __future__ import annotations

from app.api.optimize import _acled_country_key
from app.models.component import Component, DistributorOffer
from app.models.distributor import Distributor
from app.models.order import CartItem
from app.optimization.sourcing import Offer, _feed_risk_cents


# ── 1. The country-key normalizer ────────────────────────────────────────────

def test_acled_country_key_maps_catalogue_names_to_iso3():
    """Every country value present in the seeded catalogue maps to its ISO3 code."""
    # SELECT DISTINCT country FROM distributors on the shipped DB.
    assert _acled_country_key("USA") == "USA"
    assert _acled_country_key("China") == "CHN"
    assert _acled_country_key("UK") == "GBR"
    assert _acled_country_key("Germany") == "DEU"
    assert _acled_country_key("Singapore") == "SGP"
    assert _acled_country_key("Japan") == "JPN"
    assert _acled_country_key("Netherlands") == "NLD"
    assert _acled_country_key("Thailand") == "THA"
    assert _acled_country_key("Poland") == "POL"
    assert _acled_country_key("Norway") == "NOR"
    assert _acled_country_key("Canada") == "CAN"


def test_acled_country_key_is_iso3_not_iso2():
    """The ACLED feed is keyed by iso3; alpha-2 would never match."""
    assert _acled_country_key("CN") == "CHN"
    assert _acled_country_key("US") == "USA"
    assert len(_acled_country_key("China")) == 3


def test_acled_country_key_handles_missing_and_unknown():
    assert _acled_country_key(None) == "USA"
    assert _acled_country_key("") == "USA"
    assert _acled_country_key("   ") == "USA"
    # Unknown values pass through upper-cased: they simply score no conflict data,
    # which is the honest answer, rather than being silently relabelled "US".
    assert _acled_country_key("Ruritania") == "RURITANIA"


# ── 2. The surcharge actually differentiates on the field ────────────────────

class _Feed:
    def __init__(self, data):
        self.data = data


class _Cache:
    def __init__(self, acled):
        self.acled = acled
        self.gpr = None


def test_feed_risk_surcharge_differentiates_by_distributor_country():
    """Proof the field is load-bearing: same offer, different country, different cost."""
    offer = Offer(
        component_id=1, distributor_id=1, distributor_name="X",
        price_usd=100.0, stock=10, moq=1, is_domestic=False,
    )
    cache = _Cache(_Feed({"USA": 5, "CHN": 400}))

    us = _feed_risk_cents(offer, distributor_country="USA",
                          is_chinese_origin=False, cache=cache)
    cn = _feed_risk_cents(offer, distributor_country="CHN",
                          is_chinese_origin=False, cache=cache)
    # The buggy path sent "US" for EVERY distributor — no key, no surcharge, ever.
    buggy = _feed_risk_cents(offer, distributor_country="US",
                             is_chinese_origin=False, cache=cache)

    assert cn > us
    assert buggy == 0


# ── 3. End-to-end: /optimize/vrp builds Offers carrying the real country ─────

def test_optimize_vrp_offers_carry_the_real_distributor_country(
    client, db_session, auth_token, monkeypatch
):
    """The live path must not hand every offer the dataclass default."""
    db_session.add_all([
        Distributor(id=1, name="DigiKey", latitude=48.1, longitude=-96.2,
                    city="Thief River Falls", state="MN", country="USA",
                    is_domestic=True, total_offers=900),
        Distributor(id=2, name="LCSC", latitude=22.5, longitude=114.1,
                    city="Shenzhen", state=None, country="China",
                    is_domestic=False, total_offers=700),
    ])
    db_session.add_all([
        Component(id=1, mpn="MPN-1", manufacturer="M", category="Resistor",
                  risk_score=0.3),
        Component(id=2, mpn="MPN-2", manufacturer="M", category="Capacitor",
                  risk_score=0.3),
    ])
    db_session.add_all([
        DistributorOffer(id=1, component_id=1, distributor_id=1,
                         price=1.0, stock=100, moq=1),
        DistributorOffer(id=2, component_id=1, distributor_id=2,
                         price=0.8, stock=100, moq=1),
        DistributorOffer(id=3, component_id=2, distributor_id=2,
                         price=2.0, stock=100, moq=1),
    ])
    db_session.commit()

    from app.models.user import User
    user_id = db_session.query(User).filter(User.email == "test@example.com").one().id
    db_session.add_all([
        CartItem(user_id=user_id, component_id=1, distributor_id=1,
                 quantity=10, unit_price=1.0),
        CartItem(user_id=user_id, component_id=2, distributor_id=2,
                 quantity=5, unit_price=2.0),
    ])
    db_session.commit()

    captured: list = []

    def _spy(bom, offers, distributors_meta, depot, **kwargs):
        captured.extend(offers)
        # Short-circuit the solver: this test is about what goes IN, not what
        # comes out. The endpoint turns ValueError into a 400.
        raise ValueError("captured")

    monkeypatch.setattr("app.api.optimize.optimize_bom", _spy)

    resp = client.post(
        "/api/v1/optimize/vrp", json={},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 400, resp.text
    assert captured, "no offers reached the solver"

    by_did = {o.distributor_id: o for o in captured}
    assert by_did[1].distributor_country == "USA"
    # THE REGRESSION: a Shenzhen warehouse must not be labelled the United States.
    assert by_did[2].distributor_country == "CHN"
    assert by_did[2].distributor_country != "US"
    assert len({o.distributor_country for o in captured}) == 2


def test_optimize_source_passes_distributor_country_into_offer():
    """Static guard against a refactor silently dropping the field again."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "app" / "api" / "optimize.py").read_text()
    assert "distributor_country=_acled_country_key(d.country)" in src, (
        "/optimize/vrp must populate Offer.distributor_country from the distributor "
        "record; without it the dataclass default 'US' makes ACLED conflict risk "
        "country-blind for all 92 distributors."
    )
