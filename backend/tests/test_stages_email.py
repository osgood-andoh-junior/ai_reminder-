from datetime import datetime, timedelta, timezone
from sqlalchemy import select
import pytest
from app import schemas
from app.db.database import utcnow
from app.db.models import User, Task, ScheduledTask, Reminder, NotificationDelivery
from app.services.application import Application
from app.notifications.stages import STAGES, stage_times, session_reminders
from app.notifications.service import publish_due, process_outbox
from app.notifications.email import EmailNotificationChannel
from app.notifications.push import DeliveryError
from app.core.config import settings


def test_offsets_timezone_short_and_past():
    start = datetime(2030, 1, 1, 15, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    now = start - timedelta(hours=3)
    values = stage_times(start, start + timedelta(hours=2), STAGES, now)
    assert [int((value - start).total_seconds() / 60) for value in values.values()] == [-60, -30, -5, 10, 110]
    assert all(value.utcoffset() == timedelta(0) for value in values.values())
    assert set(stage_times(start, start + timedelta(minutes=5), STAGES, now)) == {
        "BEFORE_60",
        "BEFORE_30",
        "BEFORE_5",
    }
    assert set(stage_times(start, start + timedelta(hours=2), STAGES, start)) == {"AFTER_10", "END_10"}
    with pytest.raises(ValueError):
        stage_times(start.replace(tzinfo=None), start, STAGES)


def setup_session(db):
    user = db.scalar(select(User))
    service = Application(db, user)
    task = Task(user_id=user.id, title="DSP", status="SCHEDULED")
    db.add(task)
    db.flush()
    start = utcnow() + timedelta(hours=3)
    session = ScheduledTask(
        user_id=user.id, task_id=task.id, start_time=start, end_time=start + timedelta(hours=2)
    )
    db.add(session)
    db.flush()
    session_reminders(service, task, session)
    db.commit()
    return service, task, session


def test_reconcile_reschedule_history_and_completion(authenticated, database):
    with database() as db:
        service, task, session = setup_session(db)
        session_reminders(service, task, session)
        reminders = list(db.scalars(select(Reminder).order_by(Reminder.id)))
        assert len(reminders) == 5
        delivered = reminders[0]
        delivered.status, delivered.sent_at = "SENT", utcnow()
        old_time = delivered.reminder_time
        new_start = session.start_time + timedelta(hours=1)
        service.apply_schedule(
            {
                "task_id": task.id,
                "slots": [
                    {"start": new_start.isoformat(), "end": (new_start + timedelta(hours=2)).isoformat()}
                ],
            },
            1,
        )
        assert delivered.status == "SENT" and delivered.reminder_time == old_time
        assert len(list(db.scalars(select(Reminder)))) == 5
        assert reminders[1].reminder_time == new_start - timedelta(minutes=30)
        service.update_task(task.id, schemas.TaskPatch(status="COMPLETED"))
        assert delivered.status == "SENT"
        assert all(r.status == "CANCELLED" for r in reminders[1:])


def test_preferences_overrides_and_authorization(authenticated, database):
    with database() as db:
        _, task, _ = setup_session(db)
        ident = task.id
    result = authenticated.patch(
        f"/api/tasks/{ident}/reminder-preferences",
        json={"reminder_stages": ["BEFORE_5"], "email_reminders_enabled": False},
    )
    assert result.status_code == 200
    assert len([r for r in authenticated.get("/api/reminders").json() if r["status"] == "PENDING"]) == 1
    assert (
        authenticated.patch(
            "/api/preferences/notifications", json={"reminder_stages": ["INVALID"]}
        ).status_code
        == 422
    )
    authenticated.post("/api/auth/logout")
    authenticated.post(
        "/api/auth/register",
        json={"name": "Other", "email": "other@example.com", "password": "another-secure-password"},
    )
    assert (
        authenticated.patch(
            f"/api/tasks/{ident}/reminder-preferences", json={"reminder_stages": []}
        ).status_code
        == 404
    )
    assert authenticated.get("/api/preferences").json()["reminder_stages"] == list(STAGES)


class FakeEmail:
    def __init__(self):
        self.calls = []
        self.fail = True

    def send_reminder(self, payload, key):
        self.calls.append((payload, key))
        if self.fail:
            raise DeliveryError("email_network")


@pytest.mark.parametrize("enabled,override,expected", [(True, None, 1), (False, None, 0), (True, False, 0)])
def test_email_preferences_retry_idempotency(authenticated, database, enabled, override, expected):
    with database() as db:
        service, task, _ = setup_session(db)
        service.preferences().email_notifications_enabled = enabled
        task.email_reminders_enabled = override
        reminder = db.scalar(select(Reminder))
        reminder.reminder_time = utcnow() - timedelta(seconds=1)
        now = utcnow()
        assert publish_due(db, now) == 1
        db.commit()
        assert publish_due(db, now) == 0
        deliveries = list(db.scalars(select(NotificationDelivery)))
        assert len(deliveries) == expected
        if not expected:
            return
        fake = FakeEmail()
        assert process_outbox(db, now=now, email_channel=fake) == 0
        assert deliveries[0].status == "RETRY"
        fake.fail = False
        assert process_outbox(db, now=now + timedelta(minutes=1), email_channel=fake) == 1
        assert process_outbox(db, now=now + timedelta(minutes=2), email_channel=fake) == 0
        assert fake.calls[0] == fake.calls[1]
        assert fake.calls[0][0]["to"] == ["test@example.com"]


def test_unconfigured_email_and_expired_retry(authenticated, database, monkeypatch):
    monkeypatch.setattr(settings(), "email_provider", "")
    monkeypatch.setattr(settings(), "openai_api_key", "")
    with database() as db:
        service, _, _ = setup_session(db)
        service.preferences().email_notifications_enabled = True
        db.scalar(select(Reminder)).reminder_time = utcnow() - timedelta(seconds=1)
        publish_due(db)
        db.commit()
        assert process_outbox(db) == 0
        item = db.scalar(select(NotificationDelivery))
        assert item.last_error == "email_not_configured"
        assert db.scalar(select(Reminder)).status == "SENT"
        item.status = "RETRY"
        item.next_attempt_at = utcnow() - timedelta(seconds=1)
        item.retry_deadline = utcnow() - timedelta(seconds=1)
        db.commit()
        fake = FakeEmail()
        process_outbox(db, email_channel=fake)
        assert item.last_error == "email_retry_window_expired" and not fake.calls


def test_email_transport(monkeypatch):
    import httpx

    monkeypatch.setattr(settings(), "email_provider", "resend")
    monkeypatch.setattr(settings(), "email_from", "Tempo <reminders@example.com>")
    monkeypatch.setattr(settings(), "resend_api_key", "test-only")
    captured = []

    def post(url, **kwargs):
        captured.append((url, kwargs))
        return httpx.Response(200, json={"id": "test"})

    monkeypatch.setattr(httpx, "post", post)
    EmailNotificationChannel().send_reminder({"to": ["test@example.com"]}, "stable-key")
    assert captured[0][1]["headers"]["Idempotency-Key"] == "stable-key"


@pytest.mark.parametrize("status, retryable", [(429, True), (503, True), (401, False), (422, False)])
def test_email_http_failure(monkeypatch, status, retryable):
    import httpx

    monkeypatch.setattr(settings(), "email_provider", "resend")
    monkeypatch.setattr(settings(), "email_from", "reminders@example.com")
    monkeypatch.setattr(settings(), "resend_api_key", "test")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(status))
    with pytest.raises(DeliveryError) as error:
        EmailNotificationChannel().send_reminder({}, "key")
    assert error.value.retryable == retryable


@pytest.mark.parametrize("action", ["cancel", "delete", "complete_session", "disable_email", "reschedule"])
def test_obsolete_outbox_never_sends(authenticated, database, action):
    with database() as db:
        service, task, session = setup_session(db)
        service.preferences().email_notifications_enabled = True
        reminder = db.scalar(select(Reminder))
        reminder.reminder_time = utcnow() - timedelta(seconds=1)
        publish_due(db)
        db.commit()
        if action == "cancel":
            service.update_task(task.id, schemas.TaskPatch(status="CANCELLED"))
        elif action == "delete":
            service.delete_task(task.id)
        elif action == "complete_session":
            service.session_status(session.id, "COMPLETED")
        elif action == "disable_email":
            service.task_reminder_preferences(
                task.id, schemas.TaskReminderPreferences(email_reminders_enabled=False)
            )
        else:
            start = session.start_time + timedelta(hours=1)
            service.apply_schedule(
                {
                    "task_id": task.id,
                    "slots": [{"start": start.isoformat(), "end": (start + timedelta(hours=2)).isoformat()}],
                },
                1,
            )
        db.commit()
        fake = FakeEmail()
        assert process_outbox(db, email_channel=fake) == 0
        assert not fake.calls


def test_task_override_requires_proposal_confirmation(authenticated, database):
    from app.agent.tools import Registry

    with database() as db:
        service, task, _ = setup_session(db)
        registry = Registry(service)
        registry.execute("get_tasks", {})
        proposal = registry.execute(
            "configure_task_reminders",
            {"id": task.id, "changes": {"reminder_stages": ["BEFORE_30", "BEFORE_5"]}},
        )
        assert task.reminder_stages is None
        service.decide(proposal["id"], True)
        assert task.reminder_stages == ["BEFORE_30", "BEFORE_5"]


def test_in_app_disabled_does_not_disable_email(authenticated, database):
    with database() as db:
        service, _, _ = setup_session(db)
        service.preferences().in_app_notifications_enabled = False
        service.preferences().email_notifications_enabled = True
        db.scalar(select(Reminder)).reminder_time = utcnow() - timedelta(seconds=1)
        publish_due(db)
        db.commit()
        fake = FakeEmail()
        fake.fail = False
        assert process_outbox(db, email_channel=fake) == 1
    assert authenticated.get("/api/reminders/unread-count").json() == {"count": 0}
    assert authenticated.get("/api/reminders/recent").json() == []


def test_worker_email_claim_and_crash_recovery(authenticated, database):
    from concurrent.futures import ThreadPoolExecutor

    with database() as db:
        service, _, _ = setup_session(db)
        service.preferences().email_notifications_enabled = True
        db.scalar(select(Reminder)).reminder_time = utcnow() - timedelta(seconds=1)
        publish_due(db)
        db.commit()
        item = db.scalar(select(NotificationDelivery))
        saved_key, saved_payload = item.idempotency_key, item.payload
        # Simulate provider acceptance followed by a worker crash before committing SENT.
        item.status, item.lease_until = "PROCESSING", utcnow() - timedelta(seconds=1)
        db.commit()
    fake = FakeEmail()
    fake.fail = False

    def run(_):
        with database() as db:
            return process_outbox(db, email_channel=fake)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(run, range(2))) == 1
    assert fake.calls == [(saved_payload, saved_key)]


def test_actual_worker_email_without_openai(authenticated, database, monkeypatch):
    from app.worker import process_due

    fake = FakeEmail()
    fake.fail = False
    monkeypatch.setattr(settings(), "ai_enabled", False)
    monkeypatch.setattr(
        EmailNotificationChannel, "send_reminder", lambda self, payload, key: fake.send_reminder(payload, key)
    )
    with database() as db:
        service, _, _ = setup_session(db)
        service.preferences().email_notifications_enabled = True
        db.scalar(select(Reminder)).reminder_time = utcnow() - timedelta(seconds=1)
        db.commit()
        assert process_due(db) == 1
        assert process_due(db) == 0
    assert len(fake.calls) == 1
