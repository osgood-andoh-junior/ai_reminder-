from fastapi import APIRouter
from app.api.routes import Service
from app.db.models import Contact
from app.services import meetings

router = APIRouter(prefix="/api")


@router.get("/contacts")
def contacts(s: Service, query: str = ""):
    return meetings.contacts(s, query)


@router.post("/contacts/propose")
def save_contact(data: meetings.ContactInput, s: Service):
    return meetings.propose_contact(s, data)


@router.delete("/contacts/{ident}", status_code=204)
def delete_contact(ident: int, s: Service):
    s.lock()
    s.db.delete(s.own(Contact, ident))
    s.activity("CONTACT_DELETED", {"contact_id": ident})


@router.get("/meetings")
def find_meetings(s: Service, query: str = ""):
    return meetings.find_meetings(s, query)


@router.post("/meetings/availability")
def availability(data: meetings.Availability, s: Service):
    return meetings.availability(s, data)


@router.post("/meetings/propose")
def propose(data: meetings.MeetingInput, s: Service):
    return meetings.propose(s, data)


@router.get("/meetings/{ident}")
def get_meeting(ident: int, s: Service):
    return meetings.get_meeting(s, ident)


@router.post("/meetings/{ident}/propose")
def change_meeting(ident: int, data: meetings.MeetingInput, s: Service):
    return meetings.propose(s, data, ident)


@router.post("/meetings/{ident}/cancel")
def cancel_meeting(ident: int, s: Service):
    return meetings.cancel(s, ident)
