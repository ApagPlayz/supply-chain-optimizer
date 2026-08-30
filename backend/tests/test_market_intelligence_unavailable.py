"""`/market/*` must never publish a number it did not fetch.

Every one of these routes depends on SupplyMaven, which this deployment has
never once reached: the REST path `supplymaven_client.py` targets answers 404
(re-probed 2026-08-30). Before this suite existed, the unavailable paths served
`risk_weight_multiplier: 1.0`, `tariff_multiplier: 1.0`, `alerts_count: 0` and
`critical_alerts: 0` as bare values beside seven nulls, so "we checked and the
world is calm" and "we never fetched anything" were the same response.

Two unavailable paths exist and both are covered here:

  NO KEY       — SUPPLYMAVEN_API_KEY is empty, nothing is attempted.
  NO ANSWER    — a key is set but the upstream returns nothing usable. Simulated
                 by forcing `SupplyMavenClient._call` to return None, which is
                 exactly what it does in production: `raise_for_status()` raises
                 on the 404 and `except Exception` returns None.

The mirror-image tests at the bottom are the point of the whole file: they pin
the AVAILABLE path to the real values, so "null everything" is not a way to make
the unavailable tests pass. A real 1.0 computed from a real GDI score of 50 must
still be served as 1.0, and an alerts call that genuinely answers with no alerts
must still report 0 — not None.
"""
import pytest

from app.core.config import settings
from app.core.clients.supplymaven_client import SupplyMavenClient


#: Fields that must be `None` — never a stand-in constant — on an unavailable
#: path, as (route, dotted field path). The dotted path walks nested objects so
#: /summary's embedded GDI payload is checked too.
_MUST_BE_NULL = [
    ("/api/v1/market/summary", "alerts_count"),
    ("/api/v1/market/summary", "critical_alerts"),
    ("/api/v1/market/summary", "tariff_multiplier"),
    ("/api/v1/market/summary", "gdi.risk_weight_multiplier"),
    ("/api/v1/market/disruption-index", "risk_weight_multiplier"),
    ("/api/v1/market/alerts", "critical_count"),
    ("/api/v1/market/alerts", "high_count"),
    ("/api/v1/market/trade-policy", "tariff_multiplier"),
]

#: Every route with an unavailable path. /status is excluded on purpose: it
#: reports configuration, which is always known, so it has no such path.
_DATA_ROUTES = [
    "/api/v1/market/summary",
    "/api/v1/market/disruption-index",
    "/api/v1/market/alerts",
    "/api/v1/market/commodities",
    "/api/v1/market/trade-policy",
]


def _dig(payload, dotted):
    for part in dotted.split("."):
        payload = payload[part]
    return payload


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def no_key(monkeypatch):
    """UNAVAILABLE PATH 1 — no API key, so nothing is even attempted."""
    monkeypatch.setattr(settings, "SUPPLYMAVEN_API_KEY", "", raising=False)


@pytest.fixture
def key_but_dead_upstream(monkeypatch):
    """UNAVAILABLE PATH 2 — a key is set and every upstream call returns None.

    This is production's actual behaviour, not a hypothetical: the client POSTs
    to a URL that 404s, `raise_for_status()` raises, and the broad `except`
    returns None.
    """
    monkeypatch.setattr(settings, "SUPPLYMAVEN_API_KEY", "sm_free_fake_for_tests", raising=False)

    async def _dead(self, tool, params=None):
        return None

    monkeypatch.setattr(SupplyMavenClient, "_call", _dead)


# ── (a) No unavailable path may publish a number it did not fetch ─────────────

@pytest.mark.parametrize("route,field", _MUST_BE_NULL)
def test_no_key_path_returns_null_not_a_constant(client, auth_token, no_key, route, field):
    r = client.get(route, headers=_auth(auth_token))
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False, f"{route} claimed availability without a key"
    value = _dig(body, field)
    assert value is None, (
        f"{route} published {field}={value!r} with no API key configured. "
        "A bare 1.0 or 0 here is indistinguishable from a real reading."
    )


@pytest.mark.parametrize("route,field", _MUST_BE_NULL)
def test_dead_upstream_path_returns_null_not_a_constant(
    client, auth_token, key_but_dead_upstream, route, field
):
    r = client.get(route, headers=_auth(auth_token))
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False, f"{route} claimed availability from a dead upstream"
    value = _dig(body, field)
    assert value is None, (
        f"{route} published {field}={value!r} after the upstream returned nothing. "
        "A bare 1.0 or 0 here is indistinguishable from a real reading."
    )


def test_summary_embedded_gdi_is_also_flagged_unavailable(client, auth_token, no_key):
    """The nested GDI payload carries its own honest flag, not just the envelope."""
    body = client.get("/api/v1/market/summary", headers=_auth(auth_token)).json()
    assert body["gdi"]["available"] is False
    for field in ("gdi_score", "transportation", "energy", "materials", "macro"):
        assert body["gdi"][field] is None


# ── (b) unavailable_reason is populated and non-empty ─────────────────────────

@pytest.mark.parametrize("route", _DATA_ROUTES)
def test_no_key_path_explains_itself(client, auth_token, no_key, route):
    body = client.get(route, headers=_auth(auth_token)).json()
    reason = body.get("unavailable_reason")
    assert isinstance(reason, str) and reason.strip(), (
        f"{route} returned available=false with no unavailable_reason: {reason!r}"
    )
    assert "SUPPLYMAVEN_API_KEY" in reason, (
        f"{route}'s reason does not name the missing key: {reason!r}"
    )


@pytest.mark.parametrize("route", _DATA_ROUTES)
def test_dead_upstream_path_explains_itself(client, auth_token, key_but_dead_upstream, route):
    body = client.get(route, headers=_auth(auth_token)).json()
    reason = body.get("unavailable_reason")
    assert isinstance(reason, str) and reason.strip(), (
        f"{route} returned available=false with no unavailable_reason: {reason!r}"
    )
    assert "404" in reason, f"{route}'s reason does not say why the call fails: {reason!r}"


def test_summary_embedded_gdi_explains_itself(client, auth_token, no_key):
    reason = client.get(
        "/api/v1/market/summary", headers=_auth(auth_token)
    ).json()["gdi"]["unavailable_reason"]
    assert isinstance(reason, str) and reason.strip()


def test_status_route_has_no_unavailable_reason(client, auth_token, no_key):
    """/status reports configuration, which is always known — it has no such path."""
    body = client.get("/api/v1/market/status", headers=_auth(auth_token)).json()
    assert body["supplymaven"]["configured"] is False
    assert "unavailable_reason" not in body["supplymaven"]


# ── The mirror image: nulling everything must NOT pass ────────────────────────

_LIVE_GDI = {
    "gdi_score": 50.0, "transportation": 48.0, "energy": 52.0,
    "materials": 49.0, "macro": 51.0, "trend": "stable",
    "timestamp": "2026-08-30T00:00:00Z",
}


@pytest.fixture
def live_upstream(monkeypatch):
    """AVAILABLE PATH — the upstream answers. Values here must stay real."""
    monkeypatch.setattr(settings, "SUPPLYMAVEN_API_KEY", "sm_free_fake_for_tests", raising=False)

    async def _live(self, tool, params=None):
        if tool == "supply_chain_risk_assessment":
            return dict(_LIVE_GDI)
        if tool == "supply_chain_disruption_alerts":
            # Answered, with nothing to report. A REAL zero.
            return []
        if tool == "get_trade_policy_impacts":
            return {"active_tariffs": [], "sanctions": [], "export_controls": []}
        return None

    monkeypatch.setattr(SupplyMavenClient, "_call", _live)


def test_a_real_1_0_multiplier_is_still_served_as_1_0(client, auth_token, live_upstream):
    """A GDI of 50 maps to a genuine 1.0. Nulling it would be a different lie."""
    body = client.get("/api/v1/market/disruption-index", headers=_auth(auth_token)).json()
    assert body["available"] is True
    assert body["unavailable_reason"] is None
    assert body["risk_weight_multiplier"] == 1.0
    assert body["gdi_score"] == 50.0


def test_a_real_zero_alert_count_is_still_served_as_zero(client, auth_token, live_upstream):
    """The alerts feed answered with no alerts. That 0 is a finding, not a gap."""
    body = client.get("/api/v1/market/alerts", headers=_auth(auth_token)).json()
    assert body["available"] is True
    assert body["unavailable_reason"] is None
    assert body["critical_count"] == 0
    assert body["high_count"] == 0


def test_summary_reports_real_values_when_the_upstream_answers(client, auth_token, live_upstream):
    body = client.get("/api/v1/market/summary", headers=_auth(auth_token)).json()
    assert body["available"] is True
    assert body["unavailable_reason"] is None
    assert body["alerts_count"] == 0
    assert body["critical_alerts"] == 0
    assert body["tariff_multiplier"] == 1.0
    assert body["gdi"]["risk_weight_multiplier"] == 1.0
    assert body["available_sources"] == ["supplymaven"]


def test_client_separates_no_alerts_from_no_answer(monkeypatch):
    """`[]` and `None` out of `get_disruption_alerts` are different facts.

    The counts on two routes are derived from this return value, so collapsing
    the two here would reintroduce the bare `0` at the source.
    """
    import asyncio

    sm = SupplyMavenClient("sm_free_fake_for_tests")

    async def _answered(self, tool, params=None):
        return {"alerts": []}

    monkeypatch.setattr(SupplyMavenClient, "_call", _answered)
    assert asyncio.run(sm.get_disruption_alerts()) == []

    async def _silent(self, tool, params=None):
        return None

    monkeypatch.setattr(SupplyMavenClient, "_call", _silent)
    assert asyncio.run(sm.get_disruption_alerts()) is None
