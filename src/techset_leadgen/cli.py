from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select

from techset_leadgen.config import ConfigurationError, load_settings
from techset_leadgen.database import migrations_util, server_backup, transfer
from techset_leadgen.database.engine import create_db_engine, create_session_factory
from techset_leadgen.database.models import User
from techset_leadgen.services import audit, auth
from techset_leadgen.services.normalize import email_lookup_key

COMMANDS = {
    "--issue-reset-code": "Print a one-time password-reset code for the given email address.",
    "--upgrade-database": "Upgrade the database schema to this version (team database: once per release).",
    "--copy-local-to-server": "Copy a local database file (default data/sales.db) into the empty team database.",
    "--backup-team-database": "Make a verified pg_dump backup of the team database (default folder data/backups).",
    "--restore-team-database": "Restore a team-database backup into the configured, new and empty database.",
}
ARGUMENT_REQUIRED = frozenset({"--issue-reset-code", "--restore-team-database"})


def run(command: str, argument: str | None, say: Callable[[str], None]) -> int:
    if command == "--issue-reset-code":
        return issue_reset_code(argument or "", say)
    if command == "--upgrade-database":
        return upgrade_database(say)
    if command == "--copy-local-to-server":
        return copy_local_to_server(argument, say)
    if command in ("--backup-team-database", "--restore-team-database"):
        return team_backup(command, argument, say)
    raise KeyError(command)


def team_backup(command: str, argument: str | None, say: Callable[[str], None]) -> int:
    settings = load_settings()
    if not settings.is_server:
        raise ConfigurationError("This computer uses a local file; back it up from Settings → Data & backups.")
    try:
        if command == "--backup-team-database":
            folder = Path(argument).expanduser() if argument else settings.database_path.parent / "backups"
            say(f"Backup of {settings.display_database} written and verified: "
                f"{server_backup.backup(settings.database_url, folder)}")
        else:
            server_backup.restore(Path(argument or "").expanduser(), settings.database_url)
            say(f"Restored {argument} into {settings.display_database}.")
    except server_backup.BackupFailed as exc:
        say(f"{command} did not complete: {exc}")
        return 1
    return 0


def upgrade_database(say: Callable[[str], None]) -> int:
    settings = load_settings()
    engine = create_db_engine(settings)
    try:
        with engine.connect() as connection:
            state = migrations_util.schema_state(connection)
    finally:
        engine.dispose()
    if state.newer_than_app:
        say(f"{settings.display_database} has schema {state.current}, newer than this version ({state.head}). "
            "Install the latest version.")
        return 1
    if state.ready:
        say(f"{settings.display_database} is up to date (schema {state.head}).")
        return 0
    if not settings.is_server and settings.database_path.is_file():
        from techset_leadgen.services import maintenance

        say(f"Backup: {maintenance.backup_before_migration(settings.database_path, state.current, state.head)}")
    migrations_util.upgrade(settings.database_url)
    say(f"{settings.display_database} upgraded from {state.current or 'empty'} to {state.head}.")
    return 0


def copy_local_to_server(source: str | None, say: Callable[[str], None]) -> int:
    settings = load_settings()
    if not settings.is_server:
        raise ConfigurationError("Set the team database address (TSLG_DATABASE_URL or database.ini) first.")
    path = Path(source).expanduser() if source else settings.database_path
    say(f"Copying {path} into {settings.display_database}…")
    try:
        copied = transfer.copy_local_to_server(path, settings.database_url, say)
    except transfer.TransferRefused as exc:
        say(f"Nothing was copied: {exc}")
        return 1
    say(f"Done: {sum(copied.values())} rows in {sum(1 for rows in copied.values() if rows)} tables.")
    return 0


def issue_reset_code(email: str, say: Callable[[str], None]) -> int:
    settings = load_settings()
    engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as db:
            user = db.scalar(select(User).where(User.email == email_lookup_key(email)))
            if user is None or not user.is_active:
                say(f"No active account uses {email!r} in {settings.display_database}.")
                return 1
            purpose = "invite" if user.password_hash is None else "password_reset"
            code = auth.issue_token(db, settings, user, purpose)
            audit.record(db, None, f"user.{purpose}_code_issued", entity_type="user", entity_id=user.id,
                         changes={"via": "command line"})
            db.commit()
    finally:
        engine.dispose()
    say(f"One-time code for {user.full_name} ({user.email}), valid for {settings.token_ttl_hours} hours:")
    say(code)
    say("Enter it on the sign-in screen under “I have an activation or password-reset code”.")
    return 0

