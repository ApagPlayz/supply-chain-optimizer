"""
Tests for OUTSTANDING_WORK.md items 10 and 11.

Item 10 — `/live-prices/*` sorted offers by raw `price` with no currency
normalisation, so a "best price" pick could be a non-USD figure compared
numerically against USD ones (verified live: Schukat Electronic returns
2.10 EUR, Farnell UK returns 2.83 GBP, alongside USD offers). Fixed by
scoping "cheapest first" / "best price" to USD-denominated offers only
(app.api.live_prices._sort_offers_for_ranking / _PRICE_COMPARISON_BASIS) —
no FX rate source exists anywhere in this repo, and this fix intentionally
does not add one. Every offer is still returned; non-USD offers carry
`price_comparable=false` and are listed after the ranked USD offers.

Item 11 — `DigiKeyClient.search_mpn` was a `Limit:1` keyword search with no
exact-match check (verified live: querying "ESP8266EX" returned
"ESP-WROOM-02U" at $3.30 — a different, real part). Fixed by requiring the
candidate's own ManufacturerProductNumber/ManufacturerPartNumber to equal
the query MPN after normalizing case/whitespace/separators; a keyword hit
that doesn't clear that bar returns None (an honest miss), not the nearest
thing.

All DigiKey/Nexar HTTP calls in this file are mocked; no live API traffic.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.clients.digikey_client import DigiKeyClient, _normalize_mpn
from app.api.live_prices import (
    _deduplicate_offers,
    _sort_offers_for_ranking,
    _to_live_offer,
)


# ══════════════════════════════════════════════════════════════════════════════
# Item 11 — DigiKey exact-match check
# ══════════════════════════════════════════════════════════════════════════════

def _dk_response(status_code: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=body,
        request=httpx.Request("POST", "https://api.digikey.com/products/v4/search/keyword"),
    )


def _dk_client(monkeypatch, response: httpx.Response) -> DigiKeyClient:
    """A DigiKeyClient whose OAuth token fetch is stubbed and whose single
    keyword-search POST returns `response`."""
    from unittest.mock import AsyncMock

    client = DigiKeyClient("test-id", "test-secret")
    monkeypatch.setattr(client, "_get_token", AsyncMock(return_value="fake-token"))
    monkeypatch.setattr(httpx.AsyncClient, "post", AsyncMock(return_value=response))
    return client


def test_normalize_mpn_strips_case_whitespace_and_separators():
    assert _normalize_mpn("esp8266ex") == "ESP8266EX"
    assert _normalize_mpn("ESP-8266-EX") == "ESP8266EX"
    assert _normalize_mpn("ESP_8266_EX") == "ESP8266EX"
    assert _normalize_mpn(" ESP 8266 EX ") == "ESP8266EX"
    assert _normalize_mpn(None) == ""


def test_search_mpn_rejects_the_verified_near_miss(monkeypatch):
    """The exact reported regression: querying ESP8266EX must NOT come back as
    ESP-WROOM-02U, a different, real, purchasable part."""
    body = {
        "ExactMatches": [],
        "Products": [
            {
                "ManufacturerProductNumber": "ESP-WROOM-02U",
                "Manufacturer": {"Name": "Espressif"},
                "QuantityAvailable": 500,
                "MinimumOrderQuantity": 1,
                "ProductVariations": [
                    {"StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 3.30}]}
                ],
            }
        ],
    }
    client = _dk_client(monkeypatch, _dk_response(200, body))

    product = asyncio.run(client.search_mpn("ESP8266EX"))

    assert product is None  # honest miss, not the nearest-sounding part


def test_search_mpn_accepts_exact_match_in_products_list(monkeypatch):
    body = {
        "ExactMatches": [],
        "Products": [
            {
                "ManufacturerProductNumber": "ESP8266EX",
                "Manufacturer": {"Name": "Espressif"},
                "QuantityAvailable": 100,
                "MinimumOrderQuantity": 1,
                "ProductVariations": [
                    {"StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 2.10}]}
                ],
            }
        ],
    }
    client = _dk_client(monkeypatch, _dk_response(200, body))

    product = asyncio.run(client.search_mpn("ESP8266EX"))

    assert product is not None
    assert product["ManufacturerProductNumber"] == "ESP8266EX"
    offer = client.parse_offer(product)
    assert offer["price"] == 2.10
    assert offer["mpn"] == "ESP8266EX"


def test_search_mpn_prefers_exact_matches_list_over_ranked_top_hit(monkeypatch):
    """DigiKey's own ExactMatches can contain the real part even when the
    ranked Products[0] is something else — check ExactMatches first."""
    body = {
        "ExactMatches": [
            {
                "ManufacturerProductNumber": "ESP8266EX",
                "ProductVariations": [
                    {"StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 1.95}]}
                ],
            }
        ],
        "Products": [
            {
                "ManufacturerProductNumber": "ESP-WROOM-02U",
                "ProductVariations": [
                    {"StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 3.30}]}
                ],
            }
        ],
    }
    client = _dk_client(monkeypatch, _dk_response(200, body))

    product = asyncio.run(client.search_mpn("ESP8266EX"))

    assert product is not None
    assert product["ManufacturerProductNumber"] == "ESP8266EX"


def test_search_mpn_normalizes_case_and_separators_before_matching(monkeypatch):
    """A returned MPN that differs only by case/dash/whitespace still counts
    as the same part."""
    body = {
        "ExactMatches": [],
        "Products": [
            {
                "ManufacturerProductNumber": "esp-8266-ex",
                "ProductVariations": [
                    {"StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 2.05}]}
                ],
            }
        ],
    }
    client = _dk_client(monkeypatch, _dk_response(200, body))

    product = asyncio.run(client.search_mpn("ESP8266EX"))

    assert product is not None


def test_search_mpn_no_candidates_at_all_returns_none(monkeypatch):
    body = {"ExactMatches": [], "Products": []}
    client = _dk_client(monkeypatch, _dk_response(200, body))

    assert asyncio.run(client.search_mpn("ANY-MPN")) is None


def test_search_mpn_404_returns_none(monkeypatch):
    client = _dk_client(monkeypatch, _dk_response(404, {}))

    assert asyncio.run(client.search_mpn("ANY-MPN")) is None


def test_fetch_live_offers_reports_zero_offers_not_a_wrong_part(monkeypatch):
    """End-to-end through the shared fetch helper: a DigiKey near-miss must
    surface as `digikey` reporting `status=ok, offer_count=0`, never as an
    offer for the wrong SKU."""
    from app.api.live_prices import _fetch_live_offers, SourceStatus
    from app.core.config import settings

    monkeypatch.setattr(settings, "NEXAR_CLIENT_ID", "")
    monkeypatch.setattr(settings, "NEXAR_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "OEMSECRETS_API_KEY", "")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "TRUSTEDPARTS_API_KEY", "")

    async def _near_miss(self, mpn):
        # search_mpn itself already filtered the ESP-WROOM-02U near-miss out
        # (that's what test_search_mpn_rejects_the_verified_near_miss checks
        # directly) — at this layer the client simply has nothing to return.
        return None

    monkeypatch.setattr(DigiKeyClient, "search_mpn", _near_miss)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_fetch_live_offers("ESP8266EX"))

    # No sources had offers -> 404, but the digikey source itself is "ok" with
    # zero offers, not an error and not a wrong-part hit.
    assert exc_info.value.status_code == 404
    detail = exc_info.value.detail
    digikey_report = next(s for s in detail["sources"] if s["name"] == "digikey")
    assert digikey_report["status"] == SourceStatus.ok.value
    assert digikey_report["offer_count"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Item 10 — currency-safe ranking
# ══════════════════════════════════════════════════════════════════════════════

def _offer(distributor, price, currency, sku=None):
    return {"distributor": distributor, "sku": sku or distributor, "price": price,
            "currency": currency, "stock": 10, "moq": 1, "is_authorized": True,
            "source": "test"}


def test_sort_offers_for_ranking_never_ranks_a_cheaper_non_usd_offer_first():
    """The exact reported scenario: Schukat 2.10 EUR is numerically smaller
    than a 2.50 USD offer, but must not be ranked cheapest."""
    offers = [
        _offer("Schukat Electronic", 2.10, "EUR"),
        _offer("Farnell UK", 2.83, "GBP"),
        _offer("DigiKey", 2.50, "USD"),
        _offer("Mouser", 2.75, "USD"),
    ]

    ranked = _sort_offers_for_ranking(offers)

    assert ranked[0]["distributor"] == "DigiKey"   # cheapest USD, not cheapest overall
    assert ranked[1]["distributor"] == "Mouser"
    # non-USD offers come after, sorted by currency then price
    non_usd = ranked[2:]
    assert {o["currency"] for o in non_usd} == {"EUR", "GBP"}


def test_sort_offers_for_ranking_all_usd_behaves_like_plain_cheapest_first():
    offers = [_offer("A", 5.0, "USD"), _offer("B", 1.0, "USD"), _offer("C", 3.0, "USD")]
    ranked = _sort_offers_for_ranking(offers)
    assert [o["distributor"] for o in ranked] == ["B", "C", "A"]


def test_sort_offers_for_ranking_all_non_usd_no_usd_offer_at_all():
    """If every offer is non-USD there is no ranked best price — the function
    must not silently promote one to look like a comparison winner."""
    offers = [_offer("Schukat", 2.10, "EUR"), _offer("Farnell", 1.50, "GBP")]
    ranked = _sort_offers_for_ranking(offers)
    assert len(ranked) == 2
    assert all(not _to_live_offer(o).price_comparable for o in ranked)


def test_to_live_offer_flags_price_comparable_by_currency():
    usd = _to_live_offer(_offer("DigiKey", 2.50, "USD"))
    eur = _to_live_offer(_offer("Schukat", 2.10, "EUR"))
    assert usd.price_comparable is True
    assert eur.price_comparable is False


def test_deduplicate_offers_does_not_compare_prices_across_currencies():
    """Same (distributor, sku) key reported in two currencies must not have
    the 'cheaper number' win just because it's numerically smaller — that
    would be exactly the item-10 bug relocated into dedup instead of sort."""
    offers = [
        _offer("Schukat Electronic", 2.10, "EUR", sku="SKU1"),
        _offer("Schukat Electronic", 2.50, "USD", sku="SKU1"),
    ]
    deduped = _deduplicate_offers(offers)
    assert len(deduped) == 1
    # First one seen is kept when currencies disagree on the same key.
    assert deduped[0]["currency"] == "EUR"


def test_deduplicate_offers_still_keeps_cheapest_within_same_currency():
    offers = [
        _offer("Mouser", 5.00, "USD", sku="SKU2"),
        _offer("Mouser", 3.00, "USD", sku="SKU2"),
    ]
    deduped = _deduplicate_offers(offers)
    assert len(deduped) == 1
    assert deduped[0]["price"] == 3.00


# ── Endpoint-level: mixed-currency BOM/single-MPN responses ─────────────────

def _configure_nexar_only(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "NEXAR_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "NEXAR_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "OEMSECRETS_API_KEY", "")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_ID", "")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "TRUSTEDPARTS_API_KEY", "")


def _mixed_currency_nexar_part():
    return {
        "sellers": [
            {
                "company": {"name": "Schukat Electronic"},
                "isAuthorized": True,
                "offers": [{
                    "sku": "SCH-1", "inventoryLevel": 20, "moq": 1,
                    "prices": [{"quantity": 1, "price": 2.10, "currency": "EUR"}],
                }],
            },
            {
                "company": {"name": "DigiKey"},
                "isAuthorized": True,
                "offers": [{
                    "sku": "DK-1", "inventoryLevel": 50, "moq": 1,
                    "prices": [{"quantity": 1, "price": 2.50, "currency": "USD"}],
                }],
            },
        ]
    }


def test_live_prices_endpoint_ranks_cheapest_usd_not_cheapest_raw_number(client, auth_token, monkeypatch):
    from app.core.clients.nexar_client import NexarClient

    _configure_nexar_only(monkeypatch)

    async def _ok(self, mpn, currency="USD", country="US"):
        return _mixed_currency_nexar_part()

    monkeypatch.setattr(NexarClient, "search_mpn", _ok)

    r = client.get(
        "/api/v1/live-prices/ANY-MPN",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    body = r.json()

    assert body["total_offers"] == 2
    assert "price_comparison_basis" in body and body["price_comparison_basis"]

    # DigiKey (USD, 2.50) must rank ahead of Schukat (EUR, 2.10) even though
    # 2.10 < 2.50 numerically.
    assert body["offers"][0]["distributor"] == "DigiKey"
    assert body["offers"][0]["price_comparable"] is True
    assert body["offers"][1]["distributor"] == "Schukat Electronic"
    assert body["offers"][1]["price_comparable"] is False


def test_bom_endpoint_carries_price_comparison_basis_per_line_and_top_level(client, auth_token, monkeypatch):
    from app.core.clients.nexar_client import NexarClient

    _configure_nexar_only(monkeypatch)

    async def _search_bom(self, mpns, currency="USD", country="US"):
        return [{"reference": m, "error": None, "part": _mixed_currency_nexar_part()} for m in mpns]

    monkeypatch.setattr(NexarClient, "search_bom", _search_bom)

    r = client.post(
        "/api/v1/live-prices/bom",
        json={"items": [{"mpn": "ANY-MPN"}]},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    line = body["results"]["ANY-MPN"]
    assert line["offers"][0]["distributor"] == "DigiKey"
    assert line["price_comparison_basis"]


# ── sync endpoint: must never write a non-USD price into the USD price column ──

def test_sync_skips_non_usd_offers_and_reports_them(client, auth_token, db_session, monkeypatch):
    from app.core.clients.nexar_client import NexarClient
    from app.models.component import Component, DistributorOffer
    from app.models.distributor import Distributor

    _configure_nexar_only(monkeypatch)

    component = Component(mpn="ANY-MPN", manufacturer="TestCo", category="Test")
    schukat = Distributor(name="Schukat Electronic", latitude=51.2, longitude=6.8, country="Germany", is_domestic=False)
    digikey = Distributor(name="DigiKey", latitude=48.1, longitude=-96.2, country="USA", is_domestic=True)
    db_session.add_all([component, schukat, digikey])
    db_session.commit()
    db_session.refresh(component)
    db_session.refresh(schukat)
    db_session.refresh(digikey)

    async def _ok(self, mpn, currency="USD", country="US"):
        return _mixed_currency_nexar_part()

    monkeypatch.setattr(NexarClient, "search_mpn", _ok)

    r = client.post(
        f"/api/v1/live-prices/{component.mpn}/sync",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    body = r.json()

    assert body["non_usd_offers_skipped"] == 1
    assert body["db_offers_created"] == 1  # only the USD (DigiKey) offer was written

    offers = (
        db_session.query(DistributorOffer)
        .filter(DistributorOffer.component_id == component.id)
        .all()
    )
    assert len(offers) == 1
    written = offers[0]
    assert written.distributor_id == digikey.id
    assert written.price == 2.50
    assert written.currency == "USD"
    # No row was created for Schukat's EUR offer under the USD price column.
    schukat_offers = [o for o in offers if o.distributor_id == schukat.id]
    assert schukat_offers == []
