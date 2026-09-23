from typing import Protocol


class NotificationChannel(Protocol):
    """Channels own delivery semantics; external providers should use an outbox."""

    def deliver(self, recipient, payload: dict) -> None: ...
