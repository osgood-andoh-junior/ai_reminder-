from app.notifications.push import DeliveryError


class EmailNotificationChannel:
    """Extension point: a provider must acknowledge delivery before returning."""

    def deliver(self, recipient, payload):
        raise DeliveryError("email_not_configured", retryable=False)
