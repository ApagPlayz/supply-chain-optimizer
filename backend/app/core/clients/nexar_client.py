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

import logging
import time
import httpx
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

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
#
# NOTE: this was previously `supMultiMatch(lines: [SupBomLineInput!]!)`, which does not
# exist in the Nexar schema (no `lines` arg, no `SupBomLineInput` type) — every call
# returned HTTP 400. The real signature, confirmed via GraphQL introspection against
# the live API, is:
#
#   supMultiMatch(
#     queries: [SupPartMatchQuery!]!,
#     options: SupPartMatchOptions,
#     country: String!,
#     currency: String!,
#   ): [SupPartMatch!]!
#
# `SupPartMatch` is returned as a flat list (one entry per input query, in order),
# each with its own `reference`, `hits`, `error`, and `parts` (a *list* of matches,
# not a single `part` object like supSearchMpn returns).
_BOM_QUERY = """
query supMultiMatch($queries: [SupPartMatchQuery!]!, $currency: String!, $country: String!) {
  supMultiMatch(queries: $queries, currency: $currency, country: $country) {
    reference
    hits
    error
    parts {
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
          packaging
          prices { quantity price currency }
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


class NexarAPIError(RuntimeError):
    """Raised for any Nexar transport/HTTP/GraphQL failure.

    Carries a short, caller-safe message so `live_prices.py` can surface it
    verbatim in the per-source status it reports to clients, instead of the
    old pattern of catching, printing to stdout, and returning an empty
    result indistinguishable from "genuinely no offers".
    """


def _raise_for_nexar_status(resp: httpx.Response) -> None:
    """Like resp.raise_for_status(), but folds in the GraphQL error body (if any)
    so a 400 shows up as e.g. "400: Variable '$queries' ... " instead of the
    generic httpx message."""
    if resp.status_code < 400:
        return
    detail = resp.text
    try:
        body = resp.json()
        errors = body.get("errors")
        if errors:
            detail = "; ".join(
                e.get("message", str(e)) if isinstance(e, dict) else str(e)
                for e in errors
            )
    except Exception:
        pass
    raise NexarAPIError(f"HTTP {resp.status_code}: {detail[:500]}")


def _raise_on_graphql_errors(body: Dict[str, Any]) -> None:
    """A 200 response can still carry a GraphQL `errors` array (e.g. invalid
    variables that don't trip HTTP status, or a resolver failure that leaves
    `data` null). Surface those rather than silently treating `data` as
    empty. If Nexar returned partial data *alongside* errors (normal for
    field-level GraphQL errors), don't discard the usable data — just log
    the errors and let the caller parse what came back."""
    errors = body.get("errors")
    if not errors:
        return
    msg = "; ".join(
        e.get("message", str(e)) if isinstance(e, dict) else str(e)
        for e in errors
    )
    if not body.get("data"):
        raise NexarAPIError(msg[:500])
    logger.warning("Nexar returned partial data with GraphQL errors: %s", msg[:500])


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

        Raises on transport/HTTP/GraphQL errors so the caller (which is
        responsible for structured per-source status reporting) can see the
        failure instead of it being silently swallowed into "no results".
        """
        payload = {
            "query": _MPN_QUERY,
            "variables": {"mpn": mpn, "currency": currency, "country": country},
        }
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(NEXAR_API_URL, json=payload, headers=headers)
            _raise_for_nexar_status(resp)
            body = resp.json()
        _raise_on_graphql_errors(body)

        # NOTE: `dict.get(key, default)` only falls back to `default` when the
        # key is *absent*. Nexar's schema legitimately returns explicit
        # `null` for object-typed fields with no match (e.g.
        # `"supSearchMpn": null`, or a seller with `"company": null`), and a
        # bare `.get("x", {})` chain crashes with
        # `'NoneType' object has no attribute 'get'` the moment that happens.
        # Every `.get(...) or default` below guards against that.
        top = (body.get("data") or {}).get("supSearchMpn") or {}
        results = top.get("results") or []
        if not results:
            return None
        first = results[0] or {}
        return first.get("part")

    async def search_bom(
        self,
        mpns: List[str],
        currency: str = "USD",
        country: str = "US",
    ) -> List[Dict[str, Any]]:
        """
        Bulk BOM search — one call for up to ~20 MPNs via `supMultiMatch`.

        Returns a list of {reference, part, error} dicts, one per input MPN
        (in input order where Nexar preserves it). `part` is the best-match
        part dict (or None if that line had no hits), `error` carries any
        per-line error Nexar reports (e.g. an unparsable MPN) even when the
        overall call succeeds.

        Raises on transport/HTTP/GraphQL errors, same contract as search_mpn.
        """
        queries = [
            {"mpn": mpn, "reference": mpn, "start": 0, "limit": 1}
            for mpn in mpns
        ]
        payload = {
            "query": _BOM_QUERY,
            "variables": {"queries": queries, "currency": currency, "country": country},
        }
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(NEXAR_API_URL, json=payload, headers=headers)
            _raise_for_nexar_status(resp)
            body = resp.json()
        _raise_on_graphql_errors(body)

        # supMultiMatch returns `[SupPartMatch!]!` directly (a flat list, one
        # entry per input query) — NOT an object with a nested `.parts` list
        # of {reference, part} like the old (invalid) query assumed. Each
        # SupPartMatch itself has a `parts` list (plural — possible multiple
        # matches per line); we take the best (first) match, same as
        # search_mpn does for `results[0]`.
        matches = (body.get("data") or {}).get("supMultiMatch") or []
        out: List[Dict[str, Any]] = []
        for m in matches:
            if not m:
                continue
            parts = m.get("parts") or []
            out.append({
                "reference": m.get("reference"),
                "part": parts[0] if parts else None,
                "error": m.get("error"),
            })
        return out

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
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(NEXAR_API_URL, json=payload, headers=headers)
            _raise_for_nexar_status(resp)
            body = resp.json()
        _raise_on_graphql_errors(body)

        top = (body.get("data") or {}).get("supSearch") or {}
        results = top.get("results") or []
        return [r["part"] for r in results if r and r.get("part")]

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
        if not part:
            return []
        offers: List[Dict[str, Any]] = []
        for seller in part.get("sellers") or []:
            if not seller:
                continue
            # `.get("company", {})` only falls back when the key is *absent* —
            # Nexar can return `"company": null` for a seller whose company
            # record didn't resolve, and that used to crash here with
            # 'NoneType' object has no attribute 'get'.
            company_name = (seller.get("company") or {}).get("name") or "Unknown"
            is_authorized = seller.get("isAuthorized", False)
            for offer in seller.get("offers") or []:
                if not offer:
                    continue
                raw_prices = offer.get("prices") or []
                unit_price = _extract_unit_price(raw_prices)
                if unit_price is None:
                    continue
                first_price = raw_prices[0] or {} if raw_prices else {}
                offers.append({
                    "distributor": company_name,
                    "sku": offer.get("sku"),
                    "stock": offer.get("inventoryLevel", 0) or 0,
                    "moq": offer.get("moq", 1) or 1,
                    "price": unit_price,
                    "currency": first_price.get("currency", "USD") if raw_prices else "USD",
                    "is_authorized": is_authorized,
                    "price_breaks": [
                        {"qty": p["quantity"], "price": p["price"]}
                        for p in raw_prices
                        if p and p.get("quantity") is not None and p.get("price") is not None
                    ],
                })
        # Sort cheapest first
        return sorted(offers, key=lambda o: o["price"])

    def part_to_component_dict(self, part: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Nexar part to a dict compatible with Component model fields."""
        part = part or {}
        manufacturer_name = (part.get("manufacturer") or {}).get("name") or "Unknown"
        category_name = (part.get("category") or {}).get("name") or "Uncategorized"
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
    prices = [p for p in (prices or []) if p]
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
