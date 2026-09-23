import json
from datetime import timedelta
from sqlalchemy import select
from cryptography.fernet import Fernet
import pytest
from fastapi import HTTPException
from app.core.config import settings
from app.db.database import utcnow
from app.db.models import GoogleCalendarConnection, User, CalendarEvent
from app.integrations.google_calendar import GoogleCalendarService
from app.services.application import Application


@pytest.fixture
def google_config(monkeypatch):
    config = settings()
    monkeypatch.setattr(config, "google_client_id", "test-only-client")
    monkeypatch.setattr(config, "google_client_secret", "test-only-secret")
    monkeypatch.setattr(config, "token_encryption_key", Fernet.generate_key().decode())
    return config


def test_oauth_state_bound_to_user(authenticated, google_config):
    c = authenticated
    response = c.post("/api/calendar/google/connect")
    assert response.status_code == 200
    assert "accounts.google.com" in response.json()["url"]
    assert c.get("/api/calendar/google/callback?state=invented&code=bad").status_code == 400
    assert c.get("/api/calendar/google/status").json()["connected"] is False


def test_sync_all_day_pagination_and_removal(authenticated, database, google_config, monkeypatch):
    with database() as db:
        user = db.scalar(select(User))
        tokens = {"access_token": "test-only", "expires_at": utcnow().timestamp() + 3600}
        db.add(
            GoogleCalendarConnection(
                user_id=user.id,
                encrypted_tokens=Fernet(google_config.token_encryption_key.encode())
                .encrypt(json.dumps(tokens).encode())
                .decode(),
            )
        )
        db.commit()
        service = GoogleCalendarService(Application(db, user))
        day = (utcnow() + timedelta(days=1)).date()
        pages = iter(
            [
                {
                    "items": [
                        {
                            "id": "external-one",
                            "summary": "All day",
                            "start": {"date": day.isoformat()},
                            "end": {"date": (day + timedelta(days=1)).isoformat()},
                        }
                    ],
                    "timeZone": "America/New_York",
                    "nextPageToken": "next",
                },
                {"items": [], "timeZone": "America/New_York"},
            ]
        )
        monkeypatch.setattr(service, "request", lambda *args, **kwargs: next(pages))
        assert service.sync()["imported"] == 1
        event = db.scalar(select(CalendarEvent))
        assert event.start_time.hour in {4, 5}
        assert event.source == "google"
        monkeypatch.setattr(
            service, "request", lambda *args, **kwargs: {"items": [], "timeZone": "America/New_York"}
        )
        assert service.sync()["imported"] == 0
        assert db.scalar(select(CalendarEvent)) is None


def test_missing_google_config_is_graceful(authenticated, monkeypatch):
    monkeypatch.setattr(settings(), "google_client_id", "")
    assert authenticated.post("/api/calendar/google/connect").status_code == 503


def test_token_ciphertext_failure_is_safe(authenticated, database, google_config):
    with database() as db:
        user = db.scalar(select(User))
        db.add(GoogleCalendarConnection(user_id=user.id, encrypted_tokens="invalid"))
        db.commit()
        with pytest.raises(HTTPException) as error:
            GoogleCalendarService(Application(db, user)).token()
        assert error.value.status_code == 409
