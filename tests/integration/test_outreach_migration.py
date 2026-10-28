"""Migration safety for the additive LinkedIn-outreach schema."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest
from sqlalchemy import create_engine

from techset_leadgen.database import migrations_util


def _url(path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_upgrade_to_head_preserves_existing_tasks_and_integrity(tmp_path):
    database = tmp_path / "upgrade.db"
    url = _url(database)
    migrations_util.upgrade(url, "0001")
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO tasks (id, title, priority, status, created_at, updated_at, version) "
            "VALUES ('T1', 'Existing task', 'medium', 'open', '2026-10-01', '2026-10-01', 1)"
        )

    migrations_util.upgrade(url)

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0004",)
        assert connection.execute("SELECT title, kind FROM tasks WHERE id = 'T1'").fetchone() == (
            "Existing task", "task")
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        assert {"prospects", "assignment_batches", "prospect_assignments", "outreach_events",
                "notifications", "meetings", "meeting_attendees"} <= tables


def test_outreach_downgrade_fails_before_schema_or_revision_changes(tmp_path):
    database = tmp_path / "no-lossy-downgrade.db"
    url = _url(database)
    migrations_util.upgrade(url, "0002")

    with pytest.raises(RuntimeError, match="restore the pre-upgrade database backup"):
        migrations_util.downgrade(url, "0001")

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0002",)
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'prospects'"
        ).fetchone() == (1,)
        task_columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
        assert {"kind", "prospect_id", "assignment_id", "outcome", "request_id"} <= task_columns


def test_head_layout_validation_checks_outreach_tables_and_columns(tmp_path):
    database = tmp_path / "damaged.db"
    url = _url(database)
    migrations_util.upgrade(url)
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE notifications")
        with engine.connect() as connection:
            assert "missing table notifications" in migrations_util.layout_problems(connection)
    finally:
        engine.dispose()


def test_core_schema_preflight_is_read_only_and_detects_old_layout(monkeypatch, tmp_path):
    import techset_leadgen.database.local_db as core_db

    database = tmp_path / "old-core.db"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE clients (id INTEGER PRIMARY KEY, name TEXT, cif TEXT)")
        connection.execute("CREATE TABLE sales (id INTEGER PRIMARY KEY, client_id INTEGER)")
    before = database.read_bytes()
    monkeypatch.setattr(core_db, "DB_PATH", database)
    monkeypatch.setattr(core_db, "DB_NAME", str(database))

    assert core_db.base_schema_needs_migration() is True
    assert database.read_bytes() == before
