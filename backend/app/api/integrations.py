import json
import secrets
from datetime import timedelta
from urllib.parse import urlencode
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from cryptography.fernet import InvalidToken
from sqlalchemy import select
from app.api.routes import Service
from app.core.config import settings
from app.core.security import digest
from app.db.models import OAuthState, IntegrationConnection
from app.integrations.google_oauth import cipher
from app.integrations.gmail import request, SCOPE, API, ProviderError
from app.services.integrations import list_integrations, sync_gmail, disconnect_gmail, purge_gmail
from app.services import commitments
from app.schemas import Input

router = APIRouter(prefix="/api/integrations")


@router.get("")
def integrations(s: Service):
    return list_integrations(s)


@router.get("/gmail/status")
def gmail_status(s: Service):
    return next(item for item in list_integrations(s) if item["id"] == "gmail")


@router.post("/gmail/connect")
def connect(s: Service):
    cipher()
    state = secrets.token_urlsafe(32)
    s.db.add(
        OAuthState(
            user_id=s.user.id,
            token_hash=digest(state),
            provider="gmail",
            expires_at=s.now + timedelta(minutes=10),
        )
    )
    return {
        "url": "https://accounts.google.com/o/oauth2/v2/auth?"
        + urlencode(
            {
                "client_id": settings().google_client_id,
                "redirect_uri": settings().gmail_redirect_uri,
                "response_type": "code",
                "scope": SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )
    }


@router.get("/gmail/callback")
def callback(s: Service, state: str = "", code: str = "", error: str = ""):
    s.lock()
    saved = s.db.scalar(
        select(OAuthState).where(
            OAuthState.user_id == s.user.id,
            OAuthState.provider == "gmail",
            OAuthState.token_hash == digest(state),
            OAuthState.expires_at > s.now,
        )
    )
    if not saved:
        raise HTTPException(400, "OAuth state expired or invalid; connect Gmail again from Settings")
    s.db.delete(saved)
    s.db.commit()  # Consume even when code exchange fails; state is never replayable.
    result = "declined"
    if code and not error:
        try:
            tokens = request(
                "POST",
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings().google_client_id,
                    "client_secret": settings().google_client_secret,
                    "redirect_uri": settings().gmail_redirect_uri,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            if SCOPE not in tokens.get("scope", "").split() or not tokens.get("access_token"):
                raise ProviderError("missing_gmail_scope")
            profile = request(
                "GET", API + "/profile", headers={"Authorization": "Bearer " + tokens["access_token"]}
            )
            account = str(profile.get("emailAddress", "")).lower().strip()
            if not account or len(account) > 254:
                raise ProviderError("profile_unavailable")
            s.lock()
            existing = s.db.scalar(
                select(IntegrationConnection).where(
                    IntegrationConnection.user_id == s.user.id, IntegrationConnection.provider == "gmail"
                )
            )
            if existing and existing.account != account:
                purge_gmail(s)
            if existing and existing.account == account and not tokens.get("refresh_token"):
                try:
                    previous = json.loads(cipher().decrypt(existing.encrypted_tokens.encode()))
                    if previous.get("refresh_token"):
                        tokens["refresh_token"] = previous["refresh_token"]
                except (InvalidToken, ValueError):
                    pass
            tokens["expires_at"] = s.now.timestamp() + int(tokens.get("expires_in", 3600))
            connection = existing or IntegrationConnection(
                user_id=s.user.id, provider="gmail", account=account
            )
            connection.account, connection.last_error = account, None
            connection.encrypted_tokens = cipher().encrypt(json.dumps(tokens).encode()).decode()
            s.db.add(connection)
            s.activity("GMAIL_CONNECTED")
            result = "connected"
        except (ProviderError, ValueError, TypeError):
            result = "failed"
    return RedirectResponse(
        settings().frontend_url + "/settings?gmail=" + result + "#integrations", status_code=303
    )


@router.post("/gmail/sync")
def sync(s: Service):
    return sync_gmail(s)


class Disconnect(Input):
    revoke: bool = False


@router.post("/gmail/disconnect")
def disconnect(data: Disconnect, s: Service):
    return disconnect_gmail(s, data.revoke)


@router.get("/commitments")
def inbox(s: Service):
    return commitments.inbox(s)


@router.get("/commitments/{ident}")
def detail(ident: int, s: Service):
    return commitments.detail(s, ident)


@router.post("/commitments/{ident}/propose")
def propose(ident: int, data: commitments.Review, s: Service):
    return commitments.propose(s, ident, data)
