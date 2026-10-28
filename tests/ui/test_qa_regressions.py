"""Regression tests for the defects found by the QA run of 27 Oct 2026 (qa_artifacts/reports/BUGS.md)."""

from __future__ import annotations

import locale
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLabel

from techset_leadgen.database.models import User
from techset_leadgen.desktop.auth_pages import SignInPage
from techset_leadgen.desktop.pages.assignment_pages import BatchDialog
from techset_leadgen.desktop.pages.operational_dashboard_page import OperationalDashboardPage
from techset_leadgen.desktop.pages.team_pages import TeamPage
from techset_leadgen.security.passwords import hash_password

from tests.qt_helpers import TEST_PASSWORD, signed_in_context


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()


@pytest.fixture()
def context(tmp_path: Path, qapp):
    value = signed_in_context(tmp_path / "qa.db")
    yield value
    value.shutdown()
    qapp.processEvents()


def test_bug001_team_summary_date_ignores_the_system_language(qapp, context):
    previous = locale.setlocale(locale.LC_TIME)
    try:
        locale.setlocale(locale.LC_TIME, "ur_PK.UTF-8")  # month names in Urdu script
    except locale.Error:
        pytest.skip("the ur_PK locale is not installed")
    try:
        page = TeamPage(context)
        page.refresh()
        note = page.note.text()
    finally:
        locale.setlocale(locale.LC_TIME, previous)
    day = note.split(" in ")[0].removeprefix("Business day ")
    assert day.isascii() and len(day.split()) == 3, note  # "27 Oct 2026"


def test_bug002_dashboard_cards_fill_the_row_after_narrowing(qapp, context):
    page = OperationalDashboardPage(context)
    page.resize(1500, 900)
    page.show()
    qapp.processEvents()
    page.resize(1100, 900)  # 2 columns, as at 1366×768 with the sidebar
    qapp.processEvents()
    assert [page.kpi_grid.columnStretch(column) for column in range(4)] == [1, 1, 0, 0]
    page.close()


def test_bug003_sign_in_footer_names_the_team_database(qapp):
    label = QLabel()
    SignInPage.show_location(label, "Team database techset on office:5432", server=True)
    assert label.text().startswith("Team database ·")
    SignInPage.show_location(label, "Local file on this computer: /data/sales.db")
    assert label.text().startswith("Local database ·")


def test_bug004_and_005_search_placeholder_and_tagline(qapp, tmp_path, monkeypatch):
    from techset_leadgen.config import load_settings
    from techset_leadgen.desktop.main_window import MainWindow
    from techset_leadgen.desktop.session import AppContext
    from techset_leadgen.desktop.theme import ThemeManager

    context = AppContext(load_settings({}, database_path=tmp_path / "shell.db"))
    window = MainWindow(ThemeManager(qapp), context=context)
    window.resize(1366, 768)
    window.show()
    qapp.processEvents()
    assert window.search_field.placeholderText() == "Search prospects…"
    tagline = window.findChild(QLabel, "productTagline")
    assert tagline is not None and tagline.sizeHint().width() <= tagline.width(), "the tagline is cut off"
    window.close()


def test_bug006_batch_workload_columns_stay_visible(qapp, context):
    context.write("user", lambda db, _actor: db.add(User(
        email="member.with.a.long.name@techset.example", full_name="Muhammad Abdullah Siddiqui", role="bdr",
        password_hash=hash_password(TEST_PASSWORD), is_active=True)))
    dialog = BatchDialog(None, context)
    dialog.show()
    qapp.processEvents()
    table = dialog.member_table
    header = table.horizontalHeader()
    used = sum(header.sectionSize(column) for column in range(table.columnCount()))
    assert used <= table.viewport().width() + 1, (used, table.viewport().width())
    assert header.sectionSize(3) >= header.sectionSizeHint(3), "the After column is cut"
    dialog.reject()
    # Deleted now, while the application exists: a window left for interpreter shutdown crashed the
    # whole test run on exit ("pure virtual method called"), after every test had passed (QA BUG-108).
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_bug007_team_summary_names_are_not_cut(qapp, context):
    context.write("user", lambda db, _actor: db.add(User(
        email="long.name@techset.example", full_name="Muhammad Abdullah Siddiqui", role="bdr",
        password_hash=hash_password(TEST_PASSWORD), is_active=True)))
    page = TeamPage(context)
    page.resize(1100, 700)
    page.show()
    page.refresh()
    qapp.processEvents()
    needed = page.table.fontMetrics().horizontalAdvance("Muhammad Abdullah Siddiqui")
    assert page.table.columnWidth(0) >= needed + 16
    page.close()
