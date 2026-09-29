"""Session stage policy, calculated in UTC without AI or external services."""

from datetime import timedelta, timezone
from sqlalchemy import select
from app.db.database import utcnow
from app.db.models import Reminder, ScheduledTask, Task

STAGES = {
    "BEFORE_60": (-60, "📚 {title} starts in 1 hour. You've got this!"),
    "BEFORE_30": (-30, "⏰ {title} in 30 mins. Time to wrap up what you're doing!"),
    "BEFORE_5": (-5, "🚀 {title} starts in 5 mins. Let's get focused!"),
    "AFTER_10": (10, "💪 You're 10 mins into {title}. Keep the momentum going!"),
    "END_10": (-10, "🔥 Just 10 mins left in {title}. Finish strong!"),
}


def stage_times(start, end, enabled, now=None):
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Explicit timezone offsets are required")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    now = now or utcnow()
    result = {}
    for stage in enabled:
        minutes = STAGES[stage][0]
        when = (end if stage == "END_10" else start) + timedelta(minutes=minutes)
        if when <= now or (stage in {"AFTER_10", "END_10"} and not start < when < end):
            continue
        result[stage] = when
    return result


def reminder_message(stage, title):
    return STAGES[stage][1].format(title=title)


def session_reminders(service, task, session):
    enabled = (
        task.reminder_stages if task.reminder_stages is not None else service.preferences().reminder_stages
    )
    expected = stage_times(session.start_time, session.end_time, enabled, now=service.now)
    existing = list(
        service.db.scalars(
            select(Reminder).where(
                Reminder.user_id == service.user.id,
                Reminder.scheduled_task_id == session.id,
                Reminder.kind.in_([*STAGES, "SESSION"]),
            )
        )
    )
    for reminder in existing:
        if reminder.status in {"PENDING", "SNOOZED"} and reminder.kind not in expected:
            reminder.status = "CANCELLED"
    for stage, when in expected.items():
        reminder = next((r for r in existing if r.kind == stage), None)
        if reminder and (reminder.sent_at or reminder.status not in {"PENDING", "CANCELLED"}):
            continue
        if reminder is None:
            reminder = Reminder(
                user_id=service.user.id,
                task_id=task.id,
                scheduled_task_id=session.id,
                kind=stage,
                stage_key=stage,
            )
            service.db.add(reminder)
        reminder.status, reminder.reminder_time = "PENDING", when
        reminder.title, reminder.message = task.title, reminder_message(stage, task.title)
    service.db.flush()


def refresh_sessions(service, task_id=None):
    query = select(ScheduledTask).where(
        ScheduledTask.user_id == service.user.id, ScheduledTask.status == "SCHEDULED"
    )
    if task_id is not None:
        query = query.where(ScheduledTask.task_id == task_id)
    for session in service.db.scalars(query):
        session_reminders(service, service.own(Task, session.task_id), session)
