"""Meetings: summary cards, a searchable and filterable list, details with history, and the scheduling form.

The form finds existing clients and team members, previews the availability of the client and every
attendee while the time is chosen, explains each conflict, and offers free slots to pick from. The
preview is informational: saving checks the shared schedule again inside the transaction
(``services.meetings``), so a slot taken a moment ago by someone else is refused with the reason.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from PySide6.QtCore import QDate, QObject, QRunnable, Qt, QThreadPool, QTime, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from techset_leadgen.database.models import Meeting
from techset_leadgen.domain.scheduling import SchedulingRules, clock, day_text, duration_text, span_text
from techset_leadgen.domain.vocabulary import MEETING_STATUSES
from techset_leadgen.errors import Conflict, DomainError
from techset_leadgen.security.permissions import Scope
from techset_leadgen.services import meetings
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import PageRequest
from techset_leadgen.services.schemas import (
    AvailabilityQuery,
    MeetingCreate,
    MeetingReschedule,
    MeetingUpdate,
    parse,
)

from techset_leadgen.desktop.dialogs import ask_confirmation
from techset_leadgen.desktop.modal import ModalDialog
from techset_leadgen.desktop.records import ID_ROLE, Column, DetailTab, DetailView, RecordPage, Row, RowPage
from techset_leadgen.desktop.row_actions import RowAction, RowActionDelegate, install_row_action_menu
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.desktop.support import attempt, explain, label, local_time, report
from techset_leadgen.desktop.tables import enable_column_choice, tone_for
from techset_leadgen.desktop.widgets import Alert, KpiCard, SectionCard, labeled_field, repolish

DURATIONS = (15, 30, 45, 60, 90, 120)
_AUDIT_ACTIONS = {
    "meeting.created": "Created", "meeting.updated": "Updated", "meeting.rescheduled": "Rescheduled",
    "meeting.cancelled": "Cancelled", "meeting.completed": "Marked completed",
}


class _WorkerSignals(QObject):
    completed = Signal(int, object, object)


class _Worker(QRunnable):
    """Run a short authenticated read without blocking the window (searches, availability)."""

    def __init__(self, number: int, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.number = number
        self.operation = operation
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as exc:  # handed to the window, which shows it
            self.signals.completed.emit(self.number, None, exc)
        else:
            self.signals.completed.emit(self.number, result, None)


def _wall_time(day: QDate, moment: QTime, timezone: str) -> datetime:
    """A date and clock time in the business time zone, as UTC; refuses times skipped by DST."""
    zone = ZoneInfo(timezone)
    local = datetime(day.year(), day.month(), day.day(), moment.hour(), moment.minute(), tzinfo=zone)
    instant = local.astimezone(UTC)
    if instant.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
        raise ValueError("This local time does not exist because the clocks change that night. Choose another time.")
    return instant


def _day(value: QDate) -> date:
    return date(value.year(), value.month(), value.day())


def _list_height(widget: QListWidget, rows: int) -> None:
    widget.setMinimumHeight(34 * rows + 10)
    widget.setMaximumHeight(34 * rows + 10)


class MeetingDialog(ModalDialog):
    """Create, edit, or reschedule a meeting, with a live availability preview and suggested slots."""

    MODES = {
        "create": ("Create meeting", "Save meeting"),
        "edit": ("Edit meeting", "Save changes"),
        "reschedule": ("Reschedule meeting", "Reschedule"),
    }

    def __init__(self, parent: QWidget, context: AppContext, *, values: dict[str, Any] | None = None,
                 mode: str = "create") -> None:
        super().__init__(parent)
        self.context = context
        self.mode = mode
        self.values = values or {}
        self.meeting_id: str | None = self.values.get("id")
        self.request_id = uuid.uuid4().hex  # one ID for every attempt: a retried save is stored once
        self.result_value: str | None = None
        self.rules = SchedulingRules()
        self.client_id: str | None = self.values.get("client_id")
        self.client_name = str(self.values.get("client_name") or "")
        self.new_client = bool(self.client_name and not self.client_id)
        self.chosen: dict[str, tuple[str, str]] = {}  # attendee id -> (name, email), kept across searches
        self.last_availability: meetings.Availability | None = None
        self._numbers = {"clients": 0, "attendees": 0, "check": 0, "schedule": 0}
        self._sequence = 0
        self._pending: dict[int, tuple[str, int, Callable[[Any, BaseException | None], None]]] = {}
        self._senders: dict[int, _WorkerSignals] = {}
        self._quiet = False  # set while the form fills itself in, so no change handlers run
        heading, save_text = self.MODES[mode]
        self.setWindowTitle(heading)
        self.setAccessibleName(heading)
        self.setModal(True)
        self.resize(1080, 760)
        self._build(heading, save_text)
        self._load_rules()
        self._timers()
        self._populate()
        if mode == "reschedule":
            for widget in (self.title, self.client_search, self.client_results, self.new_client_button,
                           self.client_email, self.attendee_filter, self.attendee_list, self.link, self.description):
                widget.setEnabled(False)
        self.search_attendees()
        if mode != "reschedule":
            self.search_clients()
        self._schedule_check()

    # ------------------------------------------------------------ layout

    def _build(self, heading: str, save_text: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("meetingFormBody")
        body.setStyleSheet("QWidget#meetingFormBody { background: transparent; }")
        scroll.setWidget(body)
        scroll.viewport().setAutoFillBackground(False)
        root.addWidget(scroll, 1)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        title = QLabel(heading)
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        self.zone_note = QLabel()
        self.zone_note.setObjectName("dialogSubtitle")
        self.zone_note.setWordWrap(True)
        layout.addWidget(self.zone_note)

        columns = QHBoxLayout()
        columns.setSpacing(20)
        layout.addLayout(columns, 1)
        form = QVBoxLayout()
        form.setSpacing(12)
        columns.addLayout(form, 3)
        side = QVBoxLayout()
        side.setSpacing(12)
        columns.addLayout(side, 2)

        self.title = QLineEdit()
        self.title.setObjectName("meetingTitle")
        self.title.setAccessibleName("Meeting title")
        self.title.setMaxLength(200)
        self.title.setPlaceholderText("For example: Product demo")
        form.addWidget(labeled_field("Meeting title *", self.title))

        self.client_search = QLineEdit()
        self.client_search.setObjectName("meetingClientSearch")
        self.client_search.setAccessibleName("Search clients by name or email")
        self.client_search.setPlaceholderText("Search clients by name or email")
        self.client_search.setClearButtonEnabled(True)
        form.addWidget(labeled_field("Client *", self.client_search))
        self.client_results = QListWidget()
        self.client_results.setObjectName("meetingClientResults")
        self.client_results.setAccessibleName("Matching clients")
        _list_height(self.client_results, 3)
        form.addWidget(self.client_results)
        client_row = QHBoxLayout()
        self.client_choice = QLabel("No client selected.")
        self.client_choice.setObjectName("helperText")
        self.client_choice.setWordWrap(True)
        client_row.addWidget(self.client_choice, 1)
        self.new_client_button = QPushButton("Add as a new client")
        self.new_client_button.setObjectName("ghostButton")
        self.new_client_button.setAccessibleName("Add the typed name as a new client")
        self.new_client_button.hide()
        client_row.addWidget(self.new_client_button)
        form.addLayout(client_row)
        self.client_email = QLineEdit()
        self.client_email.setObjectName("meetingClientEmail")
        self.client_email.setAccessibleName("Client email")
        self.client_email.setPlaceholderText("Filled in from the client; you can change it")
        form.addWidget(labeled_field("Client email *", self.client_email))

        times = QGridLayout()
        times.setHorizontalSpacing(12)
        times.setVerticalSpacing(6)
        self.date = QDateEdit()
        self.date.setObjectName("meetingDate")
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("ddd dd MMM yyyy")
        self.date.setAccessibleName("Meeting date")
        self.start = QTimeEdit(QTime(10, 0))
        self.start.setObjectName("meetingStartTime")
        self.start.setDisplayFormat("h:mm AP")
        self.start.setAccessibleName("Start time")
        self.duration = QComboBox()
        self.duration.setObjectName("meetingDuration")
        self.duration.setAccessibleName("Meeting duration")
        for minutes in DURATIONS:
            self.duration.addItem(f"{minutes} min", minutes)
        self.duration.addItem("Custom", None)
        self.end = QTimeEdit(QTime(10, 30))
        self.end.setObjectName("meetingEndTime")
        self.end.setDisplayFormat("h:mm AP")
        self.end.setAccessibleName("End time")
        for editor in (self.start, self.end):  # typed, or changed with the arrow keys and mouse wheel
            editor.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            editor.setToolTip("Type a time, or use the Up and Down arrow keys")
        for column, (caption, widget) in enumerate((("Meeting date *", self.date), ("Start time *", self.start),
                                                    ("Duration", self.duration), ("End time *", self.end))):
            times.addWidget(labeled_field(caption, widget), 0, column)
        times.setColumnStretch(0, 3)
        for column in (1, 2, 3):
            times.setColumnStretch(column, 2)
        form.addLayout(times)
        self.duration_text = QLabel()
        self.duration_text.setObjectName("helperText")
        self.duration_text.setAccessibleName("Calculated duration")
        form.addWidget(self.duration_text)

        self.attendee_filter = QLineEdit()
        self.attendee_filter.setObjectName("meetingAttendeeSearch")
        self.attendee_filter.setAccessibleName("Search team members by name or email")
        self.attendee_filter.setPlaceholderText("Search team members by name or email")
        self.attendee_filter.setClearButtonEnabled(True)
        form.addWidget(labeled_field("Attendees * (tick one or more team members)", self.attendee_filter))
        self.attendee_list = QListWidget()
        self.attendee_list.setObjectName("meetingAttendees")
        self.attendee_list.setAccessibleName("Team members: tick the ones attending")
        _list_height(self.attendee_list, 4)
        form.addWidget(self.attendee_list)
        self.attendee_summary = QLabel("No attendees chosen.")
        self.attendee_summary.setObjectName("helperText")
        self.attendee_summary.setWordWrap(True)
        form.addWidget(self.attendee_summary)

        self.link = QLineEdit()
        self.link.setObjectName("meetingLink")
        self.link.setAccessibleName("Meeting link")
        self.link.setPlaceholderText("https://zoom.us/j/…, https://meet.google.com/…, https://teams.microsoft.com/…")
        form.addWidget(labeled_field("Meeting link (optional)", self.link))
        self.description = QPlainTextEdit()
        self.description.setObjectName("meetingDescription")
        self.description.setAccessibleName("Agenda and notes")
        self.description.setPlaceholderText("Agenda, discussion points, or anything the attendees should know")
        self.description.setTabChangesFocus(True)
        self.description.setMaximumHeight(90)
        form.addWidget(labeled_field("Agenda / notes (optional)", self.description))
        form.addStretch(1)

        availability = SectionCard("Availability", "Checked for the client and every attendee.")
        self.availability = Alert("Choose a client, attendees, and a time.", "info")
        self.availability.setObjectName("meetingAvailability")
        self.availability.setAccessibleName("Availability")
        availability.body.addWidget(self.availability)
        self.conflict_list = QLabel()
        self.conflict_list.setObjectName("meetingConflicts")
        self.conflict_list.setWordWrap(True)
        self.conflict_list.setTextFormat(Qt.TextFormat.PlainText)
        self.conflict_list.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.conflict_list.hide()
        availability.body.addWidget(self.conflict_list)
        self.suggestion_heading = QLabel()
        self.suggestion_heading.setObjectName("fieldLabel")
        self.suggestion_heading.setWordWrap(True)
        self.suggestion_heading.hide()
        availability.body.addWidget(self.suggestion_heading)
        self.suggestion_box = QWidget()
        self.suggestion_box.setObjectName("meetingSuggestions")
        self.suggestion_layout = QGridLayout(self.suggestion_box)
        self.suggestion_layout.setContentsMargins(0, 0, 0, 0)
        self.suggestion_layout.setSpacing(8)
        availability.body.addWidget(self.suggestion_box)
        self.suggestion_buttons: list[QPushButton] = []
        self.rules_note = QLabel()
        self.rules_note.setObjectName("helperText")
        self.rules_note.setWordWrap(True)
        availability.body.addWidget(self.rules_note)
        side.addWidget(availability)

        schedule = SectionCard("Client's meetings", "")
        self.schedule_text = QLabel("Select a client to see their meetings.")
        self.schedule_text.setObjectName("meetingClientSchedule")
        self.schedule_text.setWordWrap(True)
        self.schedule_text.setTextFormat(Qt.TextFormat.PlainText)
        self.schedule_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        schedule.body.addWidget(self.schedule_text)
        side.addWidget(schedule)
        side.addStretch(1)

        self.error = Alert("", "error")
        self.error.setObjectName("meetingError")
        layout.addWidget(self.error)

        footer = QFrame()
        footer.setObjectName("modalFooter")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 14, 24, 14)
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton(save_text)
        self.save_button.setObjectName("primaryButton")
        self.save_button.setDefault(True)
        self.save_button.setAccessibleName(save_text)
        self.save_button.clicked.connect(self.save)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        root.addWidget(footer)

    def _timers(self) -> None:
        def timer(callback: Callable[[], None], interval: int) -> QTimer:
            created = QTimer(self)
            created.setSingleShot(True)
            created.setInterval(interval)
            created.timeout.connect(callback)
            return created

        self._client_timer = timer(self.search_clients, 250)
        self._attendee_timer = timer(self.search_attendees, 250)
        self._check_timer = timer(self.check_availability, 300)
        self.client_search.textChanged.connect(self._client_text_changed)
        self.client_results.itemClicked.connect(self._client_clicked)
        self.client_results.itemActivated.connect(self._client_clicked)
        self.new_client_button.clicked.connect(self._choose_new_client)
        self.attendee_filter.textChanged.connect(lambda _text: self._attendee_timer.start())
        self.attendee_list.itemChanged.connect(self._attendee_toggled)
        self.date.dateChanged.connect(lambda _date: self._time_changed(load_schedule=True))
        self.start.timeChanged.connect(lambda _time: self._start_changed())
        self.end.timeChanged.connect(lambda _time: self._time_changed())
        self.duration.currentIndexChanged.connect(lambda _index: self._duration_chosen())

    # ------------------------------------------------------------ initial values

    def _load_rules(self) -> None:
        ok, rules = attempt(self, self.context, meetings.get_scheduling_rules, commit=False, touch=False,
                            title="Meetings")
        if ok and rules is not None:
            self.rules = rules
        self.zone_note.setText(f"Times are in the organization's time zone ({self.rules.timezone}). "
                               "An end time earlier than the start time means the meeting ends the next day.")
        self.rules_note.setText(f"{self.rules.summary()} Suggested times are within business hours "
                                f"({self.rules.hours_text()}).")

    def _now_local(self) -> datetime:
        return datetime.now(UTC).astimezone(self.rules.zone)

    def _populate(self) -> None:
        self._quiet = True
        values = self.values
        zone = self.rules.zone
        today = self._now_local().date()
        starts_at, ends_at = values.get("starts_at"), values.get("ends_at")
        if starts_at and ends_at:
            local_start, local_end = starts_at.astimezone(zone), ends_at.astimezone(zone)
        else:  # the next full hour, 30 minutes
            local_start = (self._now_local() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            local_end = local_start + timedelta(minutes=30)
        earliest = today if self.mode != "edit" else min(today, local_start.date())
        self.date.setMinimumDate(QDate(earliest.year, earliest.month, earliest.day))
        self.date.setDate(QDate(local_start.year, local_start.month, local_start.day))
        self.start.setTime(QTime(local_start.hour, local_start.minute))
        self.end.setTime(QTime(local_end.hour, local_end.minute))
        self.title.setText(str(values.get("title") or ""))
        self.client_email.setText(str(values.get("client_email") or ""))
        self.link.setText(str(values.get("link") or ""))
        self.description.setPlainText(str(values.get("description") or ""))
        for user_id, name, email in values.get("attendees") or []:
            self.chosen[user_id] = (name, email)
        actor = self.context.actor
        if self.mode == "create" and actor is not None:
            self.chosen.setdefault(actor.user_id, (actor.full_name, actor.email))  # the organizer attends
        if self.client_name:
            self.client_search.setText(self.client_name)
        self._quiet = False
        self._sync_duration()
        self._show_client_choice()
        self._show_attendees()
        if self.client_id:
            self.load_client_schedule()

    # ------------------------------------------------------------ background reads

    def _start(self, kind: str, operation: Callable[[Session, Actor], Any],
               callback: Callable[[Any, BaseException | None], None]) -> None:
        self._numbers[kind] += 1
        self._sequence += 1
        self._pending[self._sequence] = (kind, self._numbers[kind], callback)
        worker = _Worker(self._sequence, lambda: self.context.run(operation, commit=False, busy=False, touch=False))
        # A bound method of this dialog (a QObject) receives the answer on the GUI thread; the sender is
        # kept until then, as a queued call from an already deleted sender would be dropped.
        worker.signals.completed.connect(self._finished)
        self._senders[self._sequence] = worker.signals
        QThreadPool.globalInstance().start(worker)

    def _finished(self, sequence: int, result: Any, error: BaseException | None) -> None:
        sender = self._senders.pop(sequence, None)
        if sender is not None:
            sender.deleteLater()
        kind, number, callback = self._pending.pop(sequence)
        if number == self._numbers[kind] and self.isVisible():  # only the latest answer of each kind counts
            callback(result, error)

    # ------------------------------------------------------------ client

    def search_clients(self) -> None:
        query = self.client_search.text()
        self._start("clients", lambda db, actor: meetings.search_clients(db, actor, query, limit=20),
                    self._clients_ready)

    def _clients_ready(self, result: Any, error: BaseException | None) -> None:
        self.client_results.clear()
        if error is not None:
            self.client_results.addItem(explain(error)[0])
            return
        if not result:
            text = self.client_search.text().strip()
            self.client_results.addItem(f"No client matches “{text}”." if text else "No clients yet.")
        for choice in result or []:
            email = choice.email or "no email on file"
            item = QListWidgetItem(f"{choice.name} · {email}")
            item.setData(Qt.ItemDataRole.UserRole, choice)
            item.setToolTip(f"{choice.name}\n{email}" + (f"\nContact: {choice.contact_person}"
                                                          if choice.contact_person else ""))
            self.client_results.addItem(item)
            if choice.id == self.client_id:
                self.client_results.setCurrentItem(item)
        self._show_client_choice()

    def _client_text_changed(self, _text: str) -> None:
        if self._quiet:
            return
        self.client_id = None
        self.new_client = False
        self.client_name = ""
        self._show_client_choice()
        self._client_timer.start()
        self._schedule_check()

    def _client_clicked(self, item: QListWidgetItem) -> None:
        choice = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(choice, meetings.ClientChoice):
            self.select_client(choice)

    def select_client(self, choice: meetings.ClientChoice) -> None:
        self.client_id, self.client_name, self.new_client = choice.id, choice.name, False
        self._quiet = True
        self.client_search.setText(choice.name)
        if choice.email:
            self.client_email.setText(choice.email)
        self._quiet = False
        self._mark(self.client_search, False)
        self._show_client_choice()
        self.load_client_schedule()
        self._schedule_check()

    def _choose_new_client(self) -> None:
        name = self.client_search.text().strip()
        if len(name) < 2:
            return
        self.client_id, self.client_name, self.new_client = None, name, True
        self._show_client_choice()
        self.schedule_text.setText("A new client has no meetings yet.")
        self.client_email.setFocus()
        self._schedule_check()

    def _show_client_choice(self) -> None:
        typed = self.client_search.text().strip()
        if self.client_id:
            self.client_choice.setText(f"Selected client: {self.client_name}")
        elif self.new_client:
            self.client_choice.setText(f"New client: {self.client_name}. It is added to the clients when you save.")
        else:
            self.client_choice.setText("Select a client from the list, or add a new one.")
        can_add = self.mode != "reschedule" and len(typed) >= 2 and not self.client_id and not self.new_client
        self.new_client_button.setText(f"Add “{typed[:40]}” as a new client")
        self.new_client_button.setVisible(can_add and self.context.can("clients.create"))

    def load_client_schedule(self) -> None:
        client_id = self.client_id
        if not client_id:
            return
        on_date = _day(self.date.date())
        self._start("schedule", lambda db, actor: meetings.client_schedule(db, actor, client_id, on_date=on_date),
                    self._schedule_ready)

    def _schedule_ready(self, result: Any, error: BaseException | None) -> None:
        if error is not None:
            self.schedule_text.setText(explain(error)[0])
            return
        schedule: meetings.ClientSchedule = result
        zone = self.rules.zone
        own_id = self.meeting_id

        def lines(entries: list[meetings.ScheduleEntry], with_day: bool) -> list[str]:
            shown = []
            for entry in entries:
                when = span_text(entry.starts_at, entry.ends_at, zone,
                                 reference=None if with_day else entry.starts_at.astimezone(zone).date())
                what = entry.title or "Busy (another team member's meeting)"
                status = "" if entry.status == "scheduled" else f" [{label(MEETING_STATUSES, entry.status)}]"
                mine = " (this meeting)" if entry.id == own_id else ""
                shown.append(f"• {what}{mine}: {when}{status}")
            return shown

        parts = [f"On {day_text(_day(self.date.date()))}:"]
        parts += lines(schedule.on_date, False) or ["• No meetings that day."]
        parts += ["", "Upcoming:"] + (lines(schedule.upcoming, True) or ["• None scheduled."])
        if schedule.past:
            parts += ["", "Recent:"] + lines(schedule.past, True)
        self.schedule_text.setText("\n".join(parts))

    # ------------------------------------------------------------ attendees

    def search_attendees(self) -> None:
        query = self.attendee_filter.text()
        self._start("attendees", lambda db, actor: meetings.search_attendees(db, actor, query),
                    self._attendees_ready)

    def _attendees_ready(self, result: Any, error: BaseException | None) -> None:
        self.attendee_list.blockSignals(True)
        self.attendee_list.clear()
        if error is not None:
            self.attendee_list.addItem(explain(error)[0])
        elif not result:
            self.attendee_list.addItem("No active team member matches.")
        for person in result or []:
            item = QListWidgetItem(f"{person.full_name} · {person.email}")
            item.setData(Qt.ItemDataRole.UserRole, person.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if person.id in self.chosen else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole + 1, (person.full_name, person.email))
            self.attendee_list.addItem(item)
        self.attendee_list.blockSignals(False)

    def _attendee_toggled(self, item: QListWidgetItem) -> None:
        user_id = item.data(Qt.ItemDataRole.UserRole)
        if not user_id:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self.chosen[user_id] = item.data(Qt.ItemDataRole.UserRole + 1)
        else:
            self.chosen.pop(user_id, None)
        self._mark(self.attendee_filter, False)
        self._show_attendees()
        self._schedule_check()

    def set_attendee(self, user_id: str, attending: bool) -> bool:
        """Tick or untick a listed team member (as a click would)."""
        for row in range(self.attendee_list.count()):
            item = self.attendee_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == user_id:
                item.setCheckState(Qt.CheckState.Checked if attending else Qt.CheckState.Unchecked)
                return True
        return False

    def _show_attendees(self) -> None:
        names = sorted(name for name, _email in self.chosen.values())
        self.attendee_summary.setText(f"{len(names)} attending: " + ", ".join(names) if names
                                      else "No attendees chosen.")

    # ------------------------------------------------------------ time

    def _sync_duration(self) -> None:
        """Show the calculated duration and select the matching preset (or Custom)."""
        try:
            start, end = self.interval()
        except ValueError as exc:
            self.duration_text.setText(str(exc))
            return
        minutes = int((end - start).total_seconds() // 60)
        index = self.duration.findData(minutes)
        self.duration.blockSignals(True)
        self.duration.setCurrentIndex(index if index >= 0 else self.duration.count() - 1)
        self.duration.blockSignals(False)
        next_day = " · ends the next day" if end.astimezone(self.rules.zone).date() != \
            start.astimezone(self.rules.zone).date() else ""
        self.duration_text.setText(f"Duration: {duration_text(end - start)}{next_day}")

    def _duration_chosen(self) -> None:
        minutes = self.duration.currentData()
        if minutes is None or self._quiet:
            return
        self._quiet = True
        self.end.setTime(self.start.time().addSecs(int(minutes) * 60))
        self._quiet = False
        self._time_changed()

    def _start_changed(self) -> None:
        if self._quiet:
            return
        minutes = self.duration.currentData()
        if minutes is not None:  # keep the chosen length
            self._quiet = True
            self.end.setTime(self.start.time().addSecs(int(minutes) * 60))
            self._quiet = False
        self._time_changed()

    def _time_changed(self, *, load_schedule: bool = False) -> None:
        if self._quiet:
            return
        self._sync_duration()
        self._mark(self.start, False)
        self._mark(self.end, False)
        if load_schedule:
            self.load_client_schedule()
        self._schedule_check()

    def interval(self) -> tuple[datetime, datetime]:
        timezone = self.rules.timezone
        start = _wall_time(self.date.date(), self.start.time(), timezone)
        end_day = self.date.date()
        if self.end.time() <= self.start.time():
            end_day = end_day.addDays(1)
        return start, _wall_time(end_day, self.end.time(), timezone)

    def use_slot(self, starts_at: datetime, ends_at: datetime) -> None:
        local_start, local_end = starts_at.astimezone(self.rules.zone), ends_at.astimezone(self.rules.zone)
        self._quiet = True
        self.date.setDate(QDate(local_start.year, local_start.month, local_start.day))
        self.start.setTime(QTime(local_start.hour, local_start.minute))
        self.end.setTime(QTime(local_end.hour, local_end.minute))
        self._quiet = False
        self._time_changed(load_schedule=True)
        self.save_button.setFocus()

    # ------------------------------------------------------------ availability

    def _schedule_check(self) -> None:
        if not self._quiet:
            self.availability.set_message("Checking availability…", "info")
            self._check_timer.start()

    def check_availability(self) -> None:
        try:
            start, end = self.interval()
        except ValueError as exc:
            self._show_problem(str(exc))
            return
        if not self.client_id and not self.chosen:
            self._show_problem("Choose a client and attendees to check their availability.", tone="info")
            return
        query = parse(AvailabilityQuery, {"client_id": self.client_id, "attendee_ids": sorted(self.chosen),
                                          "starts_at": start, "ends_at": end, "meeting_id": self.meeting_id})
        self._start("check", lambda db, actor: meetings.check_availability(db, actor, query),
                    self._availability_ready)

    def _show_problem(self, message: str, *, tone: str = "warning") -> None:
        self.last_availability = None
        self.availability.set_message(message, tone)
        self.conflict_list.hide()
        self._show_suggestions(None)

    def _availability_ready(self, result: Any, error: BaseException | None) -> None:
        if error is not None:
            heading, details = explain(error)
            self._show_problem(f"{heading}\n{details}".strip())
            return
        found: meetings.Availability = result
        self.last_availability = found
        zone = found.rules.zone
        span = span_text(found.starts_at, found.ends_at, zone, reference=None)
        hours = (f"\nOutside business hours ({found.rules.hours_text()})." if found.outside_hours else "")
        if found.available:
            who = []
            if self.client_id:
                who.append(self.client_name)
            if self.chosen:
                who.append("all attendees" if len(self.chosen) > 1 else "the attendee")
            subject = " and ".join(who) or "Everyone"
            self.availability.set_message(f"Available: {subject} free {span}.{hours}", "success")
            self.conflict_list.hide()
        else:
            self.availability.set_message(f"This time slot is unavailable ({span}).{hours}", "error")
            lines = [*found.problems, *(clash.message for clash in found.conflicts)]
            self.conflict_list.setText("\n".join(f"• {line}" for line in lines))
            self.conflict_list.show()
        self._show_suggestions(found if not found.available else None)

    def _show_suggestions(self, found: meetings.Availability | None) -> None:
        for button in self.suggestion_buttons:
            self.suggestion_layout.removeWidget(button)
            button.deleteLater()
        self.suggestion_buttons = []
        if found is None:
            self.suggestion_heading.hide()
            return
        zone = found.rules.zone
        if found.suggestions and found.suggestion_day is not None:
            if found.suggestions_later:
                heading = (f"No free time that day. The next available date is {day_text(found.suggestion_day)}; "
                           "choose a time:")
            else:
                heading = "Here are some available alternatives:"
        else:
            heading = (f"No free time was found in the next 30 days within business hours "
                       f"({found.rules.hours_text()}). Choose another date or fewer attendees.")
        self.suggestion_heading.setText(heading)
        self.suggestion_heading.show()
        for index, slot in enumerate(found.suggestions):
            text = f"{clock(slot.starts_at, zone)} – {clock(slot.ends_at, zone)}"
            button = QPushButton(text)
            button.setObjectName("secondaryButton")
            button.setProperty("suggestion", True)
            button.setAccessibleName(f"Use {day_text(slot.starts_at.astimezone(zone).date())} {text}")
            button.setToolTip(f"Use {day_text(slot.starts_at.astimezone(zone).date())}, {text}")
            button.clicked.connect(lambda _checked=False, chosen=slot: self.use_slot(chosen.starts_at, chosen.ends_at))
            self.suggestion_layout.addWidget(button, index // 2, index % 2)
            button.show()
            self.suggestion_buttons.append(button)

    # ------------------------------------------------------------ saving

    def _mark(self, widget: QWidget, invalid: bool) -> None:
        if bool(widget.property("invalid")) != invalid:
            widget.setProperty("invalid", invalid)
            repolish(widget)

    def _fail(self, message: str, *widgets: QWidget) -> None:
        for widget in widgets:
            self._mark(widget, True)
        if widgets:
            widgets[0].setFocus()
        raise ValueError(message)

    def _form_values(self) -> dict[str, Any]:
        if self.mode != "reschedule":
            if not self.title.text().strip():
                self._fail("Enter a meeting title.", self.title)
            if not self.client_id and not self.new_client:
                self._fail("Search for the client by name or email and select it, or add a new client.",
                           self.client_search)
            if not self.client_email.text().strip():
                self._fail("Enter the client's email address.", self.client_email)
            if not self.chosen:
                self._fail("Choose at least one attendee.", self.attendee_filter)
        try:
            start, end = self.interval()
        except ValueError as exc:
            self._fail(str(exc), self.start)
        values: dict[str, Any] = {"starts_at": start, "ends_at": end}
        if self.mode == "reschedule":
            return values
        return {**values, "title": self.title.text(), "client_id": self.client_id,
                "client_name": self.client_name if self.new_client else None,
                "client_email": self.client_email.text(), "attendee_ids": sorted(self.chosen),
                "link": self.link.text(), "description": self.description.toPlainText()}

    _FIELDS = {"title": "title", "client_id": "client_search", "client_name": "client_search",
               "client_email": "client_email", "attendee_ids": "attendee_filter", "starts_at": "start",
               "ends_at": "end", "link": "link", "description": "description"}

    def save(self) -> None:
        self.error.set_message("")
        self.save_button.setEnabled(False)
        try:
            values = self._form_values()
            if self.mode == "reschedule":
                reschedule = parse(MeetingReschedule, {**values, "version": self.values.get("version")})
                saved = self.context.write("meeting", lambda db, actor: meetings.reschedule_meeting(
                    db, actor, self.meeting_id or "", reschedule).id)
            elif self.mode == "edit":
                update = parse(MeetingUpdate, {**values, "version": self.values.get("version")})
                saved = self.context.write("meeting", lambda db, actor: meetings.update_meeting(
                    db, actor, self.meeting_id or "", update).id)
            else:
                create = parse(MeetingCreate, {**values, "request_id": self.request_id})
                saved = self.context.write("meeting", lambda db, actor: meetings.create_meeting(
                    db, actor, create).id)
        except ValueError as exc:
            self.error.set_message(str(exc), "error")
        except DomainError as exc:  # the service's own explanation, shown in the form
            heading, details = explain(exc)
            self.error.set_message(f"{heading}\n{details}".strip(), "error")
            for field in exc.fields:
                widget = getattr(self, self._FIELDS.get(field, ""), None)
                if isinstance(widget, QWidget):
                    self._mark(widget, True)
            if isinstance(exc, Conflict):
                self.check_availability()  # show the current conflicts and free slots
        except Exception as exc:  # connection problems and the unexpected: the standard message box
            report(self, exc, title="Save meeting")
        else:
            self.result_value = saved
            self.accept()
        finally:
            self.save_button.setEnabled(True)


class MeetingsPage(RecordPage):
    title = "Meetings"
    subtitle = "Schedule client meetings without double-booking a client or a team member."
    noun = "meeting"
    plural = "meetings"
    columns = (
        Column("title", "Meeting title", "title", strong=True),
        Column("client", "Client name", "client"),
        Column("email", "Client email", muted=True),
        Column("date", "Meeting date", "date", keep=True),
        Column("start", "Start", keep=True),
        Column("end", "End", keep=True),
        Column("duration", "Duration", keep=True),
        Column("attendees", "Attendees"),
        Column("link", "Meeting link", muted=True),
        Column("status", "Status", "status", badge=True, keep=True),
        Column("creator", "Created by"),
        Column("actions", "Actions", keep=True),
    )
    default_sort = "date"
    create_permission = "meetings.create"
    ROW_ACTIONS = (
        RowAction("view", "View details", "View details", icon="eye"),
        RowAction("edit", "Edit", "Edit the meeting", icon="edit"),
        RowAction("reschedule", "Reschedule", "Reschedule", icon="calendar"),
        RowAction("cancel", "Cancel meeting", "Cancel the meeting", destructive=True, icon="close"),
    )

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.new_button.setText("Create Meeting")
        self.new_button.setObjectName("primaryButton")
        self.new_button.setAccessibleName("Create meeting")
        self.records.set_empty_state("No meetings match these filters",
                                     "Create a meeting, or change the search and filters.",
                                     action=("Create Meeting", self.create_record), icon="meetings")
        self._build_summary()
        self._row_actions = RowActionDelegate(self.ROW_ACTIONS, id_role=ID_ROLE, view=self.records.table)
        self._row_actions.triggered.connect(self.run_row_action)
        self.records.table.setItemDelegateForColumn(len(self.columns) - 1, self._row_actions)
        self.records.fixed_widths = {len(self.columns) - 1: self._row_actions.column_width()}
        enable_column_choice(self.records.table, "records/meetings", locked=(0, len(self.columns) - 1))
        install_row_action_menu(self.records.table, self.ROW_ACTIONS,
                                lambda index: str(index.data(ID_ROLE) or ""), self.run_row_action)
        self.search.setPlaceholderText("Search title, client, email, attendee, or meeting ID")
        self._conflicts: set[str] = set()
        self._shortcuts.append(QShortcut(QKeySequence("Ctrl+R"), self, self.refresh))
        self._shortcuts.append(QShortcut(QKeySequence("Ctrl+N"), self, self.create_record))

    # ------------------------------------------------------------ layout

    def _build_summary(self) -> None:
        strip = QWidget()
        strip.setObjectName("meetingSummary")
        row = QHBoxLayout(strip)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        self.summary_cards: dict[str, KpiCard] = {}
        for key, title, icon, accent in (("today", "Today's meetings", "calendar", "green"),
                                         ("upcoming", "Upcoming", "clock", "blue"),
                                         ("completed", "Completed", "check-circle", "green"),
                                         ("cancelled", "Cancelled", "close", "gold"),
                                         ("conflicts", "Scheduling conflicts", "alert", "red")):
            card = KpiCard(title, "0", compact=True, icon=icon, accent=accent, clickable=True)
            card.setToolTip(f"Show {title.lower()}")
            card.clicked.connect(lambda key=key: self.show_view(key))
            row.addWidget(card, 1)
            self.summary_cards[key] = card
        root_layout = self.layout()
        if not isinstance(root_layout, QVBoxLayout):
            raise RuntimeError("Meeting page layout was not initialized.")
        root_layout.insertWidget(1, strip)

    def build_filters(self, bar: QHBoxLayout) -> None:
        bar.removeWidget(self.search)
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        bar.addWidget(grid_host, 1)
        grid.addWidget(self.search, 0, 0, 1, 2)
        self.view_filter = QComboBox()
        self.view_filter.setAccessibleName("Show")
        self.view_filter.addItem("All meetings", None)
        for key, text in meetings.VIEWS.items():
            self.view_filter.addItem(text, key)
        self.view_filter.setCurrentIndex(self.view_filter.findData("upcoming"))  # the next meetings first
        self.status_filter = QComboBox()
        self.status_filter.setAccessibleName("Meeting status")
        self.status_filter.addItem("All statuses", None)
        for key, text in MEETING_STATUSES.items():
            self.status_filter.addItem(text, key)
        self.attendee_filter = QComboBox()
        self.attendee_filter.setAccessibleName("Team member")
        self.attendee_filter.addItem("All team members", None)
        self.attendee_filter.setMinimumWidth(180)
        for column, combo in enumerate((self.view_filter, self.status_filter, self.attendee_filter), start=2):
            combo.currentIndexChanged.connect(lambda _index: self.records.reload(page=1))
            grid.addWidget(combo, 0, column)
        self.client_filter = QLineEdit()
        self.client_filter.setAccessibleName("Client name or email")
        self.client_filter.setPlaceholderText("Client name or email")
        self.client_filter.setClearButtonEnabled(True)
        self._client_filter_timer = QTimer(self)
        self._client_filter_timer.setSingleShot(True)
        self._client_filter_timer.setInterval(300)
        self._client_filter_timer.timeout.connect(lambda: self.records.reload(page=1))
        self.client_filter.textChanged.connect(lambda _text: self._client_filter_timer.start())
        grid.addWidget(self.client_filter, 1, 0)
        self.dates_enabled = QCheckBox("Dates")
        self.dates_enabled.setAccessibleName("Filter by meeting date range")
        self.date_from = QDateEdit(QDate.currentDate())
        self.date_to = QDateEdit(QDate.currentDate())
        dates = QHBoxLayout()
        dates.setSpacing(8)
        dates.addWidget(self.dates_enabled)
        for name, editor in (("From date", self.date_from), ("To date", self.date_to)):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd MMM yyyy")
            editor.setAccessibleName(name)
            editor.setEnabled(False)
            editor.dateChanged.connect(lambda _date: self.records.reload(page=1)
                                       if self.dates_enabled.isChecked() else None)
            self.dates_enabled.toggled.connect(editor.setEnabled)
            dates.addWidget(editor, 1)
        self.dates_enabled.toggled.connect(lambda _checked: self.records.reload(page=1))
        grid.addLayout(dates, 1, 1, 1, 2)
        self.clear_button = QPushButton("Clear filters")
        self.clear_button.setObjectName("secondaryButton")
        self.clear_button.clicked.connect(self.clear_filters)
        grid.addWidget(self.clear_button, 1, 3)
        self.rules_label = QLabel()
        self.rules_label.setObjectName("helperText")
        self.rules_label.setWordWrap(True)
        grid.addWidget(self.rules_label, 1, 4)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 2)

    # ------------------------------------------------------------ filters

    def list_filters(self) -> dict[str, Any]:
        filters = super().list_filters()
        for name, combo in (("view", self.view_filter), ("status", self.status_filter),
                            ("attendee_id", self.attendee_filter)):
            if combo.currentData():
                filters[name] = combo.currentData()
        if self.client_filter.text().strip():
            filters["client_q"] = self.client_filter.text().strip()
        if self.dates_enabled.isChecked():
            filters["date_from"] = _day(self.date_from.date())
            filters["date_to"] = _day(self.date_to.date())
        return filters

    def show_view(self, view: str | None) -> None:
        """Show one summary card's meetings."""
        self.view_filter.blockSignals(True)
        self.set_combo(self.view_filter, view)
        self.view_filter.blockSignals(False)
        self.status_filter.blockSignals(True)
        self.status_filter.setCurrentIndex(0)
        self.status_filter.blockSignals(False)
        self.records.reload(page=1)
        self._highlight_card()

    def clear_filters(self) -> None:
        for widget in (self.search, self.client_filter, self.view_filter, self.status_filter, self.attendee_filter,
                       self.dates_enabled):
            widget.blockSignals(True)
        self.search.clear()
        self.client_filter.clear()
        self.view_filter.setCurrentIndex(0)
        self.status_filter.setCurrentIndex(0)
        self.attendee_filter.setCurrentIndex(0)
        self.dates_enabled.setChecked(False)
        for widget in (self.search, self.client_filter, self.view_filter, self.status_filter, self.attendee_filter,
                       self.dates_enabled):
            widget.blockSignals(False)
        for editor in (self.date_from, self.date_to):
            editor.setEnabled(False)
        self.records.reload(page=1)
        self._highlight_card()

    def set_filter_values(self, values: dict[str, str]) -> None:
        self.client_filter.setText(values.get("client_q", ""))
        self.set_combo(self.view_filter, values.get("view"))
        self.set_combo(self.status_filter, values.get("status"))

    def _highlight_card(self) -> None:
        current = self.view_filter.currentData()
        for key, card in self.summary_cards.items():
            card.setProperty("selected", key == current)
            card.setAccessibleDescription(f"{card.title_label.text()}{' (shown)' if key == current else ''}")
            repolish(card)

    # ------------------------------------------------------------ list

    def fetch(self, db: Session, actor: Actor, request: PageRequest, filters: dict[str, Any]) -> RowPage:
        page = meetings.list_meetings(db, actor, page=request, **filters)
        rules = meetings.scheduling_rules(db)
        conflicts = meetings.conflicting_ids(db, rules)
        return RowPage.build(page, lambda item: self._row(item, rules, item.id in conflicts))

    @staticmethod
    def _row(meeting: Meeting, rules: SchedulingRules, conflict: bool) -> Row:
        zone = rules.zone
        local_start = meeting.starts_at.astimezone(zone)
        local_end = meeting.ends_at.astimezone(zone)
        end_text = clock(local_end) + (f" ({day_text(local_end.date())})" if local_end.date() != local_start.date()
                                       else "")
        status = label(MEETING_STATUSES, meeting.status)
        attendees = ", ".join(f"{user.full_name}" for user in meeting.attendees)
        creator = meeting.created_by.full_name if meeting.created_by else "Former user"
        tooltip = ""
        if conflict:
            tooltip = "This meeting clashes with another under the current scheduling rules: reschedule one of them."
        cells = [meeting.title, meeting.client_name, meeting.client_email or "—", day_text(local_start.date()),
                 clock(local_start), end_text, duration_text(meeting.ends_at - meeting.starts_at), attendees,
                 meeting.link or "—", status + (" · conflict" if conflict else ""), creator, ""]
        return Row(meeting.id, cells, tooltip=tooltip,
                   emphasis="failed" if conflict else ("muted" if meeting.status != "scheduled" else ""),
                   colors={9: "danger" if conflict else (tone_for(status) or "neutral")})

    # ------------------------------------------------------------ details

    def describe(self, db: Session, actor: Actor, record_id: str) -> DetailView:
        meeting = meetings.get_meeting(db, actor, record_id)
        rules = meetings.scheduling_rules(db)
        zone = rules.zone
        entries = meetings.history(db, actor, record_id)
        status = label(MEETING_STATUSES, meeting.status)
        start = meeting.starts_at.astimezone(zone)
        when = f"{day_text(start.date())}, {span_text(meeting.starts_at, meeting.ends_at, zone, reference=start.date())}"
        attendees = [user for user in meeting.attendees]
        fields = [
            ("Client", meeting.client_name),
            ("Client email", meeting.client_email or "—"),
            ("Date and time", when),
            ("Duration", duration_text(meeting.ends_at - meeting.starts_at)),
            ("Meeting link", meeting.link or "No link added"),
            ("Attendees", "\n".join(f"{user.full_name} · {user.email}" for user in attendees) or "—"),
            ("Status", status),
            ("Created by", meeting.created_by.full_name if meeting.created_by else "Former user"),
            ("Created", local_time(meeting.created_at, rules.timezone)),
            ("Updated", local_time(meeting.updated_at, rules.timezone)),
            ("Meeting ID", meeting.id),
        ]
        if meeting.cancellation_reason:
            fields.append(("Cancellation reason", meeting.cancellation_reason))
        allowed: set[str] = set()
        involved = actor.user_id in meeting.attendee_ids or meeting.created_by_id == actor.user_id

        def may(permission: str) -> bool:
            scope = actor.scope(permission)
            return scope is Scope.ALL or (scope is Scope.OWN and involved)

        if meeting.status == "scheduled" and may("meetings.edit"):
            allowed.update(("edit", "reschedule"))
            if meeting.starts_at <= datetime.now(UTC):
                allowed.add("complete")
        if meeting.status == "scheduled" and may("meetings.cancel"):
            allowed.add("cancel")
        history_rows = [(local_time(entry.created_at, rules.timezone),
                         _AUDIT_ACTIONS.get(entry.action, entry.action),
                         entry.actor.full_name if entry.actor else "System",
                         _change_summary(entry.changes, zone)) for entry in entries]
        notice = ""
        if meeting.status == "scheduled" and meeting.id in meetings.conflicting_ids(db, rules):
            notice = ("This meeting clashes with another meeting of the same client or attendee under the current "
                      "scheduling rules. Reschedule one of them.")
        return DetailView(
            meeting.id, meeting.title, f"{meeting.client_name} · {when}", fields,
            (DetailTab("History", ("When", "What", "Who", "Details"), history_rows, empty="No changes recorded."),),
            allowed,
            {"version": meeting.version, "id": meeting.id, "client_id": meeting.client_id,
             "client_name": meeting.client_name, "client_email": meeting.client_email, "title": meeting.title,
             "attendees": [(user.id, user.full_name, user.email) for user in attendees],
             "starts_at": meeting.starts_at, "ends_at": meeting.ends_at, "link": meeting.link,
             "description": meeting.description},
            badges=[(status, tone_for(status) or "neutral")],
            notes=meeting.description or "No agenda or notes added.",
            notice=notice,
            closable=True,
        )

    def build_actions(self, panel: Any) -> None:
        self.edit_button = panel.add_action("Edit", self.edit_current, icon="edit")
        self.reschedule_button = panel.add_action("Reschedule", self.reschedule_current, icon="calendar")
        self.complete_button = panel.add_action("Mark completed", self.complete_current, primary=True, icon="check")
        self.cancel_meeting_button = panel.add_action("Cancel meeting", self.cancel_current, destructive=True)
        self.open_link_button = panel.add_action("Open meeting link", self.open_meeting_link, icon="arrow-right")
        self.copy_link_button = panel.add_action("Copy link", self.copy_meeting_link, ghost=True, icon="copy")

    def update_actions(self, view: DetailView | None) -> None:
        allowed = view.allowed if view else set()
        for button, key in ((self.edit_button, "edit"), (self.reschedule_button, "reschedule"),
                            (self.complete_button, "complete"), (self.cancel_meeting_button, "cancel")):
            button.setEnabled(key in allowed)
            button.setVisible(view is None or key in allowed)
        link = bool(view and view.data.get("link"))
        self.open_link_button.setEnabled(link)
        self.copy_link_button.setEnabled(link)

    # ------------------------------------------------------------ actions

    def run_row_action(self, key: str, record_id: str) -> None:
        if not record_id:
            return
        self.show_record(record_id)
        if key == "edit":
            self.edit_current()
        elif key == "reschedule":
            self.reschedule_current()
        elif key == "cancel":
            self.cancel_current()

    def edit_current(self) -> None:
        view = self.current_view()
        if view is None:
            return
        if "edit" not in view.allowed:
            self.status_requested.emit("Only scheduled meetings you may manage can be edited.")
            return
        dialog = MeetingDialog(self, self.context, values=view.data, mode="edit")
        if dialog.exec():
            self.after_change(view.id, "Meeting updated.")

    def reschedule_current(self) -> None:
        view = self.current_view()
        if view is None:
            return
        if "reschedule" not in view.allowed:
            self.status_requested.emit("Only scheduled meetings you may manage can be rescheduled.")
            return
        dialog = MeetingDialog(self, self.context, values=view.data, mode="reschedule")
        if dialog.exec():
            self.after_change(view.id, "Meeting rescheduled.")

    def create_record(self) -> None:
        if not self.context.can("meetings.create"):
            return
        dialog = MeetingDialog(self, self.context)
        if dialog.exec():
            self.after_change(dialog.result_value, "Meeting scheduled.")

    def complete_current(self) -> None:
        view = self.current_view()
        if view is None or "complete" not in view.allowed:
            return
        ok, _ = attempt(self, self.context, lambda db, actor: meetings.complete_meeting(
            db, actor, view.id, version=view.data["version"]), kind="meeting", title="Complete meeting")
        if ok:
            self.after_change(view.id, "Meeting marked completed.")

    def cancel_current(self) -> None:
        view = self.current_view()
        if view is None:
            return
        if "cancel" not in view.allowed:
            self.status_requested.emit("Only scheduled meetings you may manage can be cancelled.")
            return
        if not ask_confirmation(
            self, title="Cancel meeting", heading="Cancel this meeting?",
            message=f"“{view.title}” stays in the meeting history, the attendees are notified, and its time "
                    "becomes free for other meetings.",
            confirm_text="Cancel meeting", cancel_text="Keep meeting", destructive=True,
        ):
            return
        ok, _ = attempt(self, self.context, lambda db, actor: meetings.cancel_meeting(
            db, actor, view.id, version=view.data["version"]), kind="meeting", title="Cancel meeting")
        if ok:
            self.after_change(view.id, "Meeting cancelled.")

    def open_meeting_link(self) -> None:
        view = self.current_view()
        if view and view.data.get("link") and not QDesktopServices.openUrl(QUrl(view.data["link"])):
            self.status_requested.emit("The meeting link could not be opened in your browser.")

    def copy_meeting_link(self) -> None:
        view = self.current_view()
        if view and view.data.get("link"):
            QApplication.clipboard().setText(view.data["link"])
            self.status_requested.emit("Meeting link copied.")

    def after_change(self, record_id: str | None, message: str) -> None:
        super().after_change(record_id, message)
        self.refresh_summary()

    def refresh(self) -> None:
        self._load_team()
        super().refresh()
        self.refresh_summary()
        self._highlight_card()

    def refresh_summary(self) -> None:
        def work(db: Session, actor: Actor) -> tuple[dict[str, int], SchedulingRules]:
            return meetings.meeting_counts(db, actor), meetings.scheduling_rules(db)

        ok, result = attempt(self, self.context, work, commit=False, touch=False)
        if not ok or result is None:
            return
        counts, rules = result
        notes = {"today": "Not cancelled, in the business day", "upcoming": "Scheduled from now on",
                 "completed": "Held", "cancelled": "No longer reserve time",
                 "conflicts": "Clash under the current rules" if counts["conflicts"] else "None"}
        for key, card in self.summary_cards.items():
            card.set_value(str(counts.get(key, 0)), notes[key])
        self.summary_cards["conflicts"].setVisible(counts["conflicts"] > 0 or self.view_filter.currentData()
                                                   == "conflicts")
        self.rules_label.setText(f"{rules.summary()} Times in {rules.timezone}.")

    def _load_team(self) -> None:
        if not self.context.can("meetings.create"):
            self.attendee_filter.setVisible(False)
            return
        ok, people = attempt(self, self.context, lambda db, actor: meetings.search_attendees(db, actor),
                             commit=False, touch=False)
        if not ok or people is None:
            return
        current = self.attendee_filter.currentData()
        self.attendee_filter.blockSignals(True)
        self.attendee_filter.clear()
        self.attendee_filter.addItem("All team members", None)
        for person in people:
            self.attendee_filter.addItem(person.full_name, person.id)
        self.set_combo(self.attendee_filter, current)
        self.attendee_filter.blockSignals(False)


def _change_summary(changes: dict[str, Any] | None, zone: ZoneInfo) -> str:
    """A short description of an audit entry's changes (times in the business time zone)."""
    if not changes:
        return ""
    parts = []
    for field, value in changes.items():
        name = "Start" if field == "starts_at" else "End"
        if field in ("starts_at", "ends_at") and isinstance(value, list) and len(value) == 2:
            old, new = (datetime.fromisoformat(item).astimezone(zone) if item else None for item in value)
            parts.append(f"{name}: {_moment(old)} → {_moment(new)}")
        elif field in ("starts_at", "ends_at") and isinstance(value, str):  # the created entry
            parts.append(f"{name}: {_moment(datetime.fromisoformat(value).astimezone(zone))}")
        elif field == "status" and isinstance(value, list):
            parts.append(f"Status: {label(MEETING_STATUSES, value[0])} → {label(MEETING_STATUSES, value[1])}")
        elif field == "attendee_ids":
            count = len(value[1]) if isinstance(value, list) and len(value) == 2 and isinstance(value[1], list) \
                else len(value) if isinstance(value, list) else 0
            parts.append(f"Attendees: {count}")
        elif field in ("title", "client_name", "cancellation_reason") and isinstance(value, list):
            parts.append(f"{field.replace('_', ' ').capitalize()}: {value[1] or '—'}")
    return "; ".join(parts) or ", ".join(sorted(changes))


def _moment(value: datetime | None) -> str:
    return f"{day_text(value.date())} {clock(value)}" if value else "—"


__all__ = ["MeetingDialog", "MeetingsPage"]
