import os
import subprocess
import sys
from sqlalchemy import create_engine, inspect


def test_meeting_migration_sqlite_roundtrip(tmp_path):
    url = f"sqlite:///{tmp_path / 'meetings.db'}"
    env = {**os.environ, "DATABASE_URL": url}

    def run(*args):
        r = subprocess.run([sys.executable, "-m", "alembic", *args], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    run("upgrade", "head")
    run("check")
    engine = create_engine(url)
    assert "contacts" in inspect(engine).get_table_names()
    assert "meeting_metadata" in {c["name"] for c in inspect(engine).get_columns("calendar_events")}
    assert any(
        set(c["column_names"]) == {"user_id", "email"}
        for c in inspect(engine).get_unique_constraints("contacts")
    )
    run("downgrade", "f81a2c90")
    assert "contacts" not in inspect(engine).get_table_names()
    run("upgrade", "head")
    engine.dispose()


def test_meeting_postgresql_sql():
    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/unused"}
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "f81a2c90:head", "--sql"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "CREATE TABLE contacts" in r.stdout
    assert "ADD COLUMN meeting_metadata JSON" in r.stdout
    assert "UNIQUE (user_id, email)" in r.stdout
