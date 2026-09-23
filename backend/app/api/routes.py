from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError
from app import schemas
from app.db.database import get_db, utcnow
from app.db.models import (
    User,
    UserPreference,
    AuthSession,
    Task,
    CalendarEvent,
    ScheduledTask,
    Reminder,
    UserActivity,
    Proposal,
    PushSubscription,
    NotificationDelivery,
)
from app.core.security import current_user, hasher, verify, DUMMY_HASH, new_session, digest
from app.services.application import Application, serialize
from app.agent.agent import chat

router = APIRouter(prefix="/api")


def application(db=Depends(get_db), user=Depends(current_user)):
    return Application(db, user)


Service = Annotated[Application, Depends(application)]


@router.post("/auth/register", status_code=201)
def register(data: schemas.Register, response: Response, db=Depends(get_db)):
    user = User(email=str(data.email).lower(), name=data.name, password_hash=hasher.hash(data.password))
    try:
        db.add(user)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists") from None
    db.add(UserPreference(user_id=user.id))
    new_session(db, user, response)
    return serialize(user)


@router.post("/auth/login")
def login(data: schemas.Login, response: Response, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    valid = verify(data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, "Email or password is incorrect")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(data.password)
    new_session(db, user, response)
    return serialize(user)


@router.get("/auth/me")
def me(user=Depends(current_user)):
    return serialize(user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, db=Depends(get_db)):
    db.execute(
        delete(AuthSession).where(AuthSession.token_hash == digest(request.cookies.get("session", "")))
    )
    response.delete_cookie("session", path="/")
    return {"message": "Signed out"}


@router.get("/tasks")
def tasks(s: Service):
    return [serialize(t) for t in s.rows(Task)]


@router.post("/tasks", status_code=201)
def create_task(data: schemas.TaskInput, s: Service):
    return s.create_task(data)


@router.get("/tasks/{ident}")
def task(ident: int, s: Service):
    return serialize(s.own(Task, ident))


@router.patch("/tasks/{ident}")
def update_task(ident: int, data: schemas.TaskPatch, s: Service):
    return s.update_task(ident, data)


@router.delete("/tasks/{ident}", status_code=204)
def delete_task(ident: int, s: Service):
    s.delete_task(ident)


@router.get("/events")
def events(s: Service):
    return [serialize(e) for e in s.rows(CalendarEvent)]


@router.post("/events", status_code=201)
def create_event(data: schemas.EventInput, s: Service):
    return s.save_event(data)


@router.put("/events/{ident}")
def update_event(ident: int, data: schemas.EventInput, s: Service):
    return s.save_event(data, ident)


@router.delete("/events/{ident}", status_code=204)
def delete_event(ident: int, s: Service):
    s.delete_event(ident)


@router.get("/preferences")
def preferences(s: Service):
    return serialize(s.preferences())


@router.put("/preferences")
def update_preferences(data: schemas.PreferenceInput, s: Service):
    return s.update_preferences(data)


@router.get("/preferences/suggestions")
def suggestions(s: Service):
    return s.suggestions()


@router.get("/reminders")
def reminders(s: Service):
    return [serialize(r) for r in s.rows(Reminder)]


@router.post("/reminders", status_code=201)
def create_reminder(data: schemas.ReminderInput, s: Service):
    return s.create_reminder(data)


@router.patch("/reminders/{ident}")
def reminder_status(ident: int, data: schemas.ReminderPatch, s: Service):
    return s.reminder_status(ident, data.status)


@router.get("/reminders/unread-count")
def unread_count(s: Service):
    return {
        "count": s.db.scalar(
            select(func.count())
            .select_from(Reminder)
            .where(Reminder.user_id == s.user.id, Reminder.status == "SENT")
        )
    }


@router.get("/reminders/recent")
def recent_reminders(s: Service):
    return [
        serialize(r)
        for r in s.db.scalars(
            select(Reminder)
            .where(Reminder.user_id == s.user.id, Reminder.status.in_(["SENT", "READ"]))
            .order_by(Reminder.sent_at.desc())
            .limit(10)
        )
    ]


@router.get("/reminders/{ident}")
def get_reminder(ident: int, s: Service):
    item = s.own(Reminder, ident)
    result = serialize(item)
    session = s.own(ScheduledTask, item.scheduled_task_id) if item.scheduled_task_id else None
    result["scheduled_start"] = session.start_time.isoformat() if session else None
    result["timezone"] = s.preferences().timezone
    return result


@router.post("/reminders/{ident}/read")
def read_reminder(ident: int, s: Service):
    return s.reminder_status(ident, "READ")


@router.post("/reminders/{ident}/dismiss")
def dismiss_reminder(ident: int, s: Service):
    return s.reminder_status(ident, "DISMISSED")


@router.post("/reminders/{ident}/snooze")
def snooze_reminder(ident: int, data: schemas.SnoozeInput, s: Service):
    return s.snooze_reminder(ident, data)


@router.get("/reminders/{ident}/deliveries")
def reminder_deliveries(ident: int, s: Service):
    s.own(Reminder, ident)
    return [
        {
            "id": d.id,
            "channel": "push",
            "status": d.status,
            "attempts": d.attempts,
            "last_error": d.last_error,
            "sent_at": d.sent_at,
        }
        for d in s.db.scalars(
            select(NotificationDelivery).where(
                NotificationDelivery.user_id == s.user.id, NotificationDelivery.reminder_id == ident
            )
        )
    ]


@router.get("/notifications/config")
def notification_config(s: Service):
    from app.core.config import settings

    config = settings()
    return {
        "push_configured": bool(
            config.vapid_public_key and config.vapid_private_key and config.vapid_subject
        ),
        "vapid_public_key": config.vapid_public_key,
        "email_configured": False,
    }


@router.patch("/preferences/notifications")
def notification_preferences(data: schemas.NotificationPreferences, s: Service):
    values = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    return s.update_preferences(schemas.PreferenceInput(**values))


@router.post("/notifications/subscriptions", status_code=201)
def subscribe(data: schemas.PushInput, s: Service):
    from app.notifications.push import validate_subscription
    from app.core.config import settings

    if not (settings().vapid_public_key and settings().vapid_private_key and settings().vapid_subject):
        raise HTTPException(503, "Web Push is not configured on the server")
    try:
        validate_subscription(data.endpoint, data.keys.p256dh, data.keys.auth)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    s.lock()
    item = s.db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint_hash == digest(data.endpoint))
    )
    if item and item.user_id != s.user.id:
        raise HTTPException(
            409,
            "This browser subscription belongs to another account. Unsubscribe this browser before enabling again.",
        )
    if item is None:
        if (
            s.db.scalar(
                select(func.count())
                .select_from(PushSubscription)
                .where(PushSubscription.user_id == s.user.id, PushSubscription.active.is_(True))
            )
            >= 20
        ):
            raise HTTPException(409, "Device limit reached. Remove an old subscription first.")
        item = PushSubscription(
            user_id=s.user.id,
            endpoint=data.endpoint,
            endpoint_hash=digest(data.endpoint),
            p256dh=data.keys.p256dh,
            auth=data.keys.auth,
        )
        s.db.add(item)
    else:
        item.p256dh, item.auth, item.active = data.keys.p256dh, data.keys.auth, True
    s.preferences().browser_notifications_enabled = True
    s.db.flush()
    return {"id": item.id, "active": item.active}


@router.post("/notifications/subscriptions/remove")
def unsubscribe(data: schemas.PushEndpoint, s: Service):
    s.lock()
    item = s.db.scalar(
        select(PushSubscription).where(
            PushSubscription.endpoint_hash == digest(data.endpoint), PushSubscription.user_id == s.user.id
        )
    )
    if item:
        item.active = False
    return {"removed": True}


@router.get("/notifications/subscriptions")
def subscriptions(s: Service):
    return [
        {"id": row.id, "active": row.active, "created_at": row.created_at} for row in s.rows(PushSubscription)
    ]


@router.delete("/notifications/subscriptions/{ident}", status_code=204)
def remove_subscription(ident: int, s: Service):
    s.lock()
    s.own(PushSubscription, ident).active = False


@router.get("/calendar")
def calendar(s: Service):
    return {
        "events": [serialize(e) for e in s.rows(CalendarEvent)],
        "sessions": [serialize(t) for t in s.rows(ScheduledTask) if t.status == "SCHEDULED"],
        "reminders": [serialize(r) for r in s.rows(Reminder) if r.status in {"PENDING", "SENT"}],
        "timezone": s.preferences().timezone,
    }


@router.post("/calendar/plan")
def plan(data: schemas.ScheduleInput, s: Service):
    return s.plan(data)


@router.post("/calendar/plan-batch")
def plan_batch(data: schemas.BatchScheduleInput, s: Service):
    return s.plan_many(data)


@router.patch("/calendar/sessions/{ident}")
def session_status(ident: int, data: dict, s: Service):
    return s.session_status(ident, data.get("status"))


@router.get("/proposals")
def proposals(s: Service):
    return [serialize(p) for p in s.rows(Proposal) if p.status == "PENDING" and p.expires_at > utcnow()]


@router.post("/proposals/{ident}/decision")
def decide(ident: int, data: schemas.Decision, s: Service):
    return s.decide(ident, data.accept)


@router.get("/dashboard")
def dashboard(s: Service):
    return s.dashboard()


@router.get("/activity")
def activity(s: Service):
    return [serialize(a) for a in s.rows(UserActivity, 100)]


@router.get("/agent/history")
def history(s: Service):
    return s.chat_history()


@router.post("/agent/chat")
def agent(data: schemas.ChatInput, s: Service):
    return chat(s, data.message)
