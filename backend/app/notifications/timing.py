from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from app.db.database import utcnow


def local_reminder_time(day: str, clock: str, zone_name: str, now=None):
    zone = ZoneInfo(zone_name)
    today = (now or utcnow()).astimezone(zone).date()
    target = (
        today
        if day == "today"
        else today + timedelta(days=1)
        if day == "tomorrow"
        else date.fromisoformat(day)
    )
    local = datetime.combine(target, time.fromisoformat(clock))
    first, second = local.replace(tzinfo=zone, fold=0), local.replace(tzinfo=zone, fold=1)
    if (
        first.utcoffset() != second.utcoffset()
        or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local
    ):
        raise HTTPException(
            422,
            "This local time is ambiguous or does not exist due to daylight saving. Choose another time or supply an explicit offset.",
        )
    return first.astimezone(timezone.utc)
