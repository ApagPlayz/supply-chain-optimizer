"""
Live data API clients for the supply chain optimizer.

All clients read credentials from app.core.config.settings.
Keys missing or empty → that client is skipped gracefully.

Clients:
  NexarClient       — Octopart GraphQL, multi-distributor pricing in one call (Nexar covers DigiKey + Mouser + Arrow + Farnell)
  DigiKeyClient     — DigiKey API v4 OAuth2, for lifecycle_status + lead_time_weeks (pricing already in Nexar)
  OEMSecretsClient  — 40+ distributor aggregator in one call, free with approval
  TrustedPartsClient— Authorized-distributor-only results, completely free, feeds counterfeit risk flag
  EasyPostClient    — SmartRate real carrier transit days for VRP cost matrix (replaces haversine)
  SupplyMavenClient — Global Disruption Index + tariff data for Digital Twin scenarios
"""
from .nexar_client import NexarClient
from .digikey_client import DigiKeyClient
from .oemsecrets_client import OEMSecretsClient
from .trustedparts_client import TrustedPartsClient
from .easypost_client import EasyPostClient
from .supplymaven_client import SupplyMavenClient

__all__ = [
    "NexarClient",
    "DigiKeyClient",
    "OEMSecretsClient",
    "TrustedPartsClient",
    "EasyPostClient",
    "SupplyMavenClient",
]
