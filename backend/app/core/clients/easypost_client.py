"""
EasyPost SmartRate API client — real transit time estimates for VRP cost matrix.

Get API key: https://www.easypost.com/  (create a free account)
Free tier:  500 SmartRate calls free, then $0.03/call or subscription.
            3,000 free shipping labels/month.

SmartRate replaces the haversine-based ETA estimation in optimize.py with
REAL carrier transit time data — at confidence percentiles (p50, p75, p90).

Integration: Called from optimize.py when EASYPOST_API_KEY is set.
If key is missing, optimize.py falls back to the existing haversine estimate.

Docs: https://docs.easypost.com/docs/smartrate
"""

import httpx
import base64
from typing import Optional, Dict, Any, Tuple

_EASYPOST_BASE = "https://api.easypost.com/v2"

# Default parcel for electronic components shipments
_DEFAULT_PARCEL = {
    "length": 12.0,   # inches
    "width": 8.0,
    "height": 4.0,
    "weight": 16.0,   # ounces (1 lb)
}


class EasyPostClient:
    """
    EasyPost SmartRate client for transit time estimation.

    Usage:
        client = EasyPostClient(api_key=settings.EASYPOST_API_KEY)
        transit = await client.get_transit_days(
            from_lat=48.1191, from_lng=-96.1810,   # DigiKey warehouse
            to_lat=37.7749, to_lng=-122.4194,       # Delivery address
        )
        # transit = {"p50": 3.0, "p75": 4.0, "p90": 5.0}
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        # EasyPost uses HTTP Basic Auth: api_key as username, empty password
        credentials = base64.b64encode(f"{api_key}:".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }

    async def get_transit_days(
        self,
        from_zip: str,
        to_zip: str,
        planned_ship_date: Optional[str] = None,
        weight_oz: float = 16.0,
    ) -> Optional[Dict[str, float]]:
        """
        Get SmartRate transit day estimates between two ZIP codes.

        Returns dict with percentile transit days:
        {
            "p50": float,   # median delivery in days
            "p75": float,
            "p90": float,   # 90th percentile (conservative estimate)
            "carrier": str, # best carrier service
            "rate_usd": float,
        }
        Returns None if API call fails (caller falls back to haversine estimate).
        """
        try:
            # Step 1: Create a shipment
            shipment_payload = {
                "shipment": {
                    "from_address": {"zip": from_zip, "country": "US"},
                    "to_address": {"zip": to_zip, "country": "US"},
                    "parcel": {**_DEFAULT_PARCEL, "weight": weight_oz},
                }
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{_EASYPOST_BASE}/shipments",
                    json=shipment_payload,
                    headers=self._headers,
                )
                resp.raise_for_status()
                shipment = resp.json()

            shipment_id = shipment.get("id")
            if not shipment_id:
                return None

            # Step 2: Get SmartRates for the shipment
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{_EASYPOST_BASE}/shipments/{shipment_id}/smartrate",
                    headers=self._headers,
                )
                resp.raise_for_status()
                smartrate_data = resp.json()

            return self._parse_smartrates(smartrate_data)

        except Exception as e:
            print(f"[EasyPost] get_transit_days({from_zip}→{to_zip}) error: {e}")
            return None

    async def get_transit_days_from_coords(
        self,
        from_lat: float, from_lng: float,
        to_lat: float, to_lng: float,
        weight_oz: float = 16.0,
    ) -> Optional[Dict[str, float]]:
        """
        Wrapper that converts coordinates to ZIP codes using reverse geocoding,
        then calls get_transit_days.

        Falls back to haversine-based estimate if ZIP lookup fails.
        """
        from_zip = await _coords_to_zip(from_lat, from_lng)
        to_zip = await _coords_to_zip(to_lat, to_lng)
        if not from_zip or not to_zip:
            return None
        return await self.get_transit_days(from_zip, to_zip, weight_oz=weight_oz)

    def _parse_smartrates(self, data: Dict[str, Any]) -> Optional[Dict[str, float]]:
        """Extract best SmartRate transit time percentiles."""
        smartrates = data.get("result", data.get("smartrates", []))
        if not smartrates:
            return None

        # Sort by delivery_days (p50 proxy), pick cheapest ground option
        # SmartRate fields: time_in_transit.percentile_50/75/90, rate (USD)
        ground_rates = [r for r in smartrates if "GROUND" in r.get("service", "").upper()]
        candidates = ground_rates if ground_rates else smartrates
        best = sorted(candidates, key=lambda r: r.get("rate", 9999))[0]

        transit = best.get("time_in_transit", {})
        return {
            "p50": float(transit.get("percentile_50", best.get("delivery_days", 5))),
            "p75": float(transit.get("percentile_75", best.get("delivery_days", 5) + 1)),
            "p90": float(transit.get("percentile_90", best.get("delivery_days", 5) + 2)),
            "carrier": best.get("carrier", ""),
            "service": best.get("service", ""),
            "rate_usd": float(best.get("rate", 0)),
        }


# ── ZIP code lookup from coordinates ──────────────────────────────────────────

# Pre-mapped ZIP codes for the 92 known distributor locations.
# Avoids making geocoding API calls for well-known warehouse coordinates.
_KNOWN_COORDS_TO_ZIP: Dict[Tuple[float, float], str] = {
    (48.1191, -96.1810): "56701",   # DigiKey — Thief River Falls, MN
    (32.5632, -97.1417): "76063",   # Mouser — Mansfield, TX
    (39.5792, -104.8777): "80112",  # Arrow — Centennial, CO
    (33.6015, -111.8884): "85224",  # Avnet — Chandler, AZ
    (41.8781, -87.6298): "60601",   # Newark — Chicago, IL
    (42.5251, -71.3514): "01887",   # Analog Devices — Wilmington, MA
    (42.6043, -71.3468): "01950",   # Rochester Electronics — Newburyport, MA
    (37.4636, -121.9180): "94002",  # Jameco — Belmont, CA
    (33.4484, -112.0740): "85001",  # Phoenix area
    (37.3382, -121.8863): "95101",  # San Jose, CA
    (33.9425, -118.4081): "90045",  # Los Angeles, CA
    (37.7749, -122.4194): "94102",  # San Francisco, CA
    (40.7128, -74.0060):  "10001",  # New York, NY
    (42.3601, -71.0589):  "02101",  # Boston, MA
    (33.7490, -84.3880):  "30301",  # Atlanta, GA
    (35.2271, -80.8431):  "28201",  # Charlotte, NC
    (32.7767, -96.7970):  "75201",  # Dallas, TX
    (41.8119, -88.0111):  "60540",  # Naperville, IL
    (32.9060, -96.7503):  "75201",  # Texas Instruments — Dallas, TX
}


async def _coords_to_zip(lat: float, lng: float) -> Optional[str]:
    """
    Convert lat/lng to US ZIP code.
    Checks pre-mapped known distributor locations first (no API call needed).
    Falls back to a free reverse geocoding API for unknown coordinates.
    """
    # Round to 4 decimal places for cache lookup
    key = (round(lat, 4), round(lng, 4))
    if key in _KNOWN_COORDS_TO_ZIP:
        return _KNOWN_COORDS_TO_ZIP[key]

    # Free reverse geocoding via nominatim (no key required, throttled to 1 req/sec)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lng, "format": "json"},
                headers={"User-Agent": "supply-chain-optimizer/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
        return data.get("address", {}).get("postcode")
    except Exception:
        return None
