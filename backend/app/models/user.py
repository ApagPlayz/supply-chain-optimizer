from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.core.database import Base


class User(Base):
    """Factory/plant manager user model."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    factory_name = Column(String)
    latitude = Column(Float)  # Factory location
    longitude = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<User {self.email}>"
