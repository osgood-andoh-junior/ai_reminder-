from fastapi import HTTPException
from app.db.database import utcnow
from app.core.time_context import TimeContext, local_instant


def local_reminder_time(day: str, clock: str, zone_name: str, now=None):
    context = TimeContext(now or utcnow(), zone_name)
    try:
        return local_instant(context.day(day), clock, context.zone)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
