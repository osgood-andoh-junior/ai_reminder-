from datetime import timedelta
from urllib.parse import urlsplit
import pytest
from sqlalchemy import select
from app.core.config import settings
from app.core.security import digest
from app.db.database import utcnow
from app.db.models import User, EmailVerification, Reminder, NotificationDelivery
from app.notifications.email import EmailNotificationChannel
from app.notifications.service import publish_due, process_outbox
from app.notifications.push import DeliveryError


@pytest.fixture
def email_transport(monkeypatch):
    calls = []
    monkeypatch.setattr(settings(), "email_provider", "resend")
    monkeypatch.setattr(settings(), "email_from", "Xenon <reminders@example.com>")
    monkeypatch.setattr(settings(), "resend_api_key", "test-only")
    monkeypatch.setattr(
        EmailNotificationChannel, "send_reminder", lambda self, payload, key: calls.append((payload, key))
    )
    return calls


def issue(client, calls):
    assert client.post("/api/auth/email-verification/request").status_code == 200
    url = calls[-1][0]["text"].split("Verify your email: ")[1].split("\n")[0]
    assert not urlsplit(url).query
    return urlsplit(url).fragment.removeprefix("token=")


def test_signup_sends_without_google(client, database, email_transport):
    result = client.post(
        "/api/auth/register",
        json={"name": "New", "email": "NEW@example.com", "password": "a-secure-password"},
    )
    assert result.status_code == 201
    assert result.json()["email"] == "new@example.com"
    assert result.json()["email_verified_at"] is None
    assert len(email_transport) == 1
    with database() as db:
        user = db.scalar(select(User))
        assert user.email_reminders_opted_in_at is None
        assert db.scalar(select(EmailVerification)).delivery_status == "ACCEPTED"
    assert client.get("/api/preferences").json()["email_notifications_enabled"] is False


def test_token_single_use_and_explicit_consent(authenticated, database, email_transport):
    token = issue(authenticated, email_transport)
    with database() as db:
        row = db.scalar(select(EmailVerification))
        assert row.token_hash == digest(token) and row.token_hash != token
        assert db.scalar(select(User)).email_verified_at is None
    assert (
        authenticated.patch(
            "/api/preferences/notifications", json={"email_notifications_enabled": True}
        ).status_code
        == 409
    )
    assert (
        authenticated.post("/api/auth/email-verification/confirm", json={"token": token}).status_code == 200
    )
    assert (
        authenticated.post("/api/auth/email-verification/confirm", json={"token": token}).status_code == 400
    )
    assert authenticated.get("/api/auth/me").json()["email_reminders_opted_in_at"] is None
    assert (
        authenticated.patch(
            "/api/preferences/notifications", json={"email_notifications_enabled": True}
        ).status_code
        == 200
    )
    assert authenticated.get("/api/auth/me").json()["email_reminders_opted_in_at"]
    assert (
        authenticated.patch(
            "/api/preferences/notifications", json={"email_notifications_enabled": False}
        ).status_code
        == 200
    )
    assert authenticated.get("/api/auth/me").json()["email_reminders_opted_in_at"] is None


@pytest.mark.parametrize("mode", ["expired", "invalid", "other_user", "changed_email"])
def test_invalid_tokens(authenticated, database, email_transport, mode):
    token = issue(authenticated, email_transport)
    if mode == "invalid":
        token = "x" * 64
    elif mode == "other_user":
        authenticated.post("/api/auth/logout")
        authenticated.post(
            "/api/auth/register",
            json={"name": "Other", "email": "other@example.com", "password": "a-secure-password"},
        )
    else:
        with database() as db:
            if mode == "expired":
                db.scalar(select(EmailVerification)).expires_at = utcnow() - timedelta(seconds=1)
            else:
                db.scalar(select(User)).email = "changed@example.com"
            db.commit()
    assert (
        authenticated.post("/api/auth/email-verification/confirm", json={"token": token}).status_code == 400
    )
    with database() as db:
        assert all(u.email_verified_at is None for u in db.scalars(select(User)))


def test_rate_limit_and_retry(authenticated, database, email_transport, monkeypatch):
    issue(authenticated, email_transport)
    assert authenticated.post("/api/auth/email-verification/request").status_code == 429
    assert len(email_transport) == 1
    with database() as db:
        db.scalar(select(EmailVerification)).created_at = utcnow() - timedelta(minutes=2)
        db.commit()

    def fail(*args):
        raise DeliveryError("email_network")

    monkeypatch.setattr(EmailNotificationChannel, "send_reminder", fail)
    result = authenticated.post("/api/auth/email-verification/request")
    assert result.status_code == 200 and "could not be delivered" in result.json()["message"]
    with database() as db:
        assert db.scalars(select(EmailVerification.delivery_status)).all() == ["ACCEPTED", "FAILED"]
        assert db.scalar(select(User)).email_verified_at is None


@pytest.mark.parametrize(
    "verified,consent,enabled",
    [(False, True, True), (True, False, True), (True, True, False), (True, True, True)],
)
def test_delivery_gates(authenticated, database, verified, consent, enabled):
    from app.db.models import UserPreference

    calls = []

    class Fake:
        def send_reminder(self, payload, key):
            calls.append(payload)

    with database() as db:
        user = db.scalar(select(User))
        user.email_verified_at = utcnow() if verified else None
        user.email_reminders_opted_in_at = utcnow() if consent else None
        db.scalar(select(UserPreference)).email_notifications_enabled = enabled
        db.add(
            Reminder(
                user_id=user.id,
                reminder_time=utcnow() - timedelta(seconds=1),
                message="Reminder",
                title="Task",
            )
        )
        publish_due(db)
        db.commit()
        process_outbox(db, email_channel=Fake())
        assert len(calls) == int(verified and consent and enabled)
        if calls:
            assert calls[0]["to"] == [user.email]


@pytest.mark.parametrize("change", ["email", "verification", "consent", "preference"])
def test_delivery_rechecks_after_queue(authenticated, database, change):
    from app.db.models import UserPreference

    class Fake:
        def send_reminder(self, payload, key):
            pytest.fail("Ineligible queued email was sent")

    with database() as db:
        user = db.scalar(select(User))
        user.email_verified_at = user.email_reminders_opted_in_at = utcnow()
        preference = db.scalar(select(UserPreference))
        preference.email_notifications_enabled = True
        db.add(
            Reminder(
                user_id=user.id,
                reminder_time=utcnow() - timedelta(seconds=1),
                message="Reminder",
                title="Task",
            )
        )
        publish_due(db)
        db.commit()
        if change == "email":
            user.email = "changed@example.com"
        elif change == "verification":
            user.email_verified_at = None
        elif change == "consent":
            user.email_reminders_opted_in_at = None
        else:
            preference.email_notifications_enabled = False
        db.commit()
        process_outbox(db, email_channel=Fake())
        assert db.scalar(select(NotificationDelivery)).status == "CANCELLED"


def test_hourly_resend_limit(authenticated, database, email_transport):
    with database() as db:
        user = db.scalar(select(User))
        for i in range(5):
            db.add(
                EmailVerification(
                    user_id=user.id,
                    email=user.email,
                    token_hash=digest(str(i)),
                    created_at=utcnow() - timedelta(minutes=2 + i),
                    expires_at=utcnow() + timedelta(minutes=30),
                    delivery_status="FAILED",
                )
            )
        db.commit()
    assert authenticated.post("/api/auth/email-verification/request").status_code == 429
    assert not email_transport


def test_notification_status_is_owned(authenticated, database):
    from app.db.models import UserPreference

    with database() as db:
        other = User(email="other@example.com", name="Other", password_hash="unused")
        db.add(other)
        db.flush()
        db.add(UserPreference(user_id=other.id))
        reminder = Reminder(user_id=other.id, reminder_time=utcnow(), message="Private")
        db.add(reminder)
        db.flush()
        db.add(
            NotificationDelivery(
                user_id=other.id,
                reminder_id=reminder.id,
                channel="email",
                status="FAILED",
                last_error="private_error",
            )
        )
        db.commit()
    assert authenticated.get("/api/notifications/config").json()["email_last_delivery"] is None
