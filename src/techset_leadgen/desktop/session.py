from __future__ import annotations

import logging
import platform
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from PySide6.QtCore import QEvent, QObject, Qt, QTimeZone, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication
from sqlalchemy import Engine
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from techset_leadgen.branding import PRODUCT_NAME, PRODUCT_VERSION
from techset_leadgen.database.local_db import base_schema_needs_migration, init_db
from techset_leadgen.database import migrations_util
from techset_leadgen.config import ConfigurationError, Settings, load_settings
from techset_leadgen.database.engine import create_db_engine, create_session_factory, utcnow
from techset_leadgen.errors import Conflict
from techset_leadgen.services.schemas import ProfileUpdate
from techset_leadgen.services import audit, auth, maintenance, users
from techset_leadgen.services.access import Actor
from techset_leadgen.services.auth import SessionEnded, SignIn
from techset_leadgen.services.normalize import is_valid_timezone

logger = logging.getLogger("techset.leadgen.session")
T = TypeVar("T")


class ConnectionProblem(Exception):
    def __init__(self, message: str, details: str = "", *, retry: bool = True) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        self.retry = retry


@dataclass(frozen=True)
class CodeInfo:
    email: str
    full_name: str
    purpose: str


def system_timezone() -> str:
    name = bytes(QTimeZone.systemTimeZoneId().data()).decode("ascii", "ignore")
    return name if is_valid_timezone(name) else "UTC"


class AppContext(QObject):
    signed_in = Signal()
    signed_out = Signal(str)
    data_changed = Signal(str)

    def __init__(self, settings: Settings | None = None, parent: QObject | None = None, *,
                 previous_accounts: Path | None = None) -> None:
        super().__init__(parent)
        self._configured = settings
        self._settings: Settings | None = settings
        self._previous_accounts = previous_accounts
        self.engine: Engine | None = None
        self._factory: sessionmaker[Session] | None = None
        self._session_id: str | None = None
        self._token: str | None = None
        self.actor: Actor | None = None
        self.client_host = (platform.node() or "unknown computer")[:128]
        self.client_app = f"{PRODUCT_NAME} {PRODUCT_VERSION} ({platform.system()} {platform.release()})"[:128]
        self._input_seen = False
        self.last_backup: Path | None = None


    @property
    def settings(self) -> Settings:
        if self._settings is None:
            raise ConnectionProblem("The database is not open.")
        return self._settings

    @property
    def is_open(self) -> bool:
        return self._factory is not None

    @property
    def is_server(self) -> bool:
        return self._settings is not None and self._settings.is_server

    def open(self) -> None:
        self.close()
        try:
            settings = self._configured or load_settings()
        except ConfigurationError as exc:
            raise ConnectionProblem("The application settings are invalid.", str(exc), retry=False) from exc
        server = settings.is_server
        existed = not server and settings.database_path.is_file() and settings.database_path.stat().st_size > 0
        core_change = self._configured is None and not server and base_schema_needs_migration()
        engine = create_db_engine(settings)
        try:
            with self._busy():
                with engine.connect() as connection:
                    state = migrations_util.schema_state(connection)
                    before_upgrade = migrations_util.pre_upgrade_layout_problems(connection, state.current)
                if state.newer_than_app:
                    raise ConnectionProblem(
                        f"This copy of {PRODUCT_NAME} is older than its database.",
                        f"Install the latest version. Database schema {state.current}; this app supports up to "
                        f"{state.head}.\n{settings.display_database}", retry=False,
                    )
                if before_upgrade:
                    raise ConnectionProblem(
                        "This file is not a Techset LeadGen database this version can use.",
                        f"{settings.display_database}\n" + "; ".join(before_upgrade) + ".\nNothing was changed. "
                        "Restore the application database (data/sales.db) or a backup from data/backups.",
                        retry=False,
                    )
                if server and not state.ready:
                    raise ConnectionProblem(
                        "The team database needs an upgrade before this version can use it.",
                        f"{settings.display_database}: schema {state.current or 'empty'}, this app needs "
                        f"{state.head}.\nAsk your administrator to back up the database and run:\n"
                        f"{PRODUCT_NAME} --upgrade-database",
                    )
                if existed and (core_change or not state.ready):
                    self.last_backup = maintenance.backup_before_migration(settings.database_path, state.current,
                                                                           state.head)
                if self._configured is None and not server:
                    init_db()
                if not state.ready:
                    migrations_util.upgrade(settings.database_url)
                with engine.connect() as connection:
                    problems = migrations_util.layout_problems(connection)
                if problems:
                    raise ConnectionProblem(
                        "This file is not a Techset LeadGen database this version can use.",
                        f"{settings.display_database}\n" + "; ".join(problems) + ".\nNothing was changed. Restore "
                        "the application database (data/sales.db) or a backup from data/backups.", retry=False,
                    )
                self._factory = create_session_factory(engine)
                self.engine = engine
                if not server:
                    self._carry_over_accounts(settings)
        except SQLAlchemyError as exc:
            engine.dispose()
            self._factory = None
            self.engine = None
            logger.warning("Cannot open the database", exc_info=True)
            if server and isinstance(exc, OperationalError | InterfaceError):
                raise ConnectionProblem(
                    "The team database server cannot be reached.",
                    f"{settings.display_database}\nCheck this computer's network or VPN connection, then try "
                    f"again. Nothing was saved.\n\n{_short(exc)}") from exc
            raise ConnectionProblem("The database could not be opened.",
                                    f"{settings.display_database}\n\n{_short(exc)}") from exc
        except ConnectionProblem:
            engine.dispose()
            raise
        self._settings = settings

    def _carry_over_accounts(self, settings: Settings) -> None:
        legacy = self._previous_accounts
        if legacy is None and self._configured is None:
            legacy = settings.database_path.with_name("crm.db")
        if legacy is None:
            return
        with self._sessions()() as db:
            try:
                copied = maintenance.import_previous_accounts(db, legacy)
            except maintenance.LegacyRecordsFound as exc:
                self.close()
                raise ConnectionProblem("Records from an earlier version need attention.", exc.message) from exc
            if copied:
                db.commit()

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
        self.engine = None
        self._factory = None

    def shutdown(self) -> None:
        if self.is_signed_in:
            try:
                session_id = self.session_id
                self.run(lambda db, actor: auth.sign_out(db, actor, session_id), busy=False)
            except Exception:
                logger.warning("Could not end the session while closing", exc_info=True)
            self._forget()
        self.close()

    def _sessions(self) -> sessionmaker[Session]:
        if self._factory is None:
            raise ConnectionProblem("The database is not open.")
        return self._factory


    @property
    def is_signed_in(self) -> bool:
        return self._session_id is not None

    @property
    def session_id(self) -> str:
        if self._session_id is None:
            raise SessionEnded("Please sign in.")
        return self._session_id

    def has_users(self) -> bool:
        with self._sessions()() as db:
            return auth.has_users(db)

    def organization_name(self) -> str:
        with self._sessions()() as db:
            from techset_leadgen.database.models import Organization

            organization = db.get(Organization, 1)
            return organization.name if organization else ""

    def sign_in(self, email: str, password: str) -> None:
        with self._busy(), self._sessions()() as db:
            signed = auth.authenticate(db, self.settings, email=email, password=password,
                                       client_host=self.client_host, client_app=self.client_app)
        self._adopt(signed)

    def create_organization(self, *, organization_name: str, admin_name: str, email: str, password: str) -> None:
        with self._busy(), self._sessions()() as db:
            if auth.has_users(db):
                raise Conflict("Accounts already exist. Sign in instead.")
            user = auth.bootstrap_organization(db, organization_name=organization_name, admin_email=email,
                                               admin_name=admin_name, password=password)
            user.timezone = system_timezone()
            user.last_login_at = utcnow()
            signed = auth.open_session(db, self.settings, user, client_host=self.client_host,
                                       client_app=self.client_app)
            audit.record(db, None, "auth.login", entity_type="user", entity_id=user.id,
                         client_host=self.client_host)
            db.commit()
        self._adopt(signed)

    def describe_code(self, code: str) -> CodeInfo:
        with self._sessions()() as db:
            user, purpose = auth.code_owner(db, code)
            return CodeInfo(user.email, user.full_name, purpose)

    def redeem_code(self, code: str, password: str) -> None:
        with self._busy(), self._sessions()() as db:
            signed = auth.redeem_code(db, self.settings, raw_code=code, password=password,
                                      client_host=self.client_host, client_app=self.client_app)
        self._adopt(signed)
        zone = system_timezone()
        if self.actor is not None and self.actor.timezone == "UTC" and zone != "UTC":
            self.run(lambda db, actor: users.update_profile(db, actor, ProfileUpdate(timezone=zone)))

    def sign_out(self, reason: str = "You signed out.") -> None:
        if self.is_signed_in:
            session_id = self.session_id
            try:
                self.run(lambda db, actor: auth.sign_out(db, actor, session_id))
            except SessionEnded:
                return
            except Exception:
                logger.warning("Could not record the sign-out", exc_info=True)
        self._forget()
        self.signed_out.emit(reason)

    def _adopt(self, signed: SignIn) -> None:
        self._session_id = signed.session.id
        self._token = signed.raw_token
        self.actor = Actor.for_user(signed.user, client_host=self.client_host)
        self._input_seen = False
        self.signed_in.emit()

    def _forget(self) -> None:
        self._session_id = None
        self._token = None
        self.actor = None


    def can(self, permission: str) -> bool:
        return self.actor is not None and self.actor.can(permission)


    def run(self, work: Callable[[Session, Actor], T], *, commit: bool = True, busy: bool = True,
            touch: bool = True) -> T:
        session_id = self.session_id
        assert self._token is not None
        with self._busy(busy), self._sessions()() as db:
            try:
                row = auth.check_session(db, self.settings, session_id=session_id, raw_token=self._token,
                                         touch=touch)
                actor = Actor.for_user(row.user, client_host=self.client_host)
                self.actor = actor
                result = work(db, actor)
                if commit:
                    db.commit()
                else:
                    db.rollback()
                return result
            except SessionEnded as exc:
                db.rollback()
                self._forget()
                self.signed_out.emit(exc.message)
                raise
            except BaseException:
                db.rollback()
                raise

    def write(self, kind: str, work: Callable[[Session, Actor], T]) -> T:
        result = self.run(work)
        self._after_change(kind)
        return result

    def guarded(self, permission: str, action: str, operation: Callable[[], T], *, kind: str,
                entity_type: str | None = None, entity_id: Any = None,
                changes: Callable[[T], dict[str, Any] | None] | None = None) -> T:
        self.run(lambda db, actor: actor.require(permission))
        result = operation()
        described = changes(result) if changes else {}
        if described is None:
            return result
        self.run(lambda db, actor: audit.record(db, actor, action, entity_type=entity_type, entity_id=entity_id,
                                                changes=described or None))
        self._after_change(kind)
        return result

    def record(self, action: str, *, entity_type: str | None = None, entity_id: Any = None,
               changes: dict[str, Any] | None = None) -> None:
        self.run(lambda db, actor: audit.record(db, actor, action, entity_type=entity_type, entity_id=entity_id,
                                                changes=changes))

    def _after_change(self, kind: str) -> None:
        if kind in ("client", "data"):
            from techset_leadgen.analytics.models.client_manager import invalidate_clients_cache

            invalidate_clients_cache()
        self.data_changed.emit(kind)

    def verify(self) -> bool:
        if not self.is_signed_in:
            return False
        touch, self._input_seen = self._input_seen, False
        try:
            self.run(lambda db, actor: None, busy=False, touch=touch)
        except SessionEnded:
            return False
        except SQLAlchemyError:
            logger.warning("Session check failed; will retry", exc_info=True)
        return True

    def note_input(self) -> None:
        self._input_seen = True

    @contextmanager
    def _busy(self, enabled: bool = True) -> Iterator[None]:
        app = QApplication.instance()
        if not enabled or not isinstance(app, QGuiApplication):
            yield
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            yield
        finally:
            QGuiApplication.restoreOverrideCursor()


class InputMonitor(QObject):
    _EVENTS = frozenset({QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel})

    def __init__(self) -> None:
        super().__init__()
        self.seen = False
        self.installed = False

    def install(self) -> None:
        app = QApplication.instance()
        if app is not None and not self.installed:
            app.installEventFilter(self)
            self.installed = True

    def remove(self) -> None:
        app = QApplication.instance()
        if app is not None and self.installed:
            app.removeEventFilter(self)
        self.installed = False

    def take(self) -> bool:
        seen, self.seen = self.seen, False
        return seen

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        try:
            kind = event.type()
        except RuntimeError:
            return False
        if kind in self._EVENTS:
            self.seen = True
        return False


def _short(exc: BaseException) -> str:
    text = str(getattr(exc, "orig", None) or exc).strip().splitlines()
    return text[0][:300] if text else type(exc).__name__


__all__ = ["AppContext", "CodeInfo", "ConnectionProblem", "InputMonitor", "system_timezone"]

