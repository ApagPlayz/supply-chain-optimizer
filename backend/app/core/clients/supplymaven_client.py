"""
SupplyMaven API client — macro supply chain disruption intelligence.

Get API key: https://supplymaven.com/developers  (instant, no credit card)
Free tier:   sm_free_* keys — 100 queries/day, 3 tools:
               - supply_chain_risk_assessment (Global Disruption Index)
               - commodity_price_monitor (semiconductor materials)
               - supply_chain_disruption_alerts (critical severity only)
Pro tier:    sm_live_* keys — $499/month, includes trade policy + port congestion

Used in: Digital Twin scenario simulator (DigitalTwinPage.tsx)
  — Instead of users manually typing tariff %, this injects LIVE macro conditions
  — GDI score auto-adjusts the risk weight in the VRP optimizer
  — Active tariffs on Chinese-origin components trigger the chinese_origin risk flag

MCP server: SupplyMaven also exposes all tools via hosted MCP at
  https://supplymaven.com/api/mcp (configured in .mcp.json)
"""

import httpx
from typing import Optional, Dict, Any, List

_SUPPLYMAVEN_BASE = "https://supplymaven.com/api/v1"


class SupplyMavenClient:
    """
    SupplyMaven REST API client (wraps the same data as the MCP server tools).

    Usage:
        client = SupplyMavenClient(api_key=settings.SUPPLYMAVEN_API_KEY)
        gdi    = await client.get_global_disruption_index()
        alerts = await client.get_disruption_alerts()
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

    # ── Free tier (100 queries/day) ────────────────────────────────────────────

    async def get_global_disruption_index(self) -> Optional[Dict[str, Any]]:
        """
        Global Disruption Index (GDI): 0–100 composite risk score.
        Updates every 15 minutes from 200+ live data variables.

        Pillars:
          Transportation (30%) — port congestion, freight rates, border delays
          Energy (25%)         — oil prices, refinery utilization
          Materials (25%)      — commodity prices including semiconductor materials
          Macro (20%)          — PMI, PPI, NY Fed GSCPI

        Returns dict with:
          gdi_score (float)      — overall 0-100
          transportation (float)
          energy (float)
          materials (float)
          macro (float)
          timestamp (str)
          trend (str)           — "rising"/"falling"/"stable"
        """
        return await self._call("supply_chain_risk_assessment")

    async def get_disruption_alerts(
        self,
        severity: str = "all",  # "critical", "high", "medium", "low", "all"
    ) -> List[Dict[str, Any]]:
        """
        Real-time supply chain disruption alerts.
        Sources: global news intelligence, port announcements, government feeds.
        Types: port closures, tariffs, sanctions, weather, labor strikes.

        Free tier: critical severity only.
        Pro tier: all severities.

        Returns list of alert dicts:
          title (str)
          severity (str)
          category (str)    — "tariff", "port", "weather", "labor", "geopolitical"
          region (str)
          affected_commodities (list[str])
          timestamp (str)
          summary (str)
        """
        result = await self._call(
            "supply_chain_disruption_alerts",
            params={"severity": severity},
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("alerts", [])
        return []

    async def get_commodity_prices(self) -> Optional[Dict[str, Any]]:
        """
        Real-time commodity prices including semiconductor materials.
        Free tier: 5 key commodities. Pro tier: 31 commodities.

        Returns dict with commodity names → current price + 24h change %.
        Relevant for electronic components: silicon, copper, gold (wire bonding),
        tin (solder), rare earth elements (capacitors).
        """
        return await self._call("commodity_price_monitor")

    # ── Pro tier ($499/month) ──────────────────────────────────────────────────

    async def get_trade_policy_impacts(self) -> Optional[Dict[str, Any]]:
        """
        Active tariffs, sanctions, export controls with GDI impact scores.
        Key for Digital Twin: inject live tariff data affecting chinese_origin components.

        Returns dict with:
          active_tariffs (list) — country, hs_codes, rate %, effective_date
          sanctions (list)      — entity name, country, impact_score
          export_controls (list)
          overall_impact_score (float)
        """
        return await self._call("get_trade_policy_impacts")

    async def get_port_congestion(self) -> Optional[Dict[str, Any]]:
        """
        Vessel counts and congestion scores at 26 major global ports.
        Pro tier only.
        """
        return await self._call("port_congestion_monitor")

    async def get_action_signals(self) -> Optional[Dict[str, Any]]:
        """
        Granger-causal leading indicators with ACTIVE/WATCH/CLEAR status.
        Use to pre-emptively adjust risk weights in the VRP solver.
        Pro tier only.
        """
        return await self._call("get_action_signals")

    async def get_supply_chain_brief(self) -> Optional[Dict[str, Any]]:
        """
        Weekly executive situation report: GDI + SMI + ports + signals.
        Signal tier ($999/month) only.
        """
        return await self._call("get_supply_chain_weekly_brief")

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _call(
        self,
        tool: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Call a SupplyMaven tool endpoint."""
        payload = {"tool": tool, "parameters": params or {}}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{_SUPPLYMAVEN_BASE}/tools",
                    json=payload,
                    headers={**self._headers, "Content-Type": "application/json"},
                )
                if resp.status_code == 429:
                    print(f"[SupplyMaven] Rate limit hit on tool: {tool}")
                    return None
                if resp.status_code == 403:
                    print(f"[SupplyMaven] Tool {tool!r} requires Pro/Signal tier")
                    return None
                resp.raise_for_status()
                data = resp.json()
            return data.get("result") or data
        except Exception as e:
            print(f"[SupplyMaven] {tool} error: {e}")
            return None

    def get_risk_weight_adjustment(self, gdi_data: Optional[Dict]) -> float:
        """
        Convert GDI score to a risk weight multiplier for the VRP optimizer.

        VRP uses base risk_weight of 0.1–0.8 depending on strategy.
        This multiplier nudges the weight up during high-disruption periods.

        Returns a float factor (e.g. 1.0 = no adjustment, 1.3 = +30% risk weight).
        """
        if not gdi_data:
            return 1.0
        score = float(gdi_data.get("gdi_score", 50))
        if score >= 75:
            return 1.5   # High disruption — substantially increase risk weight
        elif score >= 60:
            return 1.25  # Elevated
        elif score >= 40:
            return 1.0   # Normal
        else:
            return 0.85  # Low disruption — can reduce risk premium

    def tariffs_to_scenario_multiplier(self, trade_data: Optional[Dict]) -> float:
        """
        Convert active tariff data to a cost multiplier for Digital Twin scenarios.

        Returns e.g. 1.25 meaning "25% tariff uplift on affected components".
        Used as the default tariff_multiplier in ScenarioRequest when live data available.
        """
        if not trade_data:
            return 1.0
        tariffs = trade_data.get("active_tariffs", [])
        # Find tariffs affecting electronics / semiconductors
        electronics_tariffs = [
            t for t in tariffs
            if any(
                kw in str(t).lower()
                for kw in ["semiconductor", "electronic", "8541", "8542", "8471", "china"]
            )
        ]
        if not electronics_tariffs:
            return 1.0
        # Use maximum rate found
        rates = []
        for t in electronics_tariffs:
            rate_str = str(t.get("rate", "0")).replace("%", "")
            try:
                rates.append(float(rate_str) / 100)
            except ValueError:
                pass
        return 1.0 + max(rates) if rates else 1.0
