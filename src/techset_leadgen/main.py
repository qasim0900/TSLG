from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QCoreApplication, QLocale, Qt
from PySide6.QtWidgets import QApplication

from techset_leadgen.branding import PARENT_BRAND, PRODUCT_NAME, PRODUCT_VERSION
from techset_leadgen import cli as crm_cli
from techset_leadgen.config import load_settings
from techset_leadgen.database.local_db import get_logs_dir, init_db
from techset_leadgen.desktop.dialogs import show_message
from techset_leadgen.desktop.main_window import MainWindow
from techset_leadgen.desktop.theme import ThemeManager

logger = logging.getLogger("techset.leadgen")

_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_HANDLER_NAME = "techset-leadgen"


def configure_logging() -> None:
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
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    if existing is not None:
        raise RuntimeError("A non-GUI QCoreApplication already exists in this process")

    QCoreApplication.setOrganizationName(PARENT_BRAND)
    QCoreApplication.setOrganizationDomain("techsetsolutions.com")
    QCoreApplication.setApplicationName(PRODUCT_NAME)
    QCoreApplication.setApplicationVersion(PRODUCT_VERSION)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedKingdom))
    return QApplication(list(argv) if argv is not None else sys.argv)


def create_main_window(app: QApplication | None = None) -> MainWindow:
    application = app or create_application()
    theme_manager = ThemeManager(application)
    theme_manager.apply()
    return MainWindow(theme_manager)


def run(argv: Sequence[str] | None = None) -> int:
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


def run_admin_command(command: str, argument: str | None) -> int:
    configure_logging()
    lines: list[str] = []

    def say(text: str) -> None:
        lines.append(text)
        if sys.stdout is not None:
            print(text, flush=True)

    if argument is not None and argument.startswith("--"):
        argument = None
    if command in crm_cli.ARGUMENT_REQUIRED and not argument:
        say(f"Usage: {PRODUCT_NAME} {command} EMAIL")
        code = 2
    else:
        try:
            if command == "--issue-reset-code" and not load_settings().is_server:
                init_db()
            code = crm_cli.run(command, argument, say)
        except Exception as exc:
            logger.exception("Administrator command %s failed", command)
            say(f"{command} failed: {exc}")
            code = 1
    if sys.stdout is None:
        create_application([sys.argv[0]])
        show_message(None, title=PRODUCT_NAME, heading=lines[0] if lines else command,
                     message="\n".join(lines[1:]), level="info" if code == 0 else "error")
    return code


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)
    for command in crm_cli.COMMANDS:
        if command in arguments[1:]:
            position = arguments.index(command)
            argument = arguments[position + 1] if position + 1 < len(arguments) else None
            return run_admin_command(command, argument)
    if "--version" in arguments[1:]:
        print(f"{PRODUCT_NAME} {PRODUCT_VERSION}")
        return 0
    return run(arguments)


if __name__ == "__main__":
    raise SystemExit(main())

