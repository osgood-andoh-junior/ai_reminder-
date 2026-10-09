from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.database import Base, UTCDateTime, utcnow
from datetime import datetime


class Stamp:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class User(Stamp, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    email_reminders_opted_in_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Owned:
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class AuthSession(Owned, Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class EmailVerification(Owned, Base):
    __tablename__ = "email_verifications"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(20), default="PENDING")


class UserPreference(Owned, Stamp, Base):
    __tablename__ = "user_preferences"
    __table_args__ = (UniqueConstraint("user_id"),)
    reminder_stages: Mapped[list] = mapped_column(
        JSON, default=lambda: ["BEFORE_60", "BEFORE_30", "BEFORE_5", "AFTER_10", "END_10"]
    )
    in_app_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Accra")
    preferred_start_time: Mapped[str] = mapped_column(String(5), default="09:00")
    preferred_end_time: Mapped[str] = mapped_column(String(5), default="17:00")
    preferred_days: Mapped[list] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])
    default_reminder_minutes: Mapped[int] = mapped_column(default=15)
    preferred_task_length: Mapped[int] = mapped_column(default=60)
    break_preference: Mapped[int] = mapped_column(default=15)
    allow_weekend_scheduling: Mapped[bool] = mapped_column(Boolean, default=False)
    personalization_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    browser_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    email_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    deadline_reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class Task(Owned, Stamp, Base):
    __tablename__ = "tasks"
    reminder_stages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    email_reminders_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(10), default="MEDIUM")
    estimated_duration_minutes: Mapped[int] = mapped_column(default=60)
    deadline: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class CalendarEvent(Owned, Stamp, Base):
    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("user_id", "external_id"),)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    start_time: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    event_type: Mapped[str] = mapped_column(String(20), default="FIXED")
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="internal")
    meeting_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Contact(Owned, Stamp, Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("user_id", "email"),)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254))


class ScheduledTask(Owned, Stamp, Base):
    __tablename__ = "scheduled_tasks"
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    start_time: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    end_time: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    status: Mapped[str] = mapped_column(String(20), default="SCHEDULED")


class Reminder(Owned, Stamp, Base):
    __tablename__ = "reminders"
    __table_args__ = (Index("uq_reminder_session_stage", "scheduled_task_id", "stage_key", unique=True),)
    stage_key: Mapped[str | None] = mapped_column(String(30), nullable=True)
    in_app_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)
    scheduled_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), nullable=True
    )
    reminder_time: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    message: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="Reminder")
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    generation: Mapped[int] = mapped_column(default=0)
    kind: Mapped[str] = mapped_column(String(30), default="CUSTOM")


class PushSubscription(Owned, Stamp, Base):
    __tablename__ = "push_subscriptions"
    endpoint: Mapped[str] = mapped_column(Text)
    endpoint_hash: Mapped[str] = mapped_column(String(64), unique=True)
    p256dh: Mapped[str] = mapped_column(String(128))
    auth: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class NotificationDelivery(Owned, Stamp, Base):
    """Durable outbox, one delivery per reminder occurrence and device."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("reminder_id", "generation", "subscription_id"),
        Index(
            "uq_email_occurrence",
            "reminder_id",
            "generation",
            unique=True,
            sqlite_where=text("channel = 'email'"),
            postgresql_where=text("channel = 'email'"),
        ),
    )
    reminder_id: Mapped[int] = mapped_column(ForeignKey("reminders.id", ondelete="CASCADE"), index=True)
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("push_subscriptions.id", ondelete="CASCADE"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(10), default="push")
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    retry_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    generation: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(80), nullable=True)


class UserActivity(Owned, Base):
    __tablename__ = "user_activity"
    action: Mapped[str] = mapped_column(String(60), index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class Proposal(Owned, Stamp, Base):
    __tablename__ = "proposals"
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ChatMessage(Owned, Base):
    __tablename__ = "chat_messages"
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class GoogleCalendarConnection(Owned, Stamp, Base):
    __tablename__ = "google_connections"
    __table_args__ = (UniqueConstraint("user_id"),)
    encrypted_tokens: Mapped[str] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(80), nullable=True)


class OAuthState(Owned, Base):
    __tablename__ = "oauth_states"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    provider: Mapped[str] = mapped_column(
        String(30), default="google_calendar", server_default="google_calendar"
    )


class IntegrationConnection(Owned, Stamp, Base):
    __tablename__ = "integration_connections"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)
    provider: Mapped[str] = mapped_column(String(30))
    account: Mapped[str] = mapped_column(String(254))
    encrypted_tokens: Mapped[str] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(80), nullable=True)


class ExternalMessage(Owned, Stamp, Base):
    __tablename__ = "external_messages"
    __table_args__ = (UniqueConstraint("user_id", "provider", "account", "external_id"),)
    provider: Mapped[str] = mapped_column(String(30))
    account: Mapped[str] = mapped_column(String(254))
    external_id: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(300), default="")
    sender: Mapped[str] = mapped_column(String(300), default="")
    snippet: Mapped[str] = mapped_column(String(500), default="")
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(80), nullable=True)


class DetectedCommitment(Owned, Stamp, Base):
    __tablename__ = "detected_commitments"
    __table_args__ = (UniqueConstraint("message_id", "candidate_index"),)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("external_messages.id", ondelete="CASCADE"), index=True
    )
    candidate_index: Mapped[int] = mapped_column(default=0)
    title: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))
    deadline: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(nullable=True)
    confidence: Mapped[float]
    reason: Mapped[str] = mapped_column(String(500))
    unresolved: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    revision: Mapped[int] = mapped_column(default=0)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="SET NULL"), nullable=True
    )
