"""Web Push transport. Subscription endpoints are capabilities, never log them."""

import base64
import json
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import webpush, WebPushException
import requests
from app.core.config import settings


def validate_subscription(endpoint, p256dh=None, auth=None):
    url = urlsplit(endpoint)
    host = url.hostname or ""
    allowed = host in {
        "fcm.googleapis.com",
        "updates.push.services.mozilla.com",
        "web.push.apple.com",
    } or host.endswith(".notify.windows.com")
    if (
        not allowed
        or url.scheme != "https"
        or url.port not in {None, 443}
        or url.username
        or url.password
        or url.fragment
    ):
        # Report only the provider hostname, never the capability path/query or keys.
        raise ValueError(f"Unsupported push service endpoint ({host[:253]}). Use a supported browser.")
    if p256dh is not None:
        try:
            key = base64.urlsafe_b64decode(p256dh + "=" * (-len(p256dh) % 4))
            secret = base64.urlsafe_b64decode(auth + "=" * (-len(auth) % 4))
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), key)
            if len(secret) != 16:
                raise ValueError()
        except Exception:
            raise ValueError("Invalid push subscription keys") from None


class DeliveryError(Exception):
    def __init__(self, code, *, expired=False, retryable=True):
        self.code, self.expired, self.retryable = code, expired, retryable


class NoRedirectSession(requests.Session):
    def request(self, *args, **kwargs):
        kwargs["allow_redirects"] = False
        return super().request(*args, **kwargs)


class PushNotificationChannel:
    def deliver(self, subscription, payload):
        config = settings()
        if not (config.vapid_private_key and config.vapid_public_key and config.vapid_subject):
            raise DeliveryError("push_not_configured")
        validate_subscription(subscription.endpoint)
        try:
            with NoRedirectSession() as session:
                response = webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                    },
                    data=json.dumps(payload),
                    vapid_private_key=config.vapid_private_key,
                    vapid_claims={"sub": config.vapid_subject},
                    ttl=3600,
                    timeout=10,
                    requests_session=session,
                )
                if not 200 <= response.status_code < 300:
                    raise DeliveryError(
                        "push_http_" + str(response.status_code), retryable=response.status_code >= 500
                    )
        except WebPushException as exc:
            status = exc.response.status_code if exc.response is not None else None
            raise DeliveryError(
                "push_http_" + str(status) if status else "push_network",
                expired=status in {404, 410},
                retryable=status is None or status in {408, 429} or status >= 500,
            ) from None
        except requests.RequestException:
            raise DeliveryError("push_network") from None
