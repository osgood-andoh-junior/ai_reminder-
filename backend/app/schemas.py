from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Register(Input):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=1, max_length=100)


class Login(Input):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


def aware(value):
    if value is not None and value.tzinfo is None:
        raise ValueError("Include an explicit timezone offset in datetimes")
    return value


class TaskInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    estimated_duration_minutes: int = Field(default=60, ge=5, le=10080)
    deadline: datetime | None = None
    _aware = field_validator("deadline")(aware)


class TaskPatch(Input):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=5, le=10080)
    deadline: datetime | None = None
    status: Literal["PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED"] | None = None
    _aware = field_validator("deadline")(aware)


class EventInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    start_time: datetime
    end_time: datetime
    event_type: Literal["FIXED", "FLEXIBLE", "PERSONAL", "ACADEMIC", "WORK", "OTHER"] = "FIXED"
    is_recurring: Literal[False] = False
    _aware = field_validator("start_time", "end_time")(aware)

    @model_validator(mode="after")
    def order(self):
        if self.end_time <= self.start_time:
            raise ValueError("End must be after start")
        return self


class PreferenceInput(Input):
    timezone: str = "Africa/Accra"
    preferred_start_time: str = Field(default="09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    preferred_end_time: str = Field(default="17:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    preferred_days: list[int] = Field(default=[0, 1, 2, 3, 4], min_length=1, max_length=7)
    default_reminder_minutes: int = Field(default=15, ge=0, le=10080)
    preferred_task_length: int = Field(default=60, ge=15, le=240)
    break_preference: int = Field(default=15, ge=0, le=120)
    allow_weekend_scheduling: bool = False
    personalization_enabled: bool = True
    browser_notifications_enabled: bool = False
    email_notifications_enabled: bool = False
    deadline_reminders_enabled: bool = False

    @model_validator(mode="after")
    def valid(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone") from None
        if self.preferred_start_time >= self.preferred_end_time:
            raise ValueError("Preferred hours must start and end within the same day")
        if any(day not in range(7) for day in self.preferred_days) or len(set(self.preferred_days)) != len(
            self.preferred_days
        ):
            raise ValueError("Days must be distinct integers 0 (Monday) through 6 (Sunday)")
        return self


class ReminderInput(Input):
    task_id: int | None = Field(default=None, gt=0)
    scheduled_task_id: int | None = Field(default=None, gt=0)
    reminder_time: datetime | None = None
    minutes_before: int | None = Field(default=None, ge=0, le=10080)
    local_date: str | None = Field(default=None, max_length=10)
    local_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    title: str = Field(default="Reminder", min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=500)
    _aware = field_validator("reminder_time")(aware)

    @model_validator(mode="after")
    def timing(self):
        if (
            sum(
                [self.reminder_time is not None, self.minutes_before is not None, self.local_date is not None]
            )
            != 1
        ):
            raise ValueError(
                "Provide exactly one of reminder_time, minutes_before or local_date with local_time"
            )
        if (self.local_date is None) != (self.local_time is None):
            raise ValueError("Provide local_date and local_time together")
        if self.local_date and self.local_date not in {"today", "tomorrow"}:
            from datetime import date

            date.fromisoformat(self.local_date)
        if self.minutes_before is not None and not (self.task_id or self.scheduled_task_id):
            raise ValueError("Relative reminders require a task or session")
        return self


class SnoozeInput(Input):
    minutes: int | None = Field(default=None, ge=1, le=10080)
    until: datetime | None = None
    _aware = field_validator("until")(aware)

    @model_validator(mode="after")
    def timing(self):
        if (self.minutes is None) == (self.until is None):
            raise ValueError("Provide minutes or until, exclusively")
        return self


class PushKeys(Input):
    p256dh: str = Field(min_length=80, max_length=100, pattern=r"^[A-Za-z0-9_=-]+$")
    auth: str = Field(min_length=20, max_length=32, pattern=r"^[A-Za-z0-9_=-]+$")


class PushInput(Input):
    endpoint: str = Field(max_length=2048)
    keys: PushKeys
    expirationTime: float | None = None


class PushEndpoint(Input):
    endpoint: str = Field(max_length=2048)


class NotificationPreferences(Input):
    browser_notifications_enabled: bool | None = None
    deadline_reminders_enabled: bool | None = None
    default_reminder_minutes: int | None = Field(default=None, ge=0, le=10080)


class ReminderPatch(Input):
    status: Literal["DISMISSED", "COMPLETED", "CANCELLED"]


class ScheduleInput(Input):
    task_id: int = Field(gt=0)
    not_before: datetime | None = None
    not_after: datetime | None = None
    excluded_dates: list[str] = Field(default=[], max_length=90)
    _aware = field_validator("not_before", "not_after")(aware)

    @field_validator("excluded_dates")
    @classmethod
    def dates(cls, values):
        from datetime import date

        for value in values:
            date.fromisoformat(value)
        return values


class ChatInput(Input):
    message: str = Field(min_length=1, max_length=4000)


class BatchScheduleInput(Input):
    tasks: list[ScheduleInput] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def distinct(self):
        if len({t.task_id for t in self.tasks}) != len(self.tasks):
            raise ValueError("Each task must appear once")
        return self


class Decision(Input):
    accept: bool
