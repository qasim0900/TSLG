"""The Meetings page and form, driven through the real PySide6 widgets (offscreen) on a fresh database.

Set ``TSLG_MEETINGS_SCREENSHOT_DIR`` to also save captures of the page and the form.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QDate, QLocale, QTime, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from sqlalchemy import func, select

from techset_leadgen.database.models import Client, Meeting, Organization, User
from techset_leadgen.desktop.pages.meetings_page import MeetingDialog, MeetingsPage
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.config import load_settings
from techset_leadgen.services import meetings
from techset_leadgen.services.schemas import MeetingCreate, parse
from tests.qt_helpers import TEST_ADMIN_EMAIL, TEST_PASSWORD, ModalPilot, click_button, signed_in_context, wait_until

SHOTS = os.environ.get("TSLG_MEETINGS_SCREENSHOT_DIR")


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedKingdom))  # as main.py does
    theme_manager = None
    if SHOTS:
        from techset_leadgen.desktop.theme import ThemeManager

        theme_manager = ThemeManager(application)
        theme_manager.apply()
    yield application
    application.processEvents()
    del theme_manager


def _setup(db) -> dict[str, str]:
    db.get(Organization, 1).timezone = "UTC"
    people = {}
    for key, name in (("ali", "Ali Ahmed"), ("sara", "Sara Khan")):
        user = User(email=f"{name.split()[0].lower()}@example.com", full_name=name, role="bdr", is_active=True)
        db.add(user)
        db.flush()
        people[key] = user.id
    for client_id, name, email in (("M_SMITH1", "Smith Holdings", "john@example.com"),
                                   ("M_NOVA01", "Nova Labs", "ceo@nova.example")):
        db.add(Client(id=client_id, name=name, cif="-", email=email, contact_person="John Smith"))
    db.flush()
    return people


@pytest.fixture()
def meeting_context(tmp_path: Path, qapp):
    context = signed_in_context(tmp_path / "meetings.sqlite")
    people = context.write("user", lambda db, _actor: _setup(db))
    yield context, people, tmp_path / "meetings.sqlite"
    context.shutdown()
    qapp.processEvents()


def _next_monday() -> date:
    day = date.today() + timedelta(days=3)
    while day.weekday() != 0:
        day += timedelta(days=1)
    return day


def _pilot(errors: list[BaseException], steps: Callable[[MeetingDialog], None]) -> Callable[[QWidget], None]:
    """Run ``steps`` on the open form; a failure is kept for the test and closes the form."""

    def action(widget: QWidget) -> None:
        assert isinstance(widget, MeetingDialog)
        try:
            steps(widget)
        except BaseException as exc:  # re-raised by the test after the dialog closes
            errors.append(exc)
            widget.reject()

    return action


def _pick_client(dialog: MeetingDialog, text: str, client_id: str) -> None:
    dialog.client_search.setText(text)
    assert wait_until(lambda: any(
        getattr(dialog.client_results.item(row).data(Qt.ItemDataRole.UserRole), "id", None) == client_id
        for row in range(dialog.client_results.count())), 5000), "the client was not found"
    for row in range(dialog.client_results.count()):
        item = dialog.client_results.item(row)
        if getattr(item.data(Qt.ItemDataRole.UserRole), "id", None) == client_id:
            QTest.mouseClick(dialog.client_results.viewport(), Qt.MouseButton.LeftButton,
                             pos=dialog.client_results.visualItemRect(item).center())
            return


def _choose(dialog: MeetingDialog, attendee_ids: list[str], *, only: bool = True) -> None:
    assert wait_until(lambda: all(any(dialog.attendee_list.item(row).data(Qt.ItemDataRole.UserRole) == user_id
                                      for row in range(dialog.attendee_list.count())) for user_id in attendee_ids),
                      5000), "the team members were not listed"
    if only:
        for user_id in list(dialog.chosen):
            if user_id not in attendee_ids:
                assert dialog.set_attendee(user_id, False)
    for user_id in attendee_ids:
        assert dialog.set_attendee(user_id, True)


def _set_time(dialog: MeetingDialog, day: date, hour: int, minute: int, duration: int) -> None:
    dialog.date.setDate(QDate(day.year, day.month, day.day))
    dialog.start.setTime(QTime(hour, minute))
    dialog.duration.setCurrentIndex(dialog.duration.findData(duration))


def _wait_text(widget: QWidget, prefix: str) -> None:
    assert wait_until(lambda: widget.text().startswith(prefix), 6000), f"expected {prefix!r}, saw {widget.text()!r}"


def _grab(widget: QWidget, name: str) -> None:
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        assert widget.grab().save(str(Path(SHOTS) / name))


def _count(context: AppContext, *conditions) -> int:
    return context.run(lambda db, _actor: db.scalar(select(func.count()).select_from(Meeting).where(*conditions)),
                       commit=False)


def test_create_detect_conflict_pick_suggestion_filter_cancel_and_persist(qapp, meeting_context):
    context, people, database = meeting_context
    monday = _next_monday()
    page = MeetingsPage(context)
    page.resize(1500, 950)
    page.show()
    page.ensure_loaded()
    assert page.records.table.rowCount() == 0
    assert page.summary_cards["upcoming"].value_label.text() == "0"
    errors: list[BaseException] = []

    def first(dialog: MeetingDialog) -> None:
        dialog.title.setText("Discovery call")
        _pick_client(dialog, "smith", "M_SMITH1")
        assert dialog.client_email.text() == "john@example.com"  # filled in from the client record
        _choose(dialog, [people["ali"]])
        _set_time(dialog, monday, 10, 0, 30)
        assert dialog.end.time() == QTime(10, 30)
        assert dialog.duration_text.text() == "Duration: 30 min"
        dialog.link.setText("https://meet.google.com/abc-defg-hij")
        _wait_text(dialog.availability, "Available")
        dialog.save_button.click()

    with ModalPilot(_pilot(errors, first)):
        page.create_record()
    if errors:
        raise errors[0]
    assert page.records.table.rowCount() == 1
    assert [page.records.table.item(0, column).text() for column in (0, 1, 2, 4, 5, 6)] == [
        "Discovery call", "Smith Holdings", "john@example.com", "10:00 AM", "10:30 AM", "30 min"]
    assert page.records.table.item(0, 7).text() == "Ali Ahmed"
    assert page.summary_cards["upcoming"].value_label.text() == "1"

    chosen: list[tuple[datetime, datetime]] = []

    def conflicting(dialog: MeetingDialog) -> None:
        dialog.title.setText("Contract review")
        _pick_client(dialog, "JOHN@EXAMPLE", "M_SMITH1")  # found by email
        _choose(dialog, [people["sara"]])
        _set_time(dialog, monday, 10, 15, 30)
        _wait_text(dialog.availability, "This time slot is unavailable")
        assert ("This client already has a meeting scheduled from 10:00 AM to 10:30 AM (Discovery call)."
                in dialog.conflict_list.text())
        assert dialog.suggestion_heading.text() == "Here are some available alternatives:"
        assert dialog.suggestion_buttons, "no alternatives offered"
        _grab(dialog, "create-meeting-conflict-and-suggestions.png")
        first_slot = dialog.last_availability.suggestions[0]
        chosen.append((first_slot.starts_at, first_slot.ends_at))
        dialog.suggestion_buttons[0].click()
        _wait_text(dialog.availability, "Available")
        dialog.save_button.click()

    with ModalPilot(_pilot(errors, conflicting)):
        page.create_record()
    if errors:
        raise errors[0]
    assert chosen[0][0] == datetime(monday.year, monday.month, monday.day, 12, 30, tzinfo=UTC)  # 10:30 + 120 min
    assert _count(context, Meeting.starts_at == chosen[0][0], Meeting.title == "Contract review") == 1
    assert page.records.table.rowCount() == 2
    _grab(page, "meetings-page.png")

    page.search.setText("contract")
    page.records.reload(page=1)
    assert page.records.table.rowCount() == 1
    page.clear_filters()
    page.client_filter.setText("nobody@nowhere")
    page.records.reload(page=1)
    assert page.records.table.rowCount() == 0 and page.records.empty_state.isVisible()
    page.clear_filters()
    assert page.records.table.rowCount() == 2  # "All meetings" after clearing

    contract_id = context.run(lambda db, _actor: db.scalar(select(Meeting.id).where(
        Meeting.title == "Contract review")), commit=False)
    page.show_record(contract_id)
    _grab(page, "meeting-details.png")
    with ModalPilot(click_button("Cancel meeting")):
        page.run_row_action("cancel", contract_id)
    assert _count(context, Meeting.status == "cancelled") == 1
    assert page.summary_cards["cancelled"].value_label.text() == "1"
    page.summary_cards["cancelled"].clicked.emit()
    assert page.records.table.rowCount() == 1 and page.view_filter.currentData() == "cancelled"
    page.close()

    reopened = AppContext(load_settings({}, database_path=database))  # restart: the data is still there
    reopened.open()
    reopened.sign_in(TEST_ADMIN_EMAIL, TEST_PASSWORD)
    again = MeetingsPage(reopened)
    again.show()
    again.ensure_loaded()
    again.clear_filters()
    assert again.records.table.rowCount() == 2
    again.close()
    reopened.shutdown()


def test_the_save_rechecks_and_explains_a_slot_taken_after_the_preview(qapp, meeting_context):
    context, people, _database = meeting_context
    monday = _next_monday()
    page = MeetingsPage(context)
    page.show()
    page.ensure_loaded()
    errors: list[BaseException] = []
    start = datetime(monday.year, monday.month, monday.day, 15, tzinfo=UTC)

    def race(dialog: MeetingDialog) -> None:
        dialog.title.setText("Late call")
        _pick_client(dialog, "nova", "M_NOVA01")
        _choose(dialog, [people["sara"]])
        _set_time(dialog, monday, 15, 0, 30)
        _wait_text(dialog.availability, "Available")
        # Someone else books Sara for 15:00 while this form is open.
        context.write("meeting", lambda db, actor: meetings.create_meeting(db, actor, parse(MeetingCreate, {
            "title": "Booked elsewhere", "client_id": "M_SMITH1", "attendee_ids": [people["sara"]],
            "starts_at": start, "ends_at": start + timedelta(minutes=30), "request_id": uuid4().hex})))
        dialog.save_button.click()
        assert dialog.isVisible(), "the form closed although the save was refused"
        assert dialog.error.text().startswith("This time slot is unavailable.")
        assert "Sara Khan already has a meeting from 3:00 PM to 3:30 PM" in dialog.error.text()
        assert "Available alternatives" in dialog.error.text()
        dialog.reject()

    with ModalPilot(_pilot(errors, race)):
        page.create_record()
    if errors:
        raise errors[0]
    assert _count(context, Meeting.title == "Late call") == 0
    page.close()


def test_form_validation_reschedule_and_new_client(qapp, meeting_context):
    context, people, _database = meeting_context
    monday = _next_monday()
    page = MeetingsPage(context)
    page.show()
    page.ensure_loaded()
    errors: list[BaseException] = []

    def invalid_then_new_client(dialog: MeetingDialog) -> None:
        dialog.save_button.click()
        assert dialog.error.text() == "Enter a meeting title." and dialog.title.property("invalid")
        dialog.title.setText("Kick-off")
        dialog.save_button.click()
        assert dialog.error.text().startswith("Search for the client")
        dialog.client_search.setText("Orbit Partners")
        assert wait_until(lambda: dialog.new_client_button.isVisible(), 5000)
        dialog.new_client_button.click()
        assert dialog.client_choice.text().startswith("New client: Orbit Partners")
        dialog.save_button.click()
        assert dialog.error.text() == "Enter the client's email address."
        dialog.client_email.setText("not an email")
        _choose(dialog, [people["ali"]])
        _set_time(dialog, monday, 11, 0, 45)
        dialog.link.setText("ftp://files.example.com")
        dialog.save_button.click()
        assert dialog.error.text().startswith("Please correct the highlighted fields.")
        assert dialog.client_email.property("invalid") and dialog.link.property("invalid")
        dialog.client_email.setText("hello@orbit.example")
        dialog.link.setText("https://teams.microsoft.com/l/meetup-join/x")
        dialog.save_button.click()

    with ModalPilot(_pilot(errors, invalid_then_new_client)):
        page.create_record()
    if errors:
        raise errors[0]
    assert context.run(lambda db, _actor: db.scalar(select(Client.email).where(Client.name == "Orbit Partners")),
                       commit=False) == "hello@orbit.example"
    kickoff = context.run(lambda db, _actor: db.scalar(select(Meeting.id).where(Meeting.title == "Kick-off")),
                          commit=False)

    def reschedule(dialog: MeetingDialog) -> None:
        assert not dialog.title.isEnabled() and not dialog.attendee_list.isEnabled()
        _set_time(dialog, monday, 16, 0, 45)
        _wait_text(dialog.availability, "Available")  # it does not conflict with itself
        dialog.save_button.click()

    page.show_record(kickoff)
    with ModalPilot(_pilot(errors, reschedule)):
        page.reschedule_current()
    if errors:
        raise errors[0]
    expected = datetime(monday.year, monday.month, monday.day, 16, tzinfo=UTC)
    assert _count(context, Meeting.id == kickoff, Meeting.starts_at == expected) == 1
    history = page.detail.view.tabs[0].rows
    assert [row[1] for row in history] == ["Rescheduled", "Created"]
    page.close()


def test_an_administrator_changes_the_scheduling_rules_in_settings(qapp, meeting_context):
    from techset_leadgen.desktop.forms import FormDialog
    from techset_leadgen.desktop.pages.settings_page import SettingsPage

    context, _people, _database = meeting_context
    page = SettingsPage(context)
    page.show()
    page.ensure_loaded()
    assert not page.organization_buttons["Meeting scheduling…"].isHidden()  # on the Organization tab
    errors: list[BaseException] = []

    def edit(widget: QWidget) -> None:
        try:
            assert isinstance(widget, FormDialog)
            assert widget.value("buffer_mode") == "post" and widget.value("buffer_minutes") == "120"
            widget.set_value("buffer_mode", "around")
            widget.set_value("buffer_minutes", "60")
            widget.set_value("day_start", "480")
            widget.set_value("work_days", ["1", "2", "3"])
            click_button("Save rules")(widget)
        except BaseException as exc:
            errors.append(exc)
            widget.reject()

    with ModalPilot(edit):
        page.edit_meeting_rules()
    if errors:
        raise errors[0]
    rules = context.run(lambda db, _actor: meetings.scheduling_rules(db), commit=False)
    assert (rules.buffer_mode, rules.buffer_minutes, rules.day_start, rules.work_days) == ("around", 60, 480, "123")
    shown = page.organization_list.value_labels
    assert shown["Meeting buffer"].text().startswith("60-minute buffer before and after each meeting")
    assert shown["Meeting hours"].text().startswith("8:00 AM–6:00 PM, Monday, Tuesday, Wednesday")
    page.close()
