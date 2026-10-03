"""Review, preview and confirm imported commitments through existing proposals."""

from datetime import datetime, timedelta
from typing import Literal
from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select
from app import schemas
from app.db.models import DetectedCommitment, ExternalMessage, Proposal
from app.services.application import serialize
from app.core.config import settings
from app.scheduling.scheduler import schedule, Preferences, Weights, Slot, overlaps


class Review(schemas.Input):
    action: Literal["task", "event", "schedule", "dismiss"]
    revision: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=200)
    deadline: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    estimated_duration_minutes: int | None = Field(default=None, ge=5, le=10080)
    _aware = schemas.field_validator("deadline", "start_time", "end_time")(schemas.aware)


class Propose(schemas.Input):
    commitment_id: int = Field(gt=0)
    review: Review


def detail(s, ident):
    item = s.own(DetectedCommitment, ident)
    message = s.own(ExternalMessage, item.message_id)
    return {
        **serialize(item),
        "source": "gmail",
        "source_message_id": message.external_id,
        "subject": message.subject,
        "sender": message.sender,
        "snippet": message.snippet,
        "received_at": message.received_at.isoformat() if message.received_at else None,
    }


def inbox(s):
    return [
        detail(s, item.id)
        for item in s.db.scalars(
            select(DetectedCommitment)
            .where(DetectedCommitment.user_id == s.user.id, DetectedCommitment.status == "PENDING")
            .order_by(DetectedCommitment.id.desc())
            .limit(100)
        )
    ]


def preview(s, data):
    # Same scheduling engine, preferences, busy query and clock as Application.plan;
    # no temporary database Task or event is created to obtain the preview.
    s.refresh_external_calendar()
    pref, config = s.preferences(), settings()
    result = schedule(
        data.estimated_duration_minutes,
        s.now,
        min(data.deadline, s.now + timedelta(days=90)),
        s.busy(),
        Preferences(**{k: getattr(pref, k) for k in Preferences.__dataclass_fields__}),
        data.priority,
        weights=Weights(config.preference_weight, config.early_weight, config.fragmentation_weight),
    )
    return {**result, "title": data.title, "task_id": None}


def inputs(s, review):
    if review.action == "event":
        if not review.start_time or not review.end_time:
            raise HTTPException(422, "Confirm an event start and end time")
        event = schemas.EventInput(title=review.title, start_time=review.start_time, end_time=review.end_time)
        if event.start_time <= s.now:
            raise HTTPException(422, "Choose a future event time")
        if any(overlaps(Slot(event.start_time, event.end_time), item) for item in s.busy()):
            raise HTTPException(
                409, "This event conflicts with your calendar. Edit the times before proposing it"
            )
        return event
    if not review.estimated_duration_minutes:
        raise HTTPException(422, "Enter an estimated work duration")
    if review.deadline and review.deadline <= s.now:
        raise HTTPException(422, "Confirm a future deadline")
    if review.action == "schedule" and not review.deadline:
        raise HTTPException(422, "Confirm the deadline before scheduling this commitment")
    return schemas.TaskInput(
        title=review.title,
        deadline=review.deadline,
        estimated_duration_minutes=review.estimated_duration_minutes,
    )


def propose(s, ident, review):
    s.lock()
    item = s.own(DetectedCommitment, ident)
    if item.status != "PENDING" or item.revision != review.revision:
        raise HTTPException(409, "Commitment changed or was already handled. Reload your inbox")
    payload = {
        "commitment_id": item.id,
        "revision": item.revision,
        "review": review.model_dump(mode="json"),
        "source": "gmail",
    }
    if review.action != "dismiss":
        data = inputs(s, review)
        if review.action == "event":
            s.refresh_external_calendar()
            data = inputs(s, review)
            payload["event"] = data.model_dump(mode="json")
        else:
            payload["task"] = data.model_dump(mode="json")
            if review.action == "schedule":
                plan = preview(s, data)
                if not plan["feasible"]:
                    return {"plan": plan, "proposal": None, "message": plan["explanation"]}
                payload["plan"] = plan
    # Supersede older previews; the next Confirm must match this reviewed revision.
    item.revision += 1
    payload["revision"] = item.revision
    for old in s.db.scalars(
        select(Proposal).where(
            Proposal.user_id == s.user.id,
            Proposal.kind.in_(["commitment", "commitment_dismiss"]),
            Proposal.status == "PENDING",
        )
    ):
        if old.payload.get("commitment_id") == item.id:
            old.status = "REJECTED"
    proposal = s.proposal("commitment_dismiss" if review.action == "dismiss" else "commitment", payload)
    return {"proposal": proposal}


def apply(s, proposal):
    payload = proposal.payload
    item = s.own(DetectedCommitment, payload["commitment_id"])
    if item.status != "PENDING" or item.revision != payload["revision"]:
        raise HTTPException(409, "Commitment changed or was already handled")
    review = Review(**payload["review"])
    if review.action == "dismiss":
        item.status = "DISMISSED"
    else:
        if review.action == "event":
            s.refresh_external_calendar()
        data = inputs(s, review)
        if review.action == "schedule":
            fresh = preview(s, data)
            if not fresh["feasible"] or [(x["start"], x["end"]) for x in fresh["slots"]] != [
                (x["start"], x["end"]) for x in payload["plan"]["slots"]
            ]:
                raise HTTPException(409, "Availability changed. Review a fresh schedule proposal")
        if review.action == "event":
            item.event_id = s.save_event(data)["id"]
        else:
            item.task_id = s.create_task(data)["id"]
            if review.action == "schedule":
                s.apply_schedule({**payload["plan"], "task_id": item.task_id}, proposal.id)
        item.status = "ACCEPTED"
    s.activity("COMMITMENT_" + item.status, {"commitment_id": item.id})
