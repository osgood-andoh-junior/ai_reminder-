from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from app.scheduling.scheduler import Preferences, Slot, schedule, overlaps

UTC = timezone.utc
NOW = datetime(2030, 1, 7, 8, tzinfo=UTC)  # Monday


def run(duration=120, busy=None, pref=None, deadline=None, now=NOW):
    return schedule(duration, now, deadline or now + timedelta(days=4), busy or [], pref or Preferences())


def slots(result):
    return [
        Slot(datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])) for s in result["slots"]
    ]


def test_split_and_preference():
    result = run(duration=240, pref=Preferences(preferred_start_time="19:00", preferred_end_time="22:00"))
    assert result["feasible"]
    assert sum(s.minutes for s in slots(result)) == 240
    assert len(slots(result)) == 4
    assert all(19 <= s.start.hour < 22 for s in slots(result))


@pytest.mark.parametrize(
    "obstacles",
    [
        [],
        [Slot(NOW + timedelta(hours=1), NOW + timedelta(hours=4))],
        [Slot(NOW, NOW + timedelta(hours=6)), Slot(NOW + timedelta(hours=4), NOW + timedelta(hours=10))],
    ],
)
def test_no_conflicts(obstacles):
    result = run(busy=obstacles)
    assert result["feasible"]
    assert not any(overlaps(a, b) for a in slots(result) for b in obstacles)
    assert not any(overlaps(a, b) for i, a in enumerate(slots(result)) for b in slots(result)[i + 1 :])


def test_impossible_and_partial():
    result = run(duration=360, deadline=NOW + timedelta(hours=2))
    assert not result["feasible"]
    assert 0 < result["scheduled_minutes"] <= 120
    assert result["scheduled_minutes"] + result["unscheduled_minutes"] == 360
    assert not run(deadline=NOW - timedelta(hours=1))["slots"]


def test_weekends():
    saturday = datetime(2030, 1, 12, 9, tzinfo=UTC)
    assert not run(now=saturday, deadline=saturday + timedelta(hours=5))["feasible"]
    assert run(
        now=saturday, deadline=saturday + timedelta(hours=5), pref=Preferences(allow_weekend_scheduling=True)
    )["feasible"]


def test_nonpreferred_fallback():
    result = run(
        deadline=NOW + timedelta(hours=3),
        pref=Preferences(preferred_start_time="19:00", preferred_end_time="22:00"),
    )
    assert result["feasible"]
    assert all(s.end <= NOW + timedelta(hours=3) for s in slots(result))


@pytest.mark.parametrize(
    "zone,now",
    [
        ("America/New_York", datetime(2030, 3, 10, 5, tzinfo=UTC)),
        ("America/New_York", datetime(2030, 11, 3, 4, tzinfo=UTC)),
        ("Asia/Kathmandu", NOW),
        ("Africa/Accra", NOW),
    ],
)
def test_timezone_and_dst(zone, now):
    result = run(now=now, pref=Preferences(timezone=zone, allow_weekend_scheduling=True))
    assert result["feasible"]
    assert all(9 <= s.start.astimezone(ZoneInfo(zone)).hour < 17 for s in slots(result))
    assert all(s.start >= now for s in slots(result))


def test_excluded_day_and_breaks():
    result = schedule(180, NOW, NOW + timedelta(days=4), [], Preferences(), excluded_dates=["2030-01-07"])
    times = slots(result)
    assert all(s.start.date().isoformat() != "2030-01-07" for s in times)
    assert all(b.start - a.end >= timedelta(minutes=15) for a, b in zip(times, times[1:]))


def test_touching_intervals_and_naive():
    assert not overlaps(
        Slot(NOW, NOW + timedelta(hours=1)), Slot(NOW + timedelta(hours=1), NOW + timedelta(hours=2))
    )
    with pytest.raises(ValueError):
        run(now=NOW.replace(tzinfo=None))
