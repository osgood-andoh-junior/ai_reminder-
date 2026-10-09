"""Migrate a populated legacy DB, preserving identity, sessions and preferences."""

import os
import subprocess
import sys
from sqlalchemy import create_engine, text
from app.core.security import hasher, verify


def test_populated_email_migration(tmp_path):
    url = f"sqlite:///{tmp_path / 'email-migration.db'}"
    env = {**os.environ, "DATABASE_URL": url}

    def migrate(target):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", target], env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    migrate("a12e93b4")
    engine = create_engine(url)
    password_hash = hasher.hash("preserved-password")
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO users (id,email,name,password_hash,revision,created_at,updated_at) VALUES (41,'legacy@example.com','Legacy',:hash,7,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            ),
            {"hash": password_hash},
        )
        db.execute(
            text(
                "INSERT INTO auth_sessions (id,user_id,token_hash,expires_at) VALUES (9,41,'preserved-session','2035-01-01')"
            )
        )
        db.execute(
            text(
                "INSERT INTO user_preferences (id,user_id,reminder_stages,in_app_notifications_enabled,timezone,preferred_start_time,preferred_end_time,preferred_days,default_reminder_minutes,preferred_task_length,break_preference,allow_weekend_scheduling,personalization_enabled,browser_notifications_enabled,email_notifications_enabled,deadline_reminders_enabled,created_at,updated_at) VALUES (2,41,'[\"BEFORE_5\"]',1,'Africa/Accra','09:00','17:00','[0]',15,60,15,0,1,1,1,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "INSERT INTO tasks (id,user_id,title,description,priority,estimated_duration_minutes,status,created_at,updated_at) VALUES (3,41,'Preserved task','','MEDIUM',60,'SCHEDULED',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "INSERT INTO scheduled_tasks (id,user_id,task_id,start_time,end_time,status,created_at,updated_at) VALUES (4,41,3,'2030-01-01 10:00:00','2030-01-01 11:00:00','SCHEDULED',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "INSERT INTO reminders (id,user_id,task_id,scheduled_task_id,reminder_time,message,status,title,kind,generation,in_app_visible,created_at,updated_at) VALUES (5,41,3,4,'2030-01-01 09:55:00','Preserved','PENDING','Task','BEFORE_5',0,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        columns = {
            table: [row[1] for row in db.execute(text(f"PRAGMA table_info({table})"))]
            for table in [
                "users",
                "auth_sessions",
                "user_preferences",
                "tasks",
                "scheduled_tasks",
                "reminders",
            ]
        }
        before = {table: db.execute(text(f"SELECT * FROM {table}")).all() for table in columns}
    migrate("head")
    with engine.connect() as db:
        for table, names in columns.items():
            assert db.execute(text(f"SELECT {','.join(names)} FROM {table}")).all() == before[table]
        assert db.execute(text("SELECT email_verified_at,email_reminders_opted_in_at FROM users")).one() == (
            None,
            None,
        )
        assert verify("preserved-password", db.execute(text("SELECT password_hash FROM users")).scalar_one())
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    from sqlalchemy.orm import Session
    from fastapi import Response
    from app.api.routes import login
    from app.schemas import Login

    with Session(engine) as db:
        response = Response()
        result = login(Login(email="legacy@example.com", password="preserved-password"), response, db)
        assert result["id"] == 41 and result["email_verified_at"] is None
        assert "session=" in response.headers["set-cookie"]
        db.rollback()
    engine.dispose()


def test_postgresql_migration_compiles():
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/unused"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "a12e93b4:head", "--sql"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "ADD COLUMN email_verified_at" in result.stdout
    assert "CREATE TABLE email_verifications" in result.stdout
    assert "DROP TABLE" not in result.stdout
