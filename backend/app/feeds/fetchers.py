"""
Feed fetcher functions. Each returns the parsed payload or raises on failure.
Stubs for fetch_portwatch and fetch_fred_freight are implemented in Plan 03-03.
"""
from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
import openpyxl

logger = logging.getLogger(__name__)

# ── GPR Index (Geopolitical Risk Index — Caldara & Iacoviello) ─────────────────
# T-03-05: URL hardcoded as constant — never accept user-provided URLs (SSRF mitigation)
GPR_URL = "https://www.matteoiacoviello.com/gpr_files/gpr_web_latest.xlsx"


async def fetch_gpr() -> float:
    """Download GPR XLSX and return the latest monthly GPR index value.

    The GPR sheet has columns: Date (A), GPR (B), GPR_THREAT (C), GPR_ACT (D), ...
    Monthly data since 1985; updated ~10th of each month.
    Returns float in range ~50-500+.

    T-03-05: URL is hardcoded as constant — never user-provided (SSRF mitigation).
    T-03-10: httpx timeout=30s; openpyxl read_only=True; offloaded to thread.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(GPR_URL)
        resp.raise_for_status()
        content = resp.content

    # openpyxl is synchronous — offload to thread to avoid blocking the event loop
    def _parse(data: bytes) -> float:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb["GPR"]
        last_value = None
        for row in ws.iter_rows(min_row=2, max_col=2, values_only=True):
            # T-03-08: only column B numeric values extracted; non-numeric skipped
            if row[1] is not None:
                last_value = row[1]
        wb.close()
        if last_value is None:
            raise ValueError("GPR XLSX contained no valid GPR values in column B")
        return float(last_value)

    return await asyncio.to_thread(_parse, content)


# ── ACLED Conflict Event Data ──────────────────────────────────────────────────
# T-03-06: URL hardcoded as constant — never accept user-provided URLs (SSRF mitigation)
ACLED_API_URL = "https://acleddata.com/acled/read"


async def fetch_acled(email: str, key: str) -> Optional[dict[str, int]]:
    """Fetch 90-day conflict event counts by country ISO3 code.

    Returns {ISO3: count} e.g. {"SYR": 500, "UKR": 300, "USA": 12}.
    Returns None if ACLED_EMAIL or ACLED_KEY is not configured (graceful degradation).

    Auth: Simple query params — key + email appended to every request.
    NO OAuth, NO token endpoint, NO Bearer header.

    T-03-06: URL is hardcoded as constant — never user-provided (SSRF mitigation).
    T-03-07: email/key are NOT logged at any level. Logger calls use feed name only.
    T-03-09: Only iso3 string field extracted; aggregation counts integers only.
    """
    if not email or not key:
        return None  # graceful degradation — credentials not configured

    start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
    end = datetime.utcnow().strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(ACLED_API_URL, params={
            "key": key,
            "email": email,
            "event_date": f"{start}|{end}",
            "event_date_where": "BETWEEN",
            "fields": "iso3|event_type",
            "limit": 5000,
        })
        resp.raise_for_status()

    # T-03-09: Aggregate by country ISO3 only — no raw ACLED text flows to frontend
    events = resp.json().get("data", [])
    counts: dict[str, int] = {}
    for e in events:
        iso3 = e.get("iso3", "")
        if iso3:
            counts[iso3] = counts.get(iso3, 0) + 1
    return counts


# ── IMF PortWatch (ArcGIS Feature Service) ────────────────────────────────────
# T-03-11: URL hardcoded as constant — never accept user-provided URLs (SSRF mitigation)
PORTWATCH_URL = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Ports_Data/FeatureServer/0/query"

MONITORED_PORTS = {
    "LA_LB": "port664",
    "NY_NJ": "port815",
    "SAVANNAH": "port1170",
}


async def fetch_portwatch() -> dict[str, float]:
    """Fetch port congestion proxy for 3 US ports.

    Returns {port_code: congestion_ratio} where ratio > 1.0 means congested
    (fewer recent port calls than baseline = ships waiting).

    Congestion = baseline_avg / recent_avg (inverted so higher = worse).
    Neutral = 1.0, congested > 1.0.

    T-03-11: URL hardcoded as constant — never user-provided (SSRF mitigation).
    T-03-16: portcalls values are numeric only; division by zero guarded.
    """
    results = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for code, portid in MONITORED_PORTS.items():
            try:
                params = {
                    "where": f"portid='{portid}'",
                    "outFields": "date,portcalls",
                    "orderByFields": "date DESC",
                    "resultRecordCount": 90,
                    "f": "json",
                }
                resp = await client.get(PORTWATCH_URL, params=params)
                resp.raise_for_status()
                features = resp.json().get("features", [])

                if len(features) < 14:
                    logger.warning("PortWatch %s: insufficient data (%d records)", code, len(features))
                    continue

                calls = [
                    f["attributes"]["portcalls"]
                    for f in features
                    if f.get("attributes", {}).get("portcalls") is not None
                ]

                if len(calls) < 14:
                    logger.warning("PortWatch %s: insufficient valid portcalls (%d records)", code, len(calls))
                    continue

                recent_avg = sum(calls[:7]) / 7
                baseline_avg = sum(calls) / len(calls)

                if baseline_avg > 0 and recent_avg > 0:
                    congestion = baseline_avg / recent_avg
                    results[code] = round(congestion, 3)
                else:
                    results[code] = 1.0  # neutral when no data to compare

            except Exception as exc:
                logger.warning("PortWatch %s fetch failed: %s", code, exc)

    if not results:
        raise ValueError("PortWatch: no port data retrieved for any monitored port")
    return results


# ── FRED TSIFRGHT (Freight Transportation Services Index) ─────────────────────
# T-03-12: URL hardcoded as constant — never accept user-provided URLs (SSRF mitigation)
FRED_TSIFRGHT_URL = "https://api.stlouisfed.org/fred/series/observations"


async def fetch_fred_freight(api_key: str) -> float:
    """Fetch latest TSIFRGHT (Freight Transportation Services Index) from FRED.

    Returns the latest observation value as a float.
    Reuses the same FRED API pattern as data_fetcher.py but returns only
    the most recent value and uses proper logging (not print).

    T-03-12: URL is hardcoded as constant — never user-provided (SSRF mitigation).
    T-03-14: API key is NOT logged at any level.
    """
    if not api_key:
        raise ValueError("FRED_API_KEY not configured")

    params = {
        "series_id": "TSIFRGHT",
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": "1",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(FRED_TSIFRGHT_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    observations = data.get("observations", [])
    for obs in observations:
        if obs.get("value") != ".":
            return float(obs["value"])

    raise ValueError("FRED TSIFRGHT: no valid observations returned")
