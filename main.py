"""Techset LeadGen native PySide6 application entry point."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication

from branding import PARENT_BRAND, PRODUCT_NAME
from core.db import get_logs_dir, init_db
from desktop_ui.dialogs import show_message
from desktop_ui.main_window import MainWindow
from desktop_ui.theme import ThemeManager

logger = logging.getLogger("techset.leadgen")

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_HANDLER_NAME = "techset-leadgen"


def configure_logging() -> None:
    """Configure console and rotating local application logs once."""
    root = logging.getLogger()
    if any(handler.get_name() == _HANDLER_NAME for handler in root.handlers):
        return

    configured_level = getattr(
        logging,
        os.environ.get("TSLG_LOG_LEVEL", os.environ.get("FDT_LOG_LEVEL", "INFO")).upper(),
        logging.INFO,
    )
    formatter = logging.Formatter(_LOG_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(formatter)
    console.set_name(_HANDLER_NAME)
    root.addHandler(console)

    try:
        file_handler = RotatingFileHandler(
            get_logs_dir() / "app.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Could not create the application log", exc_info=True)
    else:
        file_handler.setLevel(configured_level)
        file_handler.setFormatter(formatter)
        file_handler.set_name(_HANDLER_NAME)
        root.addHandler(file_handler)

    root.setLevel(configured_level)


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Return the process QApplication, creating it when necessary."""
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    if existing is not None:
        raise RuntimeError("A non-GUI QCoreApplication already exists in this process")

    QCoreApplication.setOrganizationName(PARENT_BRAND)
    QCoreApplication.setOrganizationDomain("techsetsolutions.com")
    QCoreApplication.setApplicationName(PRODUCT_NAME)
    QCoreApplication.setApplicationVersion("0.1.0")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    return QApplication(list(argv) if argv is not None else sys.argv)


def create_main_window(app: QApplication | None = None) -> MainWindow:
    """Initialize persistence, theme, and the top-level desktop window."""
    application = app or create_application()
    init_db()
    theme_manager = ThemeManager(application)
    theme_manager.apply()
    return MainWindow(theme_manager)


def run(argv: Sequence[str] | None = None) -> int:
    """Start Techset LeadGen and return Qt's process exit code."""
    configure_logging()
    application = create_application(argv)
    try:
        window = create_main_window(application)
    except Exception as exc:
        logger.exception("Fatal error while starting %s", PRODUCT_NAME)
        show_message(
            None,
            title=f"{PRODUCT_NAME} startup error",
            heading="The application could not start",
            message=f"{exc}\n\nTechnical details: {get_logs_dir() / 'app.log'}",
            level="error",
        )
        return 1

    window.show()
    logger.info("%s started with PySide6", PRODUCT_NAME)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(run())
