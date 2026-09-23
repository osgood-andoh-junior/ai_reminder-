import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.db.database import Base, get_db
from app.main import app, requests_by_client


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def client(database):
    def db_override():
        with database() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_db] = db_override
    requests_by_client.clear()
    with TestClient(app, headers={"X-Requested-With": "Tempo"}) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def authenticated(client):
    result = client.post(
        "/api/auth/register",
        json={"name": "Test User", "email": "test@example.com", "password": "a-secure-test-password"},
    )
    assert result.status_code == 201, result.text
    return client
