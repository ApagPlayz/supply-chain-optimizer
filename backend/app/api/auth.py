from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas import TokenResponse, UserLogin, UserRegister, UserResponse
from app.core.database import get_db
from app.core.security import create_access_token, decode_token, get_password_hash, verify_password
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """Register a new user (factory manager)."""
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Validate location is in US (simple bounds check)
    if not (24 <= user_data.latitude <= 49 and -125 <= user_data.longitude <= -66):
        raise HTTPException(status_code=400, detail="Factory location must be in United States")

    # Create user
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        email=user_data.email,
        password_hash=hashed_password,
        factory_name=user_data.factory_name,
        latitude=user_data.latitude,
        longitude=user_data.longitude,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    # Generate token
    access_token = create_access_token({"sub": db_user.id})
    return {"access_token": access_token}


@router.post("/login", response_model=TokenResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """Login user and return JWT token."""
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = create_access_token({"sub": user.id})
    return {"access_token": access_token}


@router.get("/me", response_model=UserResponse)
def get_current_user(token: str, db: Session = Depends(get_db)):
    """Get current authenticated user."""
    # In a real app, extract token from Authorization header
    token_data = decode_token(token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == token_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user
