"""
DigiKey API v4 client.

Get credentials: https://developer.digikey.com/
  1. Create an account
  2. Create an organization
  3. Add a production app → get Client ID + Client Secret
Free tier: 1,000 searches/day. No credit card required.

Auth: OAuth2 client_credentials (two-legged — no user login required)
Token URL: https://api.digikey.com/v1/oauth2/token
Sandbox:   https://sandbox-api.digikey.com (use DIGIKEY_SANDBOX=true in .env)

Key advantage: SupplyChain endpoint returns bonded inventory BY WAREHOUSE LOCATION
— directly feeds the VRP solver with location-aware stock data.
"""

import time
import httpx
from typing import Optional, List, Dict, Any

_PROD_BASE = "https://api.digikey.com"
_SANDBOX_BASE = "https://sandbox-api.digikey.com"
_TOKEN_PATH = "/v1/oauth2/token"
_SEARCH_PATH = "/products/v4/search"


class DigiKeyClient:
    """
    DigiKey API v4 client (OAuth2 client credentials).

    Usage:
        client = DigiKeyClient(
            client_id=settings.DIGIKEY_CLIENT_ID,
            client_secret=settings.DIGIKEY_CLIENT_SECRET,
            sandbox=settings.DIGIKEY_SANDBOX,
        )
        product = await client.search_mpn("296-ESP32-WROOM-32E-N4-ND")
        offer   = client.parse_offer(product)
    """

    def __init__(self, client_id: str, client_secret: str, sandbox: bool = False):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = _SANDBOX_BASE if sandbox else _PROD_BASE
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0

    # ── Auth ───────────────────────────────────────────────────────────────────

    async def _get_token(self) -> str:
        if self._access_token and time.time() < self._token_expiry - 60:
            return self._access_token
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}{_TOKEN_PATH}",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._access_token

    def _auth_headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-DIGIKEY-Client-Id": self.client_id,
            "X-DIGIKEY-Locale-Site": "US",
            "X-DIGIKEY-Locale-Language": "en",
            "X-DIGIKEY-Locale-Currency": "USD",
            "X-DIGIKEY-Customer-Id": "0",
        }

    # ── Product search ─────────────────────────────────────────────────────────

    async def search_mpn(self, mpn: str) -> Optional[Dict[str, Any]]:
        """
        Look up a DigiKey part by MPN (manufacturer part number).
        Uses keyword search and returns the first matching product.
        """
        try:
            token = await self._get_token()
            payload = {
                "Keywords": mpn,
                "Limit": 1,
                "Offset": 0,
            }
            headers = {**self._auth_headers(token), "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.base_url}{_SEARCH_PATH}/keyword",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
            products = resp.json().get("Products", [])
            return products[0] if products else None
        except Exception as e:
            print(f"[DigiKey] search_mpn({mpn}) error: {e}")
            return None

    async def keyword_search(
        self,
        keyword: str,
        limit: int = 10,
        in_stock_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Keyword search across DigiKey catalog.
        Returns list of product dicts.
        """
        try:
            token = await self._get_token()
            payload = {
                "Keywords": keyword,
                "Limit": limit,
                "Offset": 0,
                "FilterOptionsRequest": {
                    "InStockOnly": in_stock_only,
                },
                "SortOptions": {
                    "Field": "None",
                    "SortOrder": "Ascending",
                },
            }
            headers = {**self._auth_headers(token), "Content-Type": "application/json"}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.base_url}{_SEARCH_PATH}/keyword",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
            return resp.json().get("Products", [])
        except Exception as e:
            print(f"[DigiKey] keyword_search({keyword}) error: {e}")
            return []

    async def get_supply_chain(self, digikey_pn: str) -> Optional[Dict[str, Any]]:
        """
        SupplyChain endpoint: returns bonded inventory by warehouse location.
        This is the key endpoint for location-aware VRP routing —
        you know exactly which DigiKey warehouse has stock.

        Requires SupplyChain API product enabled on your DigiKey app.
        """
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/supplychains/v1/parts/{digikey_pn}",
                    headers=self._auth_headers(token),
                )
                if resp.status_code in (404, 403):
                    return None
                resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[DigiKey] get_supply_chain({digikey_pn}) error: {e}")
            return None

    # ── Normalization ──────────────────────────────────────────────────────────

    def parse_offer(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert DigiKey product response to normalized offer dict.

        {
            "distributor": "DigiKey",
            "sku": str,
            "stock": int,
            "moq": int,
            "price": float,
            "currency": "USD",
            "is_authorized": True,
            "price_breaks": [{"qty": int, "price": float}, ...]
        }
        """
        # Pricing comes from ProductVariations[0].StandardPricing
        variations = product.get("ProductVariations", [])
        pricing: List[Dict] = []
        if variations:
            pricing = variations[0].get("StandardPricing", [])

        unit_price: Optional[float] = None
        price_breaks: List[Dict] = []
        for tier in pricing:
            bp = tier.get("BreakQuantity", 1)
            up = tier.get("UnitPrice")
            if up is not None:
                price_breaks.append({"qty": bp, "price": float(up)})
                if bp == 1 and unit_price is None:
                    unit_price = float(up)
        if unit_price is None and price_breaks:
            unit_price = price_breaks[0]["price"]

        return {
            "distributor": "DigiKey",
            "sku": product.get("DigiKeyPartNumber") or (product.get("ProductVariations", [{}])[0].get("DigiKeyProductNumber") if product.get("ProductVariations") else None),
            "mpn": product.get("ManufacturerProductNumber") or product.get("ManufacturerPartNumber"),
            "manufacturer": product.get("Manufacturer", {}).get("Name"),
            "description": product.get("Description", {}).get("ProductDescription"),
            "stock": product.get("QuantityAvailable", 0) or 0,
            "moq": product.get("MinimumOrderQuantity", 1) or 1,
            "price": unit_price,
            "currency": "USD",
            "is_authorized": True,
            "price_breaks": price_breaks,
            "lead_time_weeks": product.get("ManufacturerLeadWeeks"),
            "lifecycle_status": product.get("ProductStatus", {}).get("Status"),
            "series": product.get("Series", {}).get("Name"),
        }
