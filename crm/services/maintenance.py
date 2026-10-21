"""Administrative maintenance: backups and the one-time carry-over of accounts.

The application database holds everything (sales, clients, leads, accounts,
audit trail), so a backup is a consistent copy of that one file.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..errors import ValidationFailed
from ..models import Organization, User
from ..vocabulary import ROLES
from . import audit
from .access import Actor

logger = logging.getLogger("techset.leadgen.crm")


def copy_database(source: Path, destination: Path) -> Path:
    """A consistent snapshot via SQLite's online backup API (safe while the app is in use)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    with closing(sqlite3.connect(source)) as live, closing(sqlite3.connect(destination)) as copy:
        live.backup(copy)
    return destination


def backup_before_migration(database: Path, current: str | None, head: str | None) -> Path | None:
    """Copy the database aside before its schema changes; skipped for a new, empty file."""
    if not database.is_file() or database.stat().st_size == 0:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = database.parent / "backups" / f"{database.stem}-before-{head or 'upgrade'}-{stamp}{database.suffix}"
    copy_database(database, target)
    logger.info("Backed up %s (schema %s) to %s before upgrading to %s", database, current, target, head)
    return target


def backup(db: Session, actor: Actor, settings: Settings, target: str | Path) -> Path:
    """Administrator backup to a file of their choice (Settings → Back up now)."""
    actor.require("org.manage")
    destination = Path(target)
    if destination.resolve() == settings.database_path.resolve():
        raise ValidationFailed("Choose a different file than the live database.")
    copy_database(settings.database_path, destination)
    audit.record(db, actor, "database.backed_up", entity_type="organization", entity_id=1,
                 changes={"file": destination.name})
    return destination


_LEGACY_RECORD_TABLES = ("companies", "contacts", "leads", "tasks", "activities")


class LegacyRecordsFound(ValidationFailed):
    """The earlier build's ``crm.db`` holds business records that are not carried over automatically."""


def import_previous_accounts(db: Session, legacy_file: Path) -> int:
    """Carry accounts over from the separate ``crm.db`` used by an earlier build (once).

    Only runs while this database has no accounts. Copies the organization name
    and each user's email, name, role, time zone, and password hash, so people
    keep signing in with their existing passwords. The old file is left untouched.
    If it also holds companies, contacts, leads, tasks, or activities, nothing is
    carried over and ``LegacyRecordsFound`` explains why, so those records are
    never silently left behind.
    """
    if not legacy_file.is_file() or db.scalar(select(User.id).limit(1)) is not None:
        return 0
    try:
        with closing(sqlite3.connect(f"file:{legacy_file}?mode=ro", uri=True)) as old:
            existing = {row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            records = {table: old.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 - fixed names
                       for table in _LEGACY_RECORD_TABLES if table in existing}
            organization = old.execute("SELECT name FROM organizations ORDER BY created_at LIMIT 1").fetchone()
            people = old.execute(
                "SELECT email, full_name, password_hash, role, is_active, timezone FROM users"
            ).fetchall()
    except sqlite3.Error:
        logger.warning("Could not read accounts from %s", legacy_file, exc_info=True)
        return 0
    found = {table: count for table, count in records.items() if count}
    if found:
        summary = ", ".join(f"{count} {table}" for table, count in found.items())
        raise LegacyRecordsFound(
            f"{legacy_file.name} from an earlier version holds records ({summary}) that are not imported "
            "automatically. Keep a copy of that file, then move it out of the data folder to continue; "
            "nothing in it has been changed."
        )
    if not people:
        return 0
    if organization and db.get(Organization, 1) is None:
        db.add(Organization(id=1, name=organization[0]))
    copied = 0
    for email, full_name, password_hash, role, is_active, timezone in people:
        if role not in ROLES:
            continue
        db.add(User(email=email, full_name=full_name, password_hash=password_hash, role=role,
                    is_active=bool(is_active), timezone=timezone or "UTC"))
        copied += 1
    db.flush()
    audit.record(db, None, "users.carried_over", entity_type="organization", entity_id=1,
                 changes={"from": legacy_file.name, "accounts": copied})
    logger.info("Carried %s account(s) over from %s", copied, legacy_file)
    return copied


__all__ = ["backup", "backup_before_migration", "copy_database", "import_previous_accounts"]
