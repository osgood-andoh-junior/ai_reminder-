"""Organizer-only meeting operations. Mutations execute exclusively through Proposal decisions."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from urllib.parse import quote
from uuid import uuid4

from fastapi import HTTPException
from pydantic import EmailStr, Field, field_validator, model_validator
from sqlalchemy import select

from app.schemas import Input, aware
from app.db.models import CalendarEvent, Contact, ScheduledTask, ChatMessage
from app.services.application import serialize
from app.scheduling.scheduler import Slot, overlaps, meeting_slots


class Attendee(Input):
    name: str = Field(default="", max_length=100)
    email: EmailStr | None = None

    @model_validator(mode="after")
    def identified(self):
        if not self.name and not self.email:
            raise ValueError("Provide an attendee name or email")
        return self


class ContactInput(Input):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr


class Lookup(Input):
    query: str = Field(default="", max_length=200)


class Availability(Input):
    start: datetime
    end: datetime
    duration_minutes: int = Field(ge=5, le=1440)
    _aware = field_validator("start", "end")(aware)

    @model_validator(mode="after")
    def ordered(self):
        if not self.start < self.end or self.end - self.start > timedelta(days=90):
            raise ValueError("Use an ordered search window of at most 90 days")
        return self


class MeetingInput(Input):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    start_time: datetime
    duration_minutes: int = Field(ge=5, le=1440)
    attendees: list[Attendee] = Field(default_factory=list, max_length=100)
    location: str = Field(default="", max_length=500)
    google_meet: bool = False
    _aware = field_validator("start_time")(aware)


class ChangeMeeting(Input):
    id: int = Field(gt=0)
    meeting: MeetingInput


def google(s):
    from app.integrations.google_calendar import GoogleCalendarService

    return GoogleCalendarService(s)


def contacts(s, query=""):
    rows = s.db.scalars(select(Contact).where(Contact.user_id == s.user.id).order_by(Contact.name))
    return [
        serialize(c)
        for c in rows
        if not query or query.casefold() in c.name.casefold() or query.casefold() in c.email.casefold()
    ]


def propose_contact(s, data):
    return s.proposal("save_contact", {"name": data.name, "email": str(data.email).lower()})


def pending_request(s):
    """Resume server-validated intent after an email clarification, without re-resolving tomorrow."""
    for message in s.rows(ChatMessage, 16):
        if message.created_at < s.now - timedelta(minutes=30):
            continue
        for action in reversed(message.actions):
            if action.get("ok") and action.get("tool") in {"propose_meeting", "reschedule_meeting"}:
                result = action.get("result", {})
                if result.get("proposal"):
                    return {"message": "A proposal already exists. Review that proposal."}
                if result.get("draft"):
                    return {
                        "draft": result["draft"],
                        "event_id": result.get("event_id"),
                        "alternatives": result.get("alternatives", []),
                    }
    return {"message": "No recent unfinished meeting request. Ask for the meeting details."}


def resolve(s, attendees):
    saved = contacts(s)
    resolved, missing = {}, []
    for person in attendees:
        email = str(person.email).lower() if person.email else None
        if not email:
            matches = [c for c in saved if c["name"].casefold() == person.name.casefold()]
            if len(matches) != 1:
                missing.append({"name": person.name, "reason": "ambiguous" if matches else "unknown"})
                continue
            email = matches[0]["email"]
        resolved[email] = {"name": person.name, "email": email}
    return list(resolved.values()), missing


def own_event(s, ident):
    item = s.own(CalendarEvent, ident)
    if item.source != "google":
        raise HTTPException(409, "Choose a meeting from your connected Google Calendar")
    return item


def remote_event(s, ident, writable=False):
    item = own_event(s, ident)
    remote = google(s).request("GET", "/" + quote(item.external_id, safe=""))
    if remote.get("status") == "cancelled":
        raise HTTPException(409, "This meeting was cancelled")
    if writable and (
        not remote.get("organizer", {}).get("self")
        or remote.get("recurrence")
        or remote.get("recurringEventId")
        or "date" in remote.get("start", {})
    ):
        raise HTTPException(
            409,
            "Only single timed meetings you organize can be changed here. Use Google Calendar for recurring or all-day events.",
        )
    if writable and (remote.get("attendeesOmitted") or not remote.get("etag")):
        raise HTTPException(
            409, "The complete meeting could not be read. Refresh Google Calendar and try again."
        )
    return item, remote


def snapshot(remote):
    return {
        "title": remote.get("summary", "Meeting"),
        "description": remote.get("description", ""),
        "start_time": remote["start"].get("dateTime"),
        "end_time": remote["end"].get("dateTime"),
        "attendees": [
            {"name": a.get("displayName", ""), "email": a.get("email", "")}
            for a in remote.get("attendees", [])
        ],
        "location": remote.get("location", ""),
    }


def get_meeting(s, ident):
    from app.integrations.google_calendar import meeting_metadata

    item, remote = remote_event(s, ident)
    if remote.get("start", {}).get("dateTime") and remote.get("end", {}).get("dateTime"):
        s.lock()
        return store_remote(s, remote)
    item.meeting_metadata = meeting_metadata(remote)
    s.db.flush()
    return serialize(item)


def find_meetings(s, query=""):
    google(s).sync()
    matches = []
    for item in s.rows(CalendarEvent):
        if item.source != "google":
            continue
        text = " ".join(
            [
                item.title,
                *[
                    a.get("name", "") + " " + a.get("email", "")
                    for a in (item.meeting_metadata or {}).get("attendees", [])
                ],
            ]
        )
        if query.casefold() in text.casefold():
            matches.append(serialize(item))
    return {
        "meetings": matches,
        "requires_selection": len(matches) != 1,
        "message": "Choose the intended event when several match; attendee availability is unknown.",
    }


def busy(s, exclude_id=None):
    events = s.db.scalars(select(CalendarEvent).where(CalendarEvent.user_id == s.user.id))
    sessions = s.db.scalars(
        select(ScheduledTask).where(ScheduledTask.user_id == s.user.id, ScheduledTask.status == "SCHEDULED")
    )
    return [Slot(e.start_time, e.end_time) for e in events if e.id != exclude_id] + [
        Slot(t.start_time, t.end_time) for t in sessions
    ]


def availability(s, data):
    if data.end > s.now + timedelta(days=89):
        raise HTTPException(422, "Search within the next 89 days")
    google(s).sync()
    return {
        "slots": meeting_slots(max(data.start, s.now), data.end, data.duration_minutes, busy(s)),
        "timezone": s.preferences().timezone,
        "message": "These times are free on your calendar only.",
    }


def check_time(s, data, exclude_id=None):
    if data.start_time <= s.now or data.start_time + timedelta(
        minutes=data.duration_minutes
    ) > s.now + timedelta(days=89):
        raise HTTPException(422, "Choose a future meeting ending within the next 89 days")
    start = data.start_time.astimezone(timezone.utc)
    end = start + timedelta(minutes=data.duration_minutes)
    occupied = busy(s, exclude_id)
    if any(overlaps(Slot(start, end), b) for b in occupied):
        return {
            "proposal": None,
            "conflict": True,
            "message": "Your calendar has a conflict. Choose an alternative; attendee availability is unknown.",
            "alternatives": meeting_slots(
                start,
                min(start + timedelta(days=7), s.now + timedelta(days=89)),
                data.duration_minutes,
                occupied,
            ),
        }
    return {"start_time": start.isoformat(), "end_time": end.isoformat()}


def propose(s, data, ident=None):
    if not ident and not data.attendees:
        raise HTTPException(422, "Add at least one attendee to a new meeting")
    if ident:
        own_event(s, ident)
    resolved, missing = resolve(s, data.attendees)
    if missing:
        return {
            "proposal": None,
            "draft": data.model_dump(mode="json"),
            "event_id": ident,
            "missing_contacts": missing,
            "message": "Ask for the missing email addresses; never guess an address.",
        }
    s.lock()
    service = google(s)
    service.sync()
    before, etag = None, None
    if ident:
        _, remote = remote_event(s, ident, writable=True)
        before, etag = snapshot(remote), remote["etag"]
    timing = check_time(s, data, ident)
    if timing.get("conflict"):
        return {**timing, "draft": data.model_dump(mode="json"), "event_id": ident}
    meeting = {
        **data.model_dump(mode="json"),
        **timing,
        "attendees": resolved,
        "timezone": s.preferences().timezone,
    }
    return {
        "proposal": s.proposal(
            "meeting_update" if ident else "meeting_create",
            {
                "meeting": meeting,
                "event_id": ident,
                "before": before,
                "etag": etag,
                "operation_key": uuid4().hex,
            },
        )
    }


def cancel(s, ident):
    _, remote = remote_event(s, ident, writable=True)
    return {
        "proposal": s.proposal(
            "meeting_cancel",
            {
                "event_id": ident,
                "before": snapshot(remote),
                "etag": remote["etag"],
                "operation_key": uuid4().hex,
            },
        )
    }


def store_remote(s, remote):
    from app.integrations.google_calendar import meeting_metadata

    item = s.db.scalar(
        select(CalendarEvent).where(
            CalendarEvent.user_id == s.user.id, CalendarEvent.external_id == remote["id"]
        )
    )
    item = item or CalendarEvent(user_id=s.user.id, source="google", external_id=remote["id"])
    item.title, item.description = remote.get("summary", "Meeting"), remote.get("description", "")
    item.is_recurring = bool(remote.get("recurringEventId") or remote.get("recurrence"))
    item.start_time = datetime.fromisoformat(remote["start"]["dateTime"].replace("Z", "+00:00"))
    item.end_time = datetime.fromisoformat(remote["end"]["dateTime"].replace("Z", "+00:00"))
    item.meeting_metadata = meeting_metadata(remote)
    s.db.add(item)
    s.db.flush()
    return serialize(item)


def apply(s, proposal):
    payload = proposal.payload
    if proposal.kind == "save_contact":
        data = ContactInput(**payload)
        email = str(data.email).lower()
        contact = s.db.scalar(select(Contact).where(Contact.user_id == s.user.id, Contact.email == email))
        contact = contact or Contact(user_id=s.user.id, email=email)
        contact.name = data.name
        s.db.add(contact)
        s.activity("CONTACT_SAVED")
        return {"message": "Contact saved"}
    service = google(s)
    key = sha256(f"meeting:{s.user.id}:{proposal.id}:{payload['operation_key']}".encode()).hexdigest()
    ident = payload.get("event_id")
    item = own_event(s, ident) if ident else None
    external = item.external_id if item else key
    suffix = "/" + quote(external, safe="")
    remote = None
    try:
        remote = service.request("GET", suffix)
    except HTTPException as exc:
        if exc.status_code not in {404, 410} or (ident and proposal.kind != "meeting_cancel"):
            raise
    marker = (remote or {}).get("extendedProperties", {}).get("private", {}).get("xenonMutation")
    if proposal.kind == "meeting_create" and remote and marker != key:
        raise HTTPException(409, "Event identity collision. Request a fresh proposal.")
    # Recovery after Google succeeded but the local transaction/HTTP response failed.
    if marker == key and proposal.kind != "meeting_cancel":
        if remote.get("status") == "cancelled":
            raise HTTPException(409, "The meeting was subsequently cancelled in Google Calendar")
        return {"message": "Meeting saved in Google Calendar", "meeting": store_remote(s, remote)}
    if proposal.kind == "meeting_cancel" and (not remote or remote.get("status") == "cancelled"):
        s.db.delete(item)
        return {"message": "Meeting is already cancelled in Google Calendar"}
    if ident:
        if (
            not remote.get("organizer", {}).get("self")
            or remote.get("recurrence")
            or remote.get("recurringEventId")
        ):
            raise HTTPException(409, "You must organize a single meeting to change it")
        if remote.get("etag") != payload["etag"]:
            raise HTTPException(409, "The meeting changed in Google Calendar. Review a fresh proposal.")
    if proposal.kind == "meeting_cancel":
        service.request("DELETE", suffix, params={"sendUpdates": "all"}, headers={"If-Match": remote["etag"]})
        s.db.delete(item)
        s.activity("MEETING_CANCELLED", {"proposal_id": proposal.id})
        return {"message": "Meeting cancelled. Google Calendar was asked to notify attendees."}
    meeting = payload["meeting"]
    data = MeetingInput(**{k: v for k, v in meeting.items() if k in MeetingInput.model_fields})
    service.sync()
    if check_time(s, data, ident).get("conflict"):
        raise HTTPException(409, "Your availability changed. Review a fresh meeting proposal.")
    body = {
        "summary": data.title,
        "description": data.description,
        "location": data.location,
        "start": {"dateTime": meeting["start_time"], "timeZone": meeting["timezone"]},
        "end": {"dateTime": meeting["end_time"], "timeZone": meeting["timezone"]},
        "attendees": [
            {
                **next(
                    (
                        old
                        for old in (remote or {}).get("attendees", [])
                        if old.get("email", "").lower() == a["email"].lower()
                    ),
                    {},
                ),
                "email": a["email"],
                "displayName": a["name"],
            }
            for a in meeting["attendees"]
        ],
        "extendedProperties": {
            "private": {
                **(remote or {}).get("extendedProperties", {}).get("private", {}),
                "xenonMutation": key,
            }
        },
    }
    if data.google_meet and not (remote or {}).get("conferenceData"):
        body["conferenceData"] = {
            "createRequest": {"requestId": key, "conferenceSolutionKey": {"type": "hangoutsMeet"}}
        }
    # Existing conferences are deliberately preserved by PATCH when the field is absent.
    params = {"sendUpdates": "all", "conferenceDataVersion": 1}
    if ident:
        remote = service.request(
            "PATCH", suffix, json=body, params=params, headers={"If-Match": payload["etag"]}
        )
    else:
        body["id"] = key
        try:
            remote = service.request("POST", json=body, params=params)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            remote = service.request("GET", suffix)
            if remote.get("extendedProperties", {}).get("private", {}).get("xenonMutation") != key:
                raise HTTPException(409, "Event identity collision") from None
    saved = store_remote(s, remote)
    s.activity("MEETING_SAVED", {"proposal_id": proposal.id, "event_id": saved["id"]})
    return {"message": "Meeting saved. Google Calendar was asked to notify attendees.", "meeting": saved}
