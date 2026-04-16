"""Tests for HARD-06: Demo login idempotency — both new-user and existing-user paths."""


def test_demo_login_first_call_creates_user(client):
    """First demo login creates a new user and returns a valid token."""
    r = client.post("/api/v1/auth/demo")
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert len(body["access_token"]) > 20  # JWT is not empty/None


def test_demo_login_returns_valid_token_with_real_user_id(client):
    """Token sub claim must be a numeric user ID, not 'None'."""
    r = client.post("/api/v1/auth/demo")
    assert r.status_code == 200
    token = r.json()["access_token"]
    from app.core.security import decode_token
    payload = decode_token(token)
    assert payload is not None
    assert payload.user_id is not None
    assert str(payload.user_id) != "None"


def test_demo_login_second_call_succeeds(client):
    """Repeated demo login on existing user does not raise errors."""
    r1 = client.post("/api/v1/auth/demo")
    assert r1.status_code == 200
    r2 = client.post("/api/v1/auth/demo")
    assert r2.status_code == 200


def test_demo_login_idempotent_user(client, db_session):
    """Multiple demo logins create exactly one user row."""
    from app.models.user import User
    client.post("/api/v1/auth/demo")
    client.post("/api/v1/auth/demo")
    client.post("/api/v1/auth/demo")
    count = db_session.query(User).filter(User.email == "demo@example.com").count()
    assert count == 1


def test_demo_login_token_allows_authenticated_access(client):
    """Token from demo login can access authenticated endpoints."""
    r = client.post("/api/v1/auth/demo")
    token = r.json()["access_token"]
    r2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.json()["email"] == "demo@example.com"
