"""Demo login: token contract, template idempotency, and per-visitor cart isolation.

Originally HARD-06 (demo login idempotency — both new-user and existing-user paths).
Extended for gap 55: `POST /auth/demo` used to hand every visitor the SAME user row,
so the live demo had one shared cart and simultaneous visitors watched each other's
parts appear and disappear. `demo@example.com` is now a template that is never issued;
each login mints its own ephemeral `demo+<hex>@example.com`.
"""
from datetime import datetime, timedelta

from app.api.auth import (
    DEMO_SESSION_EMAIL_DOMAIN,
    DEMO_SESSION_EMAIL_PREFIX,
    DEMO_SESSION_TTL,
    DEMO_TEMPLATE_EMAIL,
    prune_expired_demo_sessions,
)
from app.core.security import decode_token
from app.models.order import CartItem, Order
from app.models.user import User


def _demo_session(client):
    """Log in a fresh demo visitor; return (token, auth headers)."""
    r = client.post("/api/v1/auth/demo")
    assert r.status_code == 200
    token = r.json()["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


def _seed_catalog(db_session):
    """Minimal component/distributor/offer so cart writes are accepted."""
    from app.models.component import Component, DistributorOffer
    from app.models.distributor import Distributor

    db_session.add(Distributor(id=1, name="DigiKey", latitude=48.1, longitude=-96.2,
                               city="Thief River Falls", state="MN", country="USA",
                               is_domestic=True))
    db_session.add(Distributor(id=2, name="Mouser", latitude=32.2, longitude=-97.1,
                               city="Mansfield", state="TX", country="USA",
                               is_domestic=True))
    for i in (1, 2):
        db_session.add(Component(id=i, mpn=f"CART-{i:03d}", manufacturer="TestCo",
                                 category="Microcontrollers", description="x", risk_score=0.3))
        db_session.add(DistributorOffer(id=i, component_id=i, distributor_id=i,
                                        price=1.25, stock=1000, moq=1,
                                        sku=f"SKU-{i}", currency="USD"))
    db_session.commit()


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
    """Multiple demo logins create exactly one TEMPLATE row.

    The template is the source of the starting cart; the per-visitor session rows
    are separate (see the isolation tests below).
    """
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
    # The identity is a per-visitor demo session, NOT the shared template row.
    email = r2.json()["email"]
    assert email.startswith(DEMO_SESSION_EMAIL_PREFIX)
    assert email.endswith(DEMO_SESSION_EMAIL_DOMAIN)
    assert email != DEMO_TEMPLATE_EMAIL
    assert r2.json()["factory_name"] == "Greenville Advanced Manufacturing"


def test_demo_login_token_is_in_the_json_body_not_a_cookie(client):
    """The UI and the API live on different Render origins (supply-chain-ui-* vs
    supply-chain-api-*), so a session cookie set by this endpoint would be a
    third-party cookie — blocked outright by Safari and by Chrome's third-party
    cookie phase-out. The contract the frontend depends on is therefore: the token
    comes back in the JSON body and is replayed as an `Authorization: Bearer`
    header. Lock that in so nobody "improves" this into a Set-Cookie login.
    """
    r = client.post("/api/v1/auth/demo")
    assert r.status_code == 200
    assert r.json()["access_token"]
    assert r.json()["token_type"] == "bearer"
    assert "set-cookie" not in {k.lower() for k in r.headers}


def test_demo_token_authenticates_with_no_cookies_at_all(client):
    """Bearer-only auth must work for a client that stores no cookies whatsoever
    (Safari "Block all cookies", hardened privacy extensions)."""
    token = client.post("/api/v1/auth/demo").json()["access_token"]
    client.cookies.clear()
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"].startswith(DEMO_SESSION_EMAIL_PREFIX)


# ── gap 55: every demo visitor gets their own cart ────────────────────────────
#
# The live demo authenticated every visitor as user id 1, and the cart is keyed on
# `cart_items.user_id`. Two recruiters clicking through at the same time therefore
# shared one basket: parts appeared and vanished under each other, and "Clear cart"
# emptied a stranger's. These tests pin the property that fixes it.


def test_two_demo_sessions_get_different_identities(client):
    _, h1 = _demo_session(client)
    _, h2 = _demo_session(client)
    me1 = client.get("/api/v1/auth/me", headers=h1).json()
    me2 = client.get("/api/v1/auth/me", headers=h2).json()
    assert me1["id"] != me2["id"], "two demo visitors were handed the same user row"
    assert me1["email"] != me2["email"]


def test_demo_carts_are_not_shared_between_sessions(client, db_session):
    """THE regression. Visitor A's cart line must be invisible to visitor B."""
    _seed_catalog(db_session)
    _, h1 = _demo_session(client)
    _, h2 = _demo_session(client)

    added = client.post("/api/v1/cart", json={"component_id": 1, "distributor_id": 1,
                                              "quantity": 10}, headers=h1)
    assert added.status_code == 201

    assert len(client.get("/api/v1/cart", headers=h1).json()) == 1
    assert client.get("/api/v1/cart", headers=h2).json() == [], (
        "visitor B can see visitor A's cart — the demo cart is still shared"
    )


def test_one_demo_session_keeps_its_cart_across_requests(client, db_session):
    """Isolation must not be achieved by throwing the cart away each request."""
    _seed_catalog(db_session)
    _, h = _demo_session(client)

    client.post("/api/v1/cart", json={"component_id": 1, "distributor_id": 1,
                                      "quantity": 10}, headers=h)
    client.post("/api/v1/cart", json={"component_id": 2, "distributor_id": 2,
                                      "quantity": 5}, headers=h)

    for _ in range(3):
        items = client.get("/api/v1/cart", headers=h).json()
        assert {i["component_id"] for i in items} == {1, 2}
        assert {i["quantity"] for i in items} == {10.0, 5.0}


def test_one_demo_session_deleting_does_not_empty_another(client, db_session):
    """`DELETE /cart` (the 'Clear cart' button) must be scoped to the caller."""
    _seed_catalog(db_session)
    _, h1 = _demo_session(client)
    _, h2 = _demo_session(client)

    client.post("/api/v1/cart", json={"component_id": 1, "distributor_id": 1,
                                      "quantity": 10}, headers=h1)
    client.post("/api/v1/cart", json={"component_id": 2, "distributor_id": 2,
                                      "quantity": 7}, headers=h2)

    assert client.delete("/api/v1/cart", headers=h1).status_code == 204
    assert client.get("/api/v1/cart", headers=h1).json() == []
    assert len(client.get("/api/v1/cart", headers=h2).json()) == 1


def test_demo_session_cannot_delete_another_sessions_cart_item(client, db_session):
    _seed_catalog(db_session)
    _, h1 = _demo_session(client)
    _, h2 = _demo_session(client)

    item_id = client.post("/api/v1/cart", json={"component_id": 1, "distributor_id": 1,
                                                "quantity": 10}, headers=h1).json()["id"]

    assert client.delete(f"/api/v1/cart/{item_id}", headers=h2).status_code == 404
    assert len(client.get("/api/v1/cart", headers=h1).json()) == 1


def test_demo_session_never_authenticates_as_the_template_user(client, db_session):
    """The template row is the seed for the starting cart; it is never issued."""
    template = User(email=DEMO_TEMPLATE_EMAIL, password_hash="x",
                    factory_name="t", latitude=34.8, longitude=-82.3)
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)
    template_id = template.id

    for _ in range(3):
        _, h = _demo_session(client)
        assert client.get("/api/v1/auth/me", headers=h).json()["id"] != template_id


def test_demo_session_starts_from_a_copy_of_the_template_cart(client, db_session):
    """Each visitor inherits the curated BOM — as their own rows, not shared ones."""
    _seed_catalog(db_session)
    client.post("/api/v1/auth/demo")  # creates the template
    template = db_session.query(User).filter(User.email == DEMO_TEMPLATE_EMAIL).one()
    db_session.add(CartItem(user_id=template.id, component_id=1, distributor_id=1,
                            quantity=50, unit_price=1.25))
    db_session.commit()

    _, h1 = _demo_session(client)
    _, h2 = _demo_session(client)
    items1 = client.get("/api/v1/cart", headers=h1).json()
    items2 = client.get("/api/v1/cart", headers=h2).json()
    assert len(items1) == 1 and len(items2) == 1
    assert items1[0]["component_id"] == items2[0]["component_id"] == 1
    assert items1[0]["id"] != items2[0]["id"], "both visitors point at the same cart row"

    # And removing it only affects the visitor who removed it.
    assert client.delete(f"/api/v1/cart/{items1[0]['id']}", headers=h1).status_code == 204
    assert len(client.get("/api/v1/cart", headers=h2).json()) == 1


def test_expired_demo_sessions_are_pruned_with_their_rows(client, db_session):
    """Ephemeral users must not accumulate forever in the database.

    Identity is checked by EMAIL, not by id: SQLite hands the next INSERT the
    rowid that the pruned user just vacated, so an id-based assertion here passes
    or fails for reasons that have nothing to do with the sweep.
    """
    _seed_catalog(db_session)
    _, h_old = _demo_session(client)
    old = client.get("/api/v1/auth/me", headers=h_old).json()
    old_id, old_email = old["id"], old["email"]
    cart_id = client.post("/api/v1/cart", json={"component_id": 1, "distributor_id": 1,
                                                "quantity": 10}, headers=h_old).json()["id"]
    order = Order(user_id=old_id, status="pending", total_cost=1.0)
    db_session.add(order)
    db_session.commit()
    order_id = order.id

    # Age it past the TTL.
    db_session.query(User).filter(User.id == old_id).update(
        {"created_at": datetime.utcnow() - DEMO_SESSION_TTL - timedelta(hours=1)}
    )
    db_session.commit()

    # A later visitor's login sweeps it.
    _, h_new = _demo_session(client)
    new_email = client.get("/api/v1/auth/me", headers=h_new).json()["email"]
    db_session.expire_all()

    assert db_session.query(User).filter(User.email == old_email).first() is None
    assert db_session.query(CartItem).filter(CartItem.id == cart_id).first() is None
    assert db_session.query(Order).filter(Order.id == order_id).first() is None
    # The fresh session and the template survive.
    assert new_email != old_email
    assert db_session.query(User).filter(User.email == new_email).first() is not None
    assert db_session.query(User).filter(User.email == DEMO_TEMPLATE_EMAIL).count() == 1


def test_prune_leaves_live_demo_sessions_and_real_users_alone(client, db_session):
    """A sweep must never delete a session someone is still browsing in."""
    real = User(email="real@example.com", password_hash="x", factory_name="Real",
                latitude=34.8, longitude=-82.3,
                created_at=datetime.utcnow() - DEMO_SESSION_TTL - timedelta(days=30))
    db_session.add(real)
    db_session.commit()

    _, h = _demo_session(client)
    live_id = client.get("/api/v1/auth/me", headers=h).json()["id"]

    assert prune_expired_demo_sessions(db_session) == 0
    assert db_session.query(User).filter(User.id == live_id).first() is not None
    assert db_session.query(User).filter(User.email == "real@example.com").first() is not None
    assert client.get("/api/v1/auth/me", headers=h).status_code == 200
