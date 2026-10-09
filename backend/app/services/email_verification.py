"""Authenticated verification; only token digests are persisted."""

import secrets
from datetime import timedelta
from sqlalchemy import select, update
from fastapi import HTTPException
from app.core.config import settings
from app.core.security import digest
from app.db.database import utcnow
from app.db.models import EmailVerification
from app.notifications.email import EmailNotificationChannel, email_configured
from app.notifications.push import DeliveryError


def request_verification(service):
    service.lock()
    user, db, now = service.user, service.db, utcnow()
    if user.email_verified_at:
        return {"message": "Your email is already verified."}
    if not email_configured():
        return {"message": "Email delivery is unavailable. Try again after setup is complete."}
    recent = list(
        db.scalars(
            select(EmailVerification).where(
                EmailVerification.user_id == user.id,
                EmailVerification.created_at > now - timedelta(hours=1),
            )
        )
    )
    if len(recent) >= 5 or any(row.created_at > now - timedelta(seconds=60) for row in recent):
        raise HTTPException(429, "Please wait before requesting another verification email.")
    token = secrets.token_urlsafe(48)
    row = EmailVerification(
        user_id=user.id,
        email=user.email,
        token_hash=digest(token),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    db.add(row)
    db.flush()
    # Fragment keeps the secret out of HTTP URL/access logs and referrer headers.
    url = settings().frontend_url.rstrip("/") + "/verify-email#token=" + token
    payload = {
        "from": settings().email_from,
        "to": [user.email],
        "subject": "Verify your Xenon email",
        "text": "Xenon — Make time for what matters.\n\nVerify your email: "
        + url
        + "\n\nThis link expires in one hour. Sign in to the account that requested it. "
        "Email reminders remain off until you enable them in Settings.",
    }
    try:
        EmailNotificationChannel().send_reminder(payload, "verify-" + row.token_hash[:48])
        row.delivery_status = "ACCEPTED"
        return {
            "message": "Verification email accepted for delivery. Check your inbox, then enable reminders in Settings."
        }
    except DeliveryError:
        row.delivery_status = "FAILED"
        return {"message": "Verification email could not be delivered. Please retry in one minute."}


def consume_verification(service, token):
    service.lock()
    now, user = utcnow(), service.user
    claimed = service.db.execute(
        update(EmailVerification)
        .where(
            EmailVerification.user_id == user.id,
            EmailVerification.email == user.email,
            EmailVerification.token_hash == digest(token),
            EmailVerification.expires_at > now,
            EmailVerification.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    ).rowcount
    if not claimed:
        raise HTTPException(400, "Verification link is invalid or expired. Request a new link in Settings.")
    user.email_verified_at = now
    service.db.execute(
        update(EmailVerification)
        .where(EmailVerification.user_id == user.id, EmailVerification.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    return {"message": "Email verified. You can now enable email reminders in Settings."}
