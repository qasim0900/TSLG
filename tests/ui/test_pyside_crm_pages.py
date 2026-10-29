from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication

from techset_leadgen.desktop.pages.clients_page import ClientsPage
from techset_leadgen.desktop.pages.leads_page import LeadsPage
from tests.qt_helpers import wait_until


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()


class _LeadsController:
    leads = [
        {
            "id": "L1",
            "created_at": "2026-10-01",
            "source": "meta_ads",
            "status": "new",
            "meeting_date": None,
            "client_id": None,
            "client_name": "—",
        },
        {
            "id": "L2",
            "created_at": "2026-10-02",
            "source": "google_ads",
            "status": "converted",
            "meeting_date": "2026-10-04",
            "client_id": "C1",
            "client_name": "Acme",
        },
    ]

    @classmethod
    def get_leads_enriched(cls):
        return list(cls.leads)

    @staticmethod
    def get_spend_by_source():
        return {"meta_ads": 20, "google_ads": 50}

    @staticmethod
    def get_revenue_by_client():
        return {"C1": 250}

    @staticmethod
    def get_funnel_stats(leads):
        total = len(leads)
        meetings = sum(lead["status"] in ("meeting", "converted") for lead in leads)
        converted = sum(lead["status"] == "converted" for lead in leads)
        return {
            "total": total,
            "meetings": meetings,
            "converted": converted,
            "lost": 0,
            "lead_to_meeting_pct": meetings / total * 100 if total else 0,
            "meeting_to_client_pct": converted / meetings * 100 if meetings else 0,
            "lead_dropoff": total - meetings,
            "avg_time_to_meeting": 2,
        }

    @staticmethod
    def group_leads_by_source(leads):
        result = {}
        for lead in leads:
            source = lead["source"]
            result[source] = {
                "total": 1,
                "meetings": int(lead["status"] == "converted"),
                "clients": int(lead["status"] == "converted"),
                "meeting_to_client_pct": 100 if lead["status"] == "converted" else 0,
                "avg_time_to_meeting": 2 if lead["meeting_date"] else 0,
            }
        return result

    @staticmethod
    def get_marketing_data(**_kwargs):
        return {"summary": {}, "metrics": []}


def test_leads_page_filters_and_exports_current_snapshot(qapp, tmp_path: Path):
    captured = {}

    def report_generator(**kwargs):
        captured.update(kwargs)
        Path(kwargs["filename"]).write_text("report", encoding="utf-8")
        return True, "Report generated", kwargs["filename"]

    page = LeadsPage(controller=_LeadsController, report_generator=report_generator)
    assert len(page.active_leads) == 2
    assert page.leads_table.rowCount() == 2

    page.search_edit.setText("Acme")
    assert wait_until(lambda: len(page.active_leads) == 1)
    assert [lead["id"] for lead in page.active_leads] == ["L2"]

    target = tmp_path / "leads.html"
    assert page.export_report(target) == str(target)
    assert [lead["id"] for lead in captured["leads"]] == ["L2"]
    page.deleteLater()


class _ClientsController:
    @staticmethod
    def get_all_clients_with_sales():
        return [
            {
                "client_id": "C1",
                "name": "Acme",
                "cif": "A1234567",
                "address": "Main Street",
                "contact_person": "Alex",
                "email": "alex@example.com",
                "total_sales": 2,
                "total_amount": 250,
            },
            {
                "client_id": "C2",
                "name": "Beacon",
                "cif": "B1234567",
                "address": "High Street",
                "contact_person": "Bea",
                "email": "bea@example.com",
                "total_sales": 0,
                "total_amount": 0,
            },
        ]

    @staticmethod
    def find_client(client_id):
        for client in _ClientsController.get_all_clients_with_sales():
            if client["client_id"] == client_id:
                return (
                    client["client_id"], client["name"], client["cif"],
                    client["address"], client["contact_person"], client["email"],
                )
        return None

    @staticmethod
    def get_client_sales_stats(_client_id):
        return {
            "total_sales": 2,
            "total_amount": 250,
            "avg_amount": 125,
            "sales": [{"date": "2026-10-01", "product_type": "Service", "price": 250}],
        }


def test_clients_page_search_masks_and_exports(qapp, tmp_path: Path):
    captured = {}

    def report_generator(**kwargs):
        captured.update(kwargs)
        Path(kwargs["filename"]).write_text("client report", encoding="utf-8")
        return True, "Report generated", kwargs["filename"]

    page = ClientsPage(
        controller=_ClientsController,
        latest_leads_provider=lambda: {},
        report_generator=report_generator,
    )
    assert len(page.visible_clients) == 2
    assert "•" in page.clients_table.item(0, 2).text()

    page.search_edit.setText("beac")
    qapp.processEvents()
    assert [client["client_id"] for client in page.visible_clients] == ["C2"]

    target = tmp_path / "client.html"
    assert page.export_client_report("C1", target) == str(target)
    assert captured["client_info"]["name"] == "Acme"
    page.deleteLater()

