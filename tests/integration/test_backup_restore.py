"""A single-computer backup is consistent while people work, and a restored copy opens and holds every row."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing

import pytest
from sqlalchemy import func, select

from techset_leadgen.config import load_settings
from techset_leadgen.database import migrations_util
from techset_leadgen.database.engine import create_db_engine
from techset_leadgen.database.models import Prospect
from techset_leadgen.services import maintenance, prospects


def test_a_backup_taken_during_work_restores_into_a_working_database(db, acme, settings, tmp_path):
    manager = acme.actor("sales_manager")
    prospects.import_rows(db, manager, prospects.rows_from_text(
        "\n".join(f"linkedin.com/in/backup-{n}" for n in range(40))), source="Pasted")
    db.commit()
    # Someone is in the middle of an unsaved change while the backup runs.
    prospects.import_rows(db, manager, prospects.rows_from_text("linkedin.com/in/not-yet-saved"), source="x")
    db.flush()
    backup = maintenance.copy_database(settings.database_path, tmp_path / "backups" / "copy.db")
    db.rollback()

    with closing(sqlite3.connect(backup)) as copy:
        assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert copy.execute("SELECT COUNT(*) FROM prospects").fetchone() == (40,)  # saved work only

    # Restoring: the backup replaces the database file, and the application opens it as before.
    restored = tmp_path / "restored" / "sales.db"
    restored.parent.mkdir()
    shutil.copy(backup, restored)
    engine = create_db_engine(load_settings({}, database_path=restored))
    try:
        with engine.connect() as connection:
            assert migrations_util.schema_state(connection).ready
            assert migrations_util.layout_problems(connection) == []
            assert connection.execute(select(func.count()).select_from(Prospect)).scalar_one() == 40
    finally:
        engine.dispose()
    pytest.importorskip("PySide6.QtCore")
    from techset_leadgen.desktop.session import AppContext

    context = AppContext(load_settings({}, database_path=restored))
    context.open()
    assert context.has_users()
    context.close()
