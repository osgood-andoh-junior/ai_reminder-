"""The server wall clock. All current-time reads originate here."""

from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc)
