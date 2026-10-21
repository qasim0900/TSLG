"""Error reporting and display formatting shared by the desktop screens."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from PySide6.QtWidgets import QWidget
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm.exc import StaleDataError

from branding import PRODUCT_NAME
from crm.errors import DomainError
from crm.services.auth import SessionEnded
from crm.services.common import STALE_MESSAGE

from .dialogs import Level, show_message
from .session import AppContext, ConnectionProblem

logger = logging.getLogger("techset.leadgen.ui")
T = TypeVar("T")

INTEGRITY_MESSAGE = (
    "This would duplicate a record that already exists (someone may have saved it a moment ago). "
    "Reload the list and try again."
)


def explain(exc: BaseException) -> tuple[str, str]:
    """``(heading, message)`` describing ``exc`` for the user, without internals."""
    if isinstance(exc, DomainError):
        details = "\n".join(f"• {message}" for message in exc.fields.values() if message != exc.message)
        return exc.message, details
    if isinstance(exc, ConnectionProblem):
        return exc.message, exc.details
    if isinstance(exc, StaleDataError):
        return STALE_MESSAGE, ""
    if isinstance(exc, IntegrityError):
        return INTEGRITY_MESSAGE, ""
    if isinstance(exc, SQLAlchemyError):
        return (
            "The application data could not be accessed.",
            "Check that the local data file is available, then try again. Your last change was not saved.",
        )
    return "Something went wrong.", "The problem was written to the application log."


def report(parent: QWidget | None, exc: BaseException, *, title: str = "Action") -> None:
    """Show ``exc`` to the user. Session endings are announced by the sign-in screen instead."""
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
    """Run a unit of work and report failures; returns ``(succeeded, result)``."""
    try:
        if kind is not None:
            return True, context.write(kind, work)
        return True, context.run(work, **options)
    except Exception as exc:  # every failure is shown; nothing is silently swallowed
        report(parent, exc, title=title)
        return False, None


# --- formatting ---------------------------------------------------------------

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def local_time(value: datetime | None, timezone: str, *, with_time: bool = True) -> str:
    """``21 Oct 2026, 14:05`` in the user's time zone.

    Not ``strftime("%b")``: Qt applies the system locale, so month names would
    come out in, e.g., Urdu script inside English sentences and reorder the text.
    """
    if value is None:
        return ""
    local = value.astimezone(ZoneInfo(timezone))
    day = f"{local.day:02d} {_MONTHS[local.month - 1]} {local.year}"
    return f"{day}, {local:%H:%M}" if with_time else day


def date_text(value: Any) -> str:
    """``YYYY-MM-DD`` (the original date columns) as ``09 Oct 2026``; other text is returned as is."""
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
    """``[(value, label)]`` for a vocabulary dict or a tuple of plain values."""
    if isinstance(mapping, Mapping):
        return list(mapping.items())
    return [(value, value) for value in mapping]


__all__ = ["attempt", "explain", "label", "labels", "local_time", "options", "person", "report", "text"]
