from datetime import timedelta
from sqlalchemy import select
from app.db.database import utcnow
from app.db.models import User, Reminder, UserActivity
from app.worker import process_due


def task(client, **extra):
    response = client.post(
        "/api/tasks",
        json={
            "title": "Networking assignment",
            "estimated_duration_minutes": 240,
            "deadline": (utcnow() + timedelta(days=7)).isoformat(),
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_auth_and_isolation(authenticated, database):
    c = authenticated
    item = task(c)
    with database() as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
    c.post("/api/auth/logout")
    assert c.get("/api/tasks").status_code == 401
    assert (
        c.post("/api/auth/login", json={"email": "test@example.com", "password": "wrong"}).status_code == 401
    )
    c.post(
        "/api/auth/register",
        json={"name": "Other", "email": "other@example.com", "password": "another-secure-password"},
    )
    assert c.get(f"/api/tasks/{item['id']}").status_code == 404
    assert c.patch(f"/api/tasks/{item['id']}", json={"title": "stolen"}).status_code == 404
    assert c.post("/api/calendar/plan", json={"task_id": item["id"]}).status_code == 404
    assert (
        c.post(
            "/api/reminders",
            json={
                "task_id": item["id"],
                "message": "bad",
                "reminder_time": (utcnow() + timedelta(hours=1)).isoformat(),
            },
        ).status_code
        == 404
    )


def test_complete_flow(authenticated, database):
    c = authenticated
    prefs = {
        "timezone": "Africa/Accra",
        "preferred_start_time": "19:00",
        "preferred_end_time": "22:00",
        "preferred_task_length": 60,
    }
    assert c.put("/api/preferences", json=prefs).status_code == 200
    future = utcnow() + timedelta(days=2)
    meeting = future.replace(hour=19, minute=0, second=0, microsecond=0)
    event = c.post(
        "/api/events",
        json={
            "title": "Networking Meeting",
            "start_time": meeting.isoformat(),
            "end_time": (meeting + timedelta(hours=1)).isoformat(),
        },
    )
    assert event.status_code == 201
    item = task(c)
    plan = c.post("/api/calendar/plan", json={"task_id": item["id"]}).json()
    assert plan["feasible"] and len(plan["slots"]) == 4
    assert not c.get("/api/calendar").json()["sessions"]
    proposal_id = plan["proposal"]["id"]
    accepted = c.post(f"/api/proposals/{proposal_id}/decision", json={"accept": True})
    assert accepted.status_code == 200, accepted.text
    assert c.post(f"/api/proposals/{proposal_id}/decision", json={"accept": True}).status_code == 409
    assert len(c.get("/api/calendar").json()["sessions"]) == 4
    assert len(c.get("/api/reminders").json()) == 4
    assert c.get("/api/dashboard").json()["summary"]["scheduled"] == 1
    # Reschedule away from the first allocated day; old reminders are cancelled.
    day = plan["slots"][0]["start"][:10]
    moved = c.post("/api/calendar/plan", json={"task_id": item["id"], "excluded_dates": [day]}).json()
    assert all(s["start"][:10] != day for s in moved["slots"])
    assert (
        c.post(f"/api/proposals/{moved['proposal']['id']}/decision", json={"accept": True}).status_code == 200
    )
    assert any(r["status"] == "CANCELLED" for r in c.get("/api/reminders").json())
    assert c.patch(f"/api/tasks/{item['id']}", json={"status": "COMPLETED"}).status_code == 200
    assert not c.get("/api/calendar").json()["sessions"]
    assert c.get("/api/dashboard").json()["summary"]["completed"] == 1
    assert any(a["action"] == "TASK_RESCHEDULED" for a in c.get("/api/activity").json())


def test_stale_proposal_and_validation(authenticated):
    c = authenticated
    item = task(c)
    plan = c.post("/api/calendar/plan", json={"task_id": item["id"]}).json()
    slot = plan["slots"][0]
    assert (
        c.post(
            "/api/events",
            json={"title": "New conflict", "start_time": slot["start"], "end_time": slot["end"]},
        ).status_code
        == 201
    )
    assert (
        c.post(f"/api/proposals/{plan['proposal']['id']}/decision", json={"accept": True}).status_code == 409
    )
    assert (
        c.post(
            "/api/events",
            json={"title": "naive", "start_time": "2030-01-01T10:00", "end_time": "2030-01-01T11:00"},
        ).status_code
        == 422
    )
    assert c.put("/api/preferences", json={"timezone": "not/a/zone"}).status_code == 422
    assert c.post("/api/tasks", json={"title": "x", "user_id": 999}).status_code == 422
    assert (
        c.post("/api/tasks", json={"title": "x"}, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )


def test_reminder_worker_and_personalization(authenticated, database):
    c = authenticated
    reminder = c.post(
        "/api/reminders",
        json={"message": "Time to focus", "reminder_time": (utcnow() + timedelta(minutes=5)).isoformat()},
    )
    assert reminder.status_code == 201
    with database() as db:
        row = db.scalar(select(Reminder))
        row.reminder_time = utcnow() - timedelta(minutes=1)
        db.commit()
        assert process_due(db) == 1
        assert process_due(db) == 0
        for ident in range(3):
            db.add(
                UserActivity(
                    user_id=row.user_id,
                    action="TASK_RESCHEDULED",
                    details={"task_id": ident, "from_hour": 12, "to_hour": 19},
                )
            )
        db.commit()
    assert c.get("/api/reminders").json()[0]["status"] == "SENT"
    assert len(c.get("/api/preferences/suggestions").json()) == 1
    assert c.get("/api/preferences").json()["preferred_start_time"] == "09:00"


def test_no_key_is_graceful(authenticated, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings(), "openai_api_key", "")
    response = authenticated.post("/api/agent/chat", json={"message": "Schedule my assignment"})
    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]
    assert authenticated.get("/api/tasks").status_code == 200
