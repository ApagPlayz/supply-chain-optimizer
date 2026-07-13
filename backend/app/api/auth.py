
from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.schemas import TokenResponse, UserLogin, UserRegister, UserResponse
from app.core.database import get_db
from app.core.security import create_access_token, decode_token, get_password_hash, verify_password
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


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
    """Quick demo login with temporary account."""
    demo_email = "demo@example.com"
    user = db.query(User).filter(User.email == demo_email).first()

    if not user:
        # D-16: Create AND persist the demo user
        user = User(
            email=demo_email,
            password_hash=get_password_hash("demo"),
            factory_name="Greenville Advanced Manufacturing",
            latitude=34.8526,   # Greenville, SC
            longitude=-82.3940,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # D-15: Update fields with a single commit, no redundant db.add
        user.factory_name = "Greenville Advanced Manufacturing"
        user.latitude = 34.8526
        user.longitude = -82.3940
        db.commit()
        db.refresh(user)

    return {"access_token": create_access_token({"sub": str(user.id)})}
