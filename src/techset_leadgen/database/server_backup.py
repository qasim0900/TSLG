from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect, pool, text
from sqlalchemy.engine import URL, make_url


class BackupFailed(RuntimeError):
    pass


def _tool(name: str) -> str:
    folder = os.environ.get("TSLG_PG_BIN", "").strip()
    found = shutil.which(name, path=folder or None)
    if not found:
        raise BackupFailed(f"{name} was not found. Install the PostgreSQL client tools or set TSLG_PG_BIN.")
    return found


def _connection(database_url: str) -> tuple[str, dict[str, str]]:
    url: URL = make_url(database_url)
    environment = {**os.environ}
    if url.password:
        environment["PGPASSWORD"] = str(url.password)
    address = url.set(drivername="postgresql", password=None).render_as_string(hide_password=False)
    return address, environment


def _run(arguments: list[str], environment: dict[str, str]) -> str:
    result = subprocess.run(arguments, env=environment, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise BackupFailed((result.stderr or result.stdout).strip()[:2000] or f"{Path(arguments[0]).name} failed")
    return result.stdout


def backup(database_url: str, folder: Path) -> Path:
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

