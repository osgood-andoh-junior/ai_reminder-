import os
import subprocess
import sys
from sqlalchemy import create_engine, inspect, text


def test_integration_migration_round_trip_and_metadata(tmp_path):
    url = f"sqlite:///{tmp_path / 'integrations.db'}"
    env = {**os.environ, "DATABASE_URL": url}

    def run(*args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args], env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    run("upgrade", "e42b7190")
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO users (id,email,name,password_hash,revision,created_at,updated_at) VALUES (1,'a@example.com','A','hash',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "INSERT INTO google_connections (id,user_id,encrypted_tokens,created_at,updated_at) VALUES (1,1,'existing-ciphertext',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        db.execute(
            text(
                "INSERT INTO oauth_states (id,user_id,token_hash,expires_at) VALUES (1,1,'state',CURRENT_TIMESTAMP)"
            )
        )
    run("upgrade", "head")
    run("check")
    with engine.connect() as db:
        assert db.execute(text("SELECT provider FROM oauth_states")).scalar_one() == "google_calendar"
        assert (
            db.execute(text("SELECT encrypted_tokens FROM google_connections")).scalar_one()
            == "existing-ciphertext"
        )
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []
    assert "detected_commitments" in inspect(engine).get_table_names()
    run("downgrade", "e42b7190")
    assert "detected_commitments" not in inspect(engine).get_table_names()
    run("upgrade", "head")
    engine.dispose()


def test_postgresql_migration_generates_portable_sql():
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/unused"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "e42b7190:head", "--sql"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE detected_commitments" in result.stdout
    assert "ON DELETE CASCADE" in result.stdout
