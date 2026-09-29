"""Request-scoped time and deterministic local calendar arithmetic."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo


def local_instant(day: date, clock: str, zone: ZoneInfo):
    wall = time.fromisoformat(clock)
    if wall.tzinfo is not None:
        raise ValueError("Local clock time must not contain an offset")
    local = datetime.combine(day, wall)
    first, second = (local.replace(tzinfo=zone, fold=fold) for fold in (0, 1))
    if (
        first.utcoffset() != second.utcoffset()
        or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local
    ):
        raise ValueError(
            "Local time is ambiguous or nonexistent due to daylight saving; supply an explicit offset"
        )
    return first.astimezone(timezone.utc)


@dataclass(frozen=True)
class TimeContext:
    now: datetime
    timezone: str

    def __post_init__(self):
        if self.now.utcoffset() is None:
            raise ValueError("Current time requires an explicit offset")
        object.__setattr__(self, "now", self.now.astimezone(timezone.utc))
        ZoneInfo(self.timezone)

    @property
    def zone(self):
        return ZoneInfo(self.timezone)

    @property
    def local(self):
        return self.now.astimezone(self.zone)

    def day(self, expression):
        offsets = {
            "yesterday": -1,
            "today": 0,
            "later today": 0,
            "tonight": 0,
            "tomorrow": 1,
            "day after tomorrow": 2,
        }
        if expression in offsets:
            return self.local.date() + timedelta(days=offsets[expression])
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        weekday = expression.removeprefix("next ")
        if weekday in weekdays:
            delta = (weekdays.index(weekday) - self.local.weekday()) % 7
            if expression.startswith("next ") and delta == 0:
                delta = 7
            return self.local.date() + timedelta(days=delta)
        return date.fromisoformat(expression)

    def bounds(self, day):
        return (
            local_instant(day, "00:00", self.zone),
            local_instant(day + timedelta(days=1), "00:00", self.zone),
        )

    def json(self):
        return {
            "utc_now": self.now.isoformat(),
            "local_now": self.local.isoformat(),
            "local_date": self.local.date().isoformat(),
            "local_time": self.local.time().isoformat(),
            "weekday": self.local.strftime("%A"),
            "timezone": self.timezone,
            "utc_offset": self.local.isoformat()[-6:],
            "today": self.local.date().isoformat(),
            "tomorrow": self.day("tomorrow").isoformat(),
        }


NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "ten": 10,
    "fifteen": 15,
    "thirty": 30,
}
RELATIVE = re.compile(
    r"\b(?:day after tomorrow|later today|today|tomorrow|yesterday|tonight|"
    r"(?:next )?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"in (?:\d+|" + "|".join(NUMBERS) + r") (?:minutes?|mins?|hours?|days?))\b",
    re.I,
)


def unresolved_relative_time(message):
    remaining = RELATIVE.sub("", message)
    return bool(
        re.search(
            r"\b(?:(?:next|this|last)\s+(?:week|month|year)|later|soon|"
            r"in\s+(?:\w+\s+){1,3}(?:seconds?|minutes?|mins?|hours?|days?|weeks?|months?|years?))\b",
            remaining,
            re.I,
        )
    )


def resolve_mentions(message, context):
    """Extract only the current user's words; history cannot supply today's clock."""
    result = {}
    for match in RELATIVE.finditer(message):
        expression = match.group().lower()
        if expression.startswith("in "):
            _, quantity, unit = expression.split()
            count = int(quantity) if quantity.isdigit() else NUMBERS[quantity]
            if not 0 < count <= 10080:
                raise ValueError("Relative interval must be between 1 and 10080 units")
            if unit.startswith("day"):
                day = context.local.date() + timedelta(days=count)
                start, end = context.bounds(day)
                kind = "day"
            else:
                start = context.now + timedelta(minutes=count * (60 if unit.startswith("hour") else 1))
                end = None
                day = start.astimezone(context.zone).date()
                kind = "instant"
        else:
            day = context.day(expression)
            start, end = context.bounds(day)
            kind = "day"
        result[f"time_{len(result)}"] = {
            "expression": expression,
            "kind": kind,
            "local_date": day.isoformat(),
            "start": start.isoformat(),
            "end": end.isoformat() if end else None,
        }
    return result
