"""Shared encryption/configuration for Google connectors; never serialize credentials."""

from cryptography.fernet import Fernet
from fastapi import HTTPException
from app.core.config import settings


def configured():
    c = settings()
    return bool(c.google_client_id and c.google_client_secret and c.token_encryption_key)


def cipher():
    if not configured():
        raise HTTPException(
            503, "Google integration is not configured. Add OAuth credentials and TOKEN_ENCRYPTION_KEY."
        )
    try:
        return Fernet(settings().token_encryption_key.encode())
    except ValueError:
        raise HTTPException(503, "Google token encryption is not configured correctly") from None
