from copy import deepcopy
from datetime import datetime, timezone
import json

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select

from app.agent.tools import Registry
from app.core import clock
from app.core.config import settings
from app.db.models import GoogleCalendarConnection, User, ChatMessage
from app.integrations import google_calendar as gc
from app.services.application import Application

NOW = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(clock, "utcnow", lambda: NOW)


@pytest.fixture
def connected(frozen, authenticated, database, monkeypatch):
    key = Fernet.generate_key()
    monkeypatch.setattr(settings(), "token_encryption_key", key.decode())
    with database() as db:
        user = db.scalar(select(User))
        db.add(
            GoogleCalendarConnection(
                user_id=user.id,
                encrypted_tokens=Fernet(key)
                .encrypt(
                    json.dumps({"access_token": "test-secret", "expires_at": NOW.timestamp() + 3600}).encode()
                )
                .decode(),
            )
        )
        db.commit()
    events, calls = {}, []

    def request(method, url, **kwargs):
        # This transport rejects ANY attendee calendar or free/busy call, including new API paths.
        root = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
        assert url == root or url.startswith(root + "/"), url
        assert "freeBusy" not in url and "@" not in url
        assert kwargs["headers"]["Authorization"] == "Bearer test-secret"
        calls.append((method, url, deepcopy(kwargs)))
        ident = url.removeprefix(root).lstrip("/")
        if method == "GET":
            if not ident:
                return {"items": deepcopy(list(events.values())), "timeZone": "UTC"}
            if ident not in events:
                raise HTTPException(404, "Missing")
            return deepcopy(events[ident])
        if method == "POST":
            body = deepcopy(kwargs["json"])
            if body["id"] in events:
                raise HTTPException(409, "Exists")
            body.update(
                {
                    "etag": '"v1"',
                    "organizer": {"self": True, "email": "test@example.com"},
                    "htmlLink": "https://calendar.google.com/calendar/event?eid=test",
                }
            )
            for attendee in body["attendees"]:
                attendee["responseStatus"] = "needsAction"
            if "conferenceData" in body:
                body["conferenceData"]["createRequest"]["status"] = {"statusCode": "success"}
                body["conferenceData"]["entryPoints"] = [
                    {"entryPointType": "video", "uri": "https://meet.google.com/test-returned-link"}
                ]
            events[body["id"]] = body
            return deepcopy(body)
        assert kwargs["headers"]["If-Match"] == events[ident]["etag"]
        if method == "PATCH":
            events[ident].update(deepcopy(kwargs["json"]))
            events[ident]["etag"] = '"v2"'
            return deepcopy(events[ident])
        if method == "DELETE":
            del events[ident]
            return {}
        raise AssertionError(method)

    monkeypatch.setattr(gc, "google_request", request)
    return authenticated, events, calls


def draft(**changes):
    return {
        "title": "Project meeting",
        "start_time": "2026-10-04T15:00:00+00:00",
        "duration_minutes": 30,
        "attendees": [{"name": "Elliot", "email": "elliot@example.com"}],
        "google_meet": True,
        **changes,
    }


def propose(c, body=None, ident=None):
    r = c.post(f"/api/meetings/{ident}/propose" if ident else "/api/meetings/propose", json=body or draft())
    assert r.status_code == 200, r.text
    return r.json()["proposal"]


def accept(c, p):
    return c.post(f"/api/proposals/{p['id']}/decision", json={"accept": True})


def created(connected):
    c, events, calls = connected
    p = propose(c)
    r = accept(c, p)
    assert r.status_code == 200, r.text
    return r.json()["meeting"]


@pytest.mark.parametrize("count", [1, 3])
def test_invitation_confirmation_meet_and_no_attendee_calendar_access(connected, count):
    c, events, calls = connected
    people = [{"name": f"Person {i}", "email": f"person{i}@example.com"} for i in range(count)]
    p = propose(c, draft(attendees=people))
    assert not events and all(method == "GET" for method, _, _ in calls)
    assert "test-secret" not in json.dumps(p)
    r = accept(c, p)
    assert r.status_code == 200, r.text
    assert len(events) == 1
    post = next(kwargs for method, _, kwargs in calls if method == "POST")
    assert post["params"] == {"sendUpdates": "all", "conferenceDataVersion": 1}
    assert len(post["json"]["attendees"]) == count
    assert post["json"]["start"]["timeZone"] == "Africa/Accra"
    assert len(post["json"]["conferenceData"]["createRequest"]["requestId"]) == 64
    assert r.json()["meeting"]["meeting_metadata"]["meet_url"] == "https://meet.google.com/test-returned-link"
    assert accept(c, p).status_code == 409
    assert sum(method == "POST" for method, _, _ in calls) == 1


def test_cancel_declined_proposal_never_sends(connected):
    c, events, calls = connected
    p = propose(c)
    assert c.post(f"/api/proposals/{p['id']}/decision", json={"accept": False}).status_code == 200
    assert accept(c, p).status_code == 409
    assert not events


def test_contacts_missing_ambiguous_deduplicated_and_explicit_save(connected, database):
    c, events, _ = connected
    body = draft(attendees=[{"name": "Elliot"}, {"name": "Ama", "email": "ama@example.com"}])
    r = c.post("/api/meetings/propose", json=body).json()
    assert r["proposal"] is None and r["missing_contacts"] == [{"name": "Elliot", "reason": "unknown"}]
    for email in ["ELLIOT@example.com", "elliot@example.com"]:
        p = c.post("/api/contacts/propose", json={"name": "Elliot", "email": email}).json()
        assert accept(c, p).status_code == 200
    assert len(c.get("/api/contacts").json()) == 1
    assert len(propose(c, body)["payload"]["meeting"]["attendees"]) == 2
    p = c.post("/api/contacts/propose", json={"name": "Elliot", "email": "other@example.com"}).json()
    assert accept(c, p).status_code == 200
    assert c.post("/api/meetings/propose", json=body).json()["missing_contacts"][0]["reason"] == "ambiguous"
    contact = c.get("/api/contacts").json()[0]
    assert c.delete(f"/api/contacts/{contact['id']}").status_code == 204
    assert not events


def test_contacts_not_saved_by_invitation(connected):
    created(connected)
    assert connected[0].get("/api/contacts").json() == []


@pytest.mark.parametrize(
    "changes",
    [
        {"attendees": [{"name": "Elliot", "email": "not-an-email"}]},
        {"start_time": "2026-10-04T15:00:00"},
        {"duration_minutes": 0},
        {"start_time": "2026-10-02T15:00:00Z"},
        {"confirmed": True},
        {"start_time": "2027-10-04T15:00:00Z"},
    ],
)
def test_invalid_meeting_rejected(connected, changes):
    assert connected[0].post("/api/meetings/propose", json=draft(**changes)).status_code == 422


def test_organizer_conflict_and_contiguous_alternatives(connected):
    c, events, calls = connected
    c.post(
        "/api/events",
        json={"title": "Busy", "start_time": "2026-10-04T15:00:00Z", "end_time": "2026-10-04T16:00:00Z"},
    )
    r = c.post("/api/meetings/propose", json=draft()).json()
    assert r["proposal"] is None and r["conflict"]
    assert r["alternatives"][0]["start"] == "2026-10-04T16:00:00+00:00"
    r = c.post(
        "/api/meetings/availability",
        json={"start": "2026-10-04T15:00:00Z", "end": "2026-10-04T17:00:00Z", "duration_minutes": 45},
    ).json()
    assert r["slots"][0]["start"] == "2026-10-04T16:00:00+00:00"
    assert all(slot["minutes"] == 45 for slot in r["slots"])


def test_rechecks_conflicts_at_confirmation(connected):
    c, events, _ = connected
    p = propose(c)
    c.post(
        "/api/events",
        json={
            "title": "New conflict",
            "start_time": "2026-10-04T15:00:00Z",
            "end_time": "2026-10-04T16:00:00Z",
        },
    )
    assert accept(c, p).status_code == 409
    assert not events


def test_reschedule_preserves_event_and_conference_then_cancels(connected):
    c, events, calls = connected
    event = created(connected)
    p = propose(c, draft(start_time="2026-10-04T18:00:00Z", google_meet=False), event["id"])
    assert p["payload"]["before"]["start_time"] == "2026-10-04T15:00:00+00:00"
    r = accept(c, p)
    assert r.status_code == 200, r.text
    assert len(events) == 1
    assert r.json()["meeting"]["id"] == event["id"]
    assert r.json()["meeting"]["meeting_metadata"]["meet_url"]
    patch = next(kwargs for method, _, kwargs in calls if method == "PATCH")
    assert patch["params"]["sendUpdates"] == "all"
    assert "conferenceData" not in patch["json"]
    p = c.post(f"/api/meetings/{event['id']}/cancel").json()["proposal"]
    assert len(events) == 1
    assert accept(c, p).status_code == 200
    assert not events
    assert calls[-1][0] == "DELETE" and calls[-1][2]["params"]["sendUpdates"] == "all"


def test_rsvp_sync_lookup_and_ambiguity(connected):
    c, events, _ = connected
    event = created(connected)
    remote = next(iter(events.values()))
    remote["attendees"][0]["responseStatus"] = "accepted"
    assert (
        c.get(f"/api/meetings/{event['id']}").json()["meeting_metadata"]["attendees"][0]["response_status"]
        == "accepted"
    )
    assert c.get("/api/meetings?query=Elliot").json()["requires_selection"] is False
    assert accept(c, propose(c, draft(start_time="2026-10-05T15:00:00Z"))).status_code == 200
    r = c.get("/api/meetings?query=Elliot").json()
    assert r["requires_selection"] and len(r["meetings"]) == 2


@pytest.mark.parametrize("change", ["etag", "organizer", "recurring"])
def test_stale_or_unauthorized_change_blocked(connected, change):
    c, events, _ = connected
    event = created(connected)
    p = propose(c, draft(start_time="2026-10-04T18:00:00Z"), event["id"])
    remote = next(iter(events.values()))
    if change == "etag":
        remote["etag"] = '"changed"'
    elif change == "organizer":
        remote["organizer"]["self"] = False
    else:
        remote["recurringEventId"] = "series"
    assert accept(c, p).status_code == 409


def test_create_recovery_after_local_failure_does_not_reinvite(connected, monkeypatch):
    from app.services import meetings

    c, events, calls = connected
    p = propose(c)
    original = meetings.store_remote
    monkeypatch.setattr(
        meetings, "store_remote", lambda *_: (_ for _ in ()).throw(HTTPException(503, "Local failure"))
    )
    assert accept(c, p).status_code == 503
    assert len(events) == 1
    monkeypatch.setattr(meetings, "store_remote", original)
    assert accept(c, p).status_code == 200
    assert sum(method == "POST" for method, _, _ in calls) == 1


def test_cross_user_contacts_meetings_and_proposals(connected):
    c, _, _ = connected
    event = created(connected)
    p = propose(c, draft(start_time="2026-10-05T15:00:00Z"))
    contact = c.post("/api/contacts/propose", json={"name": "Elliot", "email": "elliot@example.com"}).json()
    accept(c, contact)
    cid = c.get("/api/contacts").json()[0]["id"]
    c.post("/api/auth/logout")
    assert (
        c.post(
            "/api/auth/register",
            json={"name": "Other", "email": "other@example.com", "password": "another-long-password"},
        ).status_code
        == 201
    )
    assert c.get("/api/contacts").json() == []
    assert c.delete(f"/api/contacts/{cid}").status_code == 404
    assert c.get(f"/api/meetings/{event['id']}").status_code == 404
    assert c.post(f"/api/meetings/{event['id']}/cancel").status_code == 404
    assert c.post(f"/api/meetings/{event['id']}/propose", json=draft()).status_code == 404
    assert accept(c, p).status_code == 404


def test_authentication_required(client):
    for path in ["/api/contacts", "/api/meetings", "/api/meetings/1"]:
        assert client.get(path).status_code == 401
    assert client.post("/api/meetings/propose", json=draft()).status_code == 401


def test_disconnected(frozen, authenticated):
    assert authenticated.post("/api/meetings/propose", json=draft()).status_code == 409


def test_relative_time_tools_and_no_confirmation_tool(connected, database):
    with database() as db:
        s = Application(db, db.scalar(select(User)))
        s.preferences().timezone = "America/New_York"
        reg = Registry(s, "Schedule a meeting with Elliot elliot@example.com tomorrow at 3 PM")
        body = draft(start_time={"reference": "time_0", "local_time": "15:00"})
        p = reg.execute("propose_meeting", body)["proposal"]
        assert p["payload"]["meeting"]["start_time"] == "2026-10-04T19:00:00+00:00"
        assert p["payload"]["meeting"]["end_time"] == "2026-10-04T19:30:00+00:00"
        assert not any("confirm" in name or name == "create_meeting" for name in reg.entries)
        with pytest.raises(ValueError):
            reg.execute("propose_meeting", draft())
        with pytest.raises(ValueError, match="Retrieve"):
            reg.execute("cancel_meeting", {"id": 999})


def test_email_clarification_resumes_original_server_resolved_time(connected, database):
    with database() as db:
        s = Application(db, db.scalar(select(User)))
        reg = Registry(s, "Meeting with Elliot tomorrow at 3 PM")
        result = reg.execute(
            "propose_meeting",
            draft(attendees=[{"name": "Elliot"}], start_time={"reference": "time_0", "local_time": "15:00"}),
        )
        db.add(
            ChatMessage(
                user_id=s.user.id,
                role="assistant",
                content="What email for Elliot?",
                actions=[{"tool": "propose_meeting", "ok": True, "result": result}],
            )
        )
        db.flush()
        followup = Registry(s, "elliot@example.com")
        resumed = followup.execute("get_pending_meeting_request", {})
        resumed["draft"]["attendees"][0]["email"] = "elliot@example.com"
        p = followup.execute("propose_meeting", resumed["draft"])["proposal"]
        assert p["payload"]["meeting"]["start_time"] == "2026-10-04T15:00:00+00:00"


def test_relative_window_can_propose_only_server_selected_slot(connected, database):
    with database() as db:
        s = Application(db, db.scalar(select(User)))
        reg = Registry(s, "Schedule a meeting with elliot@example.com tomorrow afternoon")
        slots = reg.execute(
            "find_my_availability",
            {
                "start": {"reference": "time_0", "edge": "start"},
                "end": {"reference": "time_0", "edge": "end"},
                "duration_minutes": 30,
            },
        )
        p = reg.execute("propose_meeting", draft(start_time=slots["slots"][0]["start"]))["proposal"]
        assert p and p["payload"]["meeting"]["duration_minutes"] == 30


def test_agent_cannot_invent_email_address(connected, database):
    with database() as db:
        s = Application(db, db.scalar(select(User)))
        reg = Registry(s, "Schedule a meeting with Elliot tomorrow at 3 PM")
        body = draft(start_time={"reference": "time_0", "local_time": "15:00"})
        with pytest.raises(ValueError, match="Never guess"):
            reg.execute("propose_meeting", body)
        reg = Registry(s, "Remember elliot@example.com for Elliot")
        with pytest.raises(ValueError, match="Never guess"):
            reg.execute("save_contact", {"name": "Elliot", "email": "liot@example.com"})
        reg = Registry(s, "Remember Elliot as elliot@example.com.")
        assert reg.execute("save_contact", {"name": "Elliot", "email": "elliot@example.com"})["kind"] == "save_contact"


def test_removing_final_attendee_is_confirmed_update(connected):
    c, events, calls = connected
    event = created(connected)
    p = propose(c, draft(attendees=[]), event["id"])
    assert next(iter(events.values()))["attendees"]
    assert accept(c, p).status_code == 200
    assert next(iter(events.values()))["attendees"] == []
    assert calls[-1][2]["params"]["sendUpdates"] == "all"


@pytest.mark.parametrize("operation", ["POST", "PATCH", "DELETE"])
def test_mutation_failure_keeps_proposal_pending(connected, database, monkeypatch, operation):
    from app.db.models import Proposal

    c, events, calls = connected
    if operation == "POST":
        p = propose(c)
    else:
        event = created(connected)
        p = (
            propose(c, draft(start_time="2026-10-04T18:00:00Z"), event["id"])
            if operation == "PATCH"
            else c.post(f"/api/meetings/{event['id']}/cancel").json()["proposal"]
        )
    original = gc.google_request
    before = deepcopy(events)

    def fail(method, *args, **kwargs):
        if method == operation:
            raise HTTPException(502, "Google Calendar unavailable")
        return original(method, *args, **kwargs)

    monkeypatch.setattr(gc, "google_request", fail)
    assert accept(c, p).status_code == 502
    assert events == before
    with database() as db:
        assert db.get(Proposal, p["id"]).status == "PENDING"


@pytest.mark.parametrize("status", ["pending", "failure"])
def test_conference_pending_or_failure_does_not_duplicate_successful_invitation(
    connected, monkeypatch, status
):
    c, events, calls = connected
    original = gc.google_request

    def conference(method, *args, **kwargs):
        remote = original(method, *args, **kwargs)
        if method == "POST":
            remote["conferenceData"].pop("entryPoints")
            remote["conferenceData"]["createRequest"]["status"]["statusCode"] = status
            events[remote["id"]] = deepcopy(remote)
        return remote

    monkeypatch.setattr(gc, "google_request", conference)
    r = accept(c, propose(c))
    assert r.status_code == 200
    metadata = r.json()["meeting"]["meeting_metadata"]
    assert metadata["conference_status"] == status and metadata["meet_url"] is None
    assert sum(method == "POST" for method, _, _ in calls) == 1


def test_meeting_without_conference_and_expired_proposal(connected, database):
    from app.db.models import Proposal

    c, events, calls = connected
    p = propose(c, draft(google_meet=False))
    assert accept(c, p).status_code == 200
    assert "conferenceData" not in next(iter(events.values()))
    p = propose(c, draft(start_time="2026-10-05T15:00:00Z"))
    with database() as db:
        db.get(Proposal, p["id"]).expires_at = NOW
        db.commit()
    # Strictly past expiry, retaining the same authenticated session.
    with database() as db:
        db.get(Proposal, p["id"]).expires_at = datetime(2026, 10, 3, 11, tzinfo=timezone.utc)
        db.commit()
    assert accept(c, p).status_code == 409
    assert len(events) == 1


@pytest.mark.parametrize("code", [401, 403, 500])
def test_google_errors_are_sanitized(monkeypatch, code):
    def failed(*args, **kwargs):
        return httpx.Response(
            code, request=httpx.Request("POST", "https://example.com"), json={"token": "secret"}
        )

    monkeypatch.setattr(httpx, "request", failed)
    with pytest.raises(HTTPException) as exc:
        gc.google_request("POST", "https://example.com")
    assert "secret" not in exc.value.detail
    assert exc.value.status_code == 502


@pytest.mark.parametrize("mode", ["expired", "revoked"])
def test_expired_and_revoked_token_never_send(connected, database, monkeypatch, mode):
    c, events, calls = connected
    with database() as db:
        connection = db.scalar(select(GoogleCalendarConnection))
        token = {"access_token": "expired", "expires_at": 0}
        if mode == "revoked":
            token["refresh_token"] = "revoked"
        connection.encrypted_tokens = (
            Fernet(settings().token_encryption_key.encode()).encrypt(json.dumps(token).encode()).decode()
        )
        db.commit()
    if mode == "revoked":
        monkeypatch.setattr(
            gc,
            "google_request",
            lambda *a, **k: (_ for _ in ()).throw(HTTPException(502, "Reconnect Google Calendar")),
        )
    assert c.post("/api/meetings/propose", json=draft()).status_code in {409, 502}
    assert not events and not calls
