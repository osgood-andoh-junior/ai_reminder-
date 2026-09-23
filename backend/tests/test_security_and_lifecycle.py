from datetime import timedelta
from sqlalchemy import select
from app.db.database import utcnow
from app.db.models import User, Proposal
from app.services.application import Application
from app import schemas


def test_session_revocation_and_duplicate_registration(authenticated):
    c = authenticated
    saved = c.cookies.get("session")
    assert "password_hash" not in c.get("/api/auth/me").json()
    response = c.post(
        "/api/auth/register",
        json={"name": "Duplicate", "email": "test@example.com", "password": "a-secure-test-password"},
    )
    assert response.status_code == 409
    assert c.post("/api/auth/logout").status_code == 200
    c.cookies.set("session", saved)
    assert c.get("/api/auth/me").status_code == 401
    c.cookies.clear()
    response = c.post(
        "/api/auth/login", json={"email": "TEST@example.com", "password": "a-secure-test-password"}
    )
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]


def test_csrf_and_safe_validation(client):
    c = client
    c.headers.pop("X-Requested-With")
    assert c.post("/api/auth/register", json={}).status_code == 403
    c.headers["X-Requested-With"] = "Tempo"
    response = c.post("/api/auth/register", json={"name": "Name", "email": "bad", "password": "private"})
    assert response.status_code == 422
    assert "private" not in response.text
    assert response.headers["x-request-id"]


def test_event_and_proposal_ownership(authenticated):
    c = authenticated
    now = utcnow() + timedelta(days=1)
    event = c.post(
        "/api/events",
        json={
            "title": "Private meeting",
            "start_time": now.isoformat(),
            "end_time": (now + timedelta(hours=1)).isoformat(),
        },
    ).json()
    task = c.post("/api/tasks", json={"title": "Private task"}).json()
    proposal = c.post("/api/calendar/plan", json={"task_id": task["id"]}).json()["proposal"]
    c.post("/api/auth/logout")
    c.post(
        "/api/auth/register",
        json={"name": "Other", "email": "second@example.com", "password": "a-secure-test-password"},
    )
    assert c.delete(f"/api/events/{event['id']}").status_code == 404
    assert c.post(f"/api/proposals/{proposal['id']}/decision", json={"accept": True}).status_code == 404
    assert c.get("/api/events").json() == []
    assert c.get("/api/proposals").json() == []


def test_expired_and_rejected_proposals(authenticated, database):
    c = authenticated
    task = c.post("/api/tasks", json={"title": "Focus"}).json()
    proposal = c.post("/api/calendar/plan", json={"task_id": task["id"]}).json()["proposal"]
    with database() as db:
        db.get(Proposal, proposal["id"]).expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert c.post(f"/api/proposals/{proposal['id']}/decision", json={"accept": True}).status_code == 409
    fresh = c.post("/api/calendar/plan", json={"task_id": task["id"]}).json()["proposal"]
    assert c.post(f"/api/proposals/{fresh['id']}/decision", json={"accept": False}).status_code == 200
    assert c.get("/api/calendar").json()["sessions"] == []


def test_session_completion_and_remaining_work(authenticated, database):
    with database() as db:
        s = Application(db, db.scalar(select(User)))
        task = s.create_task(schemas.TaskInput(title="Two sessions", estimated_duration_minutes=120))
        plan = s.plan(schemas.ScheduleInput(task_id=task["id"]))
        s.decide(plan["proposal"]["id"], True)
        db.commit()
    sessions = authenticated.get("/api/calendar").json()["sessions"]
    assert (
        authenticated.patch(
            f"/api/calendar/sessions/{sessions[0]['id']}", json={"status": "COMPLETED"}
        ).status_code
        == 200
    )
    result = authenticated.post("/api/calendar/plan", json={"task_id": task["id"]}).json()
    assert result["scheduled_minutes"] == 60
    assert (
        authenticated.patch(
            f"/api/calendar/sessions/{sessions[1]['id']}", json={"status": "COMPLETED"}
        ).status_code
        == 200
    )
    assert authenticated.get(f"/api/tasks/{task['id']}").json()["status"] == "COMPLETED"


def test_delete_cascades(authenticated):
    c = authenticated
    task = c.post("/api/tasks", json={"title": "Temporary"}).json()
    proposal = c.post("/api/calendar/plan", json={"task_id": task["id"]}).json()["proposal"]
    c.post(f"/api/proposals/{proposal['id']}/decision", json={"accept": True})
    assert c.get("/api/reminders").json()
    assert c.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert c.get("/api/calendar").json()["sessions"] == []
    assert c.get("/api/reminders").json() == []


def test_impossible_batch_does_not_persist(authenticated):
    c = authenticated
    task = c.post(
        "/api/tasks",
        json={
            "title": "Impossible",
            "estimated_duration_minutes": 360,
            "deadline": (utcnow() + timedelta(minutes=5)).isoformat(),
        },
    ).json()
    result = c.post("/api/calendar/plan-batch", json={"tasks": [{"task_id": task["id"]}]}).json()
    assert result["feasible"] is False
    assert "proposal" not in result
    assert c.get("/api/calendar").json()["sessions"] == []


def test_event_conflict_does_not_overwrite_session(authenticated):
    c = authenticated
    task = c.post("/api/tasks", json={"title": "Study"}).json()
    plan = c.post("/api/calendar/plan", json={"task_id": task["id"]}).json()
    c.post(f"/api/proposals/{plan['proposal']['id']}/decision", json={"accept": True})
    slot = plan["slots"][0]
    response = c.post(
        "/api/events",
        json={"title": "Conflicting meeting", "start_time": slot["start"], "end_time": slot["end"]},
    )
    assert response.status_code == 409
    assert len(c.get("/api/calendar").json()["sessions"]) == 1


def test_concurrent_acceptance_cannot_double_book(authenticated):
    from concurrent.futures import ThreadPoolExecutor

    c = authenticated
    proposals = []
    for title in ["First", "Second"]:
        task = c.post("/api/tasks", json={"title": title}).json()
        proposals.append(c.post("/api/calendar/plan", json={"task_id": task["id"]}).json()["proposal"]["id"])

    def accept(ident):
        return c.post(f"/api/proposals/{ident}/decision", json={"accept": True}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(accept, proposals))
    assert sorted(statuses) == [200, 409]
    assert len(c.get("/api/calendar").json()["sessions"]) == 1


def test_zero_reminder_id_is_validation_error(authenticated):
    response = authenticated.post(
        "/api/reminders",
        json={
            "task_id": 0,
            "message": "Invalid",
            "reminder_time": (utcnow() + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 422
