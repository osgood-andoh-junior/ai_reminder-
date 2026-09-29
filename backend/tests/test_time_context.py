from datetime import datetime, timedelta
import json
import pytest
from sqlalchemy import select
from app import schemas
from app.agent.agent import chat
from app.agent.tools import Registry
from app.agent.time_arguments import TimeArguments
from app.core.time_context import TimeContext, local_instant, resolve_mentions
from app.db.models import User, ChatMessage, ScheduledTask
from app.services.application import Application
from test_agent import ScriptedModel


def context(iso="2026-09-29T12:00:00+00:00", zone="Africa/Accra"):
    return TimeContext(datetime.fromisoformat(iso), zone)


@pytest.mark.parametrize(
    "iso,zone,today,tomorrow",
    [
        ("2026-09-29T12:00:00+00:00", "Africa/Accra", "2026-09-29", "2026-09-30"),
        ("2026-09-29T23:59:59+00:00", "Africa/Accra", "2026-09-29", "2026-09-30"),
        ("2026-09-30T00:00:00+00:00", "Africa/Accra", "2026-09-30", "2026-10-01"),
        ("2026-09-29T00:30:00+00:00", "America/Los_Angeles", "2026-09-28", "2026-09-29"),
        ("2026-09-29T20:00:00+00:00", "Asia/Kolkata", "2026-09-30", "2026-10-01"),
        ("2026-12-31T23:59:00+00:00", "UTC", "2026-12-31", "2027-01-01"),
    ],
)
def test_local_calendar_boundaries(iso, zone, today, tomorrow):
    clock = context(iso, zone)
    assert clock.json()["today"] == today
    assert clock.json()["tomorrow"] == tomorrow
    refs = resolve_mentions("today and tomorrow", clock)
    assert refs["time_0"]["local_date"] == today
    assert refs["time_1"]["local_date"] == tomorrow


@pytest.mark.parametrize("iso,hours", [("2026-03-07T17:00:00+00:00", 23), ("2026-10-31T16:00:00+00:00", 25)])
def test_tomorrow_is_a_local_day_not_24_hours(iso, hours):
    clock = context(iso, "America/New_York")
    start, end = clock.bounds(clock.day("tomorrow"))
    assert end - start == timedelta(hours=hours)


def test_elapsed_minutes_cross_midnight_and_dst():
    for iso, expected in [
        ("2026-09-29T23:58:00+00:00", "2026-09-30T00:03:00+00:00"),
        ("2026-03-08T06:58:00+00:00", "2026-03-08T07:03:00+00:00"),
    ]:
        clock = context(iso, "America/New_York")
        refs = resolve_mentions("remind me in five minutes", clock)
        assert refs["time_0"]["start"] == expected
    clock = context("2026-03-07T12:00:00+00:00", "America/New_York")
    with pytest.raises(ValueError, match="ambiguous or nonexistent"):
        local_instant(clock.day("tomorrow"), "02:30", clock.zone)
    clock = context("2026-10-31T12:00:00+00:00", "America/New_York")
    with pytest.raises(ValueError, match="ambiguous or nonexistent"):
        local_instant(clock.day("tomorrow"), "01:30", clock.zone)


def test_tool_arguments_cannot_replace_relative_dates_with_guesses():
    args = TimeArguments(context(), "Schedule study tomorrow")
    for tool in ["schedule_task", "reschedule_task", "find_available_time"]:
        with pytest.raises(ValueError, match="relative timestamps"):
            args.normalize(tool, {"task_id": 1, "not_before": "2026-09-28T09:00:00Z"})
        with pytest.raises(ValueError, match="time_window"):
            args.normalize(tool, {"task_id": 1})
        result = args.normalize(tool, {"task_id": 1, "time_window": "time_0"})
        assert result["not_before"] == "2026-09-30T00:00:00+00:00"
        assert result["not_after"] == "2026-10-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="current request"):
        args.normalize("schedule_task", {"task_id": 1, "time_window": "invented"})
    with pytest.raises(ValueError, match="explicit local clock"):
        args.normalize("create_reminder", {"reminder_time": {"reference": "time_0", "edge": "start"}})
    later = TimeArguments(context(), "study later today").normalize(
        "schedule_task", {"task_id": 1, "time_window": "time_0"}
    )
    assert later["not_before"] == "2026-09-29T12:00:00+00:00"
    assert later["not_after"] == "2026-09-30T00:00:00+00:00"


def test_deadline_differs_from_target_day_and_unknown_phrases_require_clarification():
    args = TimeArguments(context(), "Study is due tomorrow")
    result = args.normalize("schedule_task", {"task_id": 1, "deadline_reference": "time_0"})
    assert result["not_after"] == "2026-10-01T00:00:00+00:00"
    assert "not_before" not in result  # The application starts from the request's now.
    for phrase in ["in a few minutes", "next week", "later", "in 20 seconds"]:
        args = TimeArguments(context(), f"Schedule study {phrase}")
        with pytest.raises(ValueError, match="clarification"):
            args.normalize("find_available_time", {"task_id": 1})
    # Even without a recognized relative phrase, invented absolute dates cannot pass.
    with pytest.raises(ValueError, match="relative timestamps"):
        TimeArguments(context(), "Remind me when convenient").normalize(
            "create_reminder", {"reminder_time": "2026-09-28T09:00:00Z", "message": "Study"}
        )


@pytest.mark.parametrize(
    "iso,zone",
    [
        ("2026-09-29T00:30:00+00:00", "America/Los_Angeles"),
        ("2026-09-29T20:00:00+00:00", "Asia/Kolkata"),
    ],
)
def test_scheduler_and_availability_respect_local_tomorrow(authenticated, database, monkeypatch, iso, zone):
    clock = context(iso, zone)
    monkeypatch.setattr("app.core.clock.utcnow", lambda: clock.now)
    with database() as db:
        s = Application(db, db.scalar(select(User)))
        s.update_preferences(schemas.PreferenceInput(timezone=zone))
        item = s.create_task(schemas.TaskInput(title="Study"))
        registry = Registry(s, "Schedule Study tomorrow")
        registry.execute("get_tasks", {})
        args = {"task_id": item["id"], "time_window": "time_0"}
        available = registry.execute("find_available_time", args)
        planned = registry.execute("schedule_task", args)
        assert available["feasible"]
        assert available["slots"] == planned["slots"]
        for slot in planned["slots"]:
            assert datetime.fromisoformat(slot["start"]).astimezone(clock.zone).date() == clock.day(
                "tomorrow"
            )
        reminder = Registry(s, "Remind me tomorrow at 09:00").execute(
            "create_reminder", {"message": "Study", "local_date": "tomorrow", "local_time": "09:00"}
        )
        assert datetime.fromisoformat(reminder["reminder_time"]).astimezone(clock.zone).date() == clock.day(
            "tomorrow"
        )


def test_time_endpoint_is_authenticated_fresh_and_user_scoped(authenticated, monkeypatch):
    clock = context("2026-09-29T23:59:59+00:00")
    monkeypatch.setattr("app.core.clock.utcnow", lambda: clock.now)
    authenticated.put("/api/preferences", json={"timezone": "Asia/Kolkata"})
    response = authenticated.get("/api/time")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["local_date"] == "2026-09-30"
    assert response.json()["utc_offset"] == "+05:30"
    clock = context("2026-09-30T00:00:01+00:00")
    assert authenticated.get("/api/time").json()["utc_now"] == clock.now.isoformat()
    authenticated.post("/api/auth/logout")
    assert authenticated.get("/api/time").status_code == 401


def test_agent_refreshes_context_ignores_stale_history_and_resolves_tools(
    authenticated, database, monkeypatch
):
    clock = context("2026-09-29T23:58:00+00:00")
    monkeypatch.setattr("app.core.clock.utcnow", lambda: clock.now)
    with database() as db:
        s = Application(db, db.scalar(select(User)))
        s.db.add(ChatMessage(user_id=s.user.id, role="assistant", content="Tomorrow is September 28."))
        item = s.create_task(schemas.TaskInput(title="Study", estimated_duration_minutes=60))
        s.db.commit()
        model = ScriptedModel(
            [
                ("get_tasks", {}),
                ("find_available_time", {"task_id": item["id"], "time_window": "time_0"}),
                ("schedule_task", {"task_id": item["id"], "time_window": "time_0"}),
                "Review tomorrow's schedule.",
            ]
        )
        result = chat(s, "Schedule Study tomorrow", client=model)
        assert all(a["ok"] for a in result["actions"])
        for call in model.calls:
            instructions = call["instructions"]
            assert '"tomorrow": "2026-09-30"' in instructions
            assert '"weekday": "Tuesday"' in instructions
            assert '"local_time": "23:58:00"' in instructions
            assert '"utc_offset": "+00:00"' in instructions
        available, proposal = result["actions"][1]["result"], result["proposals"][0]
        assert available["slots"] == proposal["payload"]["plan"]["slots"]
        assert all(slot["start"].startswith("2026-09-30") for slot in available["slots"])
        assert not list(db.scalars(select(ScheduledTask)))
        # A new request after midnight gets a new clock, even with the same service.
        clock = context("2026-09-30T00:01:00+00:00")
        again = ScriptedModel(["Tomorrow is October 1."])
        chat(s, "What is tomorrow's date?", client=again)
        assert '"tomorrow": "2026-10-01"' in again.calls[0]["instructions"]
        # The earlier proposal keeps September 30 when confirmed after midnight.
        s.decide(proposal["id"], True)
        assert all(row.start_time.day == 30 for row in db.scalars(select(ScheduledTask)))


def test_reminder_and_batch_use_same_request_snapshot(authenticated, database, monkeypatch):
    clock = context("2026-09-29T23:58:00+00:00")
    monkeypatch.setattr("app.core.clock.utcnow", lambda: clock.now)
    with database() as db:
        s = Application(db, db.scalar(select(User)))
        registry = Registry(s, "Remind me in 5 minutes")
        clock = context("2026-09-30T00:02:00+00:00")  # Model latency must not change the anchor.
        reminder = registry.execute(
            "create_reminder",
            {"message": "Take a break", "reminder_time": {"reference": "time_0", "edge": "start"}},
        )
        assert reminder["reminder_time"] == "2026-09-30T00:03:00+00:00"
        one = s.create_task(schemas.TaskInput(title="One"))
        two = s.create_task(schemas.TaskInput(title="Two"))
        batch = Registry(s, "Move both tasks tomorrow")
        batch.execute("get_tasks", {})
        plan = batch.execute(
            "reschedule_multiple_tasks",
            {"tasks": [{"task_id": item["id"], "time_window": "time_0"} for item in [one, two]]},
        )
        assert plan["feasible"]
        assert all(slot["start"].startswith("2026-09-30") for p in plan["plans"] for slot in p["slots"])
        schema = next(t for t in batch.definitions() if t["name"] == "reschedule_multiple_tasks")
        assert "time_window" in schema["parameters"]["$defs"]["ScheduleInput"]["properties"]
        json.dumps(schema)  # Tool definitions remain serializable.
