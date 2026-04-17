"""
Feed fetcher functions. Each returns the parsed payload or raises on failure.
Stubs are implemented by Plans 03-02 and 03-03.
"""
import logging

logger = logging.getLogger(__name__)


async def fetch_gpr() -> float:
    raise NotImplementedError("GPR fetcher — implemented in Plan 03-02")


async def fetch_acled(email: str, key: str) -> dict[str, int]:
    raise NotImplementedError("ACLED fetcher — implemented in Plan 03-02")


async def fetch_portwatch() -> dict[str, float]:
    raise NotImplementedError("PortWatch fetcher — implemented in Plan 03-03")


async def fetch_fred_freight(api_key: str) -> float:
    raise NotImplementedError("FRED freight fetcher — implemented in Plan 03-03")
