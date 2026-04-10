"""
Ten real US freight hubs used as cross-dock consolidation candidates.

All coordinates verified against public airport/terminal databases. See
spec §5.5 for citations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class FreightHub:
    id: int
    name: str
    operator: str
    hub_type: str  # 'air', 'intermodal', 'marine/rail', 'air/intermodal'
    city: str
    state: str
    latitude: float
    longitude: float


FREIGHT_HUBS: List[FreightHub] = [
    FreightHub(1, "Memphis International SuperHub", "FedEx Express", "air",
               "Memphis", "TN", 35.0424, -89.9767),
    FreightHub(2, "UPS Worldport", "UPS", "air",
               "Louisville", "KY", 38.1744, -85.7360),
    FreightHub(3, "DFW Alliance Global Logistics Center", "BNSF/Hillwood", "intermodal",
               "Fort Worth", "TX", 32.9876, -97.3187),
    FreightHub(4, "CenterPoint Intermodal Center-Joliet", "BNSF", "intermodal",
               "Joliet", "IL", 41.4988, -87.9865),
    FreightHub(5, "Hartsfield-Jackson Cargo", "Multiple", "air",
               "Atlanta", "GA", 33.6407, -84.4277),
    FreightHub(6, "Port of Long Beach Intermodal", "Multiple", "marine/rail",
               "Long Beach", "CA", 33.7406, -118.2757),
    FreightHub(7, "Rickenbacker Intermodal Terminal", "Norfolk Southern", "intermodal",
               "Columbus", "OH", 39.8130, -82.9279),
    FreightHub(8, "Kansas City SmartPort", "BNSF/KCS", "intermodal",
               "Kansas City", "MO", 39.2976, -94.7139),
    FreightHub(9, "FedEx Indianapolis Hub", "FedEx Express", "air",
               "Indianapolis", "IN", 39.7173, -86.2944),
    FreightHub(10, "Ontario International Intermodal", "Multiple", "air/intermodal",
               "Ontario", "CA", 34.0559, -117.6005),
]


def get_hub(hub_id: int) -> FreightHub:
    for h in FREIGHT_HUBS:
        if h.id == hub_id:
            return h
    raise KeyError(f"No freight hub with id={hub_id}")
