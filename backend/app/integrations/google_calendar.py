import json
import secrets
from datetime import datetime, timedelta, time
from urllib.parse import urlencode, quote
from zoneinfo import ZoneInfo
import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select, delete
from app.api.routes import Service
from app.core.config import settings
from app.core.security import digest
from app.db.database import utcnow
from app.db.models import GoogleCalendarConnection, OAuthState, CalendarEvent, ScheduledTask
from app.services.calendar import CalendarService
from app.scheduling.scheduler import Slot, overlaps

router = APIRouter(prefix="/api/calendar/google")
SCOPE = "https://www.googleapis.com/auth/calendar.events"


def configured():
    c = settings()
    return bool(c.google_client_id and c.google_client_secret and c.token_encryption_key)


def cipher():
    if not configured():
        raise HTTPException(
            503, "Google Calendar is not configured. Add Google OAuth credentials and TOKEN_ENCRYPTION_KEY."
        )
    try:
        return Fernet(settings().token_encryption_key.encode())
    except ValueError:
        raise HTTPException(503, "Google token encryption is not configured correctly") from None


def google_request(method, url, **kwargs):
    try:
        response = httpx.request(method, url, timeout=20, **kwargs)
        response.raise_for_status()
        return response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        raise HTTPException(
            502, "Google Calendar could not complete the request. Try again or reconnect your account."
        ) from None


class GoogleCalendarService(CalendarService):
    def __init__(self, application):
        self.application = application
        self.connection = application.db.scalar(
            select(GoogleCalendarConnection).where(GoogleCalendarConnection.user_id == application.user.id)
        )
        if not self.connection:
            raise HTTPException(409, "Connect Google Calendar first")

    def token(self):
        try:
            tokens = json.loads(cipher().decrypt(self.connection.encrypted_tokens.encode()))
        except (InvalidToken, ValueError):
            raise HTTPException(
                409, "Stored Google credentials cannot be read. Reconnect Google Calendar"
            ) from None
        if tokens.get("expires_at", 0) < utcnow().timestamp() + 60:
            if not tokens.get("refresh_token"):
                raise HTTPException(409, "Google access expired. Reconnect your account")
            refreshed = google_request(
                "POST",
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings().google_client_id,
                    "client_secret": settings().google_client_secret,
                    "refresh_token": tokens["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
            tokens.update(refreshed)
            tokens["expires_at"] = utcnow().timestamp() + refreshed.get("expires_in", 3600)
            self.connection.encrypted_tokens = cipher().encrypt(json.dumps(tokens).encode()).decode()
        return tokens["access_token"]

    def request(self, method, suffix="", **kwargs):
        return google_request(
            method,
            "https://www.googleapis.com/calendar/v3/calendars/primary/events" + suffix,
            headers={"Authorization": "Bearer " + self.token()},
            **kwargs,
        )

    def get_events(self):
        result = []
        token = None
        self.window_start = utcnow() - timedelta(days=30)
        self.window_end = utcnow() + timedelta(days=90)
        for _ in range(100):
            params = {
                "timeMin": self.window_start.isoformat(),
                "timeMax": self.window_end.isoformat(),
                "singleEvents": "true",
                "maxResults": 2500,
            }
            if token:
                params["pageToken"] = token
            page = self.request("GET", params=params)
            self.calendar_timezone = page.get("timeZone", self.application.preferences().timezone)
            result.extend(page.get("items", []))
            token = page.get("nextPageToken")
            if not token:
                return result
        raise HTTPException(502, "Calendar is too large to sync safely in one request")

    def create_event(self, data):
        return self.request(
            "POST",
            json={
                "summary": data.title,
                "description": data.description,
                "start": {"dateTime": data.start_time.isoformat()},
                "end": {"dateTime": data.end_time.isoformat()},
            },
        )

    def update_event(self, ident, data):
        # Callers must resolve the external ID from an owned local event, never client IDs.
        item = self.application.own(CalendarEvent, ident)
        if item.source != "google":
            raise HTTPException(409, "This is not a Google event")
        return self.request(
            "PATCH",
            "/" + quote(item.external_id, safe=""),
            json={
                "summary": data.title,
                "description": data.description,
                "start": {"dateTime": data.start_time.isoformat()},
                "end": {"dateTime": data.end_time.isoformat()},
            },
        )

    def delete_event(self, ident):
        item = self.application.own(CalendarEvent, ident)
        if item.source != "google":
            raise HTTPException(409, "This is not a Google event")
        return self.request("DELETE", "/" + quote(item.external_id, safe=""))

    def find_free_slots(self, request):
        return self.application.plan(request, persist=False)

    def sync(self):
        remote = self.get_events()  # Fetch completely before changing local records.
        s = self.application
        s.lock()
        existing = list(
            s.db.scalars(
                select(CalendarEvent).where(
                    CalendarEvent.user_id == s.user.id, CalendarEvent.source == "google"
                )
            )
        )
        by_id = {e.external_id: e for e in existing}
        seen = set()
        for event in remote:
            if event.get("status") == "cancelled" or event.get("transparency") == "transparent":
                continue
            if any(
                a.get("self") and a.get("responseStatus") == "declined" for a in event.get("attendees", [])
            ):
                continue

            def instant(value):
                if "dateTime" in value:
                    parsed = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
                    return (
                        parsed
                        if parsed.tzinfo
                        else parsed.replace(tzinfo=ZoneInfo(value.get("timeZone", self.calendar_timezone)))
                    )
                return datetime.combine(
                    datetime.fromisoformat(value["date"]).date(), time(), ZoneInfo(self.calendar_timezone)
                )

            start, end = instant(event["start"]), instant(event["end"])
            item = by_id.get(event["id"]) or CalendarEvent(
                user_id=s.user.id, external_id=event["id"], source="google"
            )
            item.title = event.get("summary", "Busy")[:200]
            item.description = event.get("description", "")[:5000]
            item.start_time, item.end_time = start, end
            item.is_recurring = bool(event.get("recurringEventId"))
            item.event_type = "FIXED"
            s.db.add(item)
            seen.add(event["id"])
        for item in existing:
            if (
                item.external_id not in seen
                and item.start_time < self.window_end
                and item.end_time > self.window_start
            ):
                s.db.delete(item)
        self.connection.synced_at = utcnow()
        s.db.flush()
        events = list(s.db.scalars(select(CalendarEvent).where(CalendarEvent.user_id == s.user.id)))
        sessions = list(
            s.db.scalars(
                select(ScheduledTask).where(
                    ScheduledTask.user_id == s.user.id, ScheduledTask.status == "SCHEDULED"
                )
            )
        )
        affected = sorted(
            {
                t.task_id
                for t in sessions
                for e in events
                if overlaps(Slot(t.start_time, t.end_time), Slot(e.start_time, e.end_time))
            }
        )
        s.activity("GOOGLE_SYNCED", {"imported": len(seen), "conflicting_task_ids": affected})
        return {"imported": len(seen), "conflicts": affected}


@router.get("/status")
def status(s: Service):
    connection = s.db.scalar(
        select(GoogleCalendarConnection).where(GoogleCalendarConnection.user_id == s.user.id)
    )
    return {
        "configured": configured(),
        "connected": bool(connection),
        "synced_at": connection.synced_at if connection else None,
    }


@router.post("/connect")
def connect(s: Service):
    cipher()
    state = secrets.token_urlsafe(32)
    s.db.add(
        OAuthState(user_id=s.user.id, token_hash=digest(state), expires_at=utcnow() + timedelta(minutes=10))
    )
    return {
        "url": "https://accounts.google.com/o/oauth2/v2/auth?"
        + urlencode(
            {
                "client_id": settings().google_client_id,
                "redirect_uri": settings().google_redirect_uri,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )
    }


@router.get("/callback")
def callback(s: Service, state: str = "", code: str = "", error: str = ""):
    s.lock()
    saved = s.db.scalar(
        select(OAuthState).where(
            OAuthState.token_hash == digest(state),
            OAuthState.user_id == s.user.id,
            OAuthState.expires_at > utcnow(),
        )
    )
    if not saved:
        raise HTTPException(400, "OAuth state expired or invalid; start again from Settings")
    s.db.delete(saved)
    s.db.commit()
    if error or not code:
        return RedirectResponse(settings().frontend_url + "/settings?google=declined", status_code=303)
    tokens = google_request(
        "POST",
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings().google_client_id,
            "client_secret": settings().google_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings().google_redirect_uri,
        },
    )
    if SCOPE not in tokens.get("scope", "").split():
        raise HTTPException(400, "Google Calendar permission was not granted")
    tokens["expires_at"] = utcnow().timestamp() + tokens.get("expires_in", 3600)
    existing = s.db.scalar(
        select(GoogleCalendarConnection).where(GoogleCalendarConnection.user_id == s.user.id)
    )
    connection = existing or GoogleCalendarConnection(user_id=s.user.id)
    connection.encrypted_tokens = cipher().encrypt(json.dumps(tokens).encode()).decode()
    s.db.add(connection)
    s.activity("GOOGLE_CONNECTED")
    return RedirectResponse(settings().frontend_url + "/settings?google=connected", status_code=303)


@router.post("/sync")
def sync(s: Service):
    return GoogleCalendarService(s).sync()


@router.post("/disconnect")
def disconnect(s: Service):
    s.lock()
    s.db.execute(delete(GoogleCalendarConnection).where(GoogleCalendarConnection.user_id == s.user.id))
    s.db.execute(
        delete(CalendarEvent).where(CalendarEvent.user_id == s.user.id, CalendarEvent.source == "google")
    )
    s.activity("GOOGLE_DISCONNECTED")
    return {"message": "Disconnected locally. You can also revoke access in your Google account permissions."}
