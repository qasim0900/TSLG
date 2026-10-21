"""The signed-in session and units of work for every screen that changes data.

Every user action that changes data runs as one short unit of work: open a
database session, re-check the sign-in session (so a sign-out, deactivation, or
role change takes effect immediately), run the business service with the
signed-in ``Actor``, then commit or roll back. Screens copy what they show into
plain values inside the unit of work. The session token lives only in memory.

Operations that predate the account system (client merging, marketing spend,
imports, clearing tables) keep their original implementation; ``guarded``
checks the permission first and records the audit entry once they succeed.
"""

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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from branding import PRODUCT_NAME, PRODUCT_VERSION
from core.db import init_db
from crm import migrations_util
from crm.config import ConfigurationError, Settings, load_settings
from crm.db import create_db_engine, create_session_factory, utcnow
from crm.errors import Conflict
from crm.schemas import ProfileUpdate
from crm.services import audit, auth, maintenance, users
from crm.services.access import Actor
from crm.services.auth import SessionEnded, SignIn
from crm.services.normalize import is_valid_timezone

logger = logging.getLogger("techset.leadgen.session")
T = TypeVar("T")


class ConnectionProblem(Exception):
    """The database cannot be used; ``message`` is for users, ``details`` for administrators."""

    def __init__(self, message: str, details: str = "", *, retry: bool = True) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        self.retry = retry


@dataclass(frozen=True)
class CodeInfo:
    email: str
    full_name: str
    purpose: str  # "invite" or "password_reset"


def system_timezone() -> str:
    """The computer's IANA time zone (Qt reports IANA names on Windows too), or UTC."""
    name = bytes(QTimeZone.systemTimeZoneId().data()).decode("ascii", "ignore")
    return name if is_valid_timezone(name) else "UTC"


class AppContext(QObject):
    """Owns the database connection and the signed-in session."""

    signed_in = Signal()
    signed_out = Signal(str)  # reason shown on the sign-in screen
    data_changed = Signal(str)  # entity kind ("client", "lead", ...) after a successful change

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

    # ------------------------------------------------------------ connection

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            raise ConnectionProblem("The database is not open.")
        return self._settings

    @property
    def is_open(self) -> bool:
        return self._factory is not None

    def open(self) -> None:
        """Open the application database, upgrading its schema (after a backup) when needed."""
        self.close()
        try:
            settings = self._configured or load_settings()
        except ConfigurationError as exc:
            raise ConnectionProblem("The application settings are invalid.", str(exc), retry=False) from exc
        engine = create_db_engine(settings)
        try:
            with self._busy():
                if self._configured is None:
                    init_db()  # the original tables, created or migrated by core.db
                with engine.connect() as connection:
                    state = migrations_util.schema_state(connection)
                if state.newer_than_app:
                    raise ConnectionProblem(
                        f"This copy of {PRODUCT_NAME} is older than its database.",
                        f"Install the latest version. Database schema {state.current}; this app supports up to "
                        f"{state.head}.\n{settings.display_database}", retry=False,
                    )
                if not state.ready:
                    self.last_backup = maintenance.backup_before_migration(settings.database_path, state.current,
                                                                           state.head)
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
                self._carry_over_accounts(settings)
        except SQLAlchemyError as exc:
            engine.dispose()
            self._factory = None
            self.engine = None
            logger.warning("Cannot open the database", exc_info=True)
            raise ConnectionProblem("The database could not be opened.",
                                    f"{settings.display_database}\n\n{_short(exc)}") from exc
        except ConnectionProblem:
            engine.dispose()
            raise
        self._settings = settings

    def _carry_over_accounts(self, settings: Settings) -> None:
        legacy = self._previous_accounts
        if legacy is None and self._configured is None:
            legacy = settings.database_path.with_name("crm.db")  # separate database of an earlier build
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
        """End the session (best effort) and release the connection pool."""
        if self.is_signed_in:
            try:
                session_id = self.session_id
                self.run(lambda db, actor: auth.sign_out(db, actor, session_id), busy=False)
            except Exception:  # closing must never fail; the session also expires on its own
                logger.warning("Could not end the session while closing", exc_info=True)
            self._forget()
        self.close()

    def _sessions(self) -> sessionmaker[Session]:
        if self._factory is None:
            raise ConnectionProblem("The database is not open.")
        return self._factory

    # ------------------------------------------------------------ sign-in

    @property
    def is_signed_in(self) -> bool:
        return self._session_id is not None

    @property
    def session_id(self) -> str:
        """The signed-in session (raises ``SessionEnded`` when signed out)."""
        if self._session_id is None:
            raise SessionEnded("Please sign in.")
        return self._session_id

    def has_users(self) -> bool:
        with self._sessions()() as db:
            return auth.has_users(db)

    def organization_name(self) -> str:
        with self._sessions()() as db:
            from crm.models import Organization

            organization = db.get(Organization, 1)
            return organization.name if organization else ""

    def sign_in(self, email: str, password: str) -> None:
        with self._busy(), self._sessions()() as db:
            signed = auth.authenticate(db, self.settings, email=email, password=password,
                                       client_host=self.client_host, client_app=self.client_app)
        self._adopt(signed)

    def create_organization(self, *, organization_name: str, admin_name: str, email: str, password: str) -> None:
        """First run: name the organization and create the first Super Admin, then sign in."""
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
            # A new account starts in UTC; adopt this computer's zone for due dates.
            self.run(lambda db, actor: users.update_profile(db, actor, ProfileUpdate(timezone=zone)))

    def sign_out(self, reason: str = "You signed out.") -> None:
        if self.is_signed_in:
            session_id = self.session_id
            try:
                self.run(lambda db, actor: auth.sign_out(db, actor, session_id))
            except SessionEnded:
                return  # already signed out and announced
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

    # ------------------------------------------------------------ permissions shown in the UI

    def can(self, permission: str) -> bool:
        """For showing or hiding controls only; the services enforce the same rule."""
        return self.actor is not None and self.actor.can(permission)

    # ------------------------------------------------------------ units of work

    def run(self, work: Callable[[Session, Actor], T], *, commit: bool = True, busy: bool = True,
            touch: bool = True) -> T:
        """Run ``work`` as the signed-in user in one transaction.

        ``commit=False`` rolls everything back. Service errors (``DomainError``)
        propagate unchanged; ``SessionEnded`` also signs this window out.
        """
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
        """``run`` a change and announce it so other screens refresh."""
        result = self.run(work)
        self._after_change(kind)
        return result

    def guarded(self, permission: str, action: str, operation: Callable[[], T], *, kind: str,
                entity_type: str | None = None, entity_id: Any = None,
                changes: Callable[[T], dict[str, Any] | None] | None = None) -> T:
        """Run an original (pre-accounts) operation with the permission checked first and the
        audit entry recorded once it succeeds (``changes`` returns None when it did not). The
        operation uses its own connection, so it runs between the two units of work, never
        inside one: a crash in between would leave the change without its audit entry."""
        self.run(lambda db, actor: actor.require(permission))
        result = operation()
        described = changes(result) if changes else {}
        if described is None:  # the operation reported that nothing changed
            return result
        self.run(lambda db, actor: audit.record(db, actor, action, entity_type=entity_type, entity_id=entity_id,
                                                changes=described or None))
        self._after_change(kind)
        return result

    def record(self, action: str, *, entity_type: str | None = None, entity_id: Any = None,
               changes: dict[str, Any] | None = None) -> None:
        """Audit an event that already happened elsewhere (for example a finished import)."""
        self.run(lambda db, actor: audit.record(db, actor, action, entity_type=entity_type, entity_id=entity_id,
                                                changes=changes))

    def _after_change(self, kind: str) -> None:
        if kind in ("client", "data"):
            from models.client_manager import invalidate_clients_cache

            invalidate_clients_cache()  # the analytics keep a client-name cache
        self.data_changed.emit(kind)

    def verify(self) -> bool:
        """Periodic check: is the session still valid? Touches it only after real user input."""
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
    """Application-wide event filter, installed only while signed in: notes keyboard, mouse,
    and wheel input so reading or typing (not just saving) keeps the session alive."""

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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        try:
            kind = event.type()
        except RuntimeError:  # PySide can hand over a wrapper whose C++ event is already gone
            return False
        if kind in self._EVENTS:
            self.seen = True
        return False


def _short(exc: BaseException) -> str:
    text = str(getattr(exc, "orig", None) or exc).strip().splitlines()
    return text[0][:300] if text else type(exc).__name__


__all__ = ["AppContext", "CodeInfo", "ConnectionProblem", "InputMonitor", "system_timezone"]
