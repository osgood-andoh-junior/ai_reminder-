"""Allowlisted, Pydantic-validated tools bound to an authenticated Application."""

from datetime import datetime
from pydantic import Field
from app import schemas
from app.db.models import Task, CalendarEvent, Reminder, UserActivity, ScheduledTask
from app.services.application import serialize
from app.scheduling.scheduler import Slot, overlaps


class Empty(schemas.Input):
    pass


class Identifier(schemas.Input):
    id: int = Field(gt=0)


class UpdateTask(Identifier):
    changes: schemas.TaskPatch


class UpdateEvent(Identifier):
    event: schemas.EventInput


class SnoozeReminder(Identifier):
    snooze: schemas.SnoozeInput


class Range(schemas.Input):
    start: datetime
    end: datetime
    _aware = schemas.field_validator("start", "end")(schemas.aware)

    @schemas.model_validator(mode="after")
    def order(self):
        if self.end <= self.start:
            raise ValueError("End must be after start")
        return self


class Registry:
    def __init__(self, service):
        self.service = service
        s = service
        self.entries = {
            "get_user_profile": (
                Empty,
                "Read the signed-in user's name and email.",
                lambda _: {"name": s.user.name, "email": s.user.email},
            ),
            "get_user_preferences": (
                Empty,
                "Read timezone, preferred hours and session constraints.",
                lambda _: serialize(s.preferences()),
            ),
            "update_user_preference": (
                schemas.PreferenceInput,
                "Propose permanent preferences; requires a user click.",
                lambda a: s.proposal("preferences", a.model_dump()),
            ),
            "get_tasks": (
                Empty,
                "List user tasks with real IDs; always retrieve IDs before a mutation.",
                lambda _: [serialize(t) for t in s.rows(Task)],
            ),
            "get_task": (
                Identifier,
                "Read a task by its retrieved ID.",
                lambda a: serialize(s.own(Task, a.id)),
            ),
            "create_task": (
                schemas.TaskInput,
                "Create a task. Ask for missing duration or ambiguous deadline.",
                s.create_task,
            ),
            "update_task": (
                UpdateTask,
                "Update a task; changed duration or deadline cancels outdated sessions.",
                lambda a: s.update_task(a.id, a.changes),
            ),
            "complete_task": (
                Identifier,
                "Complete a task explicitly requested by the user.",
                lambda a: s.update_task(a.id, schemas.TaskPatch(status="COMPLETED")),
            ),
            "get_calendar_events": (
                Empty,
                "Read calendar events and scheduled task sessions.",
                lambda _: {
                    "events": [serialize(e) for e in s.rows(CalendarEvent)],
                    "sessions": [serialize(t) for t in s.rows(ScheduledTask) if t.status == "SCHEDULED"],
                },
            ),
            "create_calendar_event": (
                schemas.EventInput,
                "Create an explicit user-specified event, never invent times.",
                s.save_event,
            ),
            "update_calendar_event": (
                UpdateEvent,
                "Propose an event edit for confirmation.",
                lambda a: s.proposal(
                    "update_event",
                    {"event_id": s.own(CalendarEvent, a.id).id, "event": a.event.model_dump(mode="json")},
                ),
            ),
            "delete_calendar_event": (
                Identifier,
                "Propose event deletion for confirmation.",
                lambda a: s.proposal("delete_event", {"event_id": s.own(CalendarEvent, a.id).id}),
            ),
            "find_available_time": (
                schemas.ScheduleInput,
                "Calculate feasible sessions for a real task without saving.",
                lambda a: s.plan(a, persist=False),
            ),
            "detect_conflicts": (
                Range,
                "Check a requested interval against all busy calendar and task time.",
                lambda a: {
                    "conflicts": [b.json() for b in s.busy() if overlaps(Slot(a.start, a.end), b)],
                    "reminders": [
                        serialize(r)
                        for r in s.rows(Reminder)
                        if r.status in {"PENDING", "SENT"} and a.start <= r.reminder_time < a.end
                    ],
                },
            ),
            "schedule_task": (
                schemas.ScheduleInput,
                "Calculate and persist a schedule proposal. Never commits sessions.",
                s.plan,
            ),
            "reschedule_task": (
                schemas.ScheduleInput,
                "Propose replacement of remaining sessions; use excluded_dates or a bounded date range.",
                s.plan,
            ),
            "reschedule_multiple_tasks": (
                schemas.BatchScheduleInput,
                "Propose atomic changes for up to ten tasks; reserves non-overlapping slots and requires confirmation. Use for moving all matching tasks.",
                s.plan_many,
            ),
            "create_reminder": (
                schemas.ReminderInput,
                "Create a reminder. For before-session requests provide minutes_before and a retrieved scheduled_task_id; the server calculates the timestamp. Ask about ambiguous times or sessions.",
                s.create_reminder,
            ),
            "get_reminders": (
                Empty,
                "Read the user's reminders.",
                lambda _: [serialize(r) for r in s.rows(Reminder)],
            ),
            "snooze_reminder": (
                SnoozeReminder,
                "Snooze a retrieved reminder for user-requested minutes or an explicit offset timestamp.",
                lambda a: s.snooze_reminder(a.id, a.snooze),
            ),
            "dismiss_reminder": (
                Identifier,
                "Propose dismissal of a retrieved reminder. Requires user confirmation.",
                lambda a: s.proposal("dismiss_reminder", {"reminder_id": s.own(Reminder, a.id).id}),
            ),
            "get_activity_history": (
                Empty,
                "Read the 30 most recent activities only.",
                lambda _: [serialize(a) for a in s.rows(UserActivity, 30)],
            ),
        }
        self.known_ids: set[int] = set()

    def definitions(self):
        # Pydantic models enforce optional/default fields locally; strict=false permits these schemas.
        return [
            {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": model.model_json_schema(),
                "strict": False,
            }
            for name, (model, description, _) in self.entries.items()
        ]

    def remember(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"id", "task_id", "event_id", "scheduled_task_id"} and isinstance(item, int):
                    self.known_ids.add(item)
                self.remember(item)
        elif isinstance(value, list):
            for item in value:
                self.remember(item)

    def execute(self, name, arguments):
        if name not in self.entries:
            raise ValueError("Unknown tool")
        model, _, call = self.entries[name]
        parsed = model.model_validate(arguments)

        def check_ids(data):
            if isinstance(data, dict):
                for key, value in data.items():
                    if (
                        key in {"id", "task_id", "scheduled_task_id"}
                        and value is not None
                        and value not in self.known_ids
                    ):
                        raise ValueError("Retrieve the resource with a read tool before using its ID")
                    check_ids(value)
            elif isinstance(data, list):
                for value in data:
                    check_ids(value)

        check_ids(parsed.model_dump())
        result = call(parsed)
        self.remember(result)
        self.service.activity("AGENT_TOOL_EXECUTED", {"tool": name})
        return result
