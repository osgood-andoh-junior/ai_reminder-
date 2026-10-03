"""Read-only Gmail transport. No scheduling or AI writes live in this provider."""

import base64
import binascii
import json
import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote
import httpx
from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlalchemy import select
from app.core.config import settings
from app.db.models import IntegrationConnection
from app.integrations.google_oauth import cipher, configured
from app.integrations.providers import EmailMessage

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
API = "https://gmail.googleapis.com/gmail/v1/users/me"


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def request(method, url, **kwargs):
    try:
        response = httpx.request(method, url, timeout=8, **kwargs)
        if response.status_code in {400, 401}:
            raise ProviderError("access_expired_or_revoked")
        if response.status_code == 403:
            raise ProviderError("permission_denied")
        if response.status_code == 429:
            raise ProviderError("rate_limited")
        if response.status_code == 404:
            raise ProviderError("message_unavailable")
        response.raise_for_status()
        value = response.json() if response.content else {}
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (httpx.HTTPError, ValueError):
        raise ProviderError("google_unavailable") from None


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def message_text(payload, limit):
    plain, html = [], []
    remaining = [limit]

    def visit(part, depth=0):
        if depth > 12 or remaining[0] <= 0 or not isinstance(part, dict) or part.get("filename"):
            return
        mime = part.get("mimeType")
        if mime in {"text/plain", "text/html"}:
            encoded = part.get("body", {}).get("data", "")
            if encoded:
                try:
                    value = base64.urlsafe_b64decode(
                        encoded[: limit * 4] + "=" * (-len(encoded[: limit * 4]) % 4)
                    ).decode("utf-8", errors="replace")
                except (ValueError, binascii.Error):
                    raise ProviderError("malformed_message") from None
                value = value[: remaining[0]]
                remaining[0] -= len(value)
                (plain if mime == "text/plain" else html).append(value)
        for child in part.get("parts", [])[:50]:
            visit(child, depth + 1)

    visit(payload)
    if plain:
        return "\n".join(plain)[:limit]
    parser = PlainHTML()
    parser.feed("\n".join(html))
    return " ".join(parser.parts)[:limit]


class GmailProvider:
    def __init__(self, service):
        self.s = service
        self.connection = service.db.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.user_id == service.user.id, IntegrationConnection.provider == "gmail"
            )
        )

    def status(self):
        c = self.connection
        return {
            "id": "gmail",
            "name": "Gmail",
            "configured": configured(),
            "state": "needs_attention" if c and c.last_error else "connected" if c else "not_connected",
            "account": c.account if c else None,
            "synced_at": c.synced_at.isoformat() if c and c.synced_at else None,
            "error": c.last_error if c else None,
        }

    def tokens(self):
        if not self.connection:
            raise HTTPException(409, "Connect Gmail first in Settings → Integrations")
        try:
            tokens = json.loads(cipher().decrypt(self.connection.encrypted_tokens.encode()))
            if not isinstance(tokens, dict):
                raise ValueError()
            return tokens
        except (InvalidToken, ValueError):
            raise ProviderError("credentials_unreadable") from None

    def token(self):
        tokens = self.tokens()
        if SCOPE not in tokens.get("scope", "").split():
            raise ProviderError("missing_gmail_scope")
        if tokens.get("expires_at", 0) <= self.s.now.timestamp() + 60:
            if not tokens.get("refresh_token"):
                raise ProviderError("access_expired_or_revoked")
            refreshed = request(
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
            if SCOPE not in tokens.get("scope", "").split():
                raise ProviderError("missing_gmail_scope")
            tokens["expires_at"] = self.s.now.timestamp() + int(refreshed.get("expires_in", 3600))
            self.connection.encrypted_tokens = cipher().encrypt(json.dumps(tokens).encode()).decode()
        if not tokens.get("access_token"):
            raise ProviderError("access_expired_or_revoked")
        return tokens["access_token"]

    def get(self, path, **kwargs):
        return request("GET", API + path, headers={"Authorization": "Bearer " + self.token()}, **kwargs)

    def recent_ids(self):
        # Epoch bounds avoid Gmail search's implicit Pacific timezone for calendar dates.
        after = int(self.s.now.timestamp()) - settings().gmail_sync_days * 86400
        result, token = [], None
        for _ in range(3):
            params = {
                "q": f"after:{after} -in:spam -in:trash -in:sent -in:drafts -category:promotions -category:social",
                "maxResults": 100,
                "includeSpamTrash": "false",
            }
            if token:
                params["pageToken"] = token
            page = self.get("/messages", params=params)
            for item in page.get("messages", []):
                ident = item.get("id", "")
                if isinstance(ident, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,255}", ident):
                    result.append(ident)
            token = page.get("nextPageToken")
            if not token:
                break
        return list(dict.fromkeys(result))

    def read_message(self, ident):
        data = self.get("/messages/" + quote(ident, safe=""), params={"format": "full"})
        try:
            payload = data.get("payload", {})
            headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}
            ignored = bool(
                set(data.get("labelIds", [])) & {"SPAM", "TRASH", "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"}
            )
            ignored = ignored or bool(
                (headers.get("list-unsubscribe") or headers.get("list-id"))
                and re.search(
                    r"newsletter|digest|sale|special offer|promotion", headers.get("subject", ""), re.I
                )
            )
            try:
                received = datetime.fromtimestamp(int(data["internalDate"]) / 1000, timezone.utc)
            except (KeyError, ValueError, OverflowError, OSError):
                received = None
            text = "" if ignored else message_text(payload, settings().gmail_message_max_chars)
            return EmailMessage(
                ident,
                headers.get("subject", "")[:300],
                headers.get("from", "")[:300],
                unescape(data.get("snippet", ""))[:500],
                received,
                text,
                ignored,
            )
        except (TypeError, AttributeError, ValueError):
            raise ProviderError("malformed_message") from None
