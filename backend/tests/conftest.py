"""Shared pytest fixtures and path setup."""
import os
import sys
from pathlib import Path

# Ensure `backend/` is on path so `import app.*` works regardless of invocation
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Set a valid SECRET_KEY before importing app (validator will fire at Settings() instantiation)
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-characters-long-for-testing")
os.environ.setdefault("DEBUG", "true")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.database import Base, get_db
from app.models.user import User
from app.core.security import create_access_token, get_password_hash


TEST_DB_URL = "sqlite:///./test_hardening.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=test_engine)
    session = TestSession()
    yield session
    session.close()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db_session):
    def _override():
        try:
            yield db_session
        finally:
            pass
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_token(db_session):
    user = User(
        email="test@example.com",
        password_hash=get_password_hash("testpass"),
        factory_name="Test Factory",
        latitude=34.85,
        longitude=-82.39,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return create_access_token({"sub": str(user.id)})
