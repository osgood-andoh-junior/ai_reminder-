"""Authenticated integration orchestration. Email only creates review candidates."""

import time
from fastapi import HTTPException
from sqlalchemy import select, delete
from app.core.config import settings
from app.db.models import (
    GoogleCalendarConnection,
    IntegrationConnection,
    ExternalMessage,
    DetectedCommitment,
    Proposal,
)
from app.integrations.google_oauth import configured
from app.integrations.gmail import GmailProvider, ProviderError, request
from app.integrations.extraction import extract, ExtractionUnavailable


def list_integrations(s):
    calendar = s.db.scalar(
        select(GoogleCalendarConnection).where(GoogleCalendarConnection.user_id == s.user.id)
    )
    return [
        {
            "id": "google_calendar",
            "name": "Google Calendar",
            "configured": configured(),
            "state": "needs_attention"
            if calendar and calendar.last_error
            else "connected"
            if calendar
            else "not_connected",
            "synced_at": calendar.synced_at.isoformat() if calendar and calendar.synced_at else None,
            "error": calendar.last_error if calendar else None,
        },
        GmailProvider(s).status(),
        *[
            {"id": ident, "name": name, "state": "coming_soon", "configured": False}
            for ident, name in [
                ("google_tasks", "Google Tasks"),
                ("outlook", "Microsoft Outlook"),
                ("notion", "Notion"),
                ("slack", "Slack"),
            ]
        ],
    ]


def sync_gmail(s, provider=None, extractor=None):
    # Serialize against another sync, disconnect or decision for this user. The unique
    # message/candidate constraints also protect deduplication across worker processes.
    s.lock()
    provider = provider or GmailProvider(s)
    if not provider.connection:
        raise HTTPException(409, "Connect Gmail first in Settings → Integrations")
    result = {"checked": 0, "detected": 0, "skipped": 0, "failed": 0, "more": False, "error": None}
    started = time.monotonic()
    extract_fn = extractor or extract
    try:
        provider.tokens()
        ids = provider.recent_ids()
        for ident in ids:
            row = s.db.scalar(
                select(ExternalMessage).where(
                    ExternalMessage.user_id == s.user.id,
                    ExternalMessage.provider == "gmail",
                    ExternalMessage.account == provider.connection.account,
                    ExternalMessage.external_id == ident,
                )
            )
            if row and row.status in {"PROCESSED", "IGNORED"}:
                result["skipped"] += 1
                continue
            if result["checked"] >= settings().gmail_sync_limit or time.monotonic() - started >= 20:
                result["more"] = True
                break
            row = row or ExternalMessage(
                user_id=s.user.id, provider="gmail", account=provider.connection.account, external_id=ident
            )
            s.db.add(row)
            s.db.flush()
            row.attempts += 1
            result["checked"] += 1
            try:
                message = provider.read_message(ident)
                row.subject, row.sender, row.snippet, row.received_at = (
                    message.subject,
                    message.sender,
                    message.snippet,
                    message.received_at,
                )
                candidates = extract_fn(message, s.time_context)
                for index, candidate in enumerate(candidates):
                    s.db.add(
                        DetectedCommitment(
                            user_id=s.user.id, message_id=row.id, candidate_index=index, **candidate
                        )
                    )
                row.status, row.last_error = "PROCESSED" if candidates else "IGNORED", None
                result["detected"] += len(candidates)
            except ExtractionUnavailable as exc:
                row.status, row.last_error = "RETRY", str(exc)
                result["failed"] += 1
                result["error"] = str(exc)
                # A later explicit check retries this ID instead of silently losing it.
                break
            except ProviderError as exc:
                row.status, row.last_error = "RETRY", exc.code
                result["failed"] += 1
                if exc.code in {"message_unavailable", "malformed_message"}:
                    row.status = "IGNORED"
                    continue
                raise
        provider.connection.synced_at = s.now
        provider.connection.last_error = result["error"]
    except ProviderError as exc:
        provider.connection.last_error = exc.code
        result["error"] = exc.code
    s.activity("GMAIL_CHECKED", {k: result[k] for k in ["checked", "detected", "failed"]})
    s.db.flush()
    return result


def purge_gmail(s):
    # Delete review data and invalidate all related proposals. Approved tasks/events survive.
    for proposal in s.db.scalars(
        select(Proposal).where(
            Proposal.user_id == s.user.id, Proposal.kind.in_(["commitment", "commitment_dismiss"])
        )
    ):
        if proposal.status == "PENDING":
            proposal.status = "REJECTED"
        proposal.payload = {"source": "gmail", "removed": True}
    s.db.execute(delete(DetectedCommitment).where(DetectedCommitment.user_id == s.user.id))
    s.db.execute(
        delete(ExternalMessage).where(
            ExternalMessage.user_id == s.user.id, ExternalMessage.provider == "gmail"
        )
    )


def disconnect_gmail(s, revoke=False):
    s.lock()
    provider = GmailProvider(s)
    revoked, warning = False, None
    if revoke and provider.connection:
        try:
            tokens = provider.tokens()
            request(
                "POST",
                "https://oauth2.googleapis.com/revoke",
                data={"token": tokens.get("refresh_token") or tokens.get("access_token", "")},
            )
            revoked = True
            calendar = s.db.scalar(
                select(GoogleCalendarConnection).where(GoogleCalendarConnection.user_id == s.user.id)
            )
            if calendar:
                calendar.last_error = "google_access_revoked_reconnect"
        except (ProviderError, HTTPException):
            # Local deletion must still work even when Google is unavailable or a key rotated.
            warning = "Local access removed. Revoke Xenon access at myaccount.google.com/permissions."
    purge_gmail(s)
    s.db.execute(
        delete(IntegrationConnection).where(
            IntegrationConnection.user_id == s.user.id, IntegrationConnection.provider == "gmail"
        )
    )
    from app.db.models import OAuthState

    s.db.execute(delete(OAuthState).where(OAuthState.user_id == s.user.id, OAuthState.provider == "gmail"))
    s.activity("GMAIL_DISCONNECTED", {"revoked": revoked})
    return {"disconnected": True, "revoked": revoked, "warning": warning}
