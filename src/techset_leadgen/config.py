from __future__ import annotations

import configparser
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

_PREFIX = "TSLG_"
SERVER_FILE = "database.ini"
ENV_FILE = ".env"
_ENV_ALIASES = {"DATABASE_URL": _PREFIX + "DATABASE_URL"}


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    database_path: Path
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    login_max_failures: int = 5
    login_window_minutes: int = 15
    token_ttl_hours: int = 72
    server_url: str | None = None

    @property
    def is_server(self) -> bool:
        return self.server_url is not None

    @property
    def database_url(self) -> str:
        return self.server_url or f"sqlite:///{self.database_path.as_posix()}"

    @property
    def display_database(self) -> str:
        if self.server_url:
            url = make_url(self.server_url)
            return f"Team database {url.database} on {url.host}:{url.port or 5432}"
        return f"Local file on this computer: {self.database_path}"


def default_database_path() -> Path:
    from techset_leadgen.database.local_db import DB_PATH

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


def server_url(raw: str | None, source: str = _PREFIX + "DATABASE_URL") -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        url = make_url(text)
    except (ArgumentError, ValueError):
        raise ConfigurationError(f"{source} is not a valid database address.") from None
    if url.get_backend_name() != "postgresql":
        raise ConfigurationError(f"{source} must be a PostgreSQL address (postgresql://user:password@server/db).")
    if not url.host or not url.database:
        raise ConfigurationError(f"{source} must name the server and the database.")
    return url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def _server_file_url(path: Path) -> str | None:
    if not path.is_file():
        return None
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"{path} could not be read: {type(exc).__name__}.") from None
    return server_url(parser.get("database", "url", fallback=""), f"The url in {path}")


def _env_file_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"{path} could not be read: {type(exc).__name__}.") from None
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = _ENV_ALIASES.get(key.strip(), key.strip()), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key.startswith(_PREFIX):
            values[key] = value
    return values


def load_settings(env: Mapping[str, str] | None = None, *, database_path: Path | str | None = None) -> Settings:
    values = dict(os.environ if env is None else env)
    path = Path(database_path) if database_path is not None else default_database_path()
    if path.suffix == "" or str(path) == ":memory:":
        raise ConfigurationError("The database must be a file path")
    remote = None
    if database_path is None:
        env_file = path.parent.parent / ENV_FILE
        from_file = _env_file_values(env_file)
        name = _PREFIX + "DATABASE_URL"
        source = f"DATABASE_URL in {env_file}" if name in from_file and name not in values else name
        values = {**from_file, **values}
        remote = server_url(values.get(name), source) or _server_file_url(path.with_name(SERVER_FILE))
    return Settings(
        database_path=path.expanduser().resolve(),
        session_idle_minutes=_int(values, "SESSION_IDLE_MINUTES", 30),
        session_absolute_hours=_int(values, "SESSION_ABSOLUTE_HOURS", 12),
        login_max_failures=_int(values, "LOGIN_MAX_FAILURES", 5),
        login_window_minutes=_int(values, "LOGIN_WINDOW_MINUTES", 15),
        token_ttl_hours=_int(values, "TOKEN_TTL_HOURS", 72),
        server_url=remote,
    )


def settings_for_url(url: str) -> Settings:
    parsed = make_url(url)
    if parsed.get_backend_name() == "postgresql":
        base = load_settings({}, database_path=default_database_path())
        return Settings(base.database_path, server_url=server_url(url, "The database address"))
    database = parsed.database
    if not database:
        raise ConfigurationError("The database URL must name a file")
    return load_settings({}, database_path=database)

