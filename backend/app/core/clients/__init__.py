"""
Live data API clients for the supply chain optimizer.

All clients read credentials from app.core.config.settings.
Keys missing or empty → that client is skipped gracefully.

Clients:
  NexarClient       — Octopart GraphQL, multi-distributor pricing in one call (Nexar covers DigiKey + Mouser + Arrow + Farnell)
  DigiKeyClient     — DigiKey API v4 OAuth2, for lifecycle_status + lead_time_weeks (pricing already in Nexar)
  OEMSecretsClient  — 40+ distributor aggregator in one call, free with approval
  TrustedPartsClient— Authorized-distributor-only results, completely free, feeds counterfeit risk flag
  EasyPostClient    — SmartRate carrier transit days. Fully implemented but NOT WIRED IN: nothing
                      calls it, so the VRP cost matrix always uses the haversine estimate regardless
                      of this key. See easypost_client.py docstring.

REMOVED 2026-09-01: SupplyMavenClient. It POSTed to
https://supplymaven.com/api/v1/tools, which 404s with or without a bearer token
(re-probed 2026-08-30), so it never once returned data. Its only caller was
app/api/market_intelligence.py, whose six `/market/*` routes were removed the
same day; with that gone the client had no caller at all. See
docs/OUTSTANDING_WORK.md item 55.
"""
from .nexar_client import NexarClient
from .digikey_client import DigiKeyClient
from .oemsecrets_client import OEMSecretsClient
from .trustedparts_client import TrustedPartsClient
from .easypost_client import EasyPostClient

__all__ = [
    "NexarClient",
    "DigiKeyClient",
    "OEMSecretsClient",
    "TrustedPartsClient",
    "EasyPostClient",
]
