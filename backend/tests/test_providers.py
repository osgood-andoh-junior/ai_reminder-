"""Real provider serialization + real application tools, with all AI HTTP mocked."""

from copy import deepcopy
from datetime import datetime, timezone
import json

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.agent.agent import chat
from app.agent.providers import (
    PERPLEXITY_ENDPOINT,
    UNAVAILABLE,
    OpenAIProvider,
    PerplexityProvider,
    ProviderError,
    get_provider,
)
from app.core.config import Settings, settings
from app.db.models import Task, User, ScheduledTask, ChatMessage
from app.services.application import Application
from test_meetings import connected as _connected, frozen, draft, accept  # noqa: F401

connected = _connected


def answer(text="Done"):
    return {
        "status": "completed",
        "output": [
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}
        ],
    }


def call(name, arguments, ident="call_1", **extra):
    return {
        "status": "completed",
        "output": [
            {
                "type": "function_call",
                "name": name,
                "arguments": json.dumps(arguments),
                "call_id": ident,
                **extra,
            }
        ],
    }


@pytest.fixture
def model(monkeypatch):
    def install(steps):
        monkeypatch.setattr(settings(), "perplexity_api_key", "test-only-perplexity-key")
        requests = []
        steps = iter(steps)

        def post(url, **kwargs):
            assert url == PERPLEXITY_ENDPOINT
            assert kwargs["headers"] == {"Authorization": "Bearer test-only-perplexity-key"}
            assert kwargs["follow_redirects"] is False
            requests.append(deepcopy(kwargs["json"]))
            step = next(steps)
            if callable(step):
                step = step(requests[-1])
            if isinstance(step, Exception):
                raise step
            if isinstance(step, httpx.Response):
                return step
            return httpx.Response(200, json=step)

        monkeypatch.setattr(httpx, "post", post)
        return requests

    return install


def run(database, message="Hello"):
    with database() as db:
        return chat(Application(db, db.scalar(select(User))), message)


def test_selection_and_sonar_configuration(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "perplexity")
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-only")
    monkeypatch.setenv("PERPLEXITY_MODEL", "perplexity/sonar")
    config = Settings(_env_file=None)
    provider = get_provider(config)
    assert isinstance(provider, PerplexityProvider)
    assert provider.model == "perplexity/sonar"
    assert config.ai_configured
    config.ai_provider = "openai"
    config.openai_api_key = "test-only-openai"
    assert isinstance(get_provider(config), OpenAIProvider)
    assert config.ai_configured
    monkeypatch.setenv("AI_PROVIDER", "typo")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_tools_wire_format_and_continuation(authenticated, database, model):
    requests = model(
        [
            call(
                "create_task",
                {"title": "Study", "estimated_duration_minutes": 30},
                thought_signature="opaque",
            ),
            answer("Created Study"),
        ]
    )
    result = run(database, "Create a 30 minute Study task")
    assert result["actions"][0]["ok"]
    assert result["message"] == "Created Study"
    initial, continuation = requests
    assert initial["model"] == "perplexity/sonar"
    assert initial["store"] is False
    assert not {"preset", "profile", "web_search", "previous_response_id", "text"} & initial.keys()
    assert all(
        t["type"] == "function" and "parameters" in t and "function" not in t for t in initial["tools"]
    )
    names = {t["name"] for t in initial["tools"]}
    assert {
        "create_task",
        "schedule_task",
        "create_reminder",
        "get_calendar_events",
        "propose_meeting",
        "reschedule_meeting",
        "cancel_meeting",
        "find_contact",
        "save_contact",
        "find_my_availability",
    } <= names
    assert "confirm" not in names
    replay = next(i for i in continuation["input"] if i.get("type") == "function_call")
    assert replay["thought_signature"] == "opaque"
    output = next(i for i in continuation["input"] if i.get("type") == "function_call_output")
    assert output["call_id"] == replay["call_id"]
    assert json.loads(output["output"])["title"] == "Study"


@pytest.mark.parametrize(
    "zone,expected",
    [("Africa/Accra", "2026-10-04T15:00:00+00:00"), ("America/New_York", "2026-10-04T19:00:00+00:00")],
)
def test_meeting_clock_contacts_confirmation_and_invitation(connected, database, model, zone, expected):
    c, events, google_calls = connected
    c.put("/api/preferences", json={"timezone": zone})
    contact = c.post("/api/contacts/propose", json={"name": "Elliot", "email": "elliot@example.com"}).json()
    assert accept(c, contact).status_code == 200
    requests = model(
        [
            call("find_contact", {"query": "Elliot"}),
            call(
                "propose_meeting", draft(start_time={"reference": "time_0", "local_time": "15:00"}), "call_2"
            ),
            answer("Review and confirm the invitation."),
        ]
    )
    response = c.post(
        "/api/agent/chat", json={"message": "Schedule a 30-minute Google Meet with Elliot tomorrow at 3 PM."}
    )
    assert response.status_code == 200
    result = response.json()
    assert all(a["ok"] for a in result["actions"]), result
    assert result["requires_confirmation"]
    proposal = result["proposals"][0]
    assert proposal["status"] == "PENDING"
    assert proposal["payload"]["meeting"]["start_time"] == expected
    assert not events and all(method == "GET" for method, _, _ in google_calls)
    assert zone in requests[0]["instructions"]
    assert '"tomorrow": "2026-10-04"' in requests[0]["instructions"]
    assert '"utc_now": "2026-10-03T12:00:00+00:00"' in requests[0]["instructions"]
    assert accept(c, proposal).status_code == 200
    assert len(events) == 1
    post = next(kwargs for method, _, kwargs in google_calls if method == "POST")
    assert post["params"]["sendUpdates"] == "all"
    assert post["json"]["attendees"][0]["email"] == "elliot@example.com"
    assert "conferenceData" in post["json"]
    # connected's transport rejects every attendee calendar and freeBusy URL.


@pytest.mark.parametrize("arguments", [{"confirmed": True}, {"confirm": True}])
def test_model_cannot_confirm(connected, database, model, arguments):
    c, events, _ = connected
    model(
        [
            call(
                "propose_meeting",
                draft(start_time={"reference": "time_0", "local_time": "15:00"}, **arguments),
            ),
            call("confirm", {"id": 1}, "call_2"),
            answer("Could not confirm"),
        ]
    )
    result = run(database, "Meet elliot@example.com tomorrow at 3 PM for 30 minutes")
    assert not any(a["ok"] for a in result["actions"])
    assert not events and not result["proposals"]


def test_schedule_task_and_reminder_use_server_references(authenticated, database, model, monkeypatch):
    monkeypatch.setattr("app.core.clock.utcnow", lambda: datetime(2026, 10, 3, 23, 58, tzinfo=timezone.utc))
    authenticated.put("/api/preferences", json={"allow_weekend_scheduling": True})

    def schedule(payload):
        task = next(
            json.loads(i["output"]) for i in payload["input"] if i.get("type") == "function_call_output"
        )
        return call("schedule_task", {"task_id": task["id"], "time_window": "time_0"}, "call_2")

    requests = model(
        [
            call("create_task", {"title": "Study", "estimated_duration_minutes": 30}),
            schedule,
            call(
                "create_reminder",
                {"message": "Study", "local_date": "tomorrow", "local_time": "09:00"},
                "call_3",
            ),
            answer("Confirm the schedule"),
        ]
    )
    result = run(database, "Schedule Study tomorrow and remind me tomorrow at 9 AM")
    assert all(a["ok"] for a in result["actions"]), result
    assert result["requires_confirmation"]
    assert result["actions"][2]["result"]["reminder_time"] == "2026-10-04T09:00:00+00:00"
    assert all('"tomorrow": "2026-10-04"' in r["instructions"] for r in requests)
    with database() as db:
        assert not list(db.scalars(select(ScheduledTask)))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
def test_provider_failures_are_neutral_redacted_and_keep_receipts(
    authenticated, database, model, caplog, status
):
    model([call("create_task", {"title": "Saved"}), httpx.Response(status, text="secret-provider-body")])
    result = run(database)
    assert UNAVAILABLE in result["message"]
    assert result["actions"][0]["ok"]
    assert "secret-provider-body" not in json.dumps(result) + caplog.text
    assert "test-only-perplexity-key" not in json.dumps(result) + caplog.text
    with database() as db:
        assert db.scalar(select(Task).where(Task.title == "Saved"))
        assert "secret-provider-body" not in db.scalars(select(ChatMessage.content)).all()


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("secret"),
        httpx.ReadTimeout("secret"),
        httpx.Response(200, text="not json"),
        {},
        {"status": "completed", "output": []},
        {"status": "failed", "output": [], "error": {"message": "secret"}},
        {"status": "incomplete", "output": call("create_task", {"title": "Forbidden"})["output"]},
        {"status": "completed", "output": [{"type": "function_call", "name": "create_task"}]},
        {"status": "completed", "output": [{"type": "web_search_call"}]},
        {"status": "completed", "output": [{"type": "message", "role": "assistant", "content": None}]},
        {"status": "completed", "output": [*call("create_task", {"title": "Forbidden"})["output"], {}]},
    ],
)
def test_malformed_and_unavailable_responses_do_not_mutate(authenticated, database, model, failure):
    model([failure])
    result = run(database)
    assert UNAVAILABLE in result["message"]
    assert result["actions"] == []
    with database() as db:
        assert not list(db.scalars(select(Task)))


@pytest.mark.parametrize("raw", ["not json", "[]", "null", '"text"'])
def test_bad_tool_arguments_are_recoverable(authenticated, database, model, raw):
    response = call("create_task", {})
    response["output"][0]["arguments"] = raw
    requests = model([response, answer("Please clarify")])
    result = run(database)
    assert result["actions"][0]["ok"] is False
    assert "error" in json.loads(requests[1]["input"][-1]["output"])


@pytest.mark.parametrize("provider", ["perplexity", "openai"])
def test_missing_key_and_disabled_ai_leave_manual_features_working(authenticated, monkeypatch, provider):
    config = settings()
    monkeypatch.setattr(config, "ai_provider", provider)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("AI must not run"))
    c = authenticated
    assert c.get("/api/health").json()["ai_configured"] is False
    response = c.post("/api/agent/chat", json={"message": "Hello"})
    assert response.status_code == 503 and UNAVAILABLE in response.json()["detail"]
    task = c.post("/api/tasks", json={"title": "Manual", "estimated_duration_minutes": 30})
    assert task.status_code == 201
    assert c.get("/api/tasks").status_code == 200
    assert c.get("/api/time").status_code == 200
    assert c.get("/api/reminders").status_code == 200
    plan = c.post("/api/calendar/plan", json={"task_id": task.json()["id"]}).json()
    assert plan["feasible"]
    assert c.get("/api/calendar").json()["sessions"] == []
    assert accept(c, plan["proposal"]).status_code == 200
    assert len(c.get("/api/calendar").json()["sessions"]) == 1
    monkeypatch.setattr(config, "perplexity_api_key", "test-key")
    monkeypatch.setattr(config, "openai_api_key", "test-key")
    assert c.get("/api/health").json()["ai_configured"] is True
    monkeypatch.setattr(config, "ai_enabled", False)
    assert c.get("/api/health").json()["ai_configured"] is False
    assert c.post("/api/agent/chat", json={"message": "Hello"}).status_code == 503


def test_perplexity_extraction_has_no_tools(model):
    from app.integrations.extraction import extract
    from app.core.time_context import TimeContext
    from test_gmail import email, candidate, NOW

    requests = model([answer(json.dumps({"commitments": [candidate()]}))])
    result = extract(email(), TimeContext(NOW, "Africa/Accra"))
    assert result[0]["deadline"].isoformat() == "2026-09-30T23:59:00+00:00"
    assert requests[0]["tools"] == []
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert "server_time" in requests[0]["input"]


def test_hosted_tools_rejected_before_request(model):
    requests = model([])
    with pytest.raises(ProviderError):
        get_provider(settings()).generate(instructions="", inputs="", tools=[{"type": "web_search"}])
    assert not requests


def test_meeting_availability_reschedule_and_cancel_keep_confirmation(connected, database, model):
    c, events, google_calls = connected
    original = c.post("/api/meetings/propose", json=draft()).json()["proposal"]
    event = accept(c, original).json()["meeting"]
    model(
        [
            call("find_meetings", {"query": "Project meeting"}),
            call(
                "find_my_availability",
                {
                    "start": {"reference": "time_0", "edge": "start"},
                    "end": {"reference": "time_0", "edge": "end"},
                    "duration_minutes": 30,
                },
                "call_2",
            ),
            call(
                "reschedule_meeting",
                {
                    "id": event["id"],
                    "meeting": draft(start_time={"reference": "time_0", "local_time": "16:00"}),
                },
                "call_3",
            ),
            answer("Confirm the new time"),
        ]
    )
    result = run(database, "Move Project meeting with elliot@example.com tomorrow to 4 PM")
    assert all(a["ok"] for a in result["actions"]), result
    assert result["requires_confirmation"]
    assert not any(method == "PATCH" for method, _, _ in google_calls)
    assert accept(c, result["proposals"][0]).status_code == 200
    assert any(method == "PATCH" for method, _, _ in google_calls)
    model(
        [
            call("find_meetings", {"query": "Project meeting"}),
            call("cancel_meeting", {"id": event["id"]}, "call_2"),
            answer("Confirm cancellation"),
        ]
    )
    result = run(database, "Cancel Project meeting")
    assert result["requires_confirmation"] and events
    assert not any(method == "DELETE" for method, _, _ in google_calls)
    assert accept(c, result["proposals"][0]).status_code == 200
    assert not events


def test_pending_meeting_survives_provider_failure(connected, database, model):
    c, events, _ = connected
    model(
        [
            call("propose_meeting", draft(start_time={"reference": "time_0", "local_time": "15:00"})),
            httpx.Response(429, text="private"),
        ]
    )
    result = run(database, "Meet elliot@example.com tomorrow at 3 PM for 30 minutes")
    assert UNAVAILABLE in result["message"]
    assert result["requires_confirmation"] and not events
    assert accept(c, result["proposals"][0]).status_code == 200


def test_tool_reads_are_scoped_to_authenticated_user(authenticated, database, model):
    authenticated.post("/api/tasks", json={"title": "Private task"})
    authenticated.post("/api/auth/logout")
    authenticated.post(
        "/api/auth/register",
        json={"name": "Other", "email": "other@example.com", "password": "another-secure-password"},
    )
    requests = model([call("get_tasks", {}), answer("No tasks")])
    response = authenticated.post("/api/agent/chat", json={"message": "List my tasks"})
    assert response.json()["actions"][0]["result"] == []
    assert "Private task" not in json.dumps(requests)
