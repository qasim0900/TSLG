"""Regression tests for defects found in the October 2026 desktop audit.

Each test names its defect ID from ``docs/quality/DEFECT_LOG.md``. Tests drive
the real widgets and production dialogs (via ``ModalPilot``) against pytest's
sandboxed SQLite database; nothing here touches user data or settings.
"""

from __future__ import annotations

import dataclasses
import locale
import logging
import os
import subprocess
import sys
import textwrap
from contextlib import closing
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDate, QObject, QPoint, QSettings, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QToolButton
from shiboken6 import Shiboken

from analysis.leads_analysis import _log_lead_consistency
from analysis.time_grouping import group_time_series
from core.db import get_connection, init_db
from core.importer import inspect_import_file
from desktop_ui.main_window import MainWindow
from desktop_ui.pages.clients_page import ClientDetailDialog, ClientFormDialog, ClientsPage
from desktop_ui.pages.leads_page import LeadEditDialog, LeadsPage
from desktop_ui.pages.marketing_spend_dialog import MarketingSpendDialog
from desktop_ui.pages.sales_page import SalesPage
from domain.analysis_snapshot import ClientRank
from desktop_ui.row_actions import RowActionDelegate
from desktop_ui.theme import ThemeManager
from main import create_application
from models.client_manager import invalidate_clients_cache
from tests.qt_helpers import ModalPilot, choose_file, click_button, reject, wait_until
from utils.formatting import format_datetime_us, format_day_month_year_time
from utils.import_templates import write_template

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def qapp(tmp_path_factory):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path_factory.mktemp("qt-settings")),
    )
    application = QApplication.instance() or create_application(["techset-leadgen-test"])
    yield application
    application.processEvents()


def _clear_database() -> None:
    with closing(get_connection()) as connection:
        with connection:
            for table in (
                "funnel_events",
                "leads",
                "sales",
                "marketing_spend",
                "import_metadata",
                "clients",
            ):
                connection.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed whitelist
    invalidate_clients_cache()


def _count(table: str) -> int:
    with closing(get_connection()) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608


@pytest.fixture()
def empty_db():
    init_db()
    _clear_database()
    yield
    _clear_database()


@pytest.fixture()
def shell(qapp, empty_db):
    manager = ThemeManager(qapp)
    manager.apply(False)
    window = MainWindow(manager)
    window.resize(1280, 820)
    window.show()
    qapp.processEvents()
    yield window
    window.close()
    window.deleteLater()
    qapp.processEvents()


def _button(root, text: str) -> QPushButton:
    matches = [button for button in root.findChildren(QPushButton) if button.text().replace("&", "") == text]
    assert matches, f"No button {text!r}"
    return matches[0]


def _import_through_gui(shell: MainWindow, path: Path, qapp) -> list:
    """Click Dashboard > Import data, pick ``path`` in the file dialog, confirm the preview."""
    shell.navigate("dashboard")
    qapp.processEvents()
    with ModalPilot(choose_file(path), click_button("Import data")) as pilot:
        QTest.mouseClick(_button(shell.stack.currentWidget(), "Import data"), Qt.MouseButton.LeftButton)
        assert wait_until(lambda: not shell.import_coordinator.is_busy, 15000)
        qapp.processEvents()
    return pilot.seen


# ------------------------------------------------- DEF-001: teardown abort


def _python_owned_children(root: QObject) -> list[str]:
    return [
        f"{type(child).__name__}({child.objectName()})"
        for child in root.findChildren(QObject)
        if Shiboken.ownedByPython(child) and child.parent() is not None
    ]


def test_def001_widgets_are_owned_by_their_qt_parents(shell, qapp):
    """Widgets added to parentless layouts stayed Python-owned and were freed twice."""
    for page in ("sales", "leads", "clients"):
        shell.navigate(page)
        qapp.processEvents()
    dialogs = (
        ClientFormDialog(),
        ClientFormDialog(client=("C1", "Acme", "", "", "", ""), lead={"id": "L1", "status": "new"}),
        ClientDetailDialog({"client_id": "C1", "name": "Acme"}, {"sales": []}),
        LeadEditDialog({"id": "L1", "status": "new"}),
        MarketingSpendDialog(),
    )
    assert _python_owned_children(shell) == []
    for dialog in dialogs:
        assert _python_owned_children(dialog) == [], type(dialog).__name__
        dialog.deleteLater()


def test_def001_destroying_rendered_sales_pages_exits_cleanly():
    """The interpreter aborted with heap corruption after a rendered SalesPage existed."""
    script = textwrap.dedent(
        """
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        from tests.test_pyside_sales_page import _FakeSalesController, _snapshot
        from desktop_ui.pages.sales_page import SalesPage
        for _ in range(5):
            page = SalesPage(
                controller=_FakeSalesController(_snapshot()),
                clients_provider=list,
                products_provider=list,
            )
            page.resize(1100, 800)
            page.show()
            app.processEvents()
            page.close()
            del page
        """
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and inline script
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]


# ------------------------------------- DEF-003: spend files imported as leads


def test_def003_builtin_spend_template_is_detected_as_marketing_spend(tmp_path):
    for kind in ("sales", "leads", "marketing_spend"):
        template = write_template(kind, tmp_path / f"{kind}.csv")
        assert inspect_import_file(str(template))["detected_type"] == kind


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("platform,cost,date\nGoogle,120,2026-01-01\n", "marketing_spend"),
        ("campaign_id,campaign_status,channel,spend,month\n9,active,Meta,50,2026-01\n", "marketing_spend"),
        ("leadgen_id,created_time,platform,cost\nX1,2026-01-01,Meta,4\n", "leads"),
        ("date,source,status\n2026-01-01,Google,new\n", "leads"),
    ],
)
def test_def003_spend_and_lead_exports_are_told_apart(tmp_path, body, expected):
    path = tmp_path / "upload.csv"
    path.write_text(body, encoding="utf-8")
    assert inspect_import_file(str(path))["detected_type"] == expected


def test_def003_downloaded_spend_template_round_trips_into_marketing_spend(shell, qapp, tmp_path):
    target = tmp_path / "spend.csv"
    with ModalPilot(choose_file(target)):
        QTest.mouseClick(_button(shell.stack.currentWidget(), "Spend CSV"), Qt.MouseButton.LeftButton)
    assert target.read_text(encoding="utf-8").startswith("source,amount,date")

    seen = _import_through_gui(shell, target, qapp)

    assert [item.kind for item in seen if item.kind != "QProgressDialog"] == [
        "QFileDialog",
        "ImportPreviewDialog",
    ]
    assert wait_until(lambda: _count("marketing_spend") == 2)
    assert _count("leads") == 0


# ------------------------------------------ DEF-004: duplicate error dialogs


def test_def004_page_errors_open_a_single_dialog(shell, qapp):
    shell.navigate("clients")
    page = shell.stack.currentWidget()
    with ModalPilot() as pilot:
        assert page.edit_client("does-not-exist") is False
        qapp.processEvents()
    assert [item.text for item in pilot.message_boxes] == [
        "Client not found. Refresh the page and try again."
    ]


# ------------------------------- DEF-005: rejected client form discarded input


def test_def005_rejected_client_form_keeps_input_and_saves_after_correction(shell, qapp):
    shell.navigate("clients")
    page = shell.stack.currentWidget()
    observed: dict[str, object] = {}

    def fill_and_retry(dialog):
        dialog.name_edit.setText("Delta Dynamics")
        dialog.email_edit.setText("not-an-email")
        save = dialog.buttons.button(dialog.buttons.StandardButton.Save)
        save.click()
        observed.update(
            open=dialog.isVisible(),
            error=dialog.error_label.text(),
            name=dialog.name_edit.text(),
        )
        dialog.email_edit.setText("ops@delta.example")
        save.click()

    with ModalPilot(fill_and_retry) as pilot:
        assert page.add_client() is True
    assert observed == {"open": True, "error": "Enter a valid email address.", "name": "Delta Dynamics"}
    assert pilot.message_boxes == []
    with closing(get_connection()) as connection:
        stored = connection.execute("SELECT email FROM clients WHERE name = 'Delta Dynamics'").fetchall()
    assert stored == [("ops@delta.example",)]
    assert [client["name"] for client in page.visible_clients] == ["Delta Dynamics"]


# ---------------------------------------- DEF-006: numeric columns sort as text


class _ScaleLeadsController:
    """Deterministic lead source data with totals that sort differently as text."""

    leads: list[dict] = []

    @classmethod
    def get_leads_enriched(cls):
        return list(cls.leads)

    @staticmethod
    def get_spend_by_source():
        return {}

    @staticmethod
    def get_revenue_by_client():
        return {}

    @staticmethod
    def get_funnel_stats(leads):
        return {"total": len(leads), "meetings": 0, "converted": 0}

    @staticmethod
    def group_leads_by_source(_leads):
        return {
            "google_ads": {"total": 106},
            "meta_ads": {"total": 60},
            "linkedin_ads": {"total": 9},
        }

    @staticmethod
    def get_marketing_data(**_kwargs):
        return {"summary": {}, "metrics": []}

    @staticmethod
    def update_lead_info(*_args):
        return True, "saved"


class _ScaleClientsController:
    @staticmethod
    def get_all_clients_with_sales():
        return [
            {"client_id": f"C{index}", "name": name, "total_sales": sales, "total_amount": amount}
            for index, (name, sales, amount) in enumerate(
                (("Alpha", 9, 9000.0), ("Beta", 10, 10000.0), ("Gamma", 100, 950.0))
            )
        ]

    @classmethod
    def find_client(cls, client_id):
        for client in cls.get_all_clients_with_sales():
            if client["client_id"] == client_id:
                return (client_id, client["name"], "", "", "", "")
        return None


def test_def006_numeric_columns_sort_by_value(qapp):
    leads = LeadsPage(controller=_ScaleLeadsController, report_generator=lambda **_: (True, "", None))
    leads.source_table.sortItems(1, Qt.SortOrder.DescendingOrder)
    assert [leads.source_table.item(row, 1).text() for row in range(3)] == ["106", "60", "9"]

    clients = ClientsPage(controller=_ScaleClientsController, latest_leads_provider=dict)
    clients.clients_table.sortItems(5, Qt.SortOrder.DescendingOrder)
    assert [clients.clients_table.item(row, 5).text() for row in range(3)] == [
        "€10,000.00",
        "€9,000.00",
        "€950.00",
    ]
    clients.clients_table.sortItems(4, Qt.SortOrder.DescendingOrder)
    assert [clients.clients_table.item(row, 4).text() for row in range(3)] == ["100", "10", "9"]
    leads.deleteLater()
    clients.deleteLater()


def test_def006_tables_open_in_a_meaningful_order(qapp):
    clients = ClientsPage(controller=_ScaleClientsController, latest_leads_provider=dict)
    assert [clients.clients_table.item(row, 1).text() for row in range(3)] == ["Alpha", "Beta", "Gamma"]
    leads = LeadsPage(controller=_ScaleLeadsController, report_generator=lambda **_: (True, "", None))
    assert [leads.source_table.item(row, 1).text() for row in range(3)] == ["106", "60", "9"]
    clients.deleteLater()
    leads.deleteLater()


# ------------------------------- DEF-007: OS locale leaked into English copy


@pytest.fixture()
def non_english_time_locale():
    previous = locale.setlocale(locale.LC_TIME)
    for candidate in ("ur_PK.utf8", "ur_PK.UTF-8", "ar_SA.UTF-8", "fa_IR.UTF-8", "ru_RU.UTF-8", "de_DE.UTF-8", "fr_FR.UTF-8"):
        try:
            locale.setlocale(locale.LC_TIME, candidate)
        except locale.Error:
            continue
        if datetime(2026, 10, 20).strftime("%b") != "Oct":
            break
    else:
        locale.setlocale(locale.LC_TIME, previous)
        pytest.skip("No non-English LC_TIME locale is installed")
    yield
    locale.setlocale(locale.LC_TIME, previous)


def test_def007_dates_stay_english_under_a_non_english_locale(non_english_time_locale):
    moment = datetime(2026, 10, 20, 16, 48)
    assert format_datetime_us(moment) == "Oct 20, 2026 4:48 PM"
    assert format_day_month_year_time(moment) == "20 Oct 2026, 16:48"
    assert [row["label"] for row in group_time_series([("2026-10-05", 1.0)], "month")] == ["Oct 26"]


# ------------------------------------- DEF-017: one log line per inconsistent lead


def test_def017_lead_consistency_is_logged_once_per_load(caplog):
    leads = [{"id": f"L{index}", "status": "new", "client_id": "C1"} for index in range(50)]
    with caplog.at_level(logging.DEBUG, logger="analysis.leads_analysis"):
        _log_lead_consistency(leads)
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "50 with status='new' but client_id is set (e.g. L0, L1, L2)" in warnings[0].getMessage()
    assert sum(record.levelno == logging.DEBUG for record in caplog.records) == 50


# ------------------------- DEF-019: ASCII-only case folding for duplicate names


def test_def019_duplicate_client_names_are_caught_in_any_script(empty_db):
    from controllers.clients_controller import ClientsController
    from models.client_manager import get_clients

    assert ClientsController.create_client("Café Müller", "", "", "", "")[0] is True
    for variant in ("CAFÉ MÜLLER", "café müller", "  Café Müller  "):
        created, message = ClientsController.create_client(variant, "", "", "", "")
        assert created is False, variant
        assert "already exists" in message
    own_id = get_clients()[0][0]
    assert ClientsController.update_client_info(own_id, "CAFÉ MÜLLER", "", "", "", "")[0] is True


# ------------------------------- DEF-008: per-row widgets made tables O(n^2)


def _many_leads(count: int) -> list[dict]:
    return [
        {
            "id": f"L{index:05d}",
            "created_at": f"2026-01-{index % 28 + 1:02d}",
            "source": "google_ads",
            "status": "new",
            "meeting_date": None,
            "client_name": None,
        }
        for index in range(count)
    ]


def test_def008_lead_rows_are_painted_not_widgets_and_stay_linear(qapp, monkeypatch):
    calls = {"size_hint": 0}
    original = RowActionDelegate.sizeHint

    def counting_size_hint(self, option, index):
        calls["size_hint"] += 1
        return original(self, option, index)

    monkeypatch.setattr(RowActionDelegate, "sizeHint", counting_size_hint)
    monkeypatch.setattr(_ScaleLeadsController, "leads", _many_leads(2000))
    page = LeadsPage(controller=_ScaleLeadsController, report_generator=lambda **_: (True, "", None))
    page.resize(1200, 900)
    page.show()
    qapp.processEvents()
    page.refresh()
    qapp.processEvents()

    assert page.leads_table.rowCount() == 2000
    assert page.leads_table.findChildren(QToolButton) == []
    # Quadratic column re-measurement made millions of calls; linear work stays far below one per row.
    assert calls["size_hint"] < 2000

    table = page.leads_table
    table.scrollToTop()
    qapp.processEvents()
    cell = table.visualRect(table.model().index(0, 6))
    with ModalPilot(reject) as pilot:
        QTest.mouseClick(
            table.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(cell.left() + 12, cell.center().y()),
        )
        qapp.processEvents()
    assert [item.kind for item in pilot.seen] == ["LeadEditDialog"]
    page.close()
    page.deleteLater()


def test_def008_client_row_actions_reachable_by_keyboard(qapp):
    page = ClientsPage(controller=_ScaleClientsController, latest_leads_provider=dict)
    page.resize(1200, 800)
    page.show()
    table = page.clients_table
    table.setFocus()
    table.setCurrentCell(0, 1)
    qapp.processEvents()

    with ModalPilot(click_button("Cancel")) as pilot:
        QTest.keyClick(table, Qt.Key.Key_Delete)
        qapp.processEvents()
    assert [(item.kind, item.text) for item in pilot.seen] == [("QMessageBox", "Delete Alpha?")]

    menu_actions: list[str] = []

    def capture_menu():
        popup = QApplication.activePopupWidget()
        if popup is None:
            QTimer.singleShot(20, capture_menu)
            return
        menu_actions.extend(action.text() for action in popup.actions())
        popup.close()

    QTimer.singleShot(20, capture_menu)
    table.customContextMenuRequested.emit(table.visualRect(table.model().index(0, 1)).center())
    assert menu_actions == ["View", "Edit", "Delete"]
    page.close()
    page.deleteLater()


# ----------------------------------- DEF-009: Sales page overflowed narrow windows


def test_def009_sales_page_fits_the_minimum_window_after_shrinking(shell, qapp):
    shell.navigate("sales")
    shell.resize(1360, 860)
    qapp.processEvents()
    shell.resize(shell.minimumSize())
    qapp.processEvents()
    page = shell.stack.currentWidget()
    body = page.scroll_area.widget()
    assert body.minimumSizeHint().width() <= page.scroll_area.viewport().width()
    assert not page.scroll_area.horizontalScrollBar().isVisible()


# ------------------------------------------- DEF-010 / DEF-015: shell polish


def test_def010_product_name_is_not_clipped(shell, qapp):
    shell.resize(1360, 860)
    qapp.processEvents()
    name = next(label for label in shell.findChildren(QLabel) if label.objectName() == "productName")
    assert name.width() >= name.sizeHint().width()


def test_def015_theme_button_matches_the_persisted_theme(qapp, empty_db, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("appearance/dark", True)
    manager = ThemeManager(qapp, settings=settings)
    manager.apply()
    window = MainWindow(manager)
    try:
        assert window.theme_button.isChecked()
        assert window.theme_button.text() == "Light mode"
        manager.apply(False)
        assert window.theme_button.text() == "Dark mode"
        assert not window.theme_button.isChecked()
    finally:
        manager.apply(False)
        window.deleteLater()


def test_def011_lead_filters_have_visible_labels(qapp):
    page = LeadsPage(controller=_ScaleLeadsController, report_generator=lambda **_: (True, "", None))
    labels = {label.buddy(): label.text() for label in page.findChildren(QLabel) if label.buddy() is not None}
    assert labels[page.search_edit] == "Search"
    assert labels[page.source_combo] == "Source"
    assert labels[page.stage_combo] == "Stage"
    assert labels[page.quick_range_combo] == "Period"
    page.deleteLater()


def test_def016_navigation_icons_follow_the_theme(shell, qapp):
    before = {name: button.icon().cacheKey() for name, button in shell._nav_buttons.items()}
    assert all(not button.icon().isNull() for button in shell._nav_buttons.values())
    shell._toggle_theme()
    after = {name: button.icon().cacheKey() for name, button in shell._nav_buttons.items()}
    shell._toggle_theme()
    assert all(before[name] != after[name] for name in before)


# --------------------- DEF-020..022: features lost in the Flet -> Qt migration


def test_def020_marketing_spend_can_be_added_corrected_and_deleted(shell, qapp):
    shell.navigate("leads")
    qapp.processEvents()
    page = shell.stack.currentWidget()
    assert page._marketing_summary_values["avg_cpl"].text() == "—"  # undefined without spend
    observed: dict[str, object] = {}

    def edit_spend(dialog):
        dialog.source_combo.setEditText("Google Ads")
        dialog.amount_edit.setText("not money")
        dialog.save_button.click()
        observed["invalid"] = (dialog.isVisible(), dialog.error_label.text(), dialog.amount_edit.text())
        dialog.amount_edit.setText("1.250,50")  # European separators are accepted
        dialog.date_edit.setDate(QDate(2026, 2, 1))
        dialog.save_button.click()
        record_id = str(dialog._records[0]["id"])
        dialog._run_row_action("edit", record_id)
        dialog.amount_edit.setText("2000")
        dialog.save_button.click()
        with closing(get_connection()) as connection:
            observed["stored"] = connection.execute(
                "SELECT source, amount, date FROM marketing_spend"
            ).fetchall()
        dialog._run_row_action("delete", record_id)  # answered with Cancel
        observed["after_cancel"] = _count("marketing_spend")
        dialog.accept()

    with ModalPilot(edit_spend, click_button("Cancel")) as pilot:
        QTest.mouseClick(page.manage_spend_button, Qt.MouseButton.LeftButton)
        qapp.processEvents()

    assert observed["invalid"] == (True, "Enter an amount such as 1,250.00.", "not money")
    assert observed["stored"] == [("google_ads", 2000.0, "2026-02-01")]
    assert observed["after_cancel"] == 1
    assert [item.kind for item in pilot.seen] == ["MarketingSpendDialog", "QMessageBox"]
    assert page._marketing_summary_values["total_spend"].text() == "€2,000.00"

    def delete_spend(dialog):
        dialog._run_row_action("delete", str(dialog._records[0]["id"]))
        dialog.accept()

    with ModalPilot(delete_spend, click_button("Delete")):
        assert page.manage_spend() is True
    assert _count("marketing_spend") == 0


def _sales_snapshot_with(top_clients, product_labels):
    from tests.test_pyside_sales_page import _snapshot

    snapshot = _snapshot()
    distribution = dataclasses.replace(
        snapshot.period_a.product_distribution,
        labels=product_labels,
        values=[100.0 * (index + 1) for index in range(len(product_labels))],
        percentages=[0.0] * len(product_labels),
    )
    period = dataclasses.replace(
        snapshot.period_a, top_clients=top_clients, product_distribution=distribution
    )
    return dataclasses.replace(snapshot, period_a=period)


def _bar_positions(chart) -> int:
    return len({round(patch.get_y(), 6) for patch in chart.figure.axes[0].patches})


def test_def021_sales_page_shows_top_clients_without_merging_equal_names(qapp):
    from tests.test_pyside_sales_page import _FakeSalesController

    ranking = [
        ClientRank(rank=1, client_name="Acme Ltd", total_sales=900.0, transactions=3, percentage_of_total=45.0),
        ClientRank(rank=2, client_name="Acme Ltd", total_sales=700.0, transactions=2, percentage_of_total=35.0),
        ClientRank(rank=3, client_name="Beacon", total_sales=400.0, transactions=1, percentage_of_total=20.0),
    ]
    long_names = ["Enterprise analytics platform licence A", "Enterprise analytics platform licence B"]
    page = SalesPage(
        controller=_FakeSalesController(_sales_snapshot_with(ranking, long_names)),
        clients_provider=list,
        products_provider=list,
    )
    tabs = [page.chart_tabs.tabText(index) for index in range(page.chart_tabs.count())]
    assert "Top clients" in tabs
    # Equal category labels are stacked at one y-position by Matplotlib.
    assert _bar_positions(page.top_clients_chart) == 3  # two "Acme Ltd" bars kept apart
    assert _bar_positions(page.product_chart) == 2  # equal truncated labels kept apart
    assert "Acme Ltd €900.00" in page.top_clients_chart.accessibleDescription()
    page.close()
    page.deleteLater()


def test_def022_marketing_summary_reports_efficiency_for_the_active_snapshot(qapp):
    class Controller(_ScaleLeadsController):
        @staticmethod
        def get_marketing_data(**_kwargs):
            return {
                "summary": {
                    "total_spend": 500.0,
                    "total_revenue": 2000.0,
                    "avg_cpl": 25.0,
                    "avg_cac": 250.0,
                    "overall_roi": 3.0,
                },
                "metrics": [],
            }

    page = LeadsPage(controller=Controller, report_generator=lambda **_: (True, "", None))
    assert {key: label.text() for key, label in page._marketing_summary_values.items()} == {
        "total_spend": "€500.00",
        "total_revenue": "€2,000.00",
        "avg_cpl": "€25.00",
        "avg_cac": "€250.00",
        "overall_roi": "+300.0%",
    }
    page.deleteLater()


def test_def023_any_date_picker_opens_on_the_current_month(qapp):
    from tests.test_pyside_sales_page import _FakeSalesController, _snapshot

    page = SalesPage(controller=_FakeSalesController(_snapshot()), clients_provider=list, products_provider=list)
    page.resize(1200, 900)
    page.show()
    qapp.processEvents()
    editor = page.start_date_edit
    assert editor.text() == "Any date"
    QTest.mouseClick(
        editor,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(editor.width() - 10, editor.height() // 2),
    )
    qapp.processEvents()
    calendar = editor.calendarWidget()
    today = QDate.currentDate()
    try:
        assert calendar.isVisible()
        assert (calendar.yearShown(), calendar.monthShown()) == (today.year(), today.month())
        assert editor.text() == "Any date"  # opening the picker does not set a filter
    finally:
        calendar.window().close()
        page.close()
        page.deleteLater()


def _contrast(first, second) -> float:
    def channel(value: int) -> float:
        value_ratio = value / 255
        return value_ratio / 12.92 if value_ratio <= 0.03928 else ((value_ratio + 0.055) / 1.055) ** 2.4

    def luminance(color) -> float:
        return 0.2126 * channel(color.red()) + 0.7152 * channel(color.green()) + 0.0722 * channel(color.blue())

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("dark", [False, True])
def test_def024_keyboard_focus_is_visible_on_every_control_variant(shell, qapp, dark):
    from PySide6.QtGui import QColor

    shell.theme_manager.apply(dark)
    shell.navigate("leads")
    qapp.processEvents()
    search = shell.stack.currentWidget().search_edit
    shell.navigate("dashboard")
    qapp.processEvents()
    dashboard = shell.stack.currentWidget()
    targets = {
        "navigation": shell._nav_buttons["sales"],
        "checked navigation": shell._nav_buttons["dashboard"],
        "primary": _button(dashboard, "Import data"),
        "secondary": _button(dashboard, "Refresh"),
        "danger": _button(dashboard, "Clear sales"),
        "input": search,
    }

    def top_edge(widget, focused: bool):
        if focused:
            widget.setFocus(Qt.FocusReason.TabFocusReason)
        else:
            widget.clearFocus()
        qapp.processEvents()
        image = widget.grab().toImage()
        return QColor(image.pixel(widget.width() // 2, 0))

    try:
        for name, widget in targets.items():
            ratio = _contrast(top_edge(widget, False), top_edge(widget, True))
            assert ratio >= 3.0, f"{name}: focus ring contrast {ratio:.2f}:1"
    finally:
        shell.theme_manager.apply(False)


def test_def025_user_data_is_never_rendered_as_rich_text(qapp):
    markup = "<b>Bold</b> <i>Co</i>"
    dialog = ClientDetailDialog({"client_id": "C1", "name": markup, "address": markup}, {"sales": []})
    labels = [label for label in dialog.findChildren(QLabel) if label.text() == markup]
    assert len(labels) == 2  # title and address show the literal text
    assert all(label.textFormat() == Qt.TextFormat.PlainText for label in labels)
    dialog.deleteLater()

    page = LeadsPage(controller=_ScaleLeadsController, report_generator=lambda **_: (True, "", None))
    page.search_edit.setText(markup)
    page.apply_filters()
    assert markup in page.filter_summary.text()
    assert page.filter_summary.textFormat() == Qt.TextFormat.PlainText
    page.deleteLater()


def test_def026_dialogs_are_released_after_use(shell, qapp, tmp_path):
    """exec() hands parented dialogs to Python; a retained one is owned twice."""
    import gc

    from PySide6.QtWidgets import QDialog

    from core.importer import import_csv_to_db, import_leads_to_db

    sales = tmp_path / "sales.csv"
    sales.write_text("client_name,client_id,product_type,price,date\nAcme,C-1,Audit,100,2026-01-05\n", encoding="utf-8")
    leads = tmp_path / "leads.csv"
    leads.write_text("external_id,created_at,source,status\nE-1,2026-01-05,Google,new\n", encoding="utf-8")
    assert import_csv_to_db(str(sales))[0] and import_leads_to_db(str(leads))[0]
    shell.navigate("leads")
    shell.navigate("clients")
    qapp.processEvents()
    leads_page, clients_page = shell._pages["leads"], shell._pages["clients"]
    lead_id = leads_page.active_leads[0]["id"]
    flows = {
        "client profile": (lambda: clients_page.show_client_profile("C-1"), reject),
        "client edit": (lambda: clients_page.edit_client("C-1"), reject),
        "client add": (clients_page.add_client, reject),
        "client delete": (lambda: clients_page.delete_client("C-1"), click_button("Cancel")),
        "lead edit": (lambda: leads_page.edit_lead(lead_id), reject),
        "spend editor": (leads_page.manage_spend, reject),
        "error dialog": (lambda: shell.show_status("Simulated failure", "error"), reject),
    }
    for name, (flow, answer) in flows.items():
        with ModalPilot(answer):
            flow()
        gc.collect()
        qapp.processEvents()
        assert shell.findChildren(QDialog) == [], name
        assert _python_owned_children(shell) == [], name


# ------------------------------------------------ end-to-end business workflow


def test_end_to_end_import_edit_delete_and_restart(shell, qapp, tmp_path):
    sales_file = tmp_path / "sales.csv"
    sales_file.write_text(
        "client_name,client_id,product_type,price,date\n"
        "Acme Ltd,C-1,Consulting,1000,2026-09-01\n"
        "Acme Ltd,C-1,Support,500,2026-09-02\n"
        "Café Müller S.L.,C-2,Audit,250,2026-09-03\n",
        encoding="utf-8",
    )
    leads_file = tmp_path / "leads.csv"
    leads_file.write_text(
        "external_id,created_at,source,status,meeting_date,client_id\n"
        "EXT-1,2026-09-01,Google,new,,C-1\n",
        encoding="utf-8",
    )

    _import_through_gui(shell, sales_file, qapp)
    assert wait_until(lambda: _count("sales") == 3)
    _import_through_gui(shell, leads_file, qapp)
    assert wait_until(lambda: _count("leads") == 1)

    shell.navigate("dashboard")
    qapp.processEvents()
    assert shell.stack.currentWidget().sales_card.value_label.text() == "3"
    shell.navigate("sales")
    qapp.processEvents()
    assert shell.stack.currentWidget().transactions_card.value.text() == "3"

    # Edit the lead through its painted row button and the real dialog.
    shell.navigate("leads")
    qapp.processEvents()
    leads_page = shell.stack.currentWidget()

    def set_meeting(dialog):
        dialog.status_combo.setCurrentIndex(dialog.status_combo.findData("meeting"))
        dialog.has_meeting.setChecked(True)
        dialog.meeting_date.setDate(QDate(2030, 1, 15))
        dialog.accept()

    with ModalPilot(set_meeting):
        assert leads_page.edit_lead(leads_page.active_leads[0]["id"]) is True
    with closing(get_connection()) as connection:
        assert connection.execute("SELECT status, meeting_date FROM leads").fetchall() == [("meeting", "2030-01-15")]

    # Delete a client: Cancel keeps it, Delete cascades its sales and unlinks nothing else.
    shell.navigate("clients")
    qapp.processEvents()
    clients_page = shell.stack.currentWidget()
    with ModalPilot(click_button("Cancel")):
        assert clients_page.delete_client("C-2") is False
    assert _count("sales") == 3
    with ModalPilot(click_button("Delete")):
        assert clients_page.delete_client("C-2") is True
    assert _count("sales") == 2
    assert [client["client_id"] for client in clients_page.visible_clients] == ["C-1"]

    # The dashboard reflects the change, and a fresh window reads the persisted state.
    shell.navigate("dashboard")
    qapp.processEvents()
    assert shell.stack.currentWidget().sales_card.value_label.text() == "2"
    restarted = MainWindow(shell.theme_manager)
    try:
        restarted.navigate("leads")
        qapp.processEvents()
        stages = [restarted.stack.currentWidget().leads_table.item(0, 2).text()]
        assert stages == ["Meeting"]
    finally:
        restarted.deleteLater()
