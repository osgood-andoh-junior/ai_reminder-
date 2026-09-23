import hashlib
import secrets
from datetime import timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from app.db.database import get_db, utcnow
from app.db.models import AuthSession, User
from app.core.config import settings

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def verify(password, hashed):
    try:
        return hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def new_session(db, user, response):
    token = secrets.token_urlsafe(48)
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=digest(token),
            expires_at=utcnow() + timedelta(hours=settings().session_hours),
        )
    )
    response.set_cookie(
        "session",
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="lax",
        max_age=settings().session_hours * 3600,
        path="/",
    )


def current_user(request: Request, db=Depends(get_db)):
    token = request.cookies.get("session")
    if not token:
        raise HTTPException(401, "Please sign in")
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == digest(token), AuthSession.expires_at > utcnow())
    )
    if not session:
        raise HTTPException(401, "Session expired. Please sign in again")
    user = db.get(User, session.user_id)
    request.state.user_id = user.id
    return user
