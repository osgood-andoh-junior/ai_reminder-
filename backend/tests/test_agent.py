import json
from datetime import timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from fastapi import HTTPException
from app.agent.agent import chat
from app.agent.tools import Registry
from app.db.database import utcnow
from app.db.models import User, Task, ScheduledTask, Proposal
from app.services.application import Application
from app import schemas


class ScriptedModel:
    """Test-only model double; it never appears in application code."""

    def __init__(self, steps):
        self.steps = iter(steps)
        self.responses = self
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        step = next(self.steps)
        if callable(step):
            step = step(kwargs)
        if isinstance(step, str):
            return SimpleNamespace(output=[], output_text=step)
        name, arguments = step
        return SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="function_call",
                    name=name,
                    arguments=json.dumps(arguments),
                    call_id=f"call_{len(self.calls)}",
                )
            ],
            output_text="",
        )


def service(database):
    db = database()
    user = db.scalar(select(User))
    return Application(db, user)


def test_real_agent_orchestration(authenticated, database):
    s = service(database)
    s.update_preferences(schemas.PreferenceInput(preferred_start_time="19:00", preferred_end_time="22:00"))
    # Exactly the requested Wednesday meeting / Friday deadline scenario, on future dates.
    wednesday = (utcnow() + timedelta(days=7)).replace(hour=19, minute=0, second=0, microsecond=0)
    wednesday += timedelta(days=(2 - wednesday.weekday()) % 7)
    friday = (wednesday + timedelta(days=2)).replace(hour=23)
    s.save_event(
        schemas.EventInput(
            title="Networking Meeting", start_time=wednesday, end_time=wednesday + timedelta(hours=1)
        )
    )
    s.db.commit()

    def schedule_created(kwargs):
        results = [
            json.loads(x["output"])
            for x in kwargs["input"]
            if isinstance(x, dict) and x.get("type") == "function_call_output"
        ]
        task_id = next(
            r["id"] for r in results if isinstance(r, dict) and r.get("title") == "Networking assignment"
        )
        return "schedule_task", {"task_id": task_id, "not_before": wednesday.replace(hour=6).isoformat()}

    model = ScriptedModel(
        [
            ("get_user_preferences", {}),
            ("get_calendar_events", {}),
            (
                "create_task",
                {
                    "title": "Networking assignment",
                    "estimated_duration_minutes": 240,
                    "deadline": friday.isoformat(),
                },
            ),
            schedule_created,
            "I found four sessions. Review and confirm the proposed schedule.",
        ]
    )
    result = chat(s, "I have a networking assignment due Friday. It will take four hours.", client=model)
    assert result["requires_confirmation"]
    assert len(result["actions"]) == 4
    proposal = result["proposals"][0]
    slots = proposal["payload"]["plan"]["slots"]
    assert len(slots) == 4
    assert all(
        not (
            slot["start"] < (wednesday + timedelta(hours=1)).isoformat()
            and slot["end"] > wednesday.isoformat()
        )
        for slot in slots
    )
    assert not list(s.db.scalars(select(ScheduledTask)))
    s.decide(proposal["id"], True)
    s.db.commit()
    assert len(list(s.db.scalars(select(ScheduledTask)))) == 4
    assert all(call["store"] is False for call in model.calls)
    assert not any(d["name"] == "confirm" for d in model.calls[0]["tools"])
    s.db.close()


def test_ids_and_confirmation_cannot_be_invented(authenticated, database):
    s = service(database)
    task = s.create_task(schemas.TaskInput(title="Task"))
    registry = Registry(s)
    with pytest.raises(ValueError, match="Retrieve"):
        registry.execute("schedule_task", {"task_id": task["id"]})
    with pytest.raises(ValueError, match="Unknown"):
        registry.execute("confirm", {"id": 1})
    registry.execute("get_tasks", {})
    result = registry.execute("schedule_task", {"task_id": task["id"]})
    assert result["proposal"]["status"] == "PENDING"
    s.db.close()


def test_failed_tool_is_reported(authenticated, database):
    s = service(database)
    model = ScriptedModel([("delete_everything", {}), "The operation could not be completed."])
    result = chat(s, "Delete all my data", client=model)
    assert result["actions"][0]["ok"] is False
    assert "failed" in result["message"]
    s.db.close()


def test_max_iterations(authenticated, database):
    s = service(database)
    model = ScriptedModel([("get_tasks", {})] * 20)
    result = chat(s, "What next?", client=model)
    assert len(model.calls) == 8
    assert "tool limit" in result["message"]
    s.db.close()


def test_batch_atomic_confirm_and_conflicts(authenticated, database):
    s = service(database)
    first = s.create_task(schemas.TaskInput(title="AI study A", estimated_duration_minutes=120))
    second = s.create_task(schemas.TaskInput(title="AI study B", estimated_duration_minutes=120))
    request = schemas.BatchScheduleInput(
        tasks=[schemas.ScheduleInput(task_id=t["id"]) for t in [first, second]]
    )
    result = s.plan_many(request)
    assert result["feasible"]
    s.decide(result["proposal"]["id"], True)
    s.db.commit()
    sessions = list(s.db.scalars(select(ScheduledTask)))
    assert len(sessions) == 4
    from app.scheduling.scheduler import Slot, overlaps

    assert not any(
        overlaps(Slot(a.start_time, a.end_time), Slot(b.start_time, b.end_time))
        for i, a in enumerate(sessions)
        for b in sessions[i + 1 :]
    )
    with pytest.raises(HTTPException):
        s.decide(result["proposal"]["id"], True)
    s.db.close()


def test_preferences_are_only_proposed(authenticated, database):
    s = service(database)
    registry = Registry(s)
    result = registry.execute(
        "update_user_preference", {"preferred_start_time": "19:00", "preferred_end_time": "22:00"}
    )
    assert s.preferences().preferred_start_time == "09:00"
    assert s.own(Proposal, result["id"]).kind == "preferences"
    s.decide(result["id"], True)
    assert s.preferences().preferred_start_time == "19:00"
    s.db.close()


def test_external_failure_preserves_receipts(authenticated, database):
    from openai import APIConnectionError
    import httpx

    s = service(database)

    def fail(_):
        raise APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))

    model = ScriptedModel([("create_task", {"title": "Saved before outage"}), fail])
    result = chat(s, "Create a task", client=model)
    assert "unavailable" in result["message"]
    assert result["actions"][0]["ok"]
    assert s.db.scalar(select(Task).where(Task.title == "Saved before outage")) is not None
    s.db.close()


def test_provider_error_is_actionable_and_redacted(authenticated, database):
    from openai import AuthenticationError
    import httpx

    s = service(database)

    def fail(_):
        raise AuthenticationError(
            "secret-provider-body",
            response=httpx.Response(
                401, request=httpx.Request("POST", "https://api.openai.com/v1/responses")
            ),
            body={"message": "secret-provider-body"},
        )

    result = chat(s, "Hello", client=ScriptedModel([fail]))
    assert "API key was rejected" in result["message"]
    assert "secret-provider-body" not in result["message"]
    s.db.close()
