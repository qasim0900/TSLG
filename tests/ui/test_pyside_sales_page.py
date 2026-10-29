from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from techset_leadgen.desktop.pages.sales_page import SalesPage
from techset_leadgen.domain.analysis_snapshot import (
    AnalysisMode,
    AnalysisSnapshot,
    EvolutionData,
    Filters,
    Metadata,
    PeriodMetrics,
    PeriodSnapshot,
    ProductDistribution,
    TableRow,
    TimeGrouping,
)


def _snapshot() -> AnalysisSnapshot:
    filters = Filters(
        date_start="2026-01-01",
        date_end="2026-01-02",
        client_name=None,
        product_type=None,
    )
    period = PeriodSnapshot(
        label="Main period",
        filters=filters,
        table_data=[
            TableRow(
                product_type="Automation",
                quantity=2,
                total_sales=2400.0,
                avg_price=1200.0,
                min_price=1000.0,
                max_price=1400.0,
            ),
            TableRow(
                product_type="Consulting",
                quantity=1,
                total_sales=900.0,
                avg_price=900.0,
                min_price=900.0,
                max_price=900.0,
            ),
        ],
        metrics=PeriodMetrics(
            total_sales=3300.0,
            transactions=3,
            avg_ticket=1100.0,
            total_quantity=3,
            unique_clients=1,
        ),
        evolution=EvolutionData(
            labels=["2026-01-01", "2026-01-02"],
            values=[1900.0, 1400.0],
            grouping=TimeGrouping.DAY,
        ),
        product_distribution=ProductDistribution(
            labels=["Automation", "Consulting"],
            values=[2400.0, 900.0],
            percentages=[72.73, 27.27],
        ),
        top_clients=[],
    )
    return AnalysisSnapshot(
        metadata=Metadata(
            mode=AnalysisMode.NORMAL,
            grouping=TimeGrouping.DAY,
            generated_at=datetime.now(),
            app_version="test",
        ),
        filters=filters,
        period_a=period,
    )


class _FakeSalesController:
    def __init__(self, snapshot: AnalysisSnapshot) -> None:
        self.snapshot = snapshot
        self.filters: dict[str, str | None] = {}
        self.invalidations = 0

    def set_start_date(self, value):
        self.filters["start_date"] = value

    def set_end_date(self, value):
        self.filters["end_date"] = value

    def set_client(self, value):
        self.filters["client_name"] = value

    def set_product(self, value):
        self.filters["product_type"] = value

    def validate_filters(self):
        return True, None

    def clear_filters(self):
        self.filters.clear()

    def invalidate_snapshot_cache(self):
        self.invalidations += 1

    def get_sales_snapshot(self, *, grouping="day", compare_controller=None):
        assert grouping in {"day", "week", "month", "quarter", "year"}
        return self.snapshot


@pytest.fixture(scope="module")
def qt_app():
    application = QApplication.instance() or QApplication([])
    yield application


def test_sales_page_renders_snapshot_and_filters(qt_app):
    controller = _FakeSalesController(_snapshot())
    page = SalesPage(
        controller=controller,
        clients_provider=lambda: ["Acme"],
        products_provider=lambda: ["Automation", "Consulting"],
        date_range_provider=lambda: ("2026-01-01", "2026-01-02"),
    )
    page.resize(1100, 800)
    page.show()
    qt_app.processEvents()

    assert page.current_snapshot is controller.snapshot
    assert page.sales_card.value.text() == "€3,300.00"
    assert page.transactions_card.value.text() == "3"
    assert page.table.rowCount() == 2
    assert {page.table.item(row, 0).text() for row in range(2)} == {
        "Automation",
        "Consulting",
    }
    assert page.trend_chart.accessibleName() == "Sales trend chart"
    assert [page.chart_tabs.tabText(index) for index in range(page.chart_tabs.count())] == [
        "Trend", "Products", "Top clients"]

    page._set_last_days(7)
    page.apply_filters()
    assert controller.filters["start_date"] is not None
    assert controller.filters["end_date"] is not None

    page.table.sortItems(2, Qt.SortOrder.AscendingOrder)
    assert page.table.item(0, 0).text() == "Consulting"
    page.close()


def test_sales_page_exports_the_visible_snapshot(qt_app, tmp_path):
    page = SalesPage(
        controller=_FakeSalesController(_snapshot()),
        clients_provider=list,
        products_provider=list,
    )
    output = tmp_path / "sales-report"

    success, _message, written_path = page.export_report(output)

    assert success is True
    assert written_path is not None
    html = (tmp_path / "sales-report.html").read_text(encoding="utf-8")
    assert "Techset LeadGen" in html
    assert "Automation" in html
    page.close()

