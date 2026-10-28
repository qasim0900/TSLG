"""Headless integration checks for the native PySide6 application shell."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from techset_leadgen.branding import LOGO_ASSET, PRODUCT_NAME, PRODUCT_TAGLINE
from techset_leadgen.database.local_db import init_db
from techset_leadgen.desktop.main_window import MainWindow
from techset_leadgen.desktop.pages import ClientsPage, DashboardPage, LeadsPage, SalesPage
from techset_leadgen.desktop.pages.assignment_pages import AssignmentsPage
from techset_leadgen.desktop.pages.operational_dashboard_page import OperationalDashboardPage
from techset_leadgen.desktop.pages.outreach_pages import FollowUpsPage, MyWorkPage
from techset_leadgen.desktop.pages.prospects_page import ProspectsPage
from techset_leadgen.desktop.pages.team_pages import NotificationsPage, TeamPage
from techset_leadgen.desktop.theme import ThemeManager, asset_path
from techset_leadgen.main import create_application
from tests.qt_helpers import sign_in_window


@pytest.fixture(scope="module")
def qt_app(tmp_path_factory):
    settings_root = tmp_path_factory.mktemp("qt-settings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(settings_root),
    )
    application = QApplication.instance() or create_application(["techset-leadgen-test"])
    yield application
    application.processEvents()


@pytest.fixture()
def window(qt_app):
    init_db()
    manager = ThemeManager(qt_app)
    manager.apply(False)
    shell = MainWindow(manager)
    shell.show()
    qt_app.processEvents()
    sign_in_window(shell)
    yield shell
    shell.close()
    shell.deleteLater()
    qt_app.processEvents()


def test_shell_uses_brand_assets_and_all_native_pages(window, qt_app) -> None:
    assert window.windowTitle() == PRODUCT_NAME
    assert not window.windowIcon().isNull()
    assert asset_path(LOGO_ASSET).is_file()
    assert PRODUCT_TAGLINE

    expected = {
        "dashboard": OperationalDashboardPage,
        "my_work": MyWorkPage,
        "assignments": AssignmentsPage,
        "prospects": ProspectsPage,
        "followups": FollowUpsPage,
        "team": TeamPage,
        "notifications": NotificationsPage,
        "sales_overview": DashboardPage,  # the archive: the original analytics, unchanged
        "sales": SalesPage,
        "leads": LeadsPage,
        "clients": ClientsPage,
    }
    for name, page_type in expected.items():
        window.navigate(name)
        qt_app.processEvents()
        assert isinstance(window.stack.currentWidget(), page_type)
        assert window._nav_buttons[name].isChecked()


def test_theme_toggle_and_compact_navigation(window, qt_app) -> None:
    initial = window.theme_manager.dark
    window._toggle_theme()
    qt_app.processEvents()
    assert window.theme_manager.dark is not initial

    window.resize(820, 700)
    qt_app.processEvents()
    assert window._compact_navigation is True
    assert window.brand_copy.isHidden()

    window.resize(1200, 780)
    qt_app.processEvents()
    assert window._compact_navigation is False
    assert not window.brand_copy.isHidden()


def test_packaged_brand_files_exist() -> None:
    for name in ("techset_logo.png", "techset_logo_with_text.png", "techset_favicon.ico"):
        path = asset_path(name)
        assert isinstance(path, Path)
        assert path.is_file()
