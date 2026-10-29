from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

from techset_leadgen.domain.vocabulary import ACCOUNT_STATUSES, LEAD_STATUSES, PRIORITIES, TASK_STATUSES
from techset_leadgen.desktop.pages.admin_pages import ACTION_LABELS, _changes_summary, action_label, actions_matching
from techset_leadgen.desktop.pages.clients_page import ClientsPage
from techset_leadgen.desktop.pages.leads_page import LeadsPage
from techset_leadgen.desktop.support import date_text
from techset_leadgen.desktop.tables import EmptyMessage, TableDelegate, copy_selection, prepare_table, set_empty_text, tone_for
from techset_leadgen.desktop.widgets import sortable_item
from tests.qt_helpers import wait_until
from tests.ui.test_pyside_crm_pages import _ClientsController, _LeadsController


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()


def _table(rows: list[list[str]], headers: list[str], **options) -> QTableWidget:
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    prepare_table(table, **options)
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(value))
    return table


def test_every_stage_priority_and_status_has_a_badge_colour():
    labels = [*LEAD_STATUSES.values(), *PRIORITIES.values(), *TASK_STATUSES.values(), *ACCOUNT_STATUSES.values(),
              "Active", "Inactive", "Invited (no password yet)"]
    assert [label for label in labels if tone_for(label) is None] == []
    assert tone_for("Lost") == "danger" and tone_for("Client") == "success"
    assert tone_for("Acme Ltd") is None


def test_empty_message_shows_inside_the_table_until_rows_arrive(qapp):
    table = _table([], ["Name"], empty_text="No clients yet.")
    table.resize(400, 200)
    table.show()
    message = table.viewport().findChild(EmptyMessage)
    assert message is not None and message.isVisible() and message.text() == "No clients yet."
    table.setRowCount(1)
    assert not message.isVisible()
    table.setRowCount(0)
    set_empty_text(table, "No clients match this search.")
    assert message.isVisible() and message.text() == "No clients match this search."
    table.close()


def test_copy_puts_selected_rows_with_headers_on_the_clipboard(qapp):
    table = _table([["Acme", "2"], ["Beacon", "0"]], ["Name", "Sales"], numeric_columns=(1,), multi_select=True)
    table.selectRow(0)
    table.selectionModel().select(table.model().index(1, 0),
                                  table.selectionModel().SelectionFlag.Select
                                  | table.selectionModel().SelectionFlag.Rows)
    assert copy_selection(table) == "Name\tSales\nAcme\t2\nBeacon\t0"
    assert QGuiApplication.clipboard().text() == "Name\tSales\nAcme\t2\nBeacon\t0"
    header = table.horizontalHeaderItem(1)
    assert header is not None and header.textAlignment() & Qt.AlignmentFlag.AlignRight


def test_badges_paint_in_light_and_dark(qapp):
    table = _table([["Acme", "Qualified"], ["Beacon", "Lost"]], ["Name", "Stage"], badge_columns=(1,))
    assert isinstance(table.itemDelegate(), TableDelegate)
    table.resize(400, 160)
    assert not table.grab().isNull()


def test_dates_read_naturally_and_sort_by_date(qapp):
    assert date_text("2026-10-09") == "09 Oct 2026"
    assert date_text("2026-01-10 08:30:00") == "10 Jan 2026"
    assert date_text("") == "" and date_text("2026-10") == "2026-10"
    table = QTableWidget(2, 1)
    table.setItem(0, 0, sortable_item(date_text("2026-10-09"), "2026-10-09"))
    table.setItem(1, 0, sortable_item(date_text("2026-01-10"), "2026-01-10"))
    table.sortItems(0, Qt.SortOrder.AscendingOrder)
    assert [table.item(row, 0).text() for row in range(2)] == ["10 Jan 2026", "09 Oct 2026"]


def test_leads_table_uses_badges_dates_and_an_in_table_empty_message(qapp):
    page = LeadsPage(controller=_LeadsController, report_generator=lambda **_kwargs: (True, "", ""))
    table = page.leads_table
    assert table.rowCount() == 2
    assert {3, 5} <= table.itemDelegate().badge_columns
    dates = {table.item(row, 0).text() for row in range(table.rowCount())}
    assert dates == {"01 Oct 2026", "02 Oct 2026"}
    page.search_edit.setText("no such lead")
    assert wait_until(lambda: table.rowCount() == 0)
    message = table.viewport().findChild(EmptyMessage)
    assert message is not None and "No leads match" in message.text()
    assert table.isVisibleTo(page)
    page.deleteLater()


def test_clients_table_badges_numbers_and_empty_message(qapp):
    page = ClientsPage(controller=_ClientsController, latest_leads_provider=lambda: {},
                       report_generator=lambda **_kwargs: (True, "", ""))
    table = page.clients_table
    assert {7, 10} <= table.itemDelegate().badge_columns
    total = table.horizontalHeaderItem(5)
    assert total is not None and total.textAlignment() & Qt.AlignmentFlag.AlignRight
    page.search_edit.setText("zzz")
    qapp.processEvents()
    assert table.rowCount() == 0
    message = table.viewport().findChild(EmptyMessage)
    assert message is not None and "No clients match" in message.text()
    page.deleteLater()


def test_audit_actions_read_as_plain_language():
    assert action_label("lead.status_changed") == "Lead stage changed"
    assert action_label("auth.login_failed") == "Sign-in failed"
    assert action_label("something.new_thing") == "Something new thing"
    assert "lead.status_changed" in actions_matching("stage")
    assert actions_matching("SIGNED IN") == ["auth.login"]
    assert all(label[0].isupper() for label in ACTION_LABELS.values())
    names = {("user", "u-2"): "Sam Seller"}
    summary = _changes_summary({"owner_id": [None, "u-2"], "bulk": True}, entity_type="lead", names=names)
    assert summary == "owner: Unassigned → Sam Seller; bulk: Yes"
    assert _changes_summary({"status": ["new", "qualified"]}, entity_type="lead") == "status: Lead → Qualified"
    assert _changes_summary({"status": ["open", "done"]}, entity_type="task") == "status: Open → Done"
    assert _changes_summary({"reason": "bad_password"}) == "reason: wrong password"


def test_wide_tables_shrink_text_columns_so_actions_stay_visible(qapp):
    long = "A very long description that would push every later column off screen"
    table = _table([["Globex Corporation", long, "someone@example.com", "Qualified", ""]],
                   ["Name", "Notes", "Email", "Stage", "Actions"], badge_columns=(3,))
    table.resize(640, 240)
    table.show()
    from techset_leadgen.desktop.tables import fit_columns

    fit_columns(table, stretch_column=0, fixed_columns={4: 120}, min_widths={0: 150})
    qapp.processEvents()
    header = table.horizontalHeader()
    total = sum(header.sectionSize(column) for column in range(table.columnCount()))
    assert total <= table.viewport().width() + 1
    assert header.sectionSize(4) == 120
    assert header.sectionSize(0) >= table.sizeHintForColumn(0)
    assert header.sectionSize(1) < header.sectionSize(0) + 200
    table.resize(1400, 240)
    qapp.processEvents()
    assert header.sectionSize(1) > 300
    table.close()
    table.deleteLater()


@pytest.fixture
def scratch_settings(tmp_path):
    from PySide6.QtCore import QSettings

    previous = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    yield tmp_path
    QSettings.setDefaultFormat(previous)


def test_columns_can_be_hidden_and_the_choice_is_remembered(qapp, scratch_settings):
    from techset_leadgen.desktop.tables import enable_column_choice, reset_columns, set_column_shown

    headers = ["Name", "Tax ID", "Email", "Actions"]
    first = _table([["Acme", "B1", "a@x", ""]], headers)
    enable_column_choice(first, "test-clients", locked=(0, 3), hidden_by_default=(1, 2))
    assert [first.isColumnHidden(column) for column in range(4)] == [False, True, True, False]
    set_column_shown(first, 2, True)
    second = _table([["Acme", "B1", "a@x", ""]], headers)
    enable_column_choice(second, "test-clients", locked=(0, 3), hidden_by_default=(1, 2))
    assert [second.isColumnHidden(column) for column in range(4)] == [False, True, False, False]
    assert copy_selection(second) == ""
    second.selectRow(0)
    assert copy_selection(second).splitlines()[0] == "Name\tEmail"
    reset_columns(second)
    assert [second.isColumnHidden(column) for column in range(4)] == [False, True, True, False]
    third = _table([], headers)
    enable_column_choice(third, "test-clients", locked=(0, 3), hidden_by_default=(1, 2))
    assert third.isColumnHidden(2)


def test_marketing_ratios_without_spend_show_a_dash_not_zero(qapp):
    page = LeadsPage(controller=_LeadsController, report_generator=lambda **_kwargs: (True, "", ""))
    page._marketing_metrics = [
        {"source": "meta_ads", "leads": 4, "customers": 1, "revenue": 500, "spend": 0, "cpl": 0, "cac": 0, "roi": 0},
        {"source": "google_ads", "leads": 2, "customers": 1, "revenue": 300, "spend": 100, "cpl": 50, "cac": 100,
         "roi": 2},
    ]
    page._populate_marketing_table()
    rows = {page.marketing_table.item(row, 0).text(): [page.marketing_table.item(row, column).text()
                                                       for column in (5, 6, 7)]
            for row in range(page.marketing_table.rowCount())}
    assert rows["Meta Ads"] == ["—", "—", "—"]
    assert rows["Google Ads"] == ["€50.00", "€100.00", "200.0%"]
    page.deleteLater()


def test_hovering_a_shortened_cell_shows_its_full_text(qapp):
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QStyleOptionViewItem, QToolTip

    long = "Globex Corporation International Holdings and Subsidiaries"
    table = _table([[long, "Short"]], ["Name", "Other"])
    table.horizontalHeader().resizeSection(0, 90)
    table.resize(400, 120)
    table.show()
    qapp.processEvents()
    delegate = table.itemDelegate()
    option = QStyleOptionViewItem()
    option.initFrom(table.viewport())
    shortened = table.model().index(0, 0)
    point = table.visualRect(shortened).center()
    event = QHelpEvent(QEvent.Type.ToolTip, point, table.viewport().mapToGlobal(point))
    assert delegate.helpEvent(event, table, option, shortened)
    assert QToolTip.text() == long
    QToolTip.hideText()
    whole = table.model().index(0, 1)
    point = table.visualRect(whole).center()
    event = QHelpEvent(QEvent.Type.ToolTip, point, table.viewport().mapToGlobal(QPoint(point)))
    assert not delegate.helpEvent(event, table, option, whole)
    table.close()
    table.deleteLater()

