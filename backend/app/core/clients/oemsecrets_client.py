"""
OEMsecrets API client — 40+ distributor aggregator in a single call.

Get API key: https://www.oemsecrets.com/api
  Apply via the registration form — approval is typically within 24–48 hours.
  Free (funded by distributor participation fees).

Covered distributors include: Arrow, Avnet, DigiKey, Farnell, Future Electronics,
  Mouser, Newark, RS Components, and many more.

Single endpoint: GET /partsearch?searchTerm={mpn}&apiKey={key}&countryCode=US&currency=USD
Documentation: https://oemsecretsapi.com/documentation/
"""

import httpx
from typing import Optional, List, Dict, Any

_BASE_URL = "https://oemsecretsapi.com"


class OEMSecretsClient:
    """
    OEMsecrets API client.

    One call returns competitive pricing from 40+ distributors —
    the primary data source for the competitive pricing comparison table.

    Usage:
        client = OEMSecretsClient(api_key=settings.OEMSECRETS_API_KEY)
        offers = await client.search_mpn("LM358DR")
    """

    def __init__(self, api_key: str, country_code: str = "US", currency: str = "USD"):
        self.api_key = api_key
        self.country_code = country_code
        self.currency = currency

    async def search_mpn(
        self,
        mpn: str,
    ) -> List[Dict[str, Any]]:
        """
        Search all distributors by MPN in a single API call.

        Returns a list of normalized offer dicts sorted cheapest first.
        """
        params = {
            "searchTerm": mpn,
            "apiKey": self.api_key,
            "countryCode": self.country_code,
            "currency": self.currency,
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    f"{_BASE_URL}/partsearch",
                    params=params,
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 401:
                    print("[OEMsecrets] Rate limit or invalid API key")
                    return []
                resp.raise_for_status()
                data = resp.json()
            return self._parse_response(data)
        except Exception as e:
            print(f"[OEMsecrets] search_mpn({mpn}) error: {e}")
            return []

    def _parse_response(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Normalize OEMsecrets response into standard offer list."""
        raw_items = data.get("stock", [])
        offers: List[Dict[str, Any]] = []

        for item in raw_items:
            price_breaks = self._extract_price_breaks(item)
            unit_price = price_breaks[0]["price"] if price_breaks else None
            if unit_price is None or unit_price <= 0:
                continue

            dist_info = item.get("distributor", {})
            dist_name = dist_info.get("distributor_name") or dist_info.get("distributor_common_name", "Unknown")
            auth_status = (item.get("distributor_authorisation_status") or "").lower()

            offers.append({
                "distributor": dist_name,
                "sku": item.get("sku") or item.get("source_part_number"),
                "mpn": item.get("part_number"),
                "manufacturer": item.get("manufacturer"),
                "description": item.get("description"),
                "stock": _safe_int(item.get("quantity_in_stock", 0)),
                "moq": _safe_int(item.get("moq", 1)) or 1,
                "price": unit_price,
                "currency": item.get("source_currency") or self.currency,
                "is_authorized": auth_status == "authorised",
                "price_breaks": price_breaks,
                "lead_time_weeks": _safe_int(item.get("lead_time_weeks")),
                "lifecycle_status": item.get("life_cycle") or None,
                "datasheet_url": item.get("datasheet_url") or None,
                "buy_url": item.get("buy_now_url"),
            })

        # Sort by unit price ascending
        return sorted(offers, key=lambda o: o["price"])

    def _extract_price_breaks(self, item: Dict) -> List[Dict[str, Any]]:
        """Extract quantity price breaks from OEMsecrets item."""
        breaks: List[Dict[str, Any]] = []
        prices = item.get("prices", {})

        if isinstance(prices, dict):
            # OEMsecrets returns prices as {currency: [{unit_break, unit_price}, ...]}
            for currency, break_list in prices.items():
                if not isinstance(break_list, list):
                    continue
                for b in break_list:
                    qty = _safe_int(b.get("unit_break", 1)) or 1
                    price = _safe_float(b.get("unit_price"))
                    if price and price > 0:
                        breaks.append({"qty": qty, "price": price})
                break  # Use first currency only
        elif isinstance(prices, list):
            for p in prices:
                qty = _safe_int(p.get("quantity") or p.get("unit_break", 1))
                price = _safe_float(p.get("price") or p.get("unit_price"))
                if qty and price and price > 0:
                    breaks.append({"qty": qty, "price": price})

        return sorted(breaks, key=lambda b: b["qty"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_int(val: Any) -> int:
    try:
        return int(float(str(val).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
