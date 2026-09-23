"""Deterministic reminder strategies; no model or recurring model polling."""

from datetime import timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.db.database import utcnow
from app.db.models import Task, Reminder


def deadline_reminders(service, task):
    existing = list(
        service.db.scalars(
            select(Reminder).where(
                Reminder.user_id == service.user.id,
                Reminder.task_id == task.id,
                Reminder.kind.in_(["DEADLINE_DAY", "DEADLINE_NEAR"]),
            )
        )
    )
    enabled = (
        service.preferences().deadline_reminders_enabled
        and task.deadline
        and task.status not in {"COMPLETED", "CANCELLED"}
    )
    expected = (
        {
            kind: task.deadline - timedelta(minutes=minutes)
            for kind, minutes in [("DEADLINE_DAY", 1440), ("DEADLINE_NEAR", 60)]
        }
        if enabled
        else {}
    )
    for reminder in existing:
        if reminder.status in {"PENDING", "SNOOZED", "SENT", "READ"} and (
            reminder.kind not in expected or reminder.reminder_time != expected[reminder.kind]
        ):
            reminder.status = "CANCELLED"
    for kind, when in expected.items():
        if when <= utcnow() or any(
            r.kind == kind and r.reminder_time == when and r.status != "CANCELLED" for r in existing
        ):
            continue
        service.db.add(
            Reminder(
                user_id=service.user.id,
                task_id=task.id,
                title=task.title,
                kind=kind,
                reminder_time=when,
                message=f"{task.title} is due {task.deadline.astimezone(ZoneInfo(service.preferences().timezone)).strftime('%d %b at %H:%M')}. Review your remaining work.",
            )
        )


def refresh_deadlines(service):
    for task in service.db.scalars(select(Task).where(Task.user_id == service.user.id)):
        deadline_reminders(service, task)
