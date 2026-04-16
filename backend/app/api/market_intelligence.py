"""
Market intelligence endpoints — macro supply chain risk data via SupplyMaven.

Used by:
  - Dashboard page: live GDI score + disruption alert count
  - Digital Twin: auto-populate tariff_multiplier from live trade policy data
  - VRP optimizer: GDI adjusts the risk weight automatically

All endpoints return gracefully if SUPPLYMAVEN_API_KEY is not set.
Free tier (sm_free_*): supply_chain_risk_assessment, commodity_price_monitor,
                       supply_chain_disruption_alerts (critical only).
Pro tier (sm_live_*):  + trade_policy_impacts, port_congestion, action_signals.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from app.core.config import settings
from app.api.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/market", tags=["market-intelligence"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class GDIResponse(BaseModel):
    gdi_score: Optional[float]
    transportation: Optional[float]
    energy: Optional[float]
    materials: Optional[float]
    macro: Optional[float]
    trend: Optional[str]
    timestamp: Optional[str]
    risk_weight_multiplier: float   # computed from GDI — use in VRP risk weights
    available: bool


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
    critical_count: int
    high_count: int
    available: bool


class CommodityPrice(BaseModel):
    name: str
    price: float
    currency: str
    change_24h_pct: Optional[float]
    relevance: str   # "direct" (semiconductor materials) or "indirect"


class CommodityResponse(BaseModel):
    prices: List[CommodityPrice]
    available: bool


class TradePolicyResponse(BaseModel):
    active_tariffs: List[Dict[str, Any]]
    sanctions: List[Dict[str, Any]]
    export_controls: List[Dict[str, Any]]
    tariff_multiplier: float   # suggested multiplier for Digital Twin
    electronics_tariff_rate: Optional[float]   # % tariff on HS 8541/8542
    available: bool


class MarketSummaryResponse(BaseModel):
    gdi: GDIResponse
    alerts_count: int
    critical_alerts: int
    tariff_multiplier: float
    available_sources: List[str]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=MarketSummaryResponse)
async def get_market_summary(current_user: User = Depends(get_current_user)):
    """
    Dashboard summary: GDI score + alert counts + tariff multiplier in one call.
    Used by Dashboard.tsx to render the live market intelligence card.
    """
    sources: List[str] = []
    gdi_resp = GDIResponse(
        gdi_score=None, transportation=None, energy=None,
        materials=None, macro=None, trend=None, timestamp=None,
        risk_weight_multiplier=1.0, available=False,
    )
    alerts_count = 0
    critical_count = 0
    tariff_mult = 1.0

    if settings.SUPPLYMAVEN_API_KEY:
        from app.core.clients.supplymaven_client import SupplyMavenClient
        client = SupplyMavenClient(settings.SUPPLYMAVEN_API_KEY)

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

        alert_list = await client.get_disruption_alerts()
        alerts_count = len(alert_list)
        critical_count = sum(1 for a in alert_list if a.get("severity", "").lower() == "critical")

        trade_data = await client.get_trade_policy_impacts()
        if trade_data:
            tariff_mult = client.tariffs_to_scenario_multiplier(trade_data)

    return MarketSummaryResponse(
        gdi=gdi_resp,
        alerts_count=alerts_count,
        critical_alerts=critical_count,
        tariff_multiplier=tariff_mult,
        available_sources=sources,
    )


@router.get("/disruption-index", response_model=GDIResponse)
async def get_disruption_index(current_user: User = Depends(get_current_user)):
    """
    Global Disruption Index (0–100) with pillar breakdown.
    Updates every 15 minutes. Free tier.
    """
    if not settings.SUPPLYMAVEN_API_KEY:
        return GDIResponse(
            gdi_score=None, transportation=None, energy=None,
            materials=None, macro=None, trend=None, timestamp=None,
            risk_weight_multiplier=1.0, available=False,
        )

    from app.core.clients.supplymaven_client import SupplyMavenClient
    client = SupplyMavenClient(settings.SUPPLYMAVEN_API_KEY)
    data = await client.get_global_disruption_index()

    if not data:
        return GDIResponse(
            gdi_score=None, transportation=None, energy=None,
            materials=None, macro=None, trend=None, timestamp=None,
            risk_weight_multiplier=1.0, available=False,
        )

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
        return AlertsResponse(alerts=[], critical_count=0, high_count=0, available=False)

    from app.core.clients.supplymaven_client import SupplyMavenClient
    client = SupplyMavenClient(settings.SUPPLYMAVEN_API_KEY)
    raw_alerts = await client.get_disruption_alerts(severity=severity)

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
        return CommodityResponse(prices=[], available=False)

    from app.core.clients.supplymaven_client import SupplyMavenClient
    client = SupplyMavenClient(settings.SUPPLYMAVEN_API_KEY)
    data = await client.get_commodity_prices()

    if not data:
        return CommodityResponse(prices=[], available=False)

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

    Returns tariff_multiplier for Digital Twin auto-population.
    Electronics tariff rate covers HS codes 8541/8542 (semiconductors).
    """
    if not settings.SUPPLYMAVEN_API_KEY:
        return TradePolicyResponse(
            active_tariffs=[], sanctions=[], export_controls=[],
            tariff_multiplier=1.0, electronics_tariff_rate=None, available=False,
        )

    from app.core.clients.supplymaven_client import SupplyMavenClient
    client = SupplyMavenClient(settings.SUPPLYMAVEN_API_KEY)
    data = await client.get_trade_policy_impacts()

    if not data:
        return TradePolicyResponse(
            active_tariffs=[], sanctions=[], export_controls=[],
            tariff_multiplier=1.0, electronics_tariff_rate=None, available=False,
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


@router.get("/status")
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
            "description": "Real transit times for VRP cost matrix",
            "register_url": "https://www.easypost.com/",
        },
        "supplymaven": {
            "configured": bool(settings.SUPPLYMAVEN_API_KEY),
            "description": "Global disruption index + trade policy",
            "register_url": "https://supplymaven.com/developers",
        },
    }
