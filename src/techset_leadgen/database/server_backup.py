"""Backups of the shared PostgreSQL team database with PostgreSQL's own tools.

``pg_dump --format=custom`` takes a consistent snapshot while people keep
working; every backup is checked by listing its contents with ``pg_restore``
before it is reported as made. A restore goes only into a new, empty database,
so it can never overwrite live data: the administrator then points
``database.ini`` (or ``TSLG_DATABASE_URL``) at the restored database.

The password is handed to the tools in the environment (``PGPASSWORD``), never
on the command line, where other users of the server could read it. The tools
come from ``PATH`` or from the folder named by ``TSLG_PG_BIN``.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # noqa: S404 - runs PostgreSQL's own backup tools with fixed arguments
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, pool, text
from sqlalchemy.engine import URL, make_url


class BackupFailed(RuntimeError):
    """A backup or restore did not complete; the message says why (never the password)."""


def _tool(name: str) -> str:
    folder = os.environ.get("TSLG_PG_BIN", "").strip()
    found = shutil.which(name, path=folder or None)
    if not found:
        raise BackupFailed(f"{name} was not found. Install the PostgreSQL client tools or set TSLG_PG_BIN.")
    return found


def _connection(database_url: str) -> tuple[str, dict[str, str]]:
    """A libpq address without the password, and an environment that carries it."""
    url: URL = make_url(database_url)
    environment = {**os.environ}
    if url.password:
        environment["PGPASSWORD"] = str(url.password)
    address = url.set(drivername="postgresql", password=None).render_as_string(hide_password=False)
    return address, environment


def _run(arguments: list[str], environment: dict[str, str]) -> str:
    result = subprocess.run(arguments, env=environment, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise BackupFailed((result.stderr or result.stdout).strip()[:2000] or f"{Path(arguments[0]).name} failed")
    return result.stdout


def backup(database_url: str, folder: Path) -> Path:
    """Write a verified ``.dump`` of the team database into ``folder`` and return its path."""
    folder.mkdir(parents=True, exist_ok=True)
    address, environment = _connection(database_url)
    name = make_url(database_url).database or "team"
    target = folder / f"{name}-{datetime.now():%Y%m%d-%H%M%S}.dump"
    _run([_tool("pg_dump"), "--format=custom", "--no-owner", "--no-privileges", f"--file={target}",
          f"--dbname={address}"], environment)
    listing = _run([_tool("pg_restore"), "--list", str(target)], environment)
    if "TABLE DATA public alembic_version" not in listing:
        target.unlink(missing_ok=True)
        raise BackupFailed("The backup file is incomplete (it has no schema version); it was removed.")
    return target


def restore(dump: Path, empty_database_url: str) -> None:
    """Restore ``dump`` into a new, empty database (refuses one that already has tables)."""
    if not dump.is_file():
        raise BackupFailed(f"{dump} does not exist.")
    engine = create_engine(empty_database_url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            tables = inspect(connection).get_table_names()
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()
    if tables:
        raise BackupFailed("Restore only into a new, empty database: this one already has tables.")
    address, environment = _connection(empty_database_url)
    _run([_tool("pg_restore"), "--no-owner", "--no-privileges", "--exit-on-error", "--single-transaction",
          f"--dbname={address}", str(dump)], environment)


__all__ = ["BackupFailed", "backup", "restore"]
