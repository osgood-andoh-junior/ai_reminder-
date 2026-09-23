"""Run independently of the web process: python -m app.worker."""

import logging
import time
from sqlalchemy import delete
from app.db.database import SessionLocal, utcnow
from app.db.models import AuthSession, OAuthState
from app.notifications.in_app import InAppNotifications
from app.notifications.service import process_outbox
from app.core.config import settings

logger = logging.getLogger(__name__)


def process_due(db):
    # One atomic state transition, safe across workers; SENT means available in-app.
    count = InAppNotifications().publish_due(db)
    db.execute(delete(AuthSession).where(AuthSession.expires_at < utcnow()))
    db.execute(delete(OAuthState).where(OAuthState.expires_at < utcnow()))
    db.commit()
    process_outbox(db)
    return count


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            with SessionLocal() as db:
                count = process_due(db)
                if count:
                    logger.info("Published %s in-app reminders", count)
        except Exception:
            logger.exception("Reminder processing failed")
        time.sleep(settings().reminder_poll_interval_seconds)


if __name__ == "__main__":
    main()
