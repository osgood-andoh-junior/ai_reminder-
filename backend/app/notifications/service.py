"""Transactional in-app delivery and a leased, retryable Web Push outbox."""

from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, update, or_, and_
from app.db.database import utcnow
from app.db.models import Reminder, User, UserPreference, PushSubscription, NotificationDelivery
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
        InAppNotifications().deliver(reminder, {"now": now})
        record(db, reminder, "REMINDER_SENT", channel="in_app")
        preference = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
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


def process_outbox(db, channel=None, now=None):
    now = now or utcnow()
    channel = channel or PushNotificationChannel()
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
        sub = db.get(PushSubscription, item.subscription_id, populate_existing=True)
        preference = db.scalar(
            select(UserPreference)
            .where(UserPreference.user_id == item.user_id)
            .execution_options(populate_existing=True)
        )
        if (
            not reminder
            or not sub
            or not sub.active
            or not preference.browser_notifications_enabled
            or reminder.generation != item.generation
            or reminder.status != "SENT"
        ):
            item.status = "CANCELLED"
        else:
            try:
                channel.deliver(
                    sub, {"reminder_id": reminder.id, "generation": item.generation, "user_id": item.user_id}
                )
                item.status, item.sent_at, item.last_error = "SENT", now, None
                record(db, reminder, "REMINDER_PUSH_ACCEPTED", delivery_id=item.id)
                delivered += 1
            except Exception as exc:
                failure = (
                    exc
                    if isinstance(exc, DeliveryError)
                    else DeliveryError("push_internal_error", retryable=False)
                )
                item.last_error = failure.code
                item.status = "RETRY" if failure.retryable and item.attempts < 5 else "FAILED"
                item.next_attempt_at = now + timedelta(seconds=min(30 * 2 ** (item.attempts - 1), 1800))
                if failure.expired:
                    sub.active = False
                record(
                    db,
                    reminder,
                    "REMINDER_FAILED",
                    channel="push",
                    delivery_id=item.id,
                    code=failure.code,
                    retry=item.status == "RETRY",
                )
        item.lease_until, item.lease_token = None, None
        db.commit()
    return delivered
