"""
TrustedParts API client — authorized distributors only, completely free.

Get API access: https://www.trustedparts.com/docs/
  Register at trustedparts.com → request API access → administrator approval.
  Completely free in almost all circumstances (funded by distributor fees).
  Covers 25M+ unique part numbers, 2,000+ trusted manufacturers/distributors.
  Max 50 parts per request.

Key value: AUTHORIZED DISTRIBUTORS ONLY — no gray market, no counterfeit risk.
This directly reduces the risk score for components sourced from TrustedParts results.
"""

import httpx
from typing import Optional, List, Dict, Any

_BASE_URL = "https://www.trustedparts.com/api/v1"


class TrustedPartsClient:
    """
    TrustedParts API client (authorized distributors only).

    Usage:
        client = TrustedPartsClient(api_key=settings.TRUSTEDPARTS_API_KEY)
        offers = await client.search_mpn("STM32F103C8T6")
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

    async def search_mpn(self, mpn: str) -> List[Dict[str, Any]]:
        """
        Search by manufacturer part number.
        Returns list of normalized offers from authorized distributors only.
        """
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{_BASE_URL}/parts/search",
                    params={"mpn": mpn},
                    headers=self._headers,
                )
                if resp.status_code in (401, 403):
                    print("[TrustedParts] Invalid API key or unauthorized")
                    return []
                resp.raise_for_status()
                data = resp.json()
            return self._parse_response(data)
        except Exception as e:
            print(f"[TrustedParts] search_mpn({mpn}) error: {e}")
            return []

    async def search_batch(self, mpns: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Batch search up to 50 MPNs in one call.
        Returns dict keyed by MPN.
        """
        if not mpns:
            return {}
        # TrustedParts allows up to 50 per request
        batch = mpns[:50]
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{_BASE_URL}/parts/batch",
                    json={"mpns": batch},
                    headers={**self._headers, "Content-Type": "application/json"},
                )
                if resp.status_code in (401, 403):
                    print("[TrustedParts] Invalid API key or unauthorized")
                    return {}
                resp.raise_for_status()
                data = resp.json()
            return {mpn: self._parse_response(part_data) for mpn, part_data in data.items()}
        except Exception as e:
            print(f"[TrustedParts] search_batch error: {e}")
            return {}

    def _parse_response(self, data: Any) -> List[Dict[str, Any]]:
        """Normalize TrustedParts response into standard offer list."""
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("results", data.get("offers", [data] if data else []))
        else:
            return []

        offers: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            # Extract pricing
            prices_raw = item.get("prices", [])
            price_breaks: List[Dict] = []
            for p in prices_raw:
                qty = _safe_int(p.get("quantity") or p.get("qty", 1))
                price_val = _safe_float(p.get("price") or p.get("unit_price"))
                if qty and price_val:
                    price_breaks.append({"qty": qty, "price": price_val})

            unit_price = price_breaks[0]["price"] if price_breaks else _safe_float(item.get("unit_price") or item.get("price"))
            if unit_price is None:
                continue

            offers.append({
                "distributor": item.get("distributor") or item.get("company_name"),
                "sku": item.get("sku") or item.get("part_number"),
                "mpn": item.get("mpn") or item.get("manufacturer_part_number"),
                "manufacturer": item.get("manufacturer"),
                "description": item.get("description"),
                "stock": _safe_int(item.get("stock") or item.get("quantity_available", 0)),
                "moq": _safe_int(item.get("moq") or item.get("minimum_order_quantity", 1)),
                "price": unit_price,
                "currency": item.get("currency", "USD"),
                "is_authorized": True,  # TrustedParts = authorized only
                "price_breaks": price_breaks,
                "lead_time_weeks": item.get("lead_time_weeks"),
                "lifecycle_status": item.get("lifecycle_status"),
                "datasheet_url": item.get("datasheet_url"),
            })

        return sorted(offers, key=lambda o: o["price"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_int(val: Any) -> int:
    try:
        return int(str(val).replace(",", ""))
    except (TypeError, ValueError):
        return 0


def _safe_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
