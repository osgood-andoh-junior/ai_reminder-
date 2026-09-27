"""Upgrade real legacy rows; never run migrations against the user's database."""

import os
import subprocess
import sys
from sqlalchemy import create_engine, text


def test_legacy_migration_preserves_deliveries(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    env = {**os.environ, "DATABASE_URL": url}

    def migrate(target, direction="upgrade"):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", direction, target], env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    migrate("c7e2a901")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO users (id,email,name,password_hash,revision,created_at,updated_at) VALUES (1,'test@example.com','Test','hash',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "INSERT INTO reminders (id,user_id,reminder_time,message,status,title,kind,generation,created_at,updated_at) VALUES (1,1,CURRENT_TIMESTAMP,'Legacy','SENT','Reminder','CUSTOM',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "INSERT INTO push_subscriptions (id,user_id,endpoint,endpoint_hash,p256dh,auth,active,created_at,updated_at) VALUES (1,1,'https://example.com','hash','key','auth',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "INSERT INTO notification_deliveries (id,user_id,reminder_id,subscription_id,generation,status,attempts,next_attempt_at,created_at,updated_at) VALUES (1,1,1,1,0,'SENT',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    migrate("head")
    with engine.connect() as db:
        assert db.execute(text("SELECT status,channel FROM notification_deliveries")).one() == (
            "SENT",
            "push",
        )
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    migrate("c7e2a901", "downgrade")
    with engine.connect() as db:
        assert db.execute(text("SELECT status FROM notification_deliveries")).scalar_one() == "SENT"
    migrate("head")
    engine.dispose()
