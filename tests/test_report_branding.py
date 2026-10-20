"""Generated-report brand regression tests."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from domain.analysis_snapshot import (
    AnalysisMode,
    AnalysisSnapshot,
    EvolutionData,
    Filters,
    Metadata,
    PeriodMetrics,
    PeriodSnapshot,
    ProductDistribution,
    TimeGrouping,
)
from reports.report_client_html import generate_client_html_report
from reports.report_html import generate_html_report_from_snapshot
from reports.report_leads_html import generate_leads_html_report


def _normal_snapshot() -> AnalysisSnapshot:
    filters = Filters(date_start="2026-01-01", date_end="2026-01-31")
    period = PeriodSnapshot(
        label="January 2026",
        filters=filters,
        table_data=[],
        metrics=PeriodMetrics(
            total_sales=0.0,
            transactions=0,
            avg_ticket=0.0,
            total_quantity=0,
            unique_clients=0,
        ),
        evolution=EvolutionData(
            labels=[],
            values=[],
            grouping=TimeGrouping.DAY,
        ),
        product_distribution=ProductDistribution(
            labels=[],
            values=[],
            percentages=[],
        ),
        top_clients=[],
    )
    return AnalysisSnapshot(
        metadata=Metadata(
            mode=AnalysisMode.NORMAL,
            grouping=TimeGrouping.DAY,
            generated_at=datetime.now(timezone.utc),
        ),
        filters=filters,
        period_a=period,
    )


def _generate_sales_report(path: Path):
    return generate_html_report_from_snapshot(_normal_snapshot(), str(path))


def _generate_client_report(path: Path):
    return generate_client_html_report(
        {
            "name": "Example Client",
            "cif": "A-123",
            "email": "client@example.test",
            "address": "Example Street",
            "contact_person": "Example Contact",
        },
        {"total_sales": 0, "total_amount": 0, "avg_amount": 0, "sales": []},
        str(path),
    )


def _generate_leads_report(path: Path):
    return generate_leads_html_report(
        leads=[],
        funnel_stats={
            "total": 0,
            "meetings": 0,
            "converted": 0,
            "lead_to_meeting_pct": 0,
            "meeting_to_client_pct": 0,
            "avg_time_to_meeting": 0,
        },
        sources_data={},
        filename=str(path),
    )


@pytest.mark.parametrize(
    ("filename", "generator", "report_title"),
    [
        ("sales.html", _generate_sales_report, "Sales Report"),
        ("client.html", _generate_client_report, "Client Profile"),
        ("leads.html", _generate_leads_report, "Leads Report"),
    ],
)
def test_generated_reports_use_techset_branding(
    tmp_path: Path,
    filename: str,
    generator,
    report_title: str,
) -> None:
    output = tmp_path / filename

    success, message, generated_path = generator(output)

    assert success, message
    assert generated_path == str(output)
    html = output.read_text(encoding="utf-8")
    assert "Techset LeadGen" in html
    assert report_title in html
    assert "#39B54A" in html
    assert "Sales CRM" not in html
    assert "Portfolio" not in html
