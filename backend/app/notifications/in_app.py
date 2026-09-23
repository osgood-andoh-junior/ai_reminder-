from app.db.database import utcnow
from app.db.models import UserActivity


class InAppNotifications:
    def deliver(self, reminder, payload):
        reminder.status = "SENT"
        reminder.sent_at = payload["now"]
        reminder.read_at = None
        reminder.dismissed_at = None

    def publish_due(self, db):
        from app.notifications.service import publish_due

        return publish_due(db, utcnow())


def record(db, reminder, action, **details):
    db.add(
        UserActivity(
            user_id=reminder.user_id,
            action=action,
            details={"reminder_id": reminder.id, "generation": reminder.generation, **details},
        )
    )
