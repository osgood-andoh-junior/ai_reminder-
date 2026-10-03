"""Small capability contracts; existing CalendarService remains the calendar provider."""

from typing import Protocol
from dataclasses import dataclass
from datetime import datetime


class IntegrationProvider(Protocol):
    def status(self) -> dict: ...


@dataclass(frozen=True)
class EmailMessage:
    external_id: str
    subject: str
    sender: str
    snippet: str
    received_at: datetime | None
    text: str  # Ephemeral: never persisted or returned to the chat agent.
    ignored: bool = False


class EmailProvider(IntegrationProvider, Protocol):
    def recent_ids(self) -> list[str]: ...
    def read_message(self, ident: str) -> EmailMessage: ...
