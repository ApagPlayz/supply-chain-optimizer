"""
Mouser Electronics API client.

Get API key: https://www.mouser.com/api-hub/
  1. Log in with Mouser account (or create one — free)
  2. Request a Search API key from the hub
Free tier: 30 requests/minute, 1,000 requests/day. No cost, no credit card.

Base URL: https://api.mouser.com/api/v1
Auth:     ?apiKey={key} as a query parameter on every request

Purpose (Route A, Track L): Mouser exposes a real per-part ``LeadTime`` string
(e.g. "12 Weeks"), which — together with DigiKey ``ManufacturerLeadWeeks`` — is
the REAL observed lead-time signal that replaces the old synthetic formula
target. This client mirrors ``DigiKeyClient``'s interface (search_mpn +
parse_offer) so the snapshot collector can treat the two sources uniformly.
"""

import re
import httpx
from typing import Optional, List, Dict, Any

_BASE = "https://api.mouser.com/api/v1"
_KEYWORD_PATH = "/search/keyword"
_PARTNUMBER_PATH = "/search/partnumber"


class MouserClient:
    """
    Mouser Search API v1 client (API-key query-param auth).

    Usage:
        client = MouserClient(api_key=settings.MOUSER_API_KEY)
        part   = await client.search_mpn("ESP32-WROOM-32E-N4")
        offer  = client.parse_offer(part)   # -> {"lead_time_weeks": 12, ...}
    """

    def __init__(self, api_key: str):
        self.api_key = api_key

    # ── Product search ───────────────────────────────────────────────────────────

    async def search_mpn(self, mpn: str) -> Optional[Dict[str, Any]]:
        """
        Look up a Mouser part by MPN (manufacturer part number).
        Uses the keyword endpoint and returns the first matching part dict, or None.
        """
        try:
            payload = {
                "SearchByKeywordRequest": {
                    "keyword": mpn,
                    "records": 1,
                    "startingRecord": 0,
                    "searchOptions": "",
                    "searchWithYourSignUpLanguage": "",
                }
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{_BASE}{_KEYWORD_PATH}",
                    params={"apiKey": self.api_key},
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
            data = resp.json()
            # Mouser wraps errors in an "Errors" list rather than HTTP status codes.
            errors = data.get("Errors") or []
            if errors:
                print(f"[Mouser] search_mpn({mpn}) API errors: {errors}")
                return None
            parts = data.get("SearchResults", {}).get("Parts", []) or []
            return parts[0] if parts else None
        except Exception as e:
            print(f"[Mouser] search_mpn({mpn}) error: {e}")
            return None

    async def keyword_search(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Keyword search across the Mouser catalog. Returns a list of part dicts."""
        try:
            payload = {
                "SearchByKeywordRequest": {
                    "keyword": keyword,
                    "records": limit,
                    "startingRecord": 0,
                    "searchOptions": "",
                    "searchWithYourSignUpLanguage": "",
                }
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{_BASE}{_KEYWORD_PATH}",
                    params={"apiKey": self.api_key},
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
            data = resp.json()
            if data.get("Errors"):
                print(f"[Mouser] keyword_search({keyword}) API errors: {data['Errors']}")
                return []
            return data.get("SearchResults", {}).get("Parts", []) or []
        except Exception as e:
            print(f"[Mouser] keyword_search({keyword}) error: {e}")
            return []

    # ── Normalization ──────────────────────────────────────────────────────────

    def parse_offer(self, part: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a Mouser part response into a normalized offer dict that matches
        the shape DigiKeyClient.parse_offer returns, so downstream code (the
        snapshot collector) can consume both sources identically.

        {
            "distributor": "Mouser",
            "sku": str,               # Mouser part number
            "mpn": str,
            "manufacturer": str,
            "description": str,
            "stock": int,
            "moq": int,
            "price": float,           # unit price at the lowest break
            "currency": "USD",
            "is_authorized": True,    # Mouser is an authorized distributor
            "price_breaks": [{"qty": int, "price": float}, ...],
            "lead_time_weeks": int | None,   # REAL observed lead time
            "lifecycle_status": str | None,
        }
        """
        price_breaks: List[Dict] = []
        for tier in part.get("PriceBreaks", []) or []:
            qty = tier.get("Quantity")
            price = _parse_price(tier.get("Price"))
            if qty is not None and price is not None:
                price_breaks.append({"qty": int(qty), "price": price})
        price_breaks.sort(key=lambda b: b["qty"])
        unit_price = price_breaks[0]["price"] if price_breaks else None

        return {
            "distributor": "Mouser",
            "sku": part.get("MouserPartNumber"),
            "mpn": part.get("ManufacturerPartNumber"),
            "manufacturer": part.get("Manufacturer"),
            "description": part.get("Description"),
            "stock": _parse_stock(part.get("AvailabilityInStock") or part.get("Availability")),
            "moq": _parse_int(part.get("Min"), default=1),
            "price": unit_price,
            "currency": "USD",
            "is_authorized": True,
            "price_breaks": price_breaks,
            "lead_time_weeks": _parse_lead_time_weeks(part.get("LeadTime")),
            "lifecycle_status": part.get("LifecycleStatus"),
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_lead_time_weeks(lead_time: Any) -> Optional[int]:
    """
    Parse a Mouser ``LeadTime`` string into whole weeks.

    Mouser reports lead time as free text, e.g. "12 Weeks", "56 Days",
    "0 Days", or "" when unknown. Days are converted to weeks (÷7, rounded).
    Returns None when no numeric value can be extracted.
    """
    if lead_time is None:
        return None
    text = str(lead_time).strip().lower()
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    value = float(m.group(1))
    if "day" in text:
        return int(round(value / 7.0))
    # default unit is weeks ("12 Weeks", or a bare number)
    return int(round(value))


def _parse_price(price: Any) -> Optional[float]:
    """Parse a Mouser price string like "$1.23" or "1,23 €" into a float."""
    if price is None:
        return None
    text = str(price)
    cleaned = re.sub(r"[^0-9.,]", "", text)
    if not cleaned:
        return None
    # Normalize: strip thousands separators, use '.' as decimal point.
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_stock(availability: Any) -> int:
    """Parse Mouser availability text like "5000 In Stock" into an int count."""
    if availability is None:
        return 0
    m = re.search(r"(\d[\d,]*)", str(availability))
    if not m:
        return 0
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return 0


def _parse_int(value: Any, default: int = 0) -> int:
    """Best-effort int parse for fields Mouser returns as strings ("1")."""
    if value is None:
        return default
    m = re.search(r"(\d+)", str(value))
    return int(m.group(1)) if m else default
