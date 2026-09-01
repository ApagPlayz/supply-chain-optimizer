"""Tests for HARD-04: All live-price endpoints require auth.

This file also covered the six `/market/*` routes until 2026-09-01, when those
routes were removed from the API surface (docs/OUTSTANDING_WORK.md item 55).
Their auth guards went with the routes; the six tests were deleted rather than
left asserting 401 on paths that now 404.
"""


def test_live_prices_mpn_requires_auth(client):
    """GET /api/v1/live-prices/TEST-MPN returns 401 without token."""
    r = client.get("/api/v1/live-prices/TEST-MPN")
    assert r.status_code == 401


def test_live_prices_bom_requires_auth(client):
    """POST /api/v1/live-prices/bom returns 401 without token."""
    r = client.post("/api/v1/live-prices/bom", json={"items": [{"mpn": "TEST", "quantity": 1}]})
    assert r.status_code == 401


def test_live_prices_sync_requires_auth(client):
    """POST /api/v1/live-prices/TEST-MPN/sync returns 401 without token."""
    r = client.post("/api/v1/live-prices/TEST-MPN/sync")
    assert r.status_code == 401
