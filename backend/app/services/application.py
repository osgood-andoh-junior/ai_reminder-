from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, update, func
from app.db.database import utcnow
from app.db.models import (
    User,
    UserPreference,
    Task,
    CalendarEvent,
    ScheduledTask,
    Reminder,
    UserActivity,
    Proposal,
    ChatMessage,
    GoogleCalendarConnection,
)
from app import schemas
from app.core.config import settings
from app.scheduling.scheduler import Preferences, Weights, Slot, schedule, overlaps


def serialize(row):
    return {
        c.name: (
            getattr(row, c.name).isoformat()
            if isinstance(getattr(row, c.name), datetime)
            else getattr(row, c.name)
        )
        for c in row.__table__.columns
        if c.name not in {"password_hash", "token_hash", "encrypted_tokens"}
    }


class Application:
    """Only gateway used by API routes and AI tools. Identity is constructor-bound."""

    def __init__(self, db, user):
        self.db, self.user = db, user

    def lock(self):
        # An UPDATE obtains a per-user PostgreSQL row lock / SQLite writer lock.
        # All calendar and schedule writers use it until their transaction commits.
        self.db.execute(update(User).where(User.id == self.user.id).values(revision=User.revision + 1))

    def rows(self, model, limit=500):
        return list(
            self.db.scalars(
                select(model).where(model.user_id == self.user.id).order_by(model.id.desc()).limit(limit)
            )
        )

    def own(self, model, ident):
        item = self.db.scalar(select(model).where(model.id == ident, model.user_id == self.user.id))
        if item is None:
            raise HTTPException(404, "Resource not found")
        return item

    def activity(self, action, details=None):
        self.db.add(UserActivity(user_id=self.user.id, action=action, details=details or {}))

    def preferences(self):
        return self.db.scalar(select(UserPreference).where(UserPreference.user_id == self.user.id))

    def update_preferences(self, data):
        self.lock()
        pref = self.preferences()
        if data.email_notifications_enabled:
            raise HTTPException(422, "Email delivery is not configured")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(pref, key, value)
        self.db.flush()
        from app.notifications.strategies import refresh_deadlines

        refresh_deadlines(self)
        self.activity("PREFERENCE_UPDATED")
        self.db.flush()
        return serialize(pref)

    def create_task(self, data):
        task = Task(user_id=self.user.id, **data.model_dump())
        self.db.add(task)
        self.db.flush()
        self.activity("TASK_CREATED", {"task_id": task.id})
        from app.notifications.strategies import deadline_reminders

        deadline_reminders(self, task)
        return serialize(task)

    def cancel_sessions(self, task_id):
        sessions = self.db.scalars(
            select(ScheduledTask).where(
                ScheduledTask.user_id == self.user.id,
                ScheduledTask.task_id == task_id,
                ScheduledTask.status == "SCHEDULED",
            )
        )
        for session in sessions:
            session.status = "CANCELLED"
        self.db.execute(
            update(Reminder)
            .where(
                Reminder.user_id == self.user.id,
                Reminder.task_id == task_id,
                Reminder.status.in_(["PENDING", "SENT", "SNOOZED", "READ"]),
            )
            .values(status="CANCELLED")
        )

    def update_task(self, ident, data):
        self.lock()
        task = self.own(Task, ident)
        changes = data.model_dump(exclude_unset=True)
        if any(v is None for k, v in changes.items() if k != "deadline"):
            raise HTTPException(422, "Only deadline may be null")
        # Changed constraints invalidate old sessions; nothing silently misses a new deadline.
        if {"deadline", "estimated_duration_minutes"} & changes.keys():
            self.cancel_sessions(task.id)
            task.status = "PENDING"
        for key, value in changes.items():
            setattr(task, key, value)
        if task.status in {"COMPLETED", "CANCELLED", "PENDING"}:
            self.cancel_sessions(task.id)
        task.completed_at = utcnow() if task.status == "COMPLETED" else None
        self.activity(
            "TASK_COMPLETED" if task.status == "COMPLETED" else "TASK_UPDATED", {"task_id": task.id}
        )
        self.db.flush()
        from app.notifications.strategies import deadline_reminders

        deadline_reminders(self, task)
        return serialize(task)

    def delete_task(self, ident):
        self.lock()
        task = self.own(Task, ident)
        self.db.delete(task)
        self.activity("TASK_DELETED", {"task_id": ident})

    def busy(self, exclude_task=None):
        # Never limit conflict queries to a paginated UI result.
        events = self.db.scalars(select(CalendarEvent).where(CalendarEvent.user_id == self.user.id))
        sessions = self.db.scalars(
            select(ScheduledTask).where(
                ScheduledTask.user_id == self.user.id, ScheduledTask.status == "SCHEDULED"
            )
        )
        excluded = set(exclude_task) if isinstance(exclude_task, list) else {exclude_task}
        return [Slot(e.start_time, e.end_time) for e in events] + [
            Slot(s.start_time, s.end_time) for s in sessions if s.task_id not in excluded
        ]

    def save_event(self, data, ident=None):
        self.lock()
        item = self.own(CalendarEvent, ident) if ident else CalendarEvent(user_id=self.user.id)
        if ident and item.source != "internal":
            raise HTTPException(409, "Edit connected events in Google Calendar, then sync")
        proposed = Slot(data.start_time, data.end_time)
        sessions = self.db.scalars(
            select(ScheduledTask).where(
                ScheduledTask.user_id == self.user.id, ScheduledTask.status == "SCHEDULED"
            )
        )
        affected = [s.task_id for s in sessions if overlaps(proposed, Slot(s.start_time, s.end_time))]
        if affected:
            raise HTTPException(
                409,
                {
                    "message": "This event conflicts with scheduled tasks. Reschedule them first.",
                    "task_ids": sorted(set(affected)),
                },
            )
        for key, value in data.model_dump().items():
            setattr(item, key, value)
        self.db.add(item)
        self.db.flush()
        self.activity("EVENT_UPDATED" if ident else "EVENT_CREATED", {"event_id": item.id})
        return serialize(item)

    def delete_event(self, ident):
        self.lock()
        item = self.own(CalendarEvent, ident)
        if item.source != "internal":
            raise HTTPException(409, "Delete connected events in Google Calendar, then sync")
        self.db.delete(item)
        self.activity("EVENT_DELETED", {"event_id": ident})

    def create_reminder(self, data):
        self.lock()
        if data.local_date:
            from app.notifications.timing import local_reminder_time

            data.reminder_time = local_reminder_time(
                data.local_date, data.local_time, self.preferences().timezone
            )
        task = self.own(Task, data.task_id) if data.task_id else None
        if task and task.status in {"COMPLETED", "CANCELLED"}:
            raise HTTPException(409, "Task is no longer active")
        if data.minutes_before is not None and not data.scheduled_task_id:
            sessions = list(
                self.db.scalars(
                    select(ScheduledTask)
                    .where(
                        ScheduledTask.user_id == self.user.id,
                        ScheduledTask.task_id == data.task_id,
                        ScheduledTask.status == "SCHEDULED",
                        ScheduledTask.start_time > utcnow(),
                    )
                    .order_by(ScheduledTask.start_time)
                )
            )
            if len(sessions) != 1:
                raise HTTPException(
                    422, "Choose a specific scheduled session; this task has zero or multiple future sessions"
                )
            data.scheduled_task_id = sessions[0].id
        if data.scheduled_task_id:
            session = self.own(ScheduledTask, data.scheduled_task_id)
            if session.status != "SCHEDULED":
                raise HTTPException(409, "This session is no longer scheduled")
            if data.task_id and data.task_id != session.task_id:
                raise HTTPException(422, "Reminder task and session must match")
            data.task_id = session.task_id
            if data.minutes_before is not None:
                data.reminder_time = session.start_time - timedelta(minutes=data.minutes_before)
        if data.title == "Reminder" and data.task_id:
            data.title = self.own(Task, data.task_id).title
        if data.reminder_time <= utcnow():
            raise HTTPException(422, "Reminder must be in the future")
        reminder = Reminder(
            user_id=self.user.id, **data.model_dump(exclude={"minutes_before", "local_date", "local_time"})
        )
        self.db.add(reminder)
        self.db.flush()
        self.activity("REMINDER_CREATED", {"reminder_id": reminder.id})
        return serialize(reminder)

    def reminder_status(self, ident, status):
        self.lock()
        item = self.own(Reminder, ident)
        if item.status == status:
            return serialize(item)
        if status == "READ" and item.status != "SENT":
            raise HTTPException(409, "Only delivered reminders can be marked read")
        if item.status in {"DISMISSED", "CANCELLED", "COMPLETED"}:
            raise HTTPException(409, "Reminder already handled")
        item.status = status
        if status == "READ":
            item.read_at = utcnow()
        if status == "DISMISSED":
            item.dismissed_at = utcnow()
        self.activity("REMINDER_" + status, {"reminder_id": ident})
        self.db.flush()
        return serialize(item)

    def snooze_reminder(self, ident, data):
        self.lock()
        item = self.own(Reminder, ident)
        if item.status not in {"PENDING", "SENT", "READ", "SNOOZED"}:
            raise HTTPException(409, "This reminder cannot be snoozed")
        until = data.until or utcnow() + timedelta(minutes=data.minutes)
        if until <= utcnow() or until > utcnow() + timedelta(days=7):
            raise HTTPException(422, "Snooze must be in the future and within seven days")
        item.status, item.snoozed_until = "SNOOZED", until
        item.generation += 1
        item.read_at, item.dismissed_at = None, None
        self.activity("REMINDER_SNOOZED", {"reminder_id": ident, "until": until.isoformat()})
        self.db.flush()
        return serialize(item)

    def proposal(self, kind, payload):
        item = Proposal(
            user_id=self.user.id, kind=kind, payload=payload, expires_at=utcnow() + timedelta(minutes=30)
        )
        self.db.add(item)
        self.db.flush()
        return serialize(item)

    def plan(self, data, persist=True, busy_override=None):
        if busy_override is None:
            self.refresh_external_calendar()
        task = self.own(Task, data.task_id)
        if task.status in {"COMPLETED", "CANCELLED"}:
            raise HTTPException(409, "Completed or cancelled tasks cannot be scheduled")
        pref = self.preferences()
        completed = self.db.scalars(
            select(ScheduledTask).where(
                ScheduledTask.user_id == self.user.id,
                ScheduledTask.task_id == task.id,
                ScheduledTask.status == "COMPLETED",
            )
        )
        done = sum(int((s.end_time - s.start_time).total_seconds() // 60) for s in completed)
        current = utcnow()
        start = max(current, data.not_before or current)
        deadline = min(
            task.deadline or start + timedelta(days=14),
            data.not_after or task.deadline or start + timedelta(days=14),
            current + timedelta(days=90),
        )
        config = settings()
        result = schedule(
            max(0, task.estimated_duration_minutes - done),
            start,
            deadline,
            self.busy(exclude_task=task.id) if busy_override is None else busy_override,
            Preferences(**{k: getattr(pref, k) for k in Preferences.__dataclass_fields__}),
            task.priority,
            data.excluded_dates,
            Weights(config.preference_weight, config.early_weight, config.fragmentation_weight),
        )
        result.update(task_id=task.id, title=task.title)
        if persist and result["slots"]:
            # A partial allocation is explicitly labeled and requires the same confirmation.
            result["proposal"] = self.proposal(
                "schedule", {"plan": result.copy(), "request": data.model_dump(mode="json")}
            )
        return result

    def refresh_external_calendar(self):
        if self.db.scalar(
            select(GoogleCalendarConnection.id).where(GoogleCalendarConnection.user_id == self.user.id)
        ):
            # A connected provider must succeed; don't silently schedule against a stale cache.
            from app.integrations.google_calendar import GoogleCalendarService

            GoogleCalendarService(self).sync()

    def plan_many(self, data, persist=True):
        self.refresh_external_calendar()
        busy = self.busy(exclude_task=[item.task_id for item in data.tasks])
        plans = []
        # Deterministic priority/deadline order while reserving each generated plan.
        ordered = sorted(
            data.tasks,
            key=lambda item: (
                {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}[self.own(Task, item.task_id).priority],
                self.own(Task, item.task_id).deadline or utcnow() + timedelta(days=90),
                item.task_id,
            ),
        )
        for item in ordered:
            plan = self.plan(item, persist=False, busy_override=busy)
            plans.append(plan)
            busy.extend(
                Slot(datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"]))
                for s in plan["slots"]
            )
        result = {"plans": plans, "feasible": all(p["feasible"] for p in plans)}
        if persist and result["feasible"]:
            result["proposal"] = self.proposal(
                "batch_schedule", {"plans": plans, "request": data.model_dump(mode="json")}
            )
        return result

    def apply_schedule(self, plan, proposal_id):
        task = self.own(Task, plan["task_id"])
        slots = [
            Slot(datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])) for s in plan["slots"]
        ]
        old = list(
            self.db.scalars(
                select(ScheduledTask).where(
                    ScheduledTask.user_id == self.user.id,
                    ScheduledTask.task_id == task.id,
                    ScheduledTask.status == "SCHEDULED",
                )
            )
        )
        self.cancel_sessions(task.id)
        pref = self.preferences()
        for slot in slots:
            session = ScheduledTask(
                user_id=self.user.id, task_id=task.id, start_time=slot.start, end_time=slot.end
            )
            self.db.add(session)
            self.db.flush()
            self.db.add(
                Reminder(
                    user_id=self.user.id,
                    task_id=task.id,
                    scheduled_task_id=session.id,
                    title=task.title,
                    kind="SESSION",
                    reminder_time=max(
                        utcnow(), slot.start - timedelta(minutes=pref.default_reminder_minutes)
                    ),
                    message=f"{task.title}: {slot.minutes}-minute session scheduled for {slot.start.astimezone(ZoneInfo(pref.timezone)).strftime('%d %b at %H:%M')}.",
                )
            )
        task.status = "SCHEDULED"
        from app.notifications.strategies import deadline_reminders

        deadline_reminders(self, task)
        detail = {"task_id": task.id, "proposal_id": proposal_id}
        if old and slots:
            zone = ZoneInfo(pref.timezone)
            detail.update(
                from_hour=old[0].start_time.astimezone(zone).hour,
                to_hour=slots[0].start.astimezone(zone).hour,
            )
        self.activity("TASK_RESCHEDULED" if old else "SCHEDULE_ACCEPTED", detail)

    def decide(self, ident, accept):
        self.lock()
        proposal = self.own(Proposal, ident)
        if proposal.status != "PENDING":
            raise HTTPException(409, "This proposal has already been handled")
        if proposal.expires_at < utcnow():
            raise HTTPException(409, "Proposal expired. Please request a new one")
        if not accept:
            proposal.status = "REJECTED"
            self.activity("SCHEDULE_REJECTED", {"proposal_id": ident})
            return {"message": "Proposal declined", "status": "REJECTED"}
        payload = proposal.payload
        if proposal.kind == "preferences":
            self.update_preferences(schemas.PreferenceInput(**payload))
        elif proposal.kind == "dismiss_reminder":
            self.reminder_status(payload["reminder_id"], "DISMISSED")
        elif proposal.kind == "delete_event":
            self.delete_event(payload["event_id"])
        elif proposal.kind == "update_event":
            self.save_event(schemas.EventInput(**payload["event"]), payload["event_id"])
        elif proposal.kind == "batch_schedule":
            fresh = self.plan_many(schemas.BatchScheduleInput(**payload["request"]), persist=False)

            def signatures(plans):
                return [(p["task_id"], [(s["start"], s["end"]) for s in p["slots"]]) for p in plans]

            if not fresh["feasible"] or signatures(fresh["plans"]) != signatures(payload["plans"]):
                raise HTTPException(409, "Availability changed. Generate a fresh batch proposal")
            for plan in payload["plans"]:
                self.apply_schedule(plan, ident)
        elif proposal.kind == "schedule":
            plan = payload["plan"]
            task = self.own(Task, plan["task_id"])
            if task.status in {"COMPLETED", "CANCELLED"}:
                raise HTTPException(409, "Task is no longer schedulable")
            fresh = self.plan(schemas.ScheduleInput(**payload["request"]), persist=False)
            if [(s["start"], s["end"]) for s in fresh["slots"]] != [
                (s["start"], s["end"]) for s in plan["slots"]
            ]:
                raise HTTPException(409, "Availability or preferences changed. Generate a fresh proposal")
            self.apply_schedule(plan, ident)
        else:
            raise HTTPException(400, "Unsupported proposal")
        proposal.status = "ACCEPTED"
        self.db.flush()
        return {"message": "Changes saved", "status": "ACCEPTED"}

    def session_status(self, ident, status):
        self.lock()
        session = self.own(ScheduledTask, ident)
        if session.status != "SCHEDULED":
            raise HTTPException(409, "Session already handled")
        if status not in {"COMPLETED", "SKIPPED"}:
            raise HTTPException(422, "Invalid session status")
        session.status = status
        self.db.execute(
            update(Reminder)
            .where(
                Reminder.user_id == self.user.id,
                Reminder.scheduled_task_id == ident,
                Reminder.status.in_(["PENDING", "SENT", "SNOOZED", "READ"]),
            )
            .values(status="COMPLETED" if status == "COMPLETED" else "CANCELLED")
        )
        self.activity(
            "SESSION_COMPLETED" if status == "COMPLETED" else "TASK_SKIPPED",
            {"task_id": session.task_id, "session_id": ident},
        )
        self.db.flush()
        if status == "COMPLETED":
            task = self.own(Task, session.task_id)
            completed = self.db.scalars(
                select(ScheduledTask).where(
                    ScheduledTask.user_id == self.user.id,
                    ScheduledTask.task_id == task.id,
                    ScheduledTask.status == "COMPLETED",
                )
            )
            done = sum(int((s.end_time - s.start_time).total_seconds() // 60) for s in completed)
            if done >= task.estimated_duration_minutes:
                task.status = "COMPLETED"
                task.completed_at = utcnow()
                self.cancel_sessions(task.id)
                self.activity("TASK_COMPLETED", {"task_id": task.id})
        return serialize(session)

    def suggestions(self):
        if not self.preferences().personalization_enabled:
            return []
        history = self.db.scalars(
            select(UserActivity).where(
                UserActivity.user_id == self.user.id,
                UserActivity.action == "TASK_RESCHEDULED",
                UserActivity.created_at > utcnow() - timedelta(days=60),
            )
        )
        evening = [
            a for a in history if a.details.get("from_hour", 24) < 18 and a.details.get("to_hour", 0) >= 18
        ]
        if len({a.details.get("task_id") for a in evening}) < 3:
            return []
        return [
            {
                "message": "You moved at least three different tasks to the evening. Prefer 19:00–22:00?",
                "changes": {"preferred_start_time": "19:00", "preferred_end_time": "22:00"},
            }
        ]

    def chat_history(self):
        return [serialize(m) for m in reversed(self.rows(ChatMessage, 60))]

    def dashboard(self):
        zone = ZoneInfo(self.preferences().timezone)
        today = utcnow().astimezone(zone).date()
        start = datetime.combine(today, time(), zone)
        end = datetime.combine(today + timedelta(days=1), time(), zone)
        tasks = list(
            self.db.scalars(
                select(Task)
                .where(Task.user_id == self.user.id, Task.status.notin_(["COMPLETED", "CANCELLED"]))
                .order_by(Task.deadline.asc().nulls_last(), Task.id.desc())
                .limit(8)
            )
        )
        events = [
            serialize(e)
            for e in self.db.scalars(
                select(CalendarEvent)
                .where(
                    CalendarEvent.user_id == self.user.id,
                    CalendarEvent.start_time < end,
                    CalendarEvent.end_time > start,
                )
                .order_by(CalendarEvent.start_time)
            )
        ]
        sessions = [
            serialize(s)
            for s in self.db.scalars(
                select(ScheduledTask)
                .where(
                    ScheduledTask.user_id == self.user.id,
                    ScheduledTask.status == "SCHEDULED",
                    ScheduledTask.start_time < end,
                    ScheduledTask.end_time > start,
                )
                .order_by(ScheduledTask.start_time)
            )
        ]
        counts = dict(
            self.db.execute(
                select(Task.status, func.count()).where(Task.user_id == self.user.id).group_by(Task.status)
            ).all()
        )
        return {
            "tasks": [serialize(t) for t in tasks],
            "events": events,
            "sessions": sessions,
            "reminders": [
                serialize(r)
                for r in self.db.scalars(
                    select(Reminder)
                    .where(Reminder.user_id == self.user.id, Reminder.status.in_(["PENDING", "SENT"]))
                    .order_by(Reminder.reminder_time)
                    .limit(8)
                )
            ],
            "summary": {
                "total": sum(counts.values()),
                "completed": counts.get("COMPLETED", 0),
                "active": sum(v for k, v in counts.items() if k not in {"COMPLETED", "CANCELLED"}),
                "scheduled": counts.get("SCHEDULED", 0),
            },
            "timezone": str(zone),
        }
