from contextlib import closing
from pathlib import Path

import pytest

from techset_leadgen.analytics.analysis.leads_analysis import get_funnel_stats, get_leads
from techset_leadgen.analytics.analysis.sales_analysis import get_sales_summary
from techset_leadgen.database.local_db import get_connection, init_db
from techset_leadgen.analytics.importer import import_csv_to_db, import_leads_to_db, inspect_import_file
from techset_leadgen.analytics.models.client_manager import invalidate_clients_cache


def _clear_database() -> None:
    init_db()
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
                connection.execute(f"DELETE FROM {table}")
    invalidate_clients_cache()


@pytest.fixture(autouse=True)
def empty_database():
    _clear_database()
    yield
    _clear_database()


def test_sales_and_leads_import_feed_real_analytics(tmp_path: Path) -> None:
    sales_file = tmp_path / "sales.csv"
    sales_file.write_text(
        "client_name,client_id,product_type,price,date\n"
        "Acme Ltd,C-001,Consulting,1250.50,2026-10-01\n"
        "Acme Ltd,C-001,Support,249.50,2026-10-02\n",
        encoding="utf-8",
    )

    inspection = inspect_import_file(str(sales_file))
    assert inspection["valid"] is True
    assert inspection["detected_type"] == "sales"
    assert inspection["row_count"] == 2

    ok, message = import_csv_to_db(str(sales_file))
    assert ok, message
    assert "2 records imported" in message

    summary, average_sale = get_sales_summary(
        start_date="2026-10-01",
        end_date="2026-10-31",
    )
    assert summary is not None
    assert summary["total"].sum() == pytest.approx(1500.0)
    assert average_sale == pytest.approx(750.0)

    leads_file = tmp_path / "leads.csv"
    leads_file.write_text(
        "created_at,source,status,external_id,meeting_date,client_id\n"
        "2026-10-03,Meta Lead Ads,meeting,LEAD-001,2026-10-10,C-001\n",
        encoding="utf-8",
    )

    ok, message = import_leads_to_db(str(leads_file))
    assert ok, message
    ok, duplicate_message = import_leads_to_db(str(leads_file))
    assert ok, duplicate_message
    assert "duplicate" in duplicate_message

    leads = get_leads()
    assert len(leads) == 1
    assert leads[0]["source"] == "meta_ads"
    assert leads[0]["client_id"] == "C-001"
    funnel = get_funnel_stats(leads)
    assert funnel["total"] == 1
    assert funnel["meetings"] == 1


def test_sales_dry_run_validates_without_persisting(tmp_path: Path) -> None:
    sales_file = tmp_path / "dry-run.csv"
    sales_file.write_text(
        "client_name,client_id,product_type,price,date\n"
        "Preview Co,C-DRY,Audit,500,2026-10-05\n",
        encoding="utf-8",
    )

    ok, message = import_csv_to_db(str(sales_file), dry_run=True)
    assert ok, message
    assert "DRY RUN" in message

    with closing(get_connection()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0

