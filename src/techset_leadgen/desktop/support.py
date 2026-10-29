from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from PySide6.QtWidgets import QWidget
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from techset_leadgen.branding import PRODUCT_NAME
from techset_leadgen.errors import DomainError
from techset_leadgen.services.auth import SessionEnded
from techset_leadgen.services.common import STALE_MESSAGE

from techset_leadgen.desktop.dialogs import Level, show_message
from techset_leadgen.desktop.session import AppContext, ConnectionProblem

logger = logging.getLogger("techset.leadgen.ui")
T = TypeVar("T")

INTEGRITY_MESSAGE = (
    "This would duplicate a record that already exists (someone may have saved it a moment ago). "
    "Reload the list and try again."
)


def explain(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, DomainError):
        details = "\n".join(f"• {message}" for message in exc.fields.values() if message != exc.message)
        return exc.message, details
    if isinstance(exc, ConnectionProblem):
        return exc.message, exc.details
    if isinstance(exc, StaleDataError):
        return STALE_MESSAGE, ""
    if isinstance(exc, IntegrityError):
        return INTEGRITY_MESSAGE, ""
    if isinstance(exc, OperationalError | InterfaceError) and _remote(exc):
        return (
            "The team database server could not be reached.",
            "Check this computer's network or VPN connection, then try again. Your last change was not saved.",
        )
    if isinstance(exc, SQLAlchemyError):
        return (
            "The application data could not be accessed.",
            "Check that the local data file is available, then try again. Your last change was not saved.",
        )
    return "Something went wrong.", "The problem was written to the application log."


def _remote(exc: SQLAlchemyError) -> bool:
    origin = getattr(exc, "orig", None)
    return origin is not None and type(origin).__module__.startswith("psycopg")


def report(parent: QWidget | None, exc: BaseException, *, title: str = "Action") -> None:
    if isinstance(exc, SessionEnded):
        return
    if not isinstance(exc, DomainError | ConnectionProblem | SQLAlchemyError):
        logger.exception("Unexpected application error", exc_info=exc)
    elif isinstance(exc, SQLAlchemyError) and not isinstance(exc, StaleDataError | IntegrityError):
        logger.warning("Application data error", exc_info=exc)
    heading, message = explain(exc)
    level: Level = "warning" if isinstance(exc, DomainError) else "error"
    show_message(parent, title=f"{PRODUCT_NAME} – {title}", heading=heading, message=message, level=level)


def attempt(parent: QWidget | None, context: AppContext, work: Callable[..., T], *, kind: str | None = None,
            title: str = "Action", **options: Any) -> tuple[bool, T | None]:
    try:
        if kind is not None:
            return True, context.write(kind, work)
        return True, context.run(work, **options)
    except Exception as exc:
        report(parent, exc, title=title)
        return False, None


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def local_time(value: datetime | None, timezone: str, *, with_time: bool = True) -> str:
    if value is None:
        return ""
    local = value.astimezone(ZoneInfo(timezone))
    day = f"{local.day:02d} {_MONTHS[local.month - 1]} {local.year}"
    return f"{day}, {local:%H:%M}" if with_time else day


def date_text(value: Any) -> str:
    raw = str(value or "").strip()[:10]
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return raw
    return f"{parsed.day:02d} {_MONTHS[parsed.month - 1]} {parsed.year}"


def label(options: Mapping[str, str], value: str | None, default: str = "") -> str:
    if not value:
        return default
    return options.get(value, value)


def labels(options: Mapping[str, str], values: Iterable[str] | None) -> str:
    return ", ".join(options.get(value, value) for value in values or [])


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def person(user: Any, default: str = "Unassigned") -> str:
    return user.full_name if user is not None else default


def options(mapping: Mapping[str, str] | Iterable[str]) -> list[tuple[str, str]]:
    if isinstance(mapping, Mapping):
        return list(mapping.items())
    return [(value, value) for value in mapping]


__all__ = ["attempt", "explain", "label", "labels", "local_time", "options", "person", "report", "text"]

