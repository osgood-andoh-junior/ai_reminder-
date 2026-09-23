"""Pure, deterministic scheduling. No database, network or model dependencies."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from bisect import bisect_right
from math import ceil


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    score: float = 0

    @property
    def minutes(self):
        return int((self.end - self.start).total_seconds() // 60)

    def json(self):
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "minutes": self.minutes,
            "score": round(self.score, 2),
        }


def overlaps(a: Slot, b: Slot):
    return a.start < b.end and b.start < a.end


def conflicts(slots, busy):
    return [(i, j) for i, a in enumerate(slots) for j, b in enumerate(busy) if overlaps(a, b)]


@dataclass
class Preferences:
    timezone: str = "Africa/Accra"
    preferred_start_time: str = "09:00"
    preferred_end_time: str = "17:00"
    preferred_days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    preferred_task_length: int = 60
    break_preference: int = 15
    allow_weekend_scheduling: bool = False


@dataclass
class Weights:
    preference: float = 100
    early: float = 20
    fragmentation: float = 10


def schedule(
    duration: int,
    now: datetime,
    deadline: datetime,
    busy: list[Slot],
    preferences: Preferences,
    priority="MEDIUM",
    excluded_dates=(),
    weights=None,
):
    if now.tzinfo is None or deadline.tzinfo is None:
        raise ValueError("Scheduling requires timezone-aware instants")
    if duration <= 0:
        return {"feasible": True, "slots": [], "scheduled_minutes": 0, "unscheduled_minutes": 0}
    weights = weights or Weights()
    zone = ZoneInfo(preferences.timezone)
    now, deadline = now.astimezone(timezone.utc), deadline.astimezone(timezone.utc)
    horizon = min(deadline, now + timedelta(days=90))
    # UTC stepping naturally handles DST folds and gaps without inventing local instants.
    step = timedelta(minutes=15)
    first = datetime.fromtimestamp(ceil(now.timestamp() / 900) * 900, timezone.utc)
    candidates = []
    cursor = first
    while cursor < horizon:
        local = cursor.astimezone(zone)
        if (
            local.date().isoformat() not in excluded_dates
            and (preferences.allow_weekend_scheduling or local.weekday() < 5)
            and 6 <= local.hour < 23
        ):
            candidates.append(cursor)
        cursor += step
    selected = []
    remaining = duration
    occupied = list(busy)
    pause = timedelta(minutes=preferences.break_preference)
    urgency = {"LOW": 0.5, "MEDIUM": 1, "HIGH": 1.5, "CRITICAL": 2}[priority]
    while remaining > 0:
        blocked = []
        for obstacle in sorted(occupied, key=lambda s: s.start):
            a, b = obstacle.start - pause, obstacle.end + pause
            if blocked and a <= blocked[-1][1]:
                blocked[-1] = (blocked[-1][0], max(blocked[-1][1], b))
            else:
                blocked.append((a, b))
        starts = [a for a, _ in blocked]
        best = None
        for start in candidates:
            length = min(remaining, preferences.preferred_task_length)
            end = start + timedelta(minutes=length)
            # Clip to the next obstacle; short fragments are legitimate but scored lower.
            position = bisect_right(starts, start)
            if position and start < blocked[position - 1][1]:
                continue
            if position < len(blocked):
                end = min(end, blocked[position][0])
            end = min(end, horizon)
            while end > start:
                local_end = (end - timedelta(microseconds=1)).astimezone(zone)
                local_start = start.astimezone(zone)
                if local_end.date() == local_start.date() and local_end.hour < 23:
                    break
                end -= timedelta(minutes=1)
            minutes = int((end - start).total_seconds() // 60)
            if minutes < min(15, remaining):
                continue
            end = start + timedelta(minutes=minutes)
            local_start, local_end = start.astimezone(zone), end.astimezone(zone)
            preferred = (
                local_start.weekday() in preferences.preferred_days
                and local_start.strftime("%H:%M") >= preferences.preferred_start_time
                and local_end.strftime("%H:%M") <= preferences.preferred_end_time
            )
            days_away = (start - now).total_seconds() / 86400
            score = (
                weights.preference * preferred
                + weights.early * urgency / (1 + days_away)
                - weights.fragmentation * (1 - minutes / min(remaining, preferences.preferred_task_length))
            )
            option = Slot(start, end, score)
            if best is None or (option.score, -option.start.timestamp(), option.minutes) > (
                best.score,
                -best.start.timestamp(),
                best.minutes,
            ):
                best = option
        if best is None:
            break
        selected.append(best)
        occupied.append(best)
        remaining -= best.minutes
    return {
        "feasible": remaining == 0,
        "slots": [s.json() for s in sorted(selected, key=lambda s: s.start)],
        "scheduled_minutes": duration - remaining,
        "unscheduled_minutes": remaining,
        "horizon_limited": deadline > horizon,
        "explanation": "Preference match, earlier completion and longer sessions determine ranking."
        if remaining == 0
        else f"Only {duration - remaining} minutes could be allocated under current constraints. "
        "Try a later deadline, shorter duration, fewer breaks, or enable weekends.",
    }
