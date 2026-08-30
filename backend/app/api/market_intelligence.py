"""
Market intelligence endpoints — macro supply chain risk data via SupplyMaven.

Status: none of these 6 endpoints currently have a frontend consumer. There
is no "Market Intelligence" panel on Dashboard.tsx, and a case-insensitive
grep of frontend/src for market|tariff|gdi|risk_weight|supplymaven|commodit|
alerts_count|critical_alerts returns exactly one hit — the string
"Unauthorized / gray-market channel", a component-sourcing tooltip in
SchedulerPage.tsx with no relation to this router (re-verified 2026-08-30).
That panel was never built. DigitalTwinPage.tsx, which an earlier version
of this docstring claimed would auto-fill from /trade-policy, has been
deleted; App.tsx now redirects /digital-twin to /resilience. All 6 routes below are live and
independently callable, and all 6 are unconsumed. Five of them have also
never once returned real data — see UPSTREAM IS UNREACHABLE below:
  - GET /summary          — GDI score, trend, alert count, tariff multiplier
                             in one call. No caller.
  - GET /disruption-index — Global Disruption Index (0-100) with pillar
                             breakdown. No caller.
  - GET /alerts            — real-time disruption alerts by severity. No
                             caller.
  - GET /commodities        — commodity prices, semiconductor-relevant ones
                             flagged. No caller.
  - GET /trade-policy        — tariffs/sanctions/export controls plus
                             `tariff_multiplier`. No caller (its intended
                             consumer, DigitalTwinPage.tsx, was removed).
  - GET /status              — which upstream data sources are configured.
                             No caller.

UPSTREAM IS UNREACHABLE (established 2026-08-30, by probing the vendor)
----------------------------------------------------------------------
Two independent reasons these five return nothing, and fixing only the first
would NOT make them work:

1. SUPPLYMAVEN_API_KEY is not configured in this deployment, so every route
   short-circuits before it calls out. `GET /market/status` reports this
   truthfully as `supplymaven.configured: false`.

2. `supplymaven_client.py` POSTs to `https://supplymaven.com/api/v1/tools`,
   which **returns 404** — re-probed directly against the vendor on
   2026-08-30, with and without a bearer token, and both GET and POST. The
   404 body is the vendor's Next.js not-found page, so that REST path does
   not exist and the bearer token makes no difference to the response.
   SupplyMaven's developer portal documents exactly one endpoint, the hosted
   MCP server at `https://supplymaven.com/api/mcp` (Streamable HTTP, JSON-RPC
   2.0, `Authorization: Bearer sm_free_*`); it is the only `/api` URL on that
   page, and it does answer — `tools/list` returned 200 with a real 33-tool
   listing on 2026-08-30. It expects neither the `{"tool", "parameters"}`
   request body this client sends nor the plain-JSON response this client
   parses (it replies SSE-framed, `event: message` / `data: {...}`).
   `_call`'s `raise_for_status()` therefore raises on every request; the
   `except Exception` below it prints the error to stdout and returns None,
   so the failure never reaches a caller as anything but "no data".

   So this client has never successfully called the API and cannot as
   written. Adding a key would change nothing. Repointing it at the MCP
   endpoint is unverified work — nobody here holds a key to test against —
   and is deliberately NOT attempted rather than guessed at.

An earlier version of this docstring claimed these routes were "correctly
implemented" and returned "no placeholder numbers". Both were false: the
client is aimed at a 404, and the unavailable paths were publishing
`risk_weight_multiplier: 1.0` and `tariff_multiplier: 1.0` as bare floats
beside seven nulls, plus `alerts_count: 0` / `critical_alerts: 0` on
/summary with no availability flag at all. A consumer could not distinguish
"we checked and the world is calm" from "we never fetched anything" — and
since the upstream has never once answered, it was always the latter.

That is fixed here. Every number an unavailable path would have to invent is
now `None`, and each of the five data responses carries an
`unavailable_reason` string saying why — the house pattern already used by
`benchmark.py` (`available` + `unavailable_reason`) and `ml.py` (fallback
values labelled inline as fallbacks). Concretely:

  - `GDIResponse.risk_weight_multiplier`, `TradePolicyResponse.
    tariff_multiplier` and `MarketSummaryResponse.tariff_multiplier` are
    `Optional[float]`, `None` on every unavailable path.
  - `AlertsResponse.critical_count` / `.high_count` and
    `MarketSummaryResponse.alerts_count` / `.critical_alerts` are
    `Optional[int]`, `None` on every unavailable path.
  - `MarketSummaryResponse` gained the `available: bool` it never had.
  - `SupplyMavenClient.get_disruption_alerts` now returns `None` when the
    upstream did not answer and a list (possibly empty) when it did, because
    a bare `[]` cannot tell "no alerts" from "no answer" and the counts are
    derived from it.
  - Two reasons are served: `_NO_KEY_REASON` (no key configured, nothing was
    even attempted) and `_UPSTREAM_REASON` (a key is set, the call returned
    nothing usable). `GET /market/status` has no unavailable path — it
    reports configuration, which is always known — so it carries neither
    field.

Values on the AVAILABLE paths are untouched: a `1.0` computed by
`get_risk_weight_adjustment` from a real GDI score is a real reading and is
still served as `1.0`.

Even if the upstream were reachable, no UI displays the result — that still
requires building the frontend panel described above.

Not wired: `risk_weight_multiplier` on GDIResponse is not read anywhere in
app/optimization/ — the VRP optimizer's risk weights remain unaffected by
GDI, live or otherwise. Feeding it into the optimizer's cost model is future
work, not done here.

All endpoints return gracefully if SUPPLYMAVEN_API_KEY is not set.
Free tier (sm_free_*): supply_chain_risk_assessment, commodity_price_monitor,
                       supply_chain_disruption_alerts (critical only).
Pro tier (sm_live_*):  + trade_policy_impacts, port_congestion, action_signals.
"""

from fastapi import APIRouter, Depends
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from app.core.config import settings
from app.api.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/market", tags=["market-intelligence"])


# ── Why a value is missing ─────────────────────────────────────────────────────
#
# The house pattern is `benchmark.py`'s: an `available: bool` plus an
# `unavailable_reason` string saying WHY, so a client that renders this payload
# and nothing else can still explain itself.
#
# Every number these routes would otherwise have to invent is `None` when
# `available` is false — never a stand-in constant. `1.0` is a reading the GDI
# and tariff converters genuinely return for a calm world, and `0` is a real
# alert count, so publishing either on a path that never fetched anything makes
# "we checked and nothing is wrong" and "we never looked" the same response.

_NO_KEY_REASON = (
    "SUPPLYMAVEN_API_KEY is not configured in this deployment, so no upstream "
    "call was attempted. GET /market/status reports the same fact as "
    "supplymaven.configured: false."
)

_UPSTREAM_REASON = (
    "SUPPLYMAVEN_API_KEY is set but the upstream returned no usable data. "
    "supplymaven_client.py POSTs to https://supplymaven.com/api/v1/tools, which "
    "answers 404 (re-probed 2026-08-30, with and without a bearer token), so that "
    "call cannot succeed as written; a rate limit, a tier restriction or a network "
    "error would produce the same empty result. No placeholder value is "
    "substituted for data that was never received."
)


# ── Schemas ────────────────────────────────────────────────────────────────────

class GDIResponse(BaseModel):
    gdi_score: Optional[float]
    transportation: Optional[float]
    energy: Optional[float]
    materials: Optional[float]
    macro: Optional[float]
    trend: Optional[str]
    timestamp: Optional[str]
    # Computed from a live GDI score, intended for VRP risk weights (not wired —
    # see the module docstring). None whenever `available` is false: a bare 1.0
    # is indistinguishable from a real "normal disruption" reading.
    risk_weight_multiplier: Optional[float]
    available: bool
    unavailable_reason: Optional[str] = None


class DisruptionAlert(BaseModel):
    title: str
    severity: str
    category: Optional[str]
    region: Optional[str]
    affected_commodities: List[str] = []
    timestamp: Optional[str]
    summary: Optional[str]


class AlertsResponse(BaseModel):
    alerts: List[DisruptionAlert]
    # None when `available` is false. A 0 here asserts "no disruptions are
    # active", which is a different claim from "no alert feed was reached".
    critical_count: Optional[int]
    high_count: Optional[int]
    available: bool
    unavailable_reason: Optional[str] = None


class CommodityPrice(BaseModel):
    name: str
    price: float
    currency: str
    change_24h_pct: Optional[float]
    relevance: str   # "direct" (semiconductor materials) or "indirect"


class CommodityResponse(BaseModel):
    prices: List[CommodityPrice]
    available: bool
    unavailable_reason: Optional[str] = None


class TradePolicyResponse(BaseModel):
    active_tariffs: List[Dict[str, Any]]
    sanctions: List[Dict[str, Any]]
    export_controls: List[Dict[str, Any]]
    # Suggested cost multiplier derived from live tariff rates. None whenever
    # `available` is false — 1.0 is what the converter returns for "no
    # electronics tariffs found", a real finding this path has not made.
    tariff_multiplier: Optional[float]
    electronics_tariff_rate: Optional[float]   # % tariff on HS 8541/8542
    available: bool
    unavailable_reason: Optional[str] = None


class MarketSummaryResponse(BaseModel):
    gdi: GDIResponse
    # Each is None unless the specific upstream call behind it answered. The
    # counts come from an alerts call that returns None (not []) when it fails,
    # so an empty list here really does mean zero alerts.
    alerts_count: Optional[int]
    critical_alerts: Optional[int]
    tariff_multiplier: Optional[float]
    available_sources: List[str]
    # True when at least one upstream call answered. The route had no
    # availability flag at all before, so seven nulls beside `alerts_count: 0`
    # were the only signal that nothing had been fetched.
    available: bool
    unavailable_reason: Optional[str] = None


def _gdi_unavailable(reason: str) -> GDIResponse:
    """A GDI payload with every number absent and the reason it is absent."""
    return GDIResponse(
        gdi_score=None, transportation=None, energy=None,
        materials=None, macro=None, trend=None, timestamp=None,
        risk_weight_multiplier=None, available=False,
        unavailable_reason=reason,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=MarketSummaryResponse)
async def get_market_summary(current_user: User = Depends(get_current_user)):
    """
    GDI score + alert counts + tariff multiplier in one call, intended as a
    dashboard summary. Not currently called by any frontend page (see module
    docstring) — no "market intelligence card" exists in Dashboard.tsx.
    """
    if not settings.SUPPLYMAVEN_API_KEY:
        return MarketSummaryResponse(
            gdi=_gdi_unavailable(_NO_KEY_REASON),
            alerts_count=None,
            critical_alerts=None,
            tariff_multiplier=None,
            available_sources=[],
            available=False,
            unavailable_reason=_NO_KEY_REASON,
        )

    from app.core.clients.supplymaven_client import SupplyMavenClient
    client = SupplyMavenClient(settings.SUPPLYMAVEN_API_KEY)

    sources: List[str] = []
    gdi_data = await client.get_global_disruption_index()
    if gdi_data:
        gdi_resp = GDIResponse(
            gdi_score=gdi_data.get("gdi_score"),
            transportation=gdi_data.get("transportation"),
            energy=gdi_data.get("energy"),
            materials=gdi_data.get("materials"),
            macro=gdi_data.get("macro"),
            trend=gdi_data.get("trend"),
            timestamp=gdi_data.get("timestamp"),
            risk_weight_multiplier=client.get_risk_weight_adjustment(gdi_data),
            available=True,
        )
        sources.append("supplymaven")
    else:
        gdi_resp = _gdi_unavailable(_UPSTREAM_REASON)

    # None means the alerts call did not answer; [] means it answered with no
    # alerts. Those are different facts and must not collapse to the same count.
    alert_list = await client.get_disruption_alerts()
    alerts_count = len(alert_list) if alert_list is not None else None
    critical_count = (
        sum(1 for a in alert_list if a.get("severity", "").lower() == "critical")
        if alert_list is not None
        else None
    )

    trade_data = await client.get_trade_policy_impacts()
    tariff_mult = client.tariffs_to_scenario_multiplier(trade_data) if trade_data else None

    answered = bool(gdi_data) or alert_list is not None or bool(trade_data)

    return MarketSummaryResponse(
        gdi=gdi_resp,
        alerts_count=alerts_count,
        critical_alerts=critical_count,
        tariff_multiplier=tariff_mult,
        available_sources=sources,
        available=answered,
        unavailable_reason=None if answered else _UPSTREAM_REASON,
    )


@router.get("/disruption-index", response_model=GDIResponse)
async def get_disruption_index(current_user: User = Depends(get_current_user)):
    """
    Global Disruption Index (0–100) with pillar breakdown.
    Updates every 15 minutes. Free tier.
    """
    if not settings.SUPPLYMAVEN_API_KEY:
        return _gdi_unavailable(_NO_KEY_REASON)

    from app.core.clients.supplymaven_client import SupplyMavenClient
    client = SupplyMavenClient(settings.SUPPLYMAVEN_API_KEY)
    data = await client.get_global_disruption_index()

    if not data:
        return _gdi_unavailable(_UPSTREAM_REASON)

    return GDIResponse(
        gdi_score=data.get("gdi_score"),
        transportation=data.get("transportation"),
        energy=data.get("energy"),
        materials=data.get("materials"),
        macro=data.get("macro"),
        trend=data.get("trend"),
        timestamp=data.get("timestamp"),
        risk_weight_multiplier=client.get_risk_weight_adjustment(data),
        available=True,
    )


@router.get("/alerts", response_model=AlertsResponse)
async def get_disruption_alerts(
    severity: str = "all",
    current_user: User = Depends(get_current_user),
):
    """
    Real-time supply chain disruption alerts.
    Free tier: critical only. Pro tier: all severities.
    """
    if not settings.SUPPLYMAVEN_API_KEY:
        return AlertsResponse(
            alerts=[], critical_count=None, high_count=None,
            available=False, unavailable_reason=_NO_KEY_REASON,
        )

    from app.core.clients.supplymaven_client import SupplyMavenClient
    client = SupplyMavenClient(settings.SUPPLYMAVEN_API_KEY)
    raw_alerts = await client.get_disruption_alerts(severity=severity)

    # None, not [], is how the client signals "the upstream did not answer".
    if raw_alerts is None:
        return AlertsResponse(
            alerts=[], critical_count=None, high_count=None,
            available=False, unavailable_reason=_UPSTREAM_REASON,
        )

    alerts = []
    for a in raw_alerts:
        alerts.append(DisruptionAlert(
            title=a.get("title", ""),
            severity=a.get("severity", "unknown"),
            category=a.get("category"),
            region=a.get("region"),
            affected_commodities=a.get("affected_commodities", []),
            timestamp=a.get("timestamp"),
            summary=a.get("summary"),
        ))

    critical_count = sum(1 for a in alerts if a.severity.lower() == "critical")
    high_count = sum(1 for a in alerts if a.severity.lower() == "high")

    return AlertsResponse(
        alerts=alerts,
        critical_count=critical_count,
        high_count=high_count,
        available=True,
    )


@router.get("/commodities", response_model=CommodityResponse)
async def get_commodity_prices(current_user: User = Depends(get_current_user)):
    """
    Real-time commodity prices including semiconductor materials.
    Free tier: 5 key commodities. Pro tier: 31 commodities.
    """
    if not settings.SUPPLYMAVEN_API_KEY:
        return CommodityResponse(
            prices=[], available=False, unavailable_reason=_NO_KEY_REASON,
        )

    from app.core.clients.supplymaven_client import SupplyMavenClient
    client = SupplyMavenClient(settings.SUPPLYMAVEN_API_KEY)
    data = await client.get_commodity_prices()

    if not data:
        return CommodityResponse(
            prices=[], available=False, unavailable_reason=_UPSTREAM_REASON,
        )

    # Categorize commodities by relevance to electronic components
    semiconductor_relevant = {
        "silicon", "copper", "gold", "silver", "tin", "palladium",
        "rare earth", "lithium", "cobalt", "nickel"
    }

    prices: List[CommodityPrice] = []
    commodity_data = data.get("commodities", data) if isinstance(data, dict) else {}

    for name, info in commodity_data.items():
        if isinstance(info, dict):
            price_val = info.get("price", 0)
            change = info.get("change_24h_pct") or info.get("change_pct")
        else:
            price_val = float(info) if info else 0
            change = None

        relevance = "direct" if any(kw in name.lower() for kw in semiconductor_relevant) else "indirect"
        prices.append(CommodityPrice(
            name=name,
            price=float(price_val),
            currency="USD",
            change_24h_pct=float(change) if change is not None else None,
            relevance=relevance,
        ))

    return CommodityResponse(prices=prices, available=True)


@router.get("/trade-policy", response_model=TradePolicyResponse)
async def get_trade_policy(current_user: User = Depends(get_current_user)):
    """
    Active tariffs, sanctions, and export controls.
    Pro tier required (sm_live_* key).

    Returns tariff_multiplier for auto-population of a tariff-impact input.
    Its originally intended consumer, DigitalTwinPage.tsx, has been deleted
    (App.tsx redirects /digital-twin to /resilience) — no frontend page
    currently calls this endpoint.
    Electronics tariff rate covers HS codes 8541/8542 (semiconductors).
    """
    if not settings.SUPPLYMAVEN_API_KEY:
        return TradePolicyResponse(
            active_tariffs=[], sanctions=[], export_controls=[],
            tariff_multiplier=None, electronics_tariff_rate=None, available=False,
            unavailable_reason=_NO_KEY_REASON,
        )

    from app.core.clients.supplymaven_client import SupplyMavenClient
    client = SupplyMavenClient(settings.SUPPLYMAVEN_API_KEY)
    data = await client.get_trade_policy_impacts()

    if not data:
        return TradePolicyResponse(
            active_tariffs=[], sanctions=[], export_controls=[],
            tariff_multiplier=None, electronics_tariff_rate=None, available=False,
            unavailable_reason=_UPSTREAM_REASON,
        )

    tariff_mult = client.tariffs_to_scenario_multiplier(data)

    # Extract electronics-specific tariff rate
    electronics_rate: Optional[float] = None
    for t in data.get("active_tariffs", []):
        hs_codes = str(t.get("hs_codes", ""))
        if "8541" in hs_codes or "8542" in hs_codes or "semiconductor" in str(t).lower():
            rate_str = str(t.get("rate", "0")).replace("%", "")
            try:
                electronics_rate = float(rate_str)
                break
            except ValueError:
                pass

    return TradePolicyResponse(
        active_tariffs=data.get("active_tariffs", []),
        sanctions=data.get("sanctions", []),
        export_controls=data.get("export_controls", []),
        tariff_multiplier=tariff_mult,
        electronics_tariff_rate=electronics_rate,
        available=True,
    )


class DataSourceStatus(BaseModel):
    """Whether one upstream data source is configured. Never exposes key values."""
    configured: bool
    description: str
    register_url: str
    sandbox_mode: Optional[bool] = None


@router.get("/status", response_model=Dict[str, DataSourceStatus])
async def get_api_status(current_user: User = Depends(get_current_user)):
    """
    Check which live data sources are configured and active.
    Returns configuration status without exposing key values.
    """
    return {
        "nexar": {
            "configured": bool(settings.NEXAR_CLIENT_ID and settings.NEXAR_CLIENT_SECRET),
            "description": "Multi-distributor live pricing (GraphQL)",
            "register_url": "https://nexar.com/api",
        },
        "digikey": {
            "configured": bool(settings.DIGIKEY_CLIENT_ID and settings.DIGIKEY_CLIENT_SECRET),
            "sandbox_mode": settings.DIGIKEY_SANDBOX,
            "description": "DigiKey official API v4 (OAuth2)",
            "register_url": "https://developer.digikey.com/",
        },
        "oemsecrets": {
            "configured": bool(settings.OEMSECRETS_API_KEY),
            "description": "140+ distributors in one call",
            "register_url": "https://www.oemsecrets.com/api",
        },
        "trustedparts": {
            "configured": bool(settings.TRUSTEDPARTS_API_KEY),
            "description": "Authorized distributors only, free",
            "register_url": "https://www.trustedparts.com/docs/",
        },
        "easypost": {
            "configured": bool(settings.EASYPOST_API_KEY),
            "description": "SmartRate transit-time client — implemented but NOT wired into the "
                            "optimizer; this flag has no effect on the VRP cost matrix",
            "register_url": "https://www.easypost.com/",
        },
        "supplymaven": {
            "configured": bool(settings.SUPPLYMAVEN_API_KEY),
            "description": "Global disruption index + trade policy",
            "register_url": "https://supplymaven.com/developers",
        },
    }
