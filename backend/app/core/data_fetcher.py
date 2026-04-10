"""
Real-time commodity price data fetchers for FRED and Alpha Vantage APIs.

FRED (Federal Reserve Economic Data):
  - Free API key from https://fred.stlouisfed.org/docs/api/api_key.html
  - Provides PPI series for industrial commodities (e.g., PCU3353433534 for lithium)

Alpha Vantage:
  - Free API key from https://www.alphavantage.co/support/#api-key
  - Provides daily/monthly commodity prices (copper, aluminum, gold, silver, etc.)
"""

import httpx
from datetime import datetime, timedelta
from typing import Optional
from app.core.config import settings

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
AV_BASE = "https://www.alphavantage.co/query"

# Alpha Vantage supported commodity symbols (use their dedicated endpoints)
# These are the function names for the /query endpoint
AV_COMMODITY_SYMBOLS = {"COPPER", "ALUMINUM", "WTI", "BRENT", "NATURAL_GAS"}
# Precious metals accessed via forex daily endpoint
AV_PRECIOUS_METALS = {"XAUUSD": "XAU", "XAGUSD": "XAG"}


async def fetch_fred_series(
    series_id: str,
    days: int = 365,
) -> Optional[list[dict]]:
    """Fetch historical observations from FRED API.

    Returns list of {"date": datetime, "price": float, "source": "fred"} or None on failure.
    """
    if not settings.FRED_API_KEY:
        return None

    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "series_id": series_id,
        "api_key": settings.FRED_API_KEY,
        "file_type": "json",
        "observation_start": start,
        "sort_order": "asc",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(FRED_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()

        observations = data.get("observations", [])
        results = []
        for obs in observations:
            if obs["value"] == ".":  # FRED uses "." for missing values
                continue
            results.append({
                "date": datetime.strptime(obs["date"], "%Y-%m-%d"),
                "price": float(obs["value"]),
                "source": "fred",
            })
        return results if results else None
    except Exception as e:
        print(f"[FRED] Error fetching {series_id}: {e}")
        return None


async def fetch_alpha_vantage_commodity(
    symbol: str,
    days: int = 365,
) -> Optional[list[dict]]:
    """Fetch commodity price history from Alpha Vantage.

    Supports: COPPER, ALUMINUM (monthly commodities), XAUUSD, XAGUSD (forex rates).
    Returns list of {"date": datetime, "price": float, "source": "alpha_vantage"} or None.
    """
    if not settings.ALPHA_VANTAGE_API_KEY:
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if symbol in AV_PRECIOUS_METALS:
                # Precious metals via forex daily endpoint
                from_currency = AV_PRECIOUS_METALS[symbol]
                params = {
                    "function": "FX_DAILY",
                    "from_symbol": from_currency,
                    "to_symbol": "USD",
                    "outputsize": "full",
                    "apikey": settings.ALPHA_VANTAGE_API_KEY,
                }
                resp = await client.get(AV_BASE, params=params)
                resp.raise_for_status()
                data = resp.json()
                time_series = data.get("Time Series FX (Daily)", {})
                price_key = "4. close"
            elif symbol in AV_COMMODITY_SYMBOLS:
                # Commodities via dedicated monthly endpoint
                params = {
                    "function": symbol,
                    "interval": "monthly",
                    "apikey": settings.ALPHA_VANTAGE_API_KEY,
                }
                resp = await client.get(AV_BASE, params=params)
                resp.raise_for_status()
                data = resp.json()
                time_series = {
                    d["date"]: {"value": d["value"]}
                    for d in data.get("data", [])
                    if d["value"] != "."
                }
                price_key = "value"
            else:
                return None

        cutoff = datetime.utcnow() - timedelta(days=days)
        results = []
        for date_str, values in sorted(time_series.items()):
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if dt < cutoff:
                continue
            price = float(values[price_key])
            results.append({
                "date": dt,
                "price": price,
                "source": "alpha_vantage",
            })
        return results if results else None
    except Exception as e:
        print(f"[AlphaVantage] Error fetching {symbol}: {e}")
        return None


async def fetch_price_history(
    fred_series_id: Optional[str],
    alpha_vantage_symbol: Optional[str],
    days: int = 365,
) -> Optional[list[dict]]:
    """Try FRED first, then Alpha Vantage. Returns None if both fail or no keys configured."""
    if fred_series_id:
        result = await fetch_fred_series(fred_series_id, days)
        if result:
            return result

    if alpha_vantage_symbol:
        result = await fetch_alpha_vantage_commodity(alpha_vantage_symbol, days)
        if result:
            return result

    return None
