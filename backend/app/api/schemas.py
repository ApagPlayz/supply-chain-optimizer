
from pydantic import BaseModel, EmailStr


class UserRegister(BaseModel):
    """User registration request."""
    email: EmailStr
    password: str
    factory_name: str
    latitude: float
    longitude: float


class UserLogin(BaseModel):
    """User login request."""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """User response model."""
    id: int
    email: str
    factory_name: str
    latitude: float
    longitude: float

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
