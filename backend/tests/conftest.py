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


@pytest.fixture(autouse=True)
def restore_process_globals():
    """
    GraphState and MLState are process-globals populated by the app lifespan (see the
    `client` fixture, which enters TestClient as a context manager). Once set, helpers
    like resilience._graph() prefer the global over building from the test's session,
    so a leaked global silently makes later tests read the real DB. Snapshot/restore
    keeps the suite order-independent.
    """
    import app.graph as graph
    import app.ml as ml

    prev_graph, prev_ml = graph.get_graph_state(), ml.get_ml_state()
    yield
    graph.set_graph_state(prev_graph)
    ml.set_ml_state(prev_ml)


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


# ── Graph test fixtures ───────────────────────────────────────────────────────

from app.models.distributor import Distributor
from app.models.component import Component, DistributorOffer


@pytest.fixture(scope="function")
def graph_db_session():
    """In-memory SQLite DB seeded with 3 distributors, 10 components, 15 offers."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # 3 distributors
    dists = [
        Distributor(id=1, name="DigiKey", latitude=48.1, longitude=-96.2,
                    city="Thief River Falls", state="MN", country="USA", is_domestic=True),
        Distributor(id=2, name="Mouser", latitude=32.2, longitude=-97.1,
                    city="Mansfield", state="TX", country="USA", is_domestic=True),
        Distributor(id=3, name="LCSC", latitude=22.5, longitude=114.1,
                    city="Shenzhen", state=None, country="China", is_domestic=False),
    ]
    for d in dists:
        session.add(d)

    # 10 components across 2 categories
    comps = []
    for i in range(1, 11):
        cat = "Microcontrollers" if i <= 5 else "Op-Amps"
        c = Component(id=i, mpn=f"TEST-{i:03d}", manufacturer="TestCo",
                      manufacturer_country="USA", category=cat,
                      description=f"Test component {i}", risk_score=0.3)
        comps.append(c)
        session.add(c)

    # 15 offers: components 1-5 have 2 offers each (dist 1+2), components 6-10 have 1 offer each (dist 1)
    offer_id = 1
    for comp_id in range(1, 6):
        for dist_id in [1, 2]:
            session.add(DistributorOffer(
                id=offer_id, component_id=comp_id, distributor_id=dist_id,
                price=1.50 + comp_id * 0.1, stock=100, moq=1,
                sku=f"SKU-{comp_id}-{dist_id}", currency="USD",
            ))
            offer_id += 1
    for comp_id in range(6, 11):
        session.add(DistributorOffer(
            id=offer_id, component_id=comp_id, distributor_id=1,
            price=2.00 + comp_id * 0.1, stock=50, moq=1,
            sku=f"SKU-{comp_id}-1", currency="USD",
        ))
        offer_id += 1

    session.commit()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
