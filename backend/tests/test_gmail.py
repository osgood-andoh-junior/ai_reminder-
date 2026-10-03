import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import select
from app import schemas
from app.core.config import settings
from app.core.time_context import TimeContext
from app.db.models import (
    User,
    IntegrationConnection,
    GoogleCalendarConnection,
    OAuthState,
    ExternalMessage,
    DetectedCommitment,
    Task,
    CalendarEvent,
    ScheduledTask,
    Reminder,
    Proposal,
)
from app.integrations.gmail import GmailProvider, SCOPE, ProviderError, message_text
from app.integrations.providers import EmailMessage
from app.integrations.extraction import extract, ExtractionUnavailable
from app.services.application import Application
from app.services.integrations import sync_gmail
from app.services import commitments
from app.agent.tools import Registry

NOW = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)


@pytest.fixture
def configured(monkeypatch):
    c = settings()
    monkeypatch.setattr(c, "google_client_id", "test-client")
    monkeypatch.setattr(c, "google_client_secret", "test-secret")
    monkeypatch.setattr(c, "token_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr("app.core.clock.utcnow", lambda: NOW)
    return SimpleNamespace(
        gmail_redirect_uri=c.gmail_redirect_uri, token_encryption_key=c.token_encryption_key
    )


def connection(db, user, **extra):
    tokens = {
        "access_token": "private-access",
        "refresh_token": "private-refresh",
        "scope": SCOPE,
        "expires_at": NOW.timestamp() + 3600,
        **extra,
    }
    row = IntegrationConnection(
        user_id=user.id,
        provider="gmail",
        account="mail@example.test",
        encrypted_tokens=Fernet(settings().token_encryption_key.encode())
        .encrypt(json.dumps(tokens).encode())
        .decode(),
    )
    db.add(row)
    db.flush()
    return row


def model(candidates):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps({"commitments": candidates}))

    return SimpleNamespace(responses=SimpleNamespace(create=create), calls=calls)


def email(text="Your assignment is due tomorrow at 11:59 PM."):
    return EmailMessage("m1", "Assignment", "Tutor <tutor@example.test>", text[:500], NOW, text)


def candidate(**extra):
    return {
        "title": "Assignment",
        "type": "deadline",
        "date_phrase": "tomorrow",
        "time_phrase": "11:59 PM",
        "evidence": "assignment is due tomorrow",
        "confidence": 0.9,
        "reason": "An explicit assignment deadline.",
        **extra,
    }


def seed_commitment(db, user):
    msg = ExternalMessage(
        user_id=user.id,
        provider="gmail",
        account="mail@example.test",
        external_id="m1",
        subject="Assignment",
        sender="Tutor",
        snippet="Due tomorrow",
        status="PROCESSED",
    )
    db.add(msg)
    db.flush()
    item = DetectedCommitment(
        user_id=user.id,
        message_id=msg.id,
        title="Assignment",
        type="deadline",
        deadline=NOW + timedelta(days=2),
        confidence=0.9,
        reason="Possible deadline",
        unresolved=["Confirm duration"],
    )
    db.add(item)
    db.flush()
    return item


def test_oauth_scope_state_replay_and_safe_status(authenticated, database, configured, monkeypatch):
    c = authenticated
    query = parse_qs(urlparse(c.post("/api/integrations/gmail/connect").json()["url"]).query)
    assert query["scope"] == [SCOPE]
    assert query["redirect_uri"] == [configured.gmail_redirect_uri]
    state = query["state"][0]
    assert (
        c.get(f"/api/calendar/google/callback?state={state}&code=x", follow_redirects=False).status_code
        == 400
    )

    def request(method, url, **kwargs):
        body = (
            {"access_token": "private-access", "refresh_token": "private-refresh", "scope": SCOPE}
            if "token" in url
            else {"emailAddress": "mail@example.test"}
        )
        return httpx.Response(200, json=body, request=httpx.Request(method, url))

    monkeypatch.setattr("app.integrations.gmail.httpx.request", request)
    response = c.get(f"/api/integrations/gmail/callback?state={state}&code=x", follow_redirects=False)
    assert "gmail=connected" in response.headers["location"]
    assert (
        c.get(f"/api/integrations/gmail/callback?state={state}&code=x", follow_redirects=False).status_code
        == 400
    )
    response = c.get("/api/integrations")
    assert "private-access" not in response.text and "encrypted_tokens" not in response.text
    assert next(x for x in response.json() if x["id"] == "gmail")["state"] == "connected"
    with database() as db:
        assert db.scalar(select(IntegrationConnection)).encrypted_tokens != "private-access"


@pytest.mark.parametrize("failure", ["denied", "missing_scope", "provider_error", "expired"])
def test_oauth_failures_are_graceful(authenticated, database, configured, monkeypatch, failure):
    c = authenticated
    state = parse_qs(urlparse(c.post("/api/integrations/gmail/connect").json()["url"]).query)["state"][0]
    if failure == "expired":
        with database() as db:
            db.scalar(select(OAuthState)).expires_at = NOW - timedelta(seconds=1)
            db.commit()
    monkeypatch.setattr(
        "app.api.integrations.request", lambda *a, **k: {"access_token": "private", "scope": ""}
    )
    if failure == "provider_error":

        def fail(*a, **k):
            raise ProviderError("google_unavailable")

        monkeypatch.setattr("app.api.integrations.request", fail)
    suffix = "error=access_denied" if failure == "denied" else "code=x"
    response = c.get(f"/api/integrations/gmail/callback?state={state}&{suffix}", follow_redirects=False)
    assert response.status_code == (400 if failure == "expired" else 303)
    assert c.get("/api/integrations/gmail/status").json()["state"] == "not_connected"


def test_cross_user_oauth_and_commitment_ownership(authenticated, database, configured):
    c = authenticated
    state = parse_qs(urlparse(c.post("/api/integrations/gmail/connect").json()["url"]).query)["state"][0]
    with database() as db:
        item = seed_commitment(db, db.scalar(select(User)))
        ident = item.id
        db.commit()
    c.post("/api/auth/logout")
    assert c.get("/api/integrations").status_code == 401
    assert c.post("/api/integrations/gmail/sync").status_code == 401
    c.post(
        "/api/auth/register",
        json={"name": "Other", "email": "other@example.com", "password": "another-secure-password"},
    )
    assert (
        c.get(f"/api/integrations/gmail/callback?state={state}&code=x", follow_redirects=False).status_code
        == 400
    )
    assert c.get("/api/integrations/commitments").json() == []
    assert c.get(f"/api/integrations/commitments/{ident}").status_code == 404
    assert (
        c.post(
            f"/api/integrations/commitments/{ident}/propose",
            json={"action": "dismiss", "revision": 0, "title": "Other"},
        ).status_code
        == 404
    )


def test_extraction_relative_absolute_ambiguous_and_no_tools():
    client = model([candidate()])
    value = extract(email(), TimeContext(NOW, "Africa/Accra"), client)[0]
    assert value["deadline"] == datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)
    assert value["estimated_duration_minutes"] is None
    assert client.calls[0]["store"] is False and "tools" not in client.calls[0]
    text = "Your interview is October 7 at 10 AM until 11 AM."
    value = extract(
        email(text),
        TimeContext(NOW, "Asia/Kolkata"),
        model(
            [
                candidate(
                    title="Interview",
                    type="meeting",
                    date_phrase="October 7",
                    time_phrase="10 AM",
                    end_time_phrase="11 AM",
                    evidence="interview is October 7",
                )
            ]
        ),
    )[0]
    assert value["start_time"] == datetime(2026, 10, 7, 4, 30, tzinfo=timezone.utc)
    value = extract(
        email("Let's meet tomorrow at 3."),
        TimeContext(NOW, "UTC"),
        model([candidate(type="meeting", time_phrase="3", evidence="meet tomorrow")]),
    )[0]
    assert value["start_time"] is None and value["unresolved"]
    assert extract(email("Your receipt: thanks for shopping"), TimeContext(NOW, "UTC"), model([])) == []


def test_hallucinated_dates_and_ai_failure_never_become_candidates(monkeypatch):
    with pytest.raises(ExtractionUnavailable):
        extract(email(), TimeContext(NOW, "UTC"), model([candidate(date_phrase="2030-01-01")]))
    monkeypatch.setattr(settings(), "openai_api_key", "")
    with pytest.raises(ExtractionUnavailable, match="ai_unavailable"):
        extract(email(), TimeContext(NOW, "UTC"))
    bad = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **k: SimpleNamespace(output_text="not JSON"))
    )
    with pytest.raises(ExtractionUnavailable):
        extract(email(), TimeContext(NOW, "UTC"), bad)


def test_sync_deduplicates_and_never_creates_tasks(authenticated, database, configured, monkeypatch):
    with database() as db:
        user = db.scalar(select(User))
        connection(db, user)
        s = Application(db, user)
        provider = GmailProvider(s)
        monkeypatch.setattr(provider, "recent_ids", lambda: ["m1"])
        monkeypatch.setattr(provider, "read_message", lambda _: email())

        def extraction(m, context):
            return extract(m, context, model([candidate()]))

        assert sync_gmail(s, provider, extraction)["detected"] == 1
        assert sync_gmail(s, provider, extraction)["checked"] == 0
        assert len(list(db.scalars(select(DetectedCommitment)))) == 1
        assert db.scalar(select(Task)) is None and db.scalar(select(CalendarEvent)) is None
        assert not hasattr(db.scalar(select(ExternalMessage)), "body")


@pytest.mark.parametrize(
    "code", ["access_expired_or_revoked", "permission_denied", "rate_limited", "google_unavailable"]
)
def test_provider_failure_marks_attention_and_manual_tasks_still_work(
    authenticated, database, configured, monkeypatch, code
):
    with database() as db:
        connection(db, db.scalar(select(User)))
        db.commit()

    def fail(*a, **k):
        raise ProviderError(code)

    monkeypatch.setattr(GmailProvider, "recent_ids", fail)
    assert authenticated.post("/api/integrations/gmail/sync").json()["error"] == code
    assert authenticated.get("/api/integrations/gmail/status").json()["state"] == "needs_attention"
    assert authenticated.post("/api/tasks", json={"title": "Manual task"}).status_code == 201


def test_refresh_retains_encrypted_refresh_token_and_scope_checks(
    authenticated, database, configured, monkeypatch
):
    with database() as db:
        user = db.scalar(select(User))
        row = connection(db, user, expires_at=0)
        provider = GmailProvider(Application(db, user))
        monkeypatch.setattr(
            "app.integrations.gmail.request",
            lambda *a, **k: {"access_token": "new-access", "expires_in": 3600},
        )
        assert provider.token() == "new-access"
        assert provider.tokens()["refresh_token"] == "private-refresh"
        assert "new-access" not in row.encrypted_tokens
        tokens = provider.tokens()
        tokens["scope"] = "calendar"
        row.encrypted_tokens = (
            Fernet(configured.token_encryption_key.encode()).encrypt(json.dumps(tokens).encode()).decode()
        )
        with pytest.raises(ProviderError, match="missing_gmail_scope"):
            provider.token()


def test_mime_html_attachments_and_bounded_search(authenticated, database, configured, monkeypatch):
    def encode(s):
        return base64.urlsafe_b64encode(s.encode()).decode()

    text = message_text(
        {
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": encode("<p>Meet tomorrow</p><script>bad()</script>")},
                },
                {"mimeType": "text/plain", "filename": "secret.txt", "body": {"data": encode("attachment")}},
            ]
        },
        1000,
    )
    assert "Meet tomorrow" in text and "bad()" not in text and "attachment" not in text
    with database() as db:
        user = db.scalar(select(User))
        connection(db, user)
        provider = GmailProvider(Application(db, user))
        calls = []

        def get(path, **kwargs):
            calls.append(kwargs)
            return {"messages": [{"id": "m1"}], "nextPageToken": "next"}

        monkeypatch.setattr(provider, "get", get)
        assert provider.recent_ids() == ["m1"] and len(calls) == 3
        assert "after:" in calls[0]["params"]["q"] and "-in:spam" in calls[0]["params"]["q"]


@pytest.mark.parametrize("action", ["task", "event", "schedule", "dismiss"])
def test_commitment_confirmation_is_atomic_and_replay_safe(authenticated, database, configured, action):
    with database() as db:
        user = db.scalar(select(User))
        item = seed_commitment(db, user)
        s = Application(db, user)
        review = commitments.Review(
            action=action,
            revision=0,
            title="Edited assignment",
            estimated_duration_minutes=120,
            deadline=NOW + timedelta(days=2),
            start_time=NOW + timedelta(days=1),
            end_time=NOW + timedelta(days=1, hours=1),
        )
        result = commitments.propose(s, item.id, review)
        assert result["proposal"]
        assert db.scalar(select(Task)) is None and db.scalar(select(CalendarEvent)) is None
        proposal_id = result["proposal"]["id"]
        s.decide(proposal_id, True)
        assert item.status == ("DISMISSED" if action == "dismiss" else "ACCEPTED")
        if action in {"task", "schedule"}:
            assert db.scalar(select(Task)).title == "Edited assignment"
        if action == "event":
            assert db.scalar(select(CalendarEvent)).title == "Edited assignment"
        if action == "schedule":
            assert len(list(db.scalars(select(ScheduledTask)))) == 2
            assert db.scalar(select(Reminder)) is not None
        with pytest.raises(HTTPException):
            s.decide(proposal_id, True)


def test_rejection_stale_review_conflict_and_no_availability(authenticated, database, configured):
    with database() as db:
        user = db.scalar(select(User))
        item = seed_commitment(db, user)
        s = Application(db, user)
        review = commitments.Review(
            action="schedule",
            revision=0,
            title="Study",
            estimated_duration_minutes=120,
            deadline=NOW + timedelta(days=1),
        )
        first = commitments.propose(s, item.id, review)["proposal"]
        with pytest.raises(HTTPException):
            commitments.propose(s, item.id, review)
        s.decide(first["id"], False)
        assert item.status == "PENDING" and db.scalar(select(Task)) is None
        review.revision = item.revision
        second = commitments.propose(s, item.id, review)["proposal"]
        slot = second["payload"]["plan"]["slots"][0]
        s.save_event(schemas.EventInput(title="New conflict", start_time=slot["start"], end_time=slot["end"]))
        with pytest.raises(HTTPException, match="Availability changed"):
            s.decide(second["id"], True)
        assert db.scalar(select(Task)) is None
        review.revision = item.revision
        review.deadline = NOW + timedelta(minutes=1)
        impossible = commitments.propose(s, item.id, review)
        assert impossible["proposal"] is None and not impossible["plan"]["feasible"]


def test_agent_uses_proposals_and_cannot_bypass_import_confirmation(authenticated, database, configured):
    with database() as db:
        user = db.scalar(select(User))
        item = seed_commitment(db, user)
        registry = Registry(Application(db, user))
        registry.execute("list_detected_commitments", {})
        with pytest.raises(ValueError, match="confirmation cannot be bypassed"):
            registry.execute("create_task", {"title": "Email task"})
        result = registry.execute(
            "propose_commitment",
            {
                "commitment_id": item.id,
                "review": {"action": "dismiss", "revision": item.revision, "title": item.title},
            },
        )
        assert result["proposal"]["status"] == "PENDING" and item.status == "PENDING"


def test_disconnect_removes_data_but_preserves_calendar_and_approved_tasks(
    authenticated, database, configured
):
    with database() as db:
        user = db.scalar(select(User))
        connection(db, user)
        item = seed_commitment(db, user)
        db.add(GoogleCalendarConnection(user_id=user.id, encrypted_tokens="existing-calendar"))
        s = Application(db, user)
        s.create_task(schemas.TaskInput(title="Existing approved task"))
        commitments.propose(s, item.id, commitments.Review(action="dismiss", revision=0, title=item.title))
        db.commit()
    result = authenticated.post("/api/integrations/gmail/disconnect", json={"revoke": False})
    assert result.json()["disconnected"]
    with database() as db:
        assert db.scalar(select(IntegrationConnection)) is None
        assert db.scalar(select(DetectedCommitment)) is None
        assert db.scalar(select(ExternalMessage)) is None
        assert db.scalar(select(GoogleCalendarConnection)) is not None
        assert db.scalar(select(Task)) is not None
        assert db.scalar(select(Proposal)).status == "REJECTED"
