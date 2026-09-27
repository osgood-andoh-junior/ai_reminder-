import httpx
from app.core.config import settings
from app.notifications.push import DeliveryError


def email_configured():
    config = settings()
    return bool(config.email_provider == "resend" and config.email_from and config.resend_api_key)


class EmailNotificationChannel:
    """Extension point: a provider must acknowledge delivery before returning."""

    def send_reminder(self, payload, idempotency_key):
        if not email_configured():
            raise DeliveryError("email_not_configured", retryable=False)
        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings().resend_api_key}",
                    "Idempotency-Key": idempotency_key,
                },
                timeout=15,
            )
        except httpx.RequestError:
            raise DeliveryError("email_network") from None
        if not 200 <= response.status_code < 300:
            retryable = response.status_code == 429 or response.status_code >= 500
            if response.status_code == 409:
                try:
                    retryable = response.json().get("name") == "concurrent_idempotent_requests"
                except ValueError:
                    pass
            raise DeliveryError(f"email_http_{response.status_code}", retryable=retryable)
