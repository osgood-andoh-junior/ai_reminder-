"""Transactional in-app delivery and a leased, retryable push/email outbox."""

from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import select, update, or_, and_
from app.db.database import utcnow
from app.db.models import (
    Reminder,
    User,
    UserPreference,
    PushSubscription,
    NotificationDelivery,
    Task,
    ScheduledTask,
)
from app.core.config import settings
from app.notifications.email import EmailNotificationChannel
from app.notifications.in_app import InAppNotifications, record
from app.notifications.push import PushNotificationChannel, DeliveryError


def due(now):
    return or_(
        and_(Reminder.status == "PENDING", Reminder.reminder_time <= now),
        and_(Reminder.status == "SNOOZED", Reminder.snoozed_until <= now),
    )


def publish_due(db, now=None):
    now = now or utcnow()
    candidates = db.execute(
        select(Reminder.id, Reminder.user_id).where(due(now)).order_by(Reminder.id).limit(100)
    ).all()
    count = 0
    # Acquire a stable user order to avoid multi-user deadlocks on PostgreSQL.
    for user_id in sorted({user_id for _, user_id in candidates}):
        db.execute(update(User).where(User.id == user_id).values(revision=User.revision + 1))
    for ident, user_id in candidates:
        reminder = db.scalar(
            select(Reminder).where(Reminder.id == ident, due(now)).execution_options(populate_existing=True)
        )
        if reminder is None:
            continue
        if not active_reminder(db, reminder):
            reminder.status = "CANCELLED"
            continue
        InAppNotifications().deliver(reminder, {"now": now})
        record(db, reminder, "REMINDER_SENT", channel="in_app")
        preference = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
        reminder.in_app_visible = preference.in_app_notifications_enabled
        task = db.get(Task, reminder.task_id, populate_existing=True) if reminder.task_id else None
        user = db.get(User, user_id)
        session = db.get(ScheduledTask, reminder.scheduled_task_id) if reminder.scheduled_task_id else None
        instant = session.start_time if session else reminder.reminder_time
        local_time = instant.astimezone(ZoneInfo(preference.timezone)).strftime("%Y-%m-%d %H:%M %z")
        if (
            user.email_verified_at
            and user.email_reminders_opted_in_at
            and preference.email_notifications_enabled
            and (not task or task.email_reminders_enabled is not False)
        ):
            db.add(
                NotificationDelivery(
                    user_id=user_id,
                    reminder_id=ident,
                    generation=reminder.generation,
                    channel="email",
                    idempotency_key=uuid4().hex,
                    next_attempt_at=now,
                    retry_deadline=now + timedelta(hours=23),
                    payload={
                        "from": settings().email_from,
                        "to": [user.email],
                        "subject": f"Xenon: {reminder.title}",
                        "text": reminder.message
                        + "\nWhen: "
                        + local_time
                        + " ("
                        + preference.timezone
                        + ")"
                        + "\n\nOpen Xenon: "
                        + settings().frontend_url.rstrip("/")
                        + "/reminders",
                    },
                )
            )
        if preference.browser_notifications_enabled:
            for sub in db.scalars(
                select(PushSubscription).where(
                    PushSubscription.user_id == user_id, PushSubscription.active.is_(True)
                )
            ):
                db.add(
                    NotificationDelivery(
                        user_id=user_id,
                        reminder_id=ident,
                        subscription_id=sub.id,
                        generation=reminder.generation,
                        next_attempt_at=now,
                    )
                )
        count += 1
    db.flush()
    return count


def active_reminder(db, reminder):
    if reminder.task_id:
        task = db.get(Task, reminder.task_id, populate_existing=True)
        if not task or task.user_id != reminder.user_id or task.status in {"COMPLETED", "CANCELLED"}:
            return False
    if reminder.scheduled_task_id:
        session = db.get(ScheduledTask, reminder.scheduled_task_id, populate_existing=True)
        if not session or session.user_id != reminder.user_id or session.status != "SCHEDULED":
            return False
    return True


def process_outbox(db, channel=None, now=None, email_channel=None):
    now = now or utcnow()
    channel = channel or PushNotificationChannel()
    email_channel = email_channel or EmailNotificationChannel()
    ready = or_(
        and_(
            NotificationDelivery.status.in_(["PENDING", "RETRY"]), NotificationDelivery.next_attempt_at <= now
        ),
        and_(NotificationDelivery.status == "PROCESSING", NotificationDelivery.lease_until <= now),
    )
    ids = list(
        db.scalars(select(NotificationDelivery.id).where(ready).order_by(NotificationDelivery.id).limit(100))
    )
    delivered = 0
    for ident in ids:
        token = uuid4().hex
        claimed = db.execute(
            update(NotificationDelivery)
            .where(NotificationDelivery.id == ident, ready)
            .values(
                status="PROCESSING",
                lease_token=token,
                lease_until=now + timedelta(minutes=2),
                attempts=NotificationDelivery.attempts + 1,
            )
        ).rowcount
        db.commit()
        if not claimed:
            continue
        item = db.get(NotificationDelivery, ident, populate_existing=True)
        if item is None:
            continue
        db.execute(update(User).where(User.id == item.user_id).values(revision=User.revision + 1))
        db.refresh(item)
        if item.lease_token != token or item.status != "PROCESSING":
            db.commit()
            continue
        reminder = db.get(Reminder, item.reminder_id, populate_existing=True)
        sub = (
            db.get(PushSubscription, item.subscription_id, populate_existing=True)
            if item.subscription_id
            else None
        )
        preference = db.scalar(
            select(UserPreference)
            .where(UserPreference.user_id == item.user_id)
            .execution_options(populate_existing=True)
        )
        user = db.get(User, item.user_id, populate_existing=True)
        if (
            not reminder
            or reminder.user_id != item.user_id
            or not active_reminder(db, reminder)
            or (
                item.channel == "push"
                and (
                    not sub
                    or sub.user_id != item.user_id
                    or not sub.active
                    or not preference.browser_notifications_enabled
                )
            )
            or (
                item.channel == "email"
                and (
                    not user
                    or not user.email_verified_at
                    or not user.email_reminders_opted_in_at
                    or not item.payload
                    or item.payload.get("to") != [user.email]
                    or not preference.email_notifications_enabled
                    or (reminder.task_id and db.get(Task, reminder.task_id).email_reminders_enabled is False)
                )
            )
            or reminder.generation != item.generation
            or reminder.status not in {"SENT", "READ"}
        ):
            item.status = "CANCELLED"
        else:
            try:
                if item.channel == "email":
                    if not item.retry_deadline or now >= item.retry_deadline:
                        raise DeliveryError("email_retry_window_expired", retryable=False)
                    email_channel.send_reminder(item.payload, item.idempotency_key)
                else:
                    channel.deliver(
                        sub,
                        {"reminder_id": reminder.id, "generation": item.generation, "user_id": item.user_id},
                    )
                item.status, item.sent_at, item.last_error = "SENT", now, None
                record(db, reminder, "REMINDER_" + item.channel.upper() + "_ACCEPTED", delivery_id=item.id)
                delivered += 1
            except Exception as exc:
                failure = (
                    exc
                    if isinstance(exc, DeliveryError)
                    else DeliveryError(item.channel + "_internal_error", retryable=False)
                )
                item.last_error = failure.code
                item.status = "RETRY" if failure.retryable and item.attempts < 5 else "FAILED"
                item.next_attempt_at = now + timedelta(seconds=min(30 * 2 ** (item.attempts - 1), 1800))
                if failure.expired and sub:
                    sub.active = False
                record(
                    db,
                    reminder,
                    "REMINDER_FAILED",
                    channel=item.channel,
                    delivery_id=item.id,
                    code=failure.code,
                    retry=item.status == "RETRY",
                )
        item.lease_until, item.lease_token = None, None
        db.commit()
    return delivered
