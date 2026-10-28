"""Focused real-widget checks for the native LinkedIn prospect workflow."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from sqlalchemy import func, select

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTableWidget

from crm.db import utcnow
from crm.models import OutreachEvent, Prospect, ProspectAssignment
from crm.schemas import ProspectCreate, parse
from crm.services import prospects
from desktop_ui.pages import prospects_page as page_module
from desktop_ui.pages.prospects_page import HISTORY_LIMIT, ProspectImportDialog, ProspectsPage
from tests.qt_helpers import signed_in_context


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()


@pytest.fixture()
def context(tmp_path: Path, qapp):
    value = signed_in_context(tmp_path / "outreach.db")
    yield value
    value.shutdown()
    qapp.processEvents()


def _add(context, url: str, **values: str) -> str:
    data = parse(ProspectCreate, {"linkedin_url": url, **values})
    return context.write("prospect", lambda db, actor: prospects.create_prospect(db, actor, data).id)


def _count(context) -> int:
    return context.run(lambda db, _actor: db.scalar(select(func.count()).select_from(Prospect)) or 0,
                       commit=False)


def test_prospects_page_pages_searches_filters_and_stacks_narrow(qapp, context) -> None:
    def seed(db, actor):
        ids = []
        for number in range(13):
            record = prospects.create_prospect(db, actor, parse(ProspectCreate, {
                "linkedin_url": f"https://www.linkedin.com/in/person-{number:02d}",
                "full_name": "Needle Person" if number == 12 else f"Person {number:02d}",
                "company": "Northwind" if number % 2 else "Acme",
            }))
            ids.append(record.id)
        db.flush()
        db.get(Prospect, ids[12]).status = "replied"
        return ids

    ids = context.write("prospect", seed)
    page = ProspectsPage(context)
    page.resize(1100, 720)
    page.show()
    page.ensure_loaded()
    page.records.size_combo.setCurrentIndex(page.records.size_combo.findData(10))
    qapp.processEvents()

    assert page.records.table.rowCount() == 10
    assert page.records.last_page is not None and page.records.last_page.total == 13
    assert page.records.next_button.isEnabled()

    page.search.setText("Needle")
    page._search_timer.stop()
    page.records.reload(page=1)
    assert page.records.ids() == [ids[12]]

    page.search.clear()
    page.status_filter.setCurrentIndex(page.status_filter.findData("replied"))
    page.records.reload(page=1)
    assert page.records.ids() == [ids[12]]

    page.resize(820, 700)
    qapp.processEvents()
    assert page.splitter.orientation() == Qt.Orientation.Vertical
    assert page.search.accessibleName() == "Search prospects"
    assert page.records.table.accessibleName() == "Prospects list"
    page.close()
    page.deleteLater()


def test_detail_is_authoritative_bounded_role_aware_and_opens_canonical_link(
        qapp, context, monkeypatch) -> None:
    prospect_id = _add(
        context,
        "https://uk.linkedin.com/in/ayesha-malik/details/experience/?trk=profile",
        full_name="Ayesha Malik",
        company="Northwind",
        job_title="Founder",
        notes="Warm introduction from the events team.",
    )
    now = utcnow()

    def seed_history(db, actor):
        record = db.get(Prospect, prospect_id)
        record.status = "replied"
        record.last_activity_at = now
        record.next_follow_up_at = now + timedelta(days=2)
        db.add(ProspectAssignment(
            prospect_id=prospect_id,
            assignee_id=actor.user_id,
            assigned_by_id=actor.user_id,
            status="assigned",
            assigned_at=now - timedelta(days=1),
        ))
        for number in range(HISTORY_LIMIT + 7):
            db.add(OutreachEvent(
                prospect_id=prospect_id,
                event_type="note",
                note=f"History note {number}",
                occurred_at=now - timedelta(minutes=number),
                recorded_by_id=actor.user_id,
                request_id=f"history-request-{number:03d}",
            ))

    context.write("prospect", seed_history)
    page = ProspectsPage(context)
    page.show()
    page.ensure_loaded()
    page.show_record(prospect_id)
    qapp.processEvents()

    view = page.current_view()
    assert view is not None
    fields = dict(view.fields)
    assert fields["LinkedIn"] == "https://www.linkedin.com/in/ayesha-malik"
    assert fields["Status"] == "Replied"
    assert fields["Assigned to"] == "Test Admin"
    assert fields["Last activity"] != "No activity recorded"
    assert fields["Follow-up"] != "None scheduled"
    assert view.notice == f"Showing the latest {HISTORY_LIMIT} history entries."
    history = page.detail.tabs.widget(0)
    assert isinstance(history, QTableWidget)
    assert history.rowCount() == HISTORY_LIMIT

    opened: list[str] = []

    class _DesktopServices:
        @staticmethod
        def openUrl(url):  # noqa: N802 - Qt API compatibility
            opened.append(url.toString())
            return True

    monkeypatch.setattr(page_module, "QDesktopServices", _DesktopServices)
    page.open_link("linkedin")
    assert opened == ["https://www.linkedin.com/in/ayesha-malik"]

    assert not page.new_button.isHidden()
    assert not page.import_button.isHidden()
    assert not page.edit_button.isHidden()

    assert context.engine is not None
    with context.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE users SET role = 'read_only' WHERE id = ?", (context.actor.user_id,))
    assert context.verify()
    page.update_permissions()
    page.show_record(prospect_id)
    assert page.new_button.isHidden()
    assert page.import_button.isHidden()
    assert page.edit_button.isHidden()
    page.close()
    page.deleteLater()


def test_paste_preview_reports_every_outcome_and_writes_only_after_confirm(qapp, context) -> None:
    _add(context, "https://www.linkedin.com/in/already-here", full_name="Existing Person")
    dialog = ProspectImportDialog(None, context)
    dialog.input.setPlainText(
        "https://www.linkedin.com/in/new-person\tNew Person\tAcme\tFounder\n"
        "https://uk.linkedin.com/in/already-here/?trk=copy\n"
        "https://www.linkedin.com/in/new-person/details/contact-info\n"
        "https://www.linkedin.com/company/not-a-person"
    )

    dialog.preview()
    qapp.processEvents()

    assert _count(context) == 1, "Preview must never persist rows"
    assert dialog.summary.text() == "1 new · 1 existing · 1 repeated · 1 rejected"
    assert [dialog.table.item(row, 3).text() for row in range(dialog.table.rowCount())] == [
        "New", "Existing", "Repeated", "Rejected",
    ]
    assert "Same profile as row 1" in dialog.table.item(2, 4).text()
    assert "company page" in dialog.table.item(3, 4).text()
    assert dialog.import_button.isEnabled()
    assert dialog.import_button.text() == "Add 1 new prospect"

    dialog.persist()
    qapp.processEvents()

    assert dialog.result_value is not None
    assert len(dialog.result_value.created) == 1
    assert _count(context) == 2
    saved = context.run(
        lambda db, actor: prospects.list_prospects(db, actor, page=PageRequest(page_size=10), q="New Person"),
        commit=False,
    )
    assert len(saved.items) == 1
    dialog.deleteLater()

