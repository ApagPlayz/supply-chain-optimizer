
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import TokenResponse, UserLogin, UserRegister, UserResponse
from app.core.database import get_db
from app.core.security import create_access_token, decode_token, get_password_hash, verify_password
from app.models import CartItem, Order, User

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


# ── Demo sessions ─────────────────────────────────────────────────────────────
#
# `POST /auth/demo` used to log EVERY visitor into the single row
# `demo@example.com` (id 1). The cart is keyed on `cart_items.user_id`, so every
# recruiter clicking "Try the demo" at the same time shared one cart: parts
# appeared and vanished under each other, and one person's "Clear cart" emptied
# somebody else's basket mid-click.
#
# The fix keeps `demo@example.com` but demotes it to a TEMPLATE that is never
# handed out. Each demo login mints its own ephemeral user
# `demo+<16 hex>@example.com` and copies the template's cart into it, so every
# visitor gets a private, identically-seeded starting cart. The token format is
# unchanged (`sub` = a real users.id), so existing sessions — demo or real — keep
# working and nobody is logged out.
DEMO_TEMPLATE_EMAIL = "demo@example.com"
DEMO_SESSION_EMAIL_PREFIX = "demo+"
DEMO_SESSION_EMAIL_DOMAIN = "@example.com"
DEMO_SESSION_EMAIL_PATTERN = f"{DEMO_SESSION_EMAIL_PREFIX}%{DEMO_SESSION_EMAIL_DOMAIN}"

#: Demo profile, shared by the template and every session cloned from it.
DEMO_FACTORY_NAME = "Greenville Advanced Manufacturing"
DEMO_FACTORY_LAT = 34.8526    # Greenville, SC
DEMO_FACTORY_LNG = -82.3940

#: How long an ephemeral demo user survives before it is swept. Long enough that
#: nobody's browsing session is deleted underneath them, short enough that the
#: table does not grow without bound. The sweep runs on demo login, so it costs
#: one indexed query on a path that is already writing.
DEMO_SESSION_TTL = timedelta(hours=24)


def _ensure_demo_template(db: Session) -> User:
    """Return the demo TEMPLATE user, creating/refreshing it if needed.

    This row is the source of the starting cart. It is never issued as a session.
    """
    user = db.query(User).filter(User.email == DEMO_TEMPLATE_EMAIL).first()
    if not user:
        # D-16: Create AND persist the demo user
        user = User(
            email=DEMO_TEMPLATE_EMAIL,
            password_hash=get_password_hash("demo"),
            factory_name=DEMO_FACTORY_NAME,
            latitude=DEMO_FACTORY_LAT,
            longitude=DEMO_FACTORY_LNG,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            # Two visitors hitting "Try the demo" in the same instant both find no
            # template and both insert one; the unique index on users.email lets
            # exactly one win. The loser adopts the winner's row rather than 500ing.
            db.rollback()
            user = db.query(User).filter(User.email == DEMO_TEMPLATE_EMAIL).one()
        db.refresh(user)
    else:
        # D-15: Update fields with a single commit, no redundant db.add
        user.factory_name = DEMO_FACTORY_NAME
        user.latitude = DEMO_FACTORY_LAT
        user.longitude = DEMO_FACTORY_LNG
        db.commit()
        db.refresh(user)
    return user


def prune_expired_demo_sessions(db: Session, now: datetime | None = None) -> int:
    """Delete demo sessions older than ``DEMO_SESSION_TTL`` and their rows.

    `cart_items` / `orders` declare `ondelete="CASCADE"`, but SQLite only honours
    that with `PRAGMA foreign_keys=ON` per connection — which this app does not
    set — so the child rows are deleted explicitly rather than hopefully.

    Returns the number of demo users removed. The template is never touched.
    """
    cutoff = (now or datetime.utcnow()) - DEMO_SESSION_TTL
    stale_ids = [
        row[0]
        for row in db.query(User.id)
        .filter(
            User.email.like(DEMO_SESSION_EMAIL_PATTERN),
            # A demo row with no created_at predates the column's default and is,
            # by definition, not from a live session.
            or_(User.created_at < cutoff, User.created_at.is_(None)),
        )
        .all()
    ]
    if not stale_ids:
        return 0

    db.query(CartItem).filter(CartItem.user_id.in_(stale_ids)).delete(synchronize_session=False)
    db.query(Order).filter(Order.user_id.in_(stale_ids)).delete(synchronize_session=False)
    db.query(User).filter(User.id.in_(stale_ids)).delete(synchronize_session=False)
    db.commit()
    return len(stale_ids)


def _clone_cart(db: Session, source_user_id: int, target_user_id: int) -> int:
    """Copy every cart line from one user to another. Returns lines copied."""
    rows = db.query(CartItem).filter(CartItem.user_id == source_user_id).all()
    for row in rows:
        db.add(
            CartItem(
                user_id=target_user_id,
                component_id=row.component_id,
                distributor_id=row.distributor_id,
                quantity=row.quantity,
                unit_price=row.unit_price,
            )
        )
    if rows:
        db.commit()
    return len(rows)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Reusable dependency: decode Bearer token → User row."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token_data = decode_token(credentials.credentials)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == token_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/register", response_model=TokenResponse)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """Register a new factory manager."""
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    if not (24 <= user_data.latitude <= 49 and -125 <= user_data.longitude <= -66):
        raise HTTPException(status_code=400, detail="Factory location must be in United States")

    db_user = User(
        email=user_data.email,
        password_hash=get_password_hash(user_data.password),
        factory_name=user_data.factory_name,
        latitude=user_data.latitude,
        longitude=user_data.longitude,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return {"access_token": create_access_token({"sub": str(db_user.id)})}


@router.post("/login", response_model=TokenResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """Login and return JWT token."""
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"access_token": create_access_token({"sub": str(user.id)})}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    """Return current authenticated user profile."""
    return current_user


@router.post("/demo", response_model=TokenResponse)
def demo_login(db: Session = Depends(get_db)):
    """Start a PRIVATE demo session.

    Every call mints its own ephemeral user, so two recruiters clicking "Try the
    demo" at the same moment get two independent carts. The token is an ordinary
    access token for that user, so the session survives refreshes and deep links
    for as long as the browser holds it.
    """
    template = _ensure_demo_template(db)
    prune_expired_demo_sessions(db)

    # 16 hex chars = 64 bits; collisions on the unique email index are not a
    # practical concern, and a collision would surface as a clean 500 rather than
    # silently reusing somebody else's cart.
    session_id = secrets.token_hex(8)
    session_user = User(
        email=f"{DEMO_SESSION_EMAIL_PREFIX}{session_id}{DEMO_SESSION_EMAIL_DOMAIN}",
        # Deliberately unguessable and never shown: a demo session is reachable
        # only through the token this endpoint returns, not via /auth/login.
        password_hash=get_password_hash(secrets.token_urlsafe(32)),
        factory_name=DEMO_FACTORY_NAME,
        latitude=DEMO_FACTORY_LAT,
        longitude=DEMO_FACTORY_LNG,
    )
    db.add(session_user)
    db.commit()
    db.refresh(session_user)

    # Each visitor starts from the same curated BOM (seeds/seed_demo_cart.py
    # populates the template) but owns their copy of it.
    _clone_cart(db, template.id, session_user.id)

    return {"access_token": create_access_token({"sub": str(session_user.id)})}
