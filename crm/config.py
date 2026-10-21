"""Settings for the application database and sign-in policy.

The application keeps all of its data in one local SQLite file, the same one
the analytics use (``core.db.DB_PATH``: ``data/sales.db``, or ``FDT_DATA_DIR``).
Session and sign-in limits have safe defaults and can be tuned with environment
variables (``TSLG_SESSION_IDLE_MINUTES`` and friends). No secrets are configured
anywhere: passwords are stored only as Argon2 hashes inside the database.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url

_PREFIX = "TSLG_"


class ConfigurationError(RuntimeError):
    """A setting is invalid; the message is shown to the user."""


@dataclass(frozen=True)
class Settings:
    database_path: Path
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    login_max_failures: int = 5
    login_window_minutes: int = 15
    token_ttl_hours: int = 72

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"

    @property
    def display_database(self) -> str:
        return f"Local file on this computer: {self.database_path}"


def default_database_path() -> Path:
    from core.db import DB_PATH  # the analytics database: one file for everything

    return Path(DB_PATH)


def _int(values: Mapping[str, str], name: str, default: int, minimum: int = 1) -> int:
    raw = values.get(_PREFIX + name, "").strip()
    if not raw:
        return default
    try:
        number = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{_PREFIX}{name} must be a whole number, got {raw!r}") from exc
    if number < minimum:
        raise ConfigurationError(f"{_PREFIX}{name} must be at least {minimum}")
    return number


def load_settings(env: Mapping[str, str] | None = None, *, database_path: Path | str | None = None) -> Settings:
    values = dict(os.environ if env is None else env)
    path = Path(database_path) if database_path is not None else default_database_path()
    if path.suffix == "" or str(path) == ":memory:":
        raise ConfigurationError("The database must be a file path")
    return Settings(
        database_path=path.expanduser().resolve(),
        session_idle_minutes=_int(values, "SESSION_IDLE_MINUTES", 30),
        session_absolute_hours=_int(values, "SESSION_ABSOLUTE_HOURS", 12),
        login_max_failures=_int(values, "LOGIN_MAX_FAILURES", 5),
        login_window_minutes=_int(values, "LOGIN_WINDOW_MINUTES", 15),
        token_ttl_hours=_int(values, "TOKEN_TTL_HOURS", 72),
    )


def settings_for_url(url: str) -> Settings:
    """Settings for an explicit ``sqlite:///path`` URL (used by migrations and tests)."""
    database = make_url(url).database
    if not database:
        raise ConfigurationError("The database URL must name a file")
    return load_settings({}, database_path=database)
