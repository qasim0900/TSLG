from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from techset_leadgen.config import load_settings
from techset_leadgen.database.models import Notification, OutreachEvent, ProspectAssignment, Task, User
from techset_leadgen.desktop.pages import team_pages
from techset_leadgen.desktop.pages.assignment_pages import AssignmentsPage, BatchDialog
from techset_leadgen.desktop.pages.outreach_pages import FollowUpsPage, MyWorkPage
from techset_leadgen.desktop.pages.team_pages import NotificationsPage, TeamPage
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.security.passwords import hash_password
from techset_leadgen.services import prospects

from tests.qt_helpers import TEST_PASSWORD, ModalPilot, signed_in_context


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()


@pytest.fixture()
def office(tmp_path: Path, qapp):
    database = tmp_path / "outreach.db"
    admin = signed_in_context(database)
    password_hash = hash_password(TEST_PASSWORD)

    def seed(db, actor):
        for name in ("Ali Raza", "Sara Khan"):
            db.add(User(email=f"{name.split()[0].lower()}@techset.example", full_name=name, role="bdr",
                        password_hash=password_hash, is_active=True))
        rows = prospects.rows_from_text("linkedin.com/in/first-person\nlinkedin.com/in/second-person\n"
                                        "linkedin.com/in/third-person")
        prospects.import_rows(db, actor, rows, source="Pasted")

    admin.write("prospect", seed)
    yield admin, database
    admin.shutdown()
    qapp.processEvents()


def _member(database: Path, email: str) -> AppContext:
    context = AppContext(load_settings({}, database_path=database))
    context.open()
    context.sign_in(email, TEST_PASSWORD)
    return context


def _count(context: AppContext, model, *conditions) -> int:
    return context.run(lambda db, _actor: db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0,
                       commit=False)


def _check(table, row: int) -> None:
    table.item(row, 0).setCheckState(Qt.CheckState.Checked)


def test_a_manager_assigns_a_balanced_batch_and_a_member_works_it(qapp, office, monkeypatch, tmp_path):
    admin, database = office

    page = AssignmentsPage(admin)
    page.show()
    page.ensure_loaded()

    def plan(dialog: BatchDialog) -> None:
        assert dialog.prospect_table.rowCount() == 3
        members = {dialog.member_table.item(row, 0).text(): row for row in range(dialog.member_table.rowCount())}
        for row in range(3):
            _check(dialog.prospect_table, row)
        _check(dialog.member_table, members["Ali Raza"])
        _check(dialog.member_table, members["Sara Khan"])
        new = sorted(int(dialog.member_table.item(members[name], 2).text()) for name in ("Ali Raza", "Sara Khan"))
        assert new == [1, 2]
        assert dialog.save_button.text() == "Assign 3"
        dialog.save()

    with ModalPilot(plan):
        page.create_record()
    assert _count(admin, ProspectAssignment, ProspectAssignment.status == "assigned") == 3
    assert page.records.table.rowCount() == 3
    assert page.batch_filter.currentData() is not None

    ali = _member(database, "ali@techset.example")
    my_work = MyWorkPage(ali)
    my_work.show()
    my_work.ensure_loaded()
    mine = my_work.records.ids()
    assert len(mine) == _count(ali, ProspectAssignment, ProspectAssignment.assignee_id == ali.actor.user_id)
    my_work.show_record(mine[0])
    assert my_work.record_button.isEnabled() and my_work.complete_button.isEnabled()
    due = datetime.now(UTC) + timedelta(days=2)

    def outcome(dialog) -> None:
        dialog.set_value("event_type", "follow_up_requested")
        dialog.set_value("note", "Asked to talk again on Thursday")
        dialog.set_value("follow_up_at", due)
        dialog.save_button.click()

    with ModalPilot(outcome):
        my_work.record()
    assert _count(ali, OutreachEvent, OutreachEvent.event_type == "follow_up_requested") == 1
    assert _count(ali, Task, Task.kind == "follow_up", Task.status == "open") == 1
    assert _count(ali, Notification, Notification.recipient_id == ali.actor.user_id) >= 1

    follow_ups = FollowUpsPage(ali)
    follow_ups.show()
    follow_ups.ensure_loaded()
    assert follow_ups.records.table.rowCount() == 1
    follow_ups.show_record(follow_ups.records.ids()[0])
    with ModalPilot(lambda dialog: (dialog.set_value("outcome", "Booked a call"), dialog.save_button.click())):
        follow_ups.mark_done()
    assert _count(ali, Task, Task.kind == "follow_up", Task.status == "done") == 1

    notifications = NotificationsPage(ali)
    notifications.show()
    notifications.ensure_loaded()
    assert notifications.records.table.rowCount() >= 1
    notifications.mark_all_read()
    assert _count(ali, Notification, Notification.recipient_id == ali.actor.user_id,
                  Notification.read_at.is_(None)) == 0

    team = TeamPage(admin)
    team.show()
    team.ensure_loaded()
    names = [team.table.item(row, 0).text() for row in range(team.table.rowCount())]
    assert "Ali Raza" in names and names[-1] == "Team total"
    target = tmp_path / "summary.csv"
    monkeypatch.setattr(team_pages.QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    team.export()
    exported = target.read_text(encoding="utf-8-sig")
    assert exported.splitlines()[0].startswith("Date,Time zone,Team member")
    assert "Ali Raza" in exported
    ali.shutdown()


def test_a_member_cannot_open_the_manager_screens_actions(qapp, office):
    admin, database = office
    sara = _member(database, "sara@techset.example")
    page = AssignmentsPage(sara)
    page.show()
    with ModalPilot() as pilot:
        page.ensure_loaded()
    assert pilot.message_boxes and all("permission" in item.text.lower() or "role" in item.text.lower()
                                       for item in pilot.message_boxes)
    assert not page.new_button.isVisible()
    assert page.records.table.rowCount() == 0
    sara.shutdown()


def test_a_prospect_file_is_read_in_the_background_then_previewed(qapp, office, tmp_path):
    from techset_leadgen.desktop.pages.prospects_page import ProspectImportDialog
    from tests.qt_helpers import wait_until

    admin, _database = office
    good = tmp_path / "profiles.csv"
    good.write_text("LinkedIn URL,Name,Company\nhttps://www.linkedin.com/in/file-person/,File Person,Acme\n"
                    "not a profile,Bad Row,\nhttps://www.linkedin.com/in/first-person,Again,Acme\n", encoding="utf-8")
    dialog = ProspectImportDialog(None, admin)
    dialog.load_file(str(good))
    assert dialog.is_reading and not dialog.import_button.isEnabled()
    assert wait_until(lambda: not dialog.is_reading and dialog.table.rowCount() == 3, 5000)
    results = sorted(dialog.table.item(row, 3).text() for row in range(3))
    assert results == ["Existing", "New", "Rejected"]
    assert dialog.import_button.isEnabled()

    bad = tmp_path / "no-url-column.csv"
    bad.write_text("Name,Company\nSomeone,Acme\n", encoding="utf-8")
    with ModalPilot() as pilot:
        dialog.load_file(str(bad))
        assert wait_until(lambda: not dialog.is_reading, 5000)
    assert [item.text for item in pilot.message_boxes] == ["This file cannot be imported."]
    dialog.reject()

