"""
Tests for audit item 9: Nexar live-pricing failures on both `/live-prices/{mpn}`
and `/live-prices/bom`.

Root causes fixed in app/core/clients/nexar_client.py and app/api/live_prices.py:

  (a) The BOM/multi-MPN GraphQL query used `supMultiMatch(lines: [SupBomLineInput!]!)`,
      which does not exist in the Nexar schema (no `lines` arg, no `SupBomLineInput`
      type) -> every call returned HTTP 400. Confirmed via live GraphQL introspection
      that the real signature is
      `supMultiMatch(queries: [SupPartMatchQuery!]!, country: String!, currency: String!)
      -> [SupPartMatch!]!` (a flat list, not an object with a nested `.parts` field).

  (b) `dict.get(key, default)` only falls back to `default` when the key is *absent* —
      Nexar can return an explicit `null` for object-typed fields with no match
      (e.g. `"supSearchMpn": null`, or a seller's `"company": null`), and the old
      `.get("x", {}).get("y")` chains crashed with
      'NoneType' object has no attribute 'get' the moment that happened.

  (c) Every per-source failure was caught and swallowed into a bare `print(...)`,
      so a caller could not tell "this source had zero offers" apart from
      "this source's call blew up" — both looked like an identical 200 with
      fewer offers. Sources are now reported structurally (see SourceReport).

All Nexar HTTP calls in this file are mocked; no live API traffic. The BOM query
shape and the supMultiMatch response shape were independently confirmed against
the live Nexar API during development (see task report) but are not re-verified
live here, to respect the account's tiny (10-lookup) quota.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.clients.nexar_client import NexarAPIError, NexarClient


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fake_response(status_code: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=body,
        request=httpx.Request("POST", "https://api.nexar.com/graphql/"),
    )


def _client(monkeypatch, response: httpx.Response) -> NexarClient:
    """A NexarClient whose OAuth token fetch is stubbed out and whose single
    GraphQL POST call returns `response`."""
    client = NexarClient("test-id", "test-secret")
    monkeypatch.setattr(client, "_ensure_token", AsyncMock(return_value="fake-token"))
    monkeypatch.setattr(httpx.AsyncClient, "post", AsyncMock(return_value=response))
    return client


def _capture_payload(monkeypatch, response: httpx.Response) -> tuple[NexarClient, dict]:
    """Like _client(), but also captures the JSON payload sent to Nexar."""
    client = NexarClient("test-id", "test-secret")
    monkeypatch.setattr(client, "_ensure_token", AsyncMock(return_value="fake-token"))
    captured: dict = {}

    async def _fake_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    return client, captured


# ── (a) BOM query shape ─────────────────────────────────────────────────────────

def test_search_bom_sends_valid_supMultiMatch_shape(monkeypatch):
    """The request payload must use `queries: [SupPartMatchQuery!]!` (+ country/currency),
    not the old, nonexistent `lines: [SupBomLineInput!]!` that caused every BOM call
    to 400."""
    response = _fake_response(200, {"data": {"supMultiMatch": []}})
    client, captured = _capture_payload(monkeypatch, response)

    asyncio.run(client.search_bom(["STM32F103C8T6", "ATMEGA328P-AUR"]))

    variables = captured["json"]["variables"]
    assert "lines" not in variables, "old, invalid `lines` argument must be gone"
    assert "queries" in variables
    assert variables["country"] == "US"
    assert variables["currency"] == "USD"
    assert variables["queries"] == [
        {"mpn": "STM32F103C8T6", "reference": "STM32F103C8T6", "start": 0, "limit": 1},
        {"mpn": "ATMEGA328P-AUR", "reference": "ATMEGA328P-AUR", "start": 0, "limit": 1},
    ]
    # The query string itself must reference the real field/arg names.
    query_text = captured["json"]["query"]
    assert "supMultiMatch(queries: $queries" in query_text
    assert "SupPartMatchQuery" in query_text
    assert "SupBomLineInput" not in query_text


def test_search_bom_400_bad_request_raises_with_message(monkeypatch):
    """Reproduces the original defect directly: a malformed/rejected query gets HTTP
    400 with a GraphQL error body. This must now raise (visibly), not be swallowed."""
    response = _fake_response(
        400,
        {"errors": [{"message": "Cannot query field \"lines\" on type \"Query\"."}]},
    )
    client = _client(monkeypatch, response)

    with pytest.raises(NexarAPIError, match="400"):
        asyncio.run(client.search_bom(["STM32F103C8T6"]))


def test_search_bom_parses_real_supMultiMatch_response_shape(monkeypatch):
    """supMultiMatch returns `[SupPartMatch!]!` directly (a flat list keyed by
    `reference`/`hits`/`error`/`parts`), not the old assumed
    `{hits, parts: [{reference, part}]}` object shape."""
    body = {
        "data": {
            "supMultiMatch": [
                {
                    "reference": "STM32F103C8T6",
                    "hits": 1,
                    "error": None,
                    "parts": [{
                        "mpn": "STM32F103C8T6",
                        "manufacturer": {"name": "STMicroelectronics"},
                        "shortDescription": "MCU",
                        "sellers": [{
                            "company": {"name": "DigiKey"},
                            "isAuthorized": True,
                            "offers": [{
                                "sku": "497-STM32F103C8T6",
                                "inventoryLevel": 500,
                                "moq": 1,
                                "packaging": "Cut Tape",
                                "prices": [{"quantity": 1, "price": 3.21, "currency": "USD"}],
                            }],
                        }],
                    }],
                },
                {
                    "reference": "BOGUS-MPN",
                    "hits": 0,
                    "error": "invalid MPN format",
                    "parts": [],
                },
            ]
        }
    }
    client = _client(monkeypatch, _fake_response(200, body))

    results = asyncio.run(client.search_bom(["STM32F103C8T6", "BOGUS-MPN"]))

    assert len(results) == 2
    good, bad = results
    assert good["reference"] == "STM32F103C8T6"
    assert good["error"] is None
    assert good["part"]["mpn"] == "STM32F103C8T6"
    offers = client.parse_offers(good["part"])
    assert len(offers) == 1
    assert offers[0]["distributor"] == "DigiKey"
    assert offers[0]["price"] == 3.21

    assert bad["reference"] == "BOGUS-MPN"
    assert bad["error"] == "invalid MPN format"
    assert bad["part"] is None


# ── (b) NoneType deref guards ────────────────────────────────────────────────────

def test_search_mpn_null_supSearchMpn_does_not_crash(monkeypatch):
    """Reproduces the exact reported crash: `data.get("data", {}).get("supSearchMpn", {})`
    blows up with 'NoneType' object has no attribute 'get' when Nexar returns an
    explicit `"supSearchMpn": null` (e.g. for an MPN it can't resolve at all)."""
    body = {"data": {"supSearchMpn": None}}
    client = _client(monkeypatch, _fake_response(200, body))

    part = asyncio.run(client.search_mpn("ATMEGA328P-AUR"))

    assert part is None  # must return gracefully, not raise


def test_search_mpn_null_results_entry_does_not_crash(monkeypatch):
    body = {"data": {"supSearchMpn": {"results": [None]}}}
    client = _client(monkeypatch, _fake_response(200, body))

    part = asyncio.run(client.search_mpn("SOME-MPN"))

    assert part is None


def test_search_mpn_null_data_with_graphql_errors_raises(monkeypatch):
    """A 200 response can still carry `"data": null` alongside a GraphQL `errors`
    array (e.g. a resolver exception). That must be surfaced as an error, not
    silently treated as 'zero results'."""
    body = {"data": None, "errors": [{"message": "internal resolver error"}]}
    client = _client(monkeypatch, _fake_response(200, body))

    with pytest.raises(NexarAPIError, match="internal resolver error"):
        asyncio.run(client.search_mpn("SOME-MPN"))


def test_parse_offers_null_company_does_not_crash():
    """`seller.get("company", {}).get("name")` crashes if `company` is explicitly
    null (a seller whose company record didn't resolve) — this is the other
    concrete way the 'NoneType' object has no attribute 'get' crash was reported."""
    part = {
        "sellers": [
            {
                "company": None,  # <- the crash trigger
                "isAuthorized": False,
                "offers": [{
                    "sku": "X1",
                    "inventoryLevel": 10,
                    "moq": 1,
                    "prices": [{"quantity": 1, "price": 1.23, "currency": "USD"}],
                }],
            },
        ]
    }
    client = NexarClient("id", "secret")

    offers = client.parse_offers(part)  # must not raise

    assert len(offers) == 1
    assert offers[0]["distributor"] == "Unknown"
    assert offers[0]["price"] == 1.23


def test_parse_offers_handles_null_part_and_null_seller_and_null_offer():
    client = NexarClient("id", "secret")
    assert client.parse_offers(None) == []
    assert client.parse_offers({"sellers": None}) == []
    assert client.parse_offers({"sellers": [None]}) == []
    assert client.parse_offers({
        "sellers": [{"company": {"name": "X"}, "offers": None}]
    }) == []
    assert client.parse_offers({
        "sellers": [{"company": {"name": "X"}, "offers": [None]}]
    }) == []


def test_search_mpn_valid_response_still_works(monkeypatch):
    """Sanity check: the guarded/rewritten code path still parses a normal,
    fully-populated response correctly (no regression on the working case)."""
    body = {
        "data": {
            "supSearchMpn": {
                "results": [{
                    "part": {
                        "mpn": "STM32F103C8T6",
                        "manufacturer": {"name": "STMicroelectronics"},
                        "sellers": [{
                            "company": {"name": "Mouser"},
                            "isAuthorized": True,
                            "offers": [{
                                "sku": "511-STM32F103C8T6",
                                "inventoryLevel": 1200,
                                "moq": 1,
                                "prices": [
                                    {"quantity": 1, "price": 2.87, "currency": "USD"},
                                    {"quantity": 10, "price": 2.50, "currency": "USD"},
                                ],
                            }],
                        }],
                    }
                }]
            }
        }
    }
    client = _client(monkeypatch, _fake_response(200, body))

    part = asyncio.run(client.search_mpn("STM32F103C8T6"))
    offers = client.parse_offers(part)

    assert part is not None
    assert len(offers) == 1
    assert offers[0]["distributor"] == "Mouser"
    assert offers[0]["price"] == 2.87
    assert len(offers[0]["price_breaks"]) == 2


# ── (c) Structured per-source reporting at the API layer ────────────────────────

class _NoAuth:
    """Minimal stand-in user object so we can call the endpoint helper directly
    without going through the FastAPI auth dependency in pure-unit tests."""


def test_fetch_live_offers_no_sources_configured_raises_503(monkeypatch):
    from app.api.live_prices import _fetch_live_offers
    from app.core.config import settings

    monkeypatch.setattr(settings, "NEXAR_CLIENT_ID", "")
    monkeypatch.setattr(settings, "NEXAR_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "OEMSECRETS_API_KEY", "")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_ID", "")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "TRUSTEDPARTS_API_KEY", "")

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_fetch_live_offers("ANY-MPN"))

    assert exc_info.value.status_code == 503
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert len(detail["sources"]) == 4
    assert all(s["status"] == "not_configured" for s in detail["sources"])


def test_fetch_live_offers_all_configured_sources_error_raises_502(monkeypatch):
    """This is the exact bug scenario: Nexar is 'configured: true' but every call
    fails. That must not come back as a silent 200 with zero offers."""
    from app.api.live_prices import _fetch_live_offers
    from app.core.config import settings
    from app.core.clients.nexar_client import NexarClient

    monkeypatch.setattr(settings, "NEXAR_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "NEXAR_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "OEMSECRETS_API_KEY", "")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_ID", "")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "TRUSTEDPARTS_API_KEY", "")

    async def _boom(self, mpn, currency="USD", country="US"):
        raise NexarAPIError("HTTP 400: Cannot query field \"lines\"")

    monkeypatch.setattr(NexarClient, "search_mpn", _boom)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_fetch_live_offers("STM32F103C8T6"))

    assert exc_info.value.status_code == 502
    detail = exc_info.value.detail
    assert detail["all_sources_failed"] is True
    nexar_report = next(s for s in detail["sources"] if s["name"] == "nexar")
    assert nexar_report["status"] == "error"
    assert "400" in nexar_report["error"]


def test_fetch_live_offers_success_reports_ok_status(monkeypatch):
    from app.api.live_prices import _fetch_live_offers, SourceStatus
    from app.core.config import settings
    from app.core.clients.nexar_client import NexarClient

    monkeypatch.setattr(settings, "NEXAR_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "NEXAR_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "OEMSECRETS_API_KEY", "")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_ID", "")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "TRUSTEDPARTS_API_KEY", "")

    fake_part = {
        "sellers": [{
            "company": {"name": "DigiKey"},
            "isAuthorized": True,
            "offers": [{"sku": "S1", "inventoryLevel": 5, "moq": 1,
                        "prices": [{"quantity": 1, "price": 1.0, "currency": "USD"}]}],
        }]
    }

    async def _ok(self, mpn, currency="USD", country="US"):
        return fake_part

    monkeypatch.setattr(NexarClient, "search_mpn", _ok)

    all_offers, sources_used, reports = asyncio.run(_fetch_live_offers("STM32F103C8T6"))

    assert len(all_offers) == 1
    assert sources_used == ["nexar"]
    nexar_report = next(r for r in reports if r.name == "nexar")
    assert nexar_report.status == SourceStatus.ok
    assert nexar_report.offer_count == 1
    other_reports = [r for r in reports if r.name != "nexar"]
    assert all(r.status == SourceStatus.not_configured for r in other_reports)


# ── Endpoint-level tests (structured `sources` field on the HTTP response) ──────

@pytest.fixture
def _configure_nexar_only(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "NEXAR_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "NEXAR_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "OEMSECRETS_API_KEY", "")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_ID", "")
    monkeypatch.setattr(settings, "DIGIKEY_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "TRUSTEDPARTS_API_KEY", "")


def test_get_live_prices_endpoint_returns_sources_array(client, auth_token, _configure_nexar_only, monkeypatch):
    from app.core.clients.nexar_client import NexarClient

    fake_part = {
        "sellers": [{
            "company": {"name": "DigiKey"},
            "isAuthorized": True,
            "offers": [{"sku": "S1", "inventoryLevel": 5, "moq": 1,
                        "prices": [{"quantity": 1, "price": 1.0, "currency": "USD"}]}],
        }]
    }

    async def _ok(self, mpn, currency="USD", country="US"):
        return fake_part

    monkeypatch.setattr(NexarClient, "search_mpn", _ok)

    r = client.get(
        "/api/v1/live-prices/STM32F103C8T6",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total_offers"] == 1
    assert "sources" in body
    names = {s["name"] for s in body["sources"]}
    assert names == {"nexar", "oemsecrets", "digikey", "trustedparts"}
    nexar_source = next(s for s in body["sources"] if s["name"] == "nexar")
    assert nexar_source["status"] == "ok"
    assert nexar_source["configured"] is True


def test_get_live_prices_endpoint_502_when_only_source_errors(client, auth_token, _configure_nexar_only, monkeypatch):
    from app.core.clients.nexar_client import NexarClient

    async def _boom(self, mpn, currency="USD", country="US"):
        raise NexarAPIError("HTTP 400: malformed query")

    monkeypatch.setattr(NexarClient, "search_mpn", _boom)

    r = client.get(
        "/api/v1/live-prices/STM32F103C8T6",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 502
    body = r.json()
    assert body["detail"]["all_sources_failed"] is True


def test_bom_endpoint_reports_per_mpn_and_top_level_sources(client, auth_token, _configure_nexar_only, monkeypatch):
    from app.core.clients.nexar_client import NexarClient

    async def _search_bom(self, mpns, currency="USD", country="US"):
        return [
            {
                "reference": "STM32F103C8T6",
                "error": None,
                "part": {
                    "sellers": [{
                        "company": {"name": "DigiKey"},
                        "isAuthorized": True,
                        "offers": [{"sku": "S1", "inventoryLevel": 5, "moq": 1,
                                    "prices": [{"quantity": 1, "price": 1.0, "currency": "USD"}]}],
                    }]
                },
            },
            {
                "reference": "ATMEGA328P-AUR",
                "error": "no match",
                "part": None,
            },
        ]

    monkeypatch.setattr(NexarClient, "search_bom", _search_bom)

    r = client.post(
        "/api/v1/live-prices/bom",
        json={"items": [{"mpn": "STM32F103C8T6"}, {"mpn": "ATMEGA328P-AUR"}]},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 200
    body = r.json()

    good = body["results"]["STM32F103C8T6"]
    assert good["total_offers"] == 1
    good_nexar = next(s for s in good["sources"] if s["name"] == "nexar")
    assert good_nexar["status"] == "ok"

    bad = body["results"]["ATMEGA328P-AUR"]
    assert bad["total_offers"] == 0
    bad_nexar = next(s for s in bad["sources"] if s["name"] == "nexar")
    assert bad_nexar["status"] == "error"
    assert bad_nexar["error"] == "no match"

    top_nexar = next(s for s in body["sources"] if s["name"] == "nexar")
    assert top_nexar["status"] == "ok"  # bulk call itself succeeded even though one line errored


def test_bom_endpoint_surfaces_400_style_failure_not_silent_zero(client, auth_token, _configure_nexar_only, monkeypatch):
    """The exact reported regression: BOM with 2 MPNs, Nexar bulk 400s. Must not
    come back as a quiet `total_offers: 0` / 200 with no indication anything failed."""
    from app.core.clients.nexar_client import NexarClient

    async def _search_bom(self, mpns, currency="USD", country="US"):
        raise NexarAPIError("HTTP 400: Cannot query field \"lines\" on type \"Query\".")

    monkeypatch.setattr(NexarClient, "search_bom", _search_bom)

    r = client.post(
        "/api/v1/live-prices/bom",
        json={"items": [{"mpn": "STM32F103C8T6"}, {"mpn": "ATMEGA328P-AUR"}]},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert r.status_code == 502
    body = r.json()
    assert body["detail"]["all_sources_failed"] is True
    nexar_report = next(s for s in body["detail"]["sources"] if s["name"] == "nexar")
    assert nexar_report["status"] == "error"
    assert "400" in nexar_report["error"]
