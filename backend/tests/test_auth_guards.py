"""Tests for HARD-04: All live-price and market-intelligence endpoints require auth."""


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


def test_market_summary_requires_auth(client):
    """GET /api/v1/market/summary returns 401 without token."""
    r = client.get("/api/v1/market/summary")
    assert r.status_code == 401


def test_market_disruption_index_requires_auth(client):
    """GET /api/v1/market/disruption-index returns 401 without token."""
    r = client.get("/api/v1/market/disruption-index")
    assert r.status_code == 401


def test_market_alerts_requires_auth(client):
    """GET /api/v1/market/alerts returns 401 without token."""
    r = client.get("/api/v1/market/alerts")
    assert r.status_code == 401


def test_market_commodities_requires_auth(client):
    """GET /api/v1/market/commodities returns 401 without token."""
    r = client.get("/api/v1/market/commodities")
    assert r.status_code == 401


def test_market_trade_policy_requires_auth(client):
    """GET /api/v1/market/trade-policy returns 401 without token."""
    r = client.get("/api/v1/market/trade-policy")
    assert r.status_code == 401


def test_market_status_requires_auth(client):
    """GET /api/v1/market/status returns 401 without token."""
    r = client.get("/api/v1/market/status")
    assert r.status_code == 401
