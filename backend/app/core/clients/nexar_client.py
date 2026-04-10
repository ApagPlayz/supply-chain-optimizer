"""
Nexar API client (Octopart GraphQL — the authoritative electronic components database).

Get API key: https://nexar.com/api  (free evaluation account — instant approval)
Free tier:   1,000 part lookups (lifetime, resets never — enough for dev/demo)
Paid tiers:  2,000/month (Standard), 15,000/month (Pro)

This is the same underlying data as the HuggingFace dataset we currently use,
but live — real-time stock levels, current prices, actual lead times.

Auth:     OAuth2 client credentials → Bearer token (auto-refreshed)
Endpoint: https://api.nexar.com/graphql/
"""

import time
import httpx
from typing import Optional, List, Dict, Any

NEXAR_TOKEN_URL = "https://identity.nexar.com/connect/token"
NEXAR_API_URL = "https://api.nexar.com/graphql/"

# ── GraphQL Queries ────────────────────────────────────────────────────────────

# Single MPN search — returns all distributor offers with price breaks
_MPN_QUERY = """
query supSearchMPN($mpn: String!, $currency: String!, $country: String!) {
  supSearchMpn(q: $mpn, currency: $currency, country: $country, limit: 1) {
    results {
      part {
        mpn
        manufacturer { name }
        shortDescription
        category { name }
        manufacturerUrl
        specs { attribute { name } displayValue }
        sellers {
          company {
            name
            homepageUrl
          }
          isAuthorized
          offers {
            sku
            inventoryLevel
            moq
            packaging
            prices {
              quantity
              price
              currency
            }
          }
        }
      }
    }
  }
}
"""

# Bulk BOM search — multiple MPNs in one network call (critical for checkout optimization)
_BOM_QUERY = """
query supMultiMatch($lines: [SupBomLineInput!]!) {
  supMultiMatch(lines: $lines) {
    hits
    parts {
      reference
      part {
        mpn
        manufacturer { name }
        shortDescription
        sellers {
          company { name }
          isAuthorized
          offers {
            sku
            inventoryLevel
            moq
            prices { quantity price currency }
          }
        }
      }
    }
  }
}
"""

# Category + parametric search — for Scheduler page browsing
_CATEGORY_QUERY = """
query supSearch($q: String!, $limit: Int!, $currency: String!) {
  supSearch(q: $q, limit: $limit, currency: $currency) {
    total
    results {
      part {
        mpn
        manufacturer { name }
        shortDescription
        category { name }
        sellers {
          company { name }
          isAuthorized
          offers {
            sku
            inventoryLevel
            prices { quantity price currency }
          }
        }
      }
    }
  }
}
"""


class NexarClient:
    """
    Nexar/Octopart GraphQL client with OAuth2 auto-refresh.

    Usage:
        client = NexarClient(
            client_id=settings.NEXAR_CLIENT_ID,
            client_secret=settings.NEXAR_CLIENT_SECRET,
        )
        part   = await client.search_mpn("ESP32-WROOM-32E")
        offers = client.parse_offers(part)

    Returns normalized offer dicts compatible with DistributorOffer model.
    """

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._token_expiry: float = 0

    async def _ensure_token(self) -> str:
        """Get a valid bearer token, refreshing via OAuth2 client credentials if expired."""
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                NEXAR_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "supply.domain",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        self._token = data["access_token"]
        self._token_expiry = time.time() + data.get("expires_in", 3600)
        return self._token

    async def _headers(self) -> Dict[str, str]:
        token = await self._ensure_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ── Public methods ─────────────────────────────────────────────────────────

    async def search_mpn(
        self,
        mpn: str,
        currency: str = "USD",
        country: str = "US",
    ) -> Optional[Dict[str, Any]]:
        """
        Search for a single MPN. Returns the best matching part dict or None.

        The returned dict contains a 'sellers' list with all distributor offers.
        Pass it to parse_offers() to get normalized pricing data.
        """
        payload = {
            "query": _MPN_QUERY,
            "variables": {"mpn": mpn, "currency": currency, "country": country},
        }
        try:
            headers = await self._headers()
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(NEXAR_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            results = (
                data.get("data", {})
                .get("supSearchMpn", {})
                .get("results", [])
            )
            return results[0]["part"] if results else None
        except Exception as e:
            print(f"[Nexar] search_mpn({mpn}) error: {e}")
            return None

    async def search_bom(
        self,
        mpns: List[str],
        currency: str = "USD",
    ) -> List[Dict[str, Any]]:
        """
        Bulk BOM search — one call for up to ~20 MPNs.

        Returns list of {reference, part} dicts matching input order.
        Use this in checkout/optimize flow instead of N individual calls.
        """
        lines = [{"mpn": mpn, "reference": mpn} for mpn in mpns]
        payload = {
            "query": _BOM_QUERY,
            "variables": {"lines": lines},
        }
        try:
            headers = await self._headers()
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(NEXAR_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            return (
                data.get("data", {})
                .get("supMultiMatch", {})
                .get("parts", [])
            )
        except Exception as e:
            print(f"[Nexar] search_bom error: {e}")
            return []

    async def search_category(
        self,
        query: str,
        limit: int = 50,
        currency: str = "USD",
    ) -> List[Dict[str, Any]]:
        """
        Free-text/category search for the Scheduler page component browser.
        E.g. query='microcontroller ESP32', 'STM32 ARM', 'op-amp TI'
        """
        payload = {
            "query": _CATEGORY_QUERY,
            "variables": {"q": query, "limit": limit, "currency": currency},
        }
        try:
            headers = await self._headers()
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(NEXAR_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            results = (
                data.get("data", {})
                .get("supSearch", {})
                .get("results", [])
            )
            return [r["part"] for r in results if r.get("part")]
        except Exception as e:
            print(f"[Nexar] search_category({query}) error: {e}")
            return []

    # ── Normalization helpers ──────────────────────────────────────────────────

    def parse_offers(self, part: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert a Nexar part dict into a list of normalized offer dicts.

        Each offer dict:
        {
            "distributor": str,
            "sku": str,
            "stock": int,
            "moq": int,
            "price": float,           # unit price at qty=1
            "currency": str,
            "is_authorized": bool,
            "price_breaks": [{"qty": int, "price": float}, ...]
        }
        """
        offers: List[Dict[str, Any]] = []
        for seller in part.get("sellers", []):
            company_name = seller.get("company", {}).get("name", "Unknown")
            is_authorized = seller.get("isAuthorized", False)
            for offer in seller.get("offers", []):
                raw_prices = offer.get("prices", [])
                unit_price = _extract_unit_price(raw_prices)
                if unit_price is None:
                    continue
                offers.append({
                    "distributor": company_name,
                    "sku": offer.get("sku"),
                    "stock": offer.get("inventoryLevel", 0) or 0,
                    "moq": offer.get("moq", 1) or 1,
                    "price": unit_price,
                    "currency": raw_prices[0].get("currency", "USD") if raw_prices else "USD",
                    "is_authorized": is_authorized,
                    "price_breaks": [
                        {"qty": p["quantity"], "price": p["price"]}
                        for p in raw_prices
                    ],
                })
        # Sort cheapest first
        return sorted(offers, key=lambda o: o["price"])

    def part_to_component_dict(self, part: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Nexar part to a dict compatible with Component model fields."""
        manufacturer_name = part.get("manufacturer", {}).get("name", "Unknown")
        category_name = part.get("category", {}).get("name", "Uncategorized")
        return {
            "mpn": part.get("mpn", ""),
            "manufacturer": manufacturer_name,
            "manufacturer_country": None,  # Nexar doesn't expose this at this level
            "category": category_name,
            "description": part.get("shortDescription"),
            "datasheets": [],
            "risk_score": 0.0,
            "risk_factors": [],
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_unit_price(prices: List[Dict]) -> Optional[float]:
    """Extract unit price at qty=1, falling back to lowest qty available."""
    if not prices:
        return None
    # Prefer qty=1 price
    for p in prices:
        if p.get("quantity") == 1:
            v = p.get("price")
            return float(v) if v is not None else None
    # Fall back to lowest quantity tier
    sorted_prices = sorted(prices, key=lambda p: p.get("quantity", 999999))
    v = sorted_prices[0].get("price")
    return float(v) if v is not None else None
