from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from base64 import urlsafe_b64encode
import pytest
from sqlalchemy import select, func
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from app.db.database import utcnow
from app.db.models import (
    Reminder,
    UserPreference,
    PushSubscription,
    NotificationDelivery,
    UserActivity,
    ScheduledTask,
)
from app.notifications.service import publish_due, process_outbox
from app.notifications.push import DeliveryError, validate_subscription
from app.core.config import settings
from app.worker import process_due


def create(client, **values):
    payload = {
        "title": "Study",
        "message": "A test reminder",
        "reminder_time": (utcnow() + timedelta(minutes=2)).isoformat(),
        **values,
    }
    result = client.post("/api/reminders", json=payload)
    assert result.status_code == 201, result.text
    return result.json()


def make_due(database, ident):
    with database() as db:
        db.get(Reminder, ident).reminder_time = utcnow() - timedelta(minutes=1)
        db.commit()


def subscription_data():
    key = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )
    return {
        "endpoint": "https://fcm.googleapis.com/fcm/send/test-only",
        "keys": {
            "p256dh": urlsafe_b64encode(key).decode().rstrip("="),
            "auth": urlsafe_b64encode(b"a" * 16).decode().rstrip("="),
        },
    }


def enable_push(client, monkeypatch):
    for field in ["vapid_public_key", "vapid_private_key", "vapid_subject"]:
        monkeypatch.setattr(settings(), field, "test-only")
    response = client.post("/api/notifications/subscriptions", json=subscription_data())
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_due_future_read_snooze_dismiss(authenticated, database):
    r = create(authenticated)
    with database() as db:
        assert process_due(db) == 0
    make_due(database, r["id"])
    with database() as db:
        assert process_due(db) == 1
        assert process_due(db) == 0
    assert authenticated.get("/api/reminders/unread-count").json()["count"] == 1
    assert authenticated.post(f"/api/reminders/{r['id']}/read").json()["read_at"]
    assert authenticated.get("/api/reminders/unread-count").json()["count"] == 0
    snoozed = authenticated.post(f"/api/reminders/{r['id']}/snooze", json={"minutes": 1}).json()
    assert snoozed["status"] == "SNOOZED" and snoozed["generation"] == 1
    with database() as db:
        assert process_due(db) == 0
        db.get(Reminder, r["id"]).snoozed_until = utcnow() - timedelta(seconds=1)
        db.commit()
        assert process_due(db) == 1
    result = authenticated.post(f"/api/reminders/{r['id']}/dismiss").json()
    assert result["dismissed_at"] and result["status"] == "DISMISSED"
    assert authenticated.post(f"/api/reminders/{r['id']}/snooze", json={"minutes": 10}).status_code == 409
    with database() as db:
        assert process_due(db) == 0
        actions = list(db.scalars(select(UserActivity.action)))
        assert actions.count("REMINDER_SENT") == 2
        assert {"REMINDER_READ", "REMINDER_DISMISSED", "REMINDER_SNOOZED"} <= set(actions)


def test_timezone_and_invalid_time(authenticated):
    future = (utcnow() + timedelta(days=1)).astimezone(
        __import__("datetime").timezone(timedelta(hours=5, minutes=30))
    )
    item = create(authenticated, reminder_time=future.isoformat())
    assert item["reminder_time"].endswith("+00:00") or item["reminder_time"].endswith("+05:30")
    loaded = authenticated.get(f"/api/reminders/{item['id']}").json()
    assert loaded["reminder_time"].endswith("+00:00")
    assert (
        authenticated.post(
            f"/api/reminders/{item['id']}/snooze", json={"until": "2030-01-01T08:00:00"}
        ).status_code
        == 422
    )
    assert authenticated.post(f"/api/reminders/{item['id']}/read").status_code == 409


def test_user_isolation(authenticated, monkeypatch):
    item = create(authenticated)
    sub = enable_push(authenticated, monkeypatch)
    authenticated.post("/api/auth/logout")
    authenticated.post(
        "/api/auth/register",
        json={"name": "Other", "email": "other@example.com", "password": "another-safe-password"},
    )
    for suffix in ["", "/deliveries"]:
        assert authenticated.get(f"/api/reminders/{item['id']}{suffix}").status_code == 404
    for action in ["read", "dismiss", "snooze"]:
        assert (
            authenticated.post(
                f"/api/reminders/{item['id']}/{action}", json={"minutes": 10} if action == "snooze" else None
            ).status_code
            == 404
        )
    assert authenticated.delete(f"/api/notifications/subscriptions/{sub}").status_code == 404
    assert authenticated.post("/api/notifications/subscriptions", json=subscription_data()).status_code == 409
    assert authenticated.get("/api/notifications/subscriptions").json() == []
    assert authenticated.get("/api/reminders/unread-count").json() == {"count": 0}


class FakePush:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def deliver(self, sub, payload):
        self.calls.append(payload)
        if self.error:
            raise self.error


def prepared_push(client, database, monkeypatch):
    enable_push(client, monkeypatch)
    item = create(client)
    make_due(database, item["id"])
    with database() as db:
        assert publish_due(db) == 1
        db.commit()
    return item


def test_push_retry_and_in_app_survives(authenticated, database, monkeypatch):
    item = prepared_push(authenticated, database, monkeypatch)
    now = utcnow()
    transport = FakePush(DeliveryError("push_network"))
    with database() as db:
        assert process_outbox(db, transport, now) == 0
        delivery = db.scalar(select(NotificationDelivery))
        assert delivery.status == "RETRY" and delivery.attempts == 1
        assert db.get(Reminder, item["id"]).status == "SENT"
        assert process_outbox(db, transport, now) == 0
        transport.error = None
        assert process_outbox(db, transport, now + timedelta(seconds=31)) == 1
        assert process_outbox(db, transport, now + timedelta(minutes=3)) == 0
        assert len(transport.calls) == 2


def test_expired_subscription_deactivated(authenticated, database, monkeypatch):
    prepared_push(authenticated, database, monkeypatch)
    with database() as db:
        process_outbox(db, FakePush(DeliveryError("push_http_410", expired=True, retryable=False)))
        assert not db.scalar(select(PushSubscription)).active
        assert db.scalar(select(NotificationDelivery)).status == "FAILED"
        assert db.scalar(select(Reminder)).status == "SENT"


def test_worker_restart_recovers_lease(authenticated, database, monkeypatch):
    prepared_push(authenticated, database, monkeypatch)
    with database() as db:
        delivery = db.scalar(select(NotificationDelivery))
        delivery.status, delivery.lease_until = "PROCESSING", utcnow() - timedelta(seconds=1)
        db.commit()
        assert process_outbox(db, FakePush()) == 1


def test_snooze_cancels_old_outbox_and_creates_new(authenticated, database, monkeypatch):
    item = prepared_push(authenticated, database, monkeypatch)
    authenticated.post(f"/api/reminders/{item['id']}/snooze", json={"minutes": 1})
    with database() as db:
        transport = FakePush()
        assert process_outbox(db, transport) == 0
        assert db.scalar(select(NotificationDelivery)).status == "CANCELLED"
        db.get(Reminder, item["id"]).snoozed_until = utcnow() - timedelta(seconds=1)
        db.commit()
        assert publish_due(db) == 1
        db.commit()
        assert process_outbox(db, transport) == 1
        assert transport.calls[0]["generation"] == 1


def test_two_workers_only_publish_once(authenticated, database):
    item = create(authenticated)
    make_due(database, item["id"])

    def run(_):
        with database() as db:
            return process_due(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(run, range(2))) == 1
    with database() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(UserActivity).where(UserActivity.action == "REMINDER_SENT")
            )
            == 1
        )


def test_disabled_preferences_prevent_push(authenticated, database, monkeypatch):
    prepared_push(authenticated, database, monkeypatch)
    authenticated.patch("/api/preferences/notifications", json={"browser_notifications_enabled": False})
    with database() as db:
        assert process_outbox(db, FakePush()) == 0
        assert db.scalar(select(NotificationDelivery)).status == "CANCELLED"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/x",
        "https://localhost/x",
        "https://127.0.0.1/x",
        "https://fcm.googleapis.com.evil.com/x",
        "https://fcm.googleapis.com:444/x",
        "https://user@fcm.googleapis.com/x",
    ],
)
def test_push_ssrf_rejected(endpoint):
    with pytest.raises(ValueError):
        validate_subscription(endpoint)


def test_deadline_preferences_and_idempotency(authenticated, database):
    task = authenticated.post(
        "/api/tasks", json={"title": "Deadline test", "deadline": (utcnow() + timedelta(days=3)).isoformat()}
    ).json()
    for _ in range(2):
        assert (
            authenticated.patch(
                "/api/preferences/notifications", json={"deadline_reminders_enabled": True}
            ).status_code
            == 200
        )
    assert len(authenticated.get("/api/reminders").json()) == 2
    authenticated.patch(f"/api/tasks/{task['id']}", json={"status": "COMPLETED"})
    assert all(r["status"] == "CANCELLED" for r in authenticated.get("/api/reminders").json())


def test_relative_session_reminder(authenticated, database):
    task = authenticated.post("/api/tasks", json={"title": "Study"}).json()
    with database() as db:
        user_id = db.scalar(select(UserPreference.user_id))
        start = utcnow() + timedelta(hours=2)
        session = ScheduledTask(
            user_id=user_id, task_id=task["id"], start_time=start, end_time=start + timedelta(hours=1)
        )
        db.add(session)
        db.commit()
        ident = session.id
    result = authenticated.post(
        "/api/reminders", json={"scheduled_task_id": ident, "minutes_before": 30, "message": "Study soon"}
    )
    assert result.status_code == 201, result.text
    from datetime import datetime

    assert datetime.fromisoformat(result.json()["reminder_time"]) == start - timedelta(minutes=30)


def test_local_time_resolution_and_dst():
    from datetime import datetime, timezone
    from fastapi import HTTPException
    from app.notifications.timing import local_reminder_time

    now = datetime(2030, 1, 1, 23, tzinfo=timezone.utc)
    assert local_reminder_time("tomorrow", "08:00", "Africa/Accra", now) == datetime(
        2030, 1, 2, 8, tzinfo=timezone.utc
    )
    assert local_reminder_time("tomorrow", "08:00", "Asia/Kolkata", now) == datetime(
        2030, 1, 3, 2, 30, tzinfo=timezone.utc
    )
    for day in ["2030-03-10", "2030-11-03"]:
        with pytest.raises(HTTPException):
            local_reminder_time(day, "02:30" if "03-10" in day else "01:30", "America/New_York", now)


def test_retry_limit(authenticated, database, monkeypatch):
    prepared_push(authenticated, database, monkeypatch)
    now = utcnow()
    transport = FakePush(DeliveryError("push_network"))
    with database() as db:
        for attempt in range(6):
            process_outbox(db, transport, now + timedelta(hours=attempt))
        item = db.scalar(select(NotificationDelivery))
        assert item.status == "FAILED" and item.attempts == 5
        assert len(transport.calls) == 5


def test_two_workers_only_claim_one_push(authenticated, database, monkeypatch):
    prepared_push(authenticated, database, monkeypatch)
    transport = FakePush()

    def run(_):
        with database() as db:
            return process_outbox(db, transport)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(run, range(2))) == 1
    assert len(transport.calls) == 1


def test_real_push_encryption_and_vapid_signing(monkeypatch):
    from types import SimpleNamespace
    import requests
    from app.notifications.push import PushNotificationChannel, NoRedirectSession

    key = ec.generate_private_key(ec.SECP256R1())
    private = (
        urlsafe_b64encode(
            key.private_bytes(
                serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
        .decode()
        .rstrip("=")
    )
    monkeypatch.setattr(settings(), "vapid_private_key", private)
    monkeypatch.setattr(settings(), "vapid_public_key", "test-public")
    monkeypatch.setattr(settings(), "vapid_subject", "https://example.com")
    captured = []

    def send(self, *args, **kwargs):
        captured.append(kwargs)
        response = requests.Response()
        response.status_code = 201
        response._content = b""
        return response

    monkeypatch.setattr(NoRedirectSession, "post", send)
    data = subscription_data()
    PushNotificationChannel().deliver(
        SimpleNamespace(endpoint=data["endpoint"], **data["keys"]), {"reminder_id": 987}
    )
    assert len(captured) == 1
    assert b"reminder_id" not in captured[0]["data"]
    assert any(k.lower() == "authorization" for k in captured[0]["headers"])
