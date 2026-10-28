"""Native LinkedIn prospect list, detail, editing, and reviewed imports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from techset_leadgen.analytics.importer import read_table
from techset_leadgen.database.engine import utcnow
from techset_leadgen.errors import ValidationFailed
from techset_leadgen.services.schemas import ProspectCreate, ProspectUpdate, parse
from techset_leadgen.services import prospects
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import PageRequest
from techset_leadgen.security.permissions import Scope
from techset_leadgen.domain.vocabulary import ASSIGNMENT_STATUSES, PROSPECT_STATUSES

from techset_leadgen.desktop.dialogs import show_message
from techset_leadgen.desktop.forms import FieldSpec, FormDialog
from techset_leadgen.desktop.icons import set_button_icon
from techset_leadgen.desktop.modal import ModalDialog
from techset_leadgen.desktop.records import Column, DetailPanel, DetailTab, DetailView, RecordPage, Row, RowPage
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.desktop.support import attempt, label, local_time, person, text
from techset_leadgen.desktop.tables import TONE_ROLE, fit_columns
from techset_leadgen.desktop.widgets import Alert, set_table_defaults

HISTORY_LIMIT = 100


def _display_name(prospect: Any) -> str:
    return prospect.full_name or prospect.linkedin_key.removeprefix("in/").replace("-", " ").title()


def _status_tone(status: str) -> str:
    if status in {"not_interested", "invalid"}:
        return "danger"
    if status in {"replied", "meeting"}:
        return "success"
    if status in {"connection_sent", "connected", "messaged"}:
        return "info"
    return "neutral"


def _prospect_fields() -> list[FieldSpec]:
    return [
        FieldSpec(
            "linkedin_url",
            "LinkedIn profile",
            required=True,
            span=True,
            placeholder="https://www.linkedin.com/in/profile-name",
            hint="Public member profiles are normalized so the same person is not added twice.",
        ),
        FieldSpec("full_name", "Name", placeholder="e.g. Ayesha Malik"),
        FieldSpec("company", "Company"),
        FieldSpec("job_title", "Job title", span=True),
        FieldSpec("notes", "Notes", "multiline"),
    ]


def create_prospect(parent: QWidget, context: AppContext) -> str | None:
    """Open the one-prospect form and return the new ID when it is saved."""

    def submit(dialog: FormDialog) -> str:
        data = parse(ProspectCreate, {**dialog.values(), "source": "Added by hand"})
        return context.write("prospect", lambda db, actor: prospects.create_prospect(db, actor, data).id)

    dialog = FormDialog(
        parent,
        title="Prospect",
        heading="Add a LinkedIn prospect",
        note="This records a profile for manual outreach. It does not contact LinkedIn or send messages.",
        fields=_prospect_fields(),
        submit=submit,
        submit_text="Add prospect",
    )
    return str(dialog.result_value) if dialog.exec() and dialog.result_value else None


class _FileSignals(QObject):
    """Results of a file read, delivered on the GUI thread."""

    succeeded = Signal(int, str, object)  # token, path, rows
    failed = Signal(int, str)


class _FileReader(QRunnable):
    """Read a CSV/XLSX file into prospect rows off the GUI thread (no database or widget access)."""

    def __init__(self, token: int, path: str) -> None:
        super().__init__()
        self.token = token
        self.path = path
        self.signals = _FileSignals()

    @Slot()
    def run(self) -> None:
        try:
            headers, records = read_table(self.path, max_rows=prospects.MAX_IMPORT_ROWS)
            rows = prospects.rows_from_table(headers, records)
        except ValidationFailed as exc:
            self.signals.failed.emit(self.token, exc.message)
        except Exception as exc:  # unreadable or malformed file: shown to the user, nothing is saved
            self.signals.failed.emit(self.token, f"The file could not be read: {exc}")
        else:
            self.signals.succeeded.emit(self.token, self.path, rows)


class ProspectImportDialog(ModalDialog):
    """Paste profiles or load a table, preview every outcome, then explicitly import.

    A chosen file is read by a background worker, so a large spreadsheet never
    freezes the window. The workflow is paste/load -> preview -> confirm;
    neither preview path writes data.
    """

    _TONES = {"New": "success", "Existing": "info", "Repeated": "warning", "Rejected": "danger"}

    def __init__(self, parent: QWidget, context: AppContext) -> None:
        super().__init__(parent)
        self.context = context
        self.result_value: prospects.ImportResult | None = None
        self._preview_rows: list[Any] | None = None
        self._preview_result: prospects.ImportPreview | None = None
        self._file_rows: list[Any] | None = None
        self._source = "Pasted profiles"
        self._loading_file = False
        self._read_token = 0
        self._reader: _FileReader | None = None

        self.setWindowTitle("Add prospects")
        self.setAccessibleName("Add or import LinkedIn prospects")
        self.setModal(True)
        self.resize(860, 680)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        root.addWidget(body, 1)

        heading = QLabel("Add several LinkedIn profiles")
        heading.setObjectName("dialogTitle")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(heading)
        intro = QLabel(
            "Paste one public LinkedIn profile per line. You may also paste spreadsheet columns in the order "
            "profile, name, company, and job title. Preview checks invalid and duplicate rows without saving."
        )
        intro.setObjectName("dialogSubtitle")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(intro)

        source_row = QHBoxLayout()
        source_row.setSpacing(8)
        source_label = QLabel("Profiles to review")
        source_label.setObjectName("fieldLabel")
        source_row.addWidget(source_label)
        source_row.addStretch(1)
        self.file_button = QPushButton("Choose CSV/XLSX…")
        self.file_button.setObjectName("secondaryButton")
        self.file_button.setAccessibleName("Choose a prospect CSV or Excel file")
        self.file_button.setToolTip("Reads the selected file now, then shows the same preview before saving")
        set_button_icon(self.file_button, "folder", "text")
        self.file_button.clicked.connect(self.choose_file)
        source_row.addWidget(self.file_button)
        layout.addLayout(source_row)

        self.input = QPlainTextEdit()
        self.input.setAccessibleName("LinkedIn profiles to preview")
        self.input.setPlaceholderText(
            "https://www.linkedin.com/in/jane-doe\n"
            "https://www.linkedin.com/in/amir-khan\tAmir Khan\tNorthwind\tFounder"
        )
        self.input.setTabChangesFocus(True)
        self.input.setMinimumHeight(112)
        source_label.setBuddy(self.input)
        self.input.textChanged.connect(self._input_changed)
        layout.addWidget(self.input)

        preview_row = QHBoxLayout()
        preview_row.setSpacing(10)
        self.preview_button = QPushButton("Preview")
        self.preview_button.setObjectName("secondaryButton")
        self.preview_button.setAccessibleName("Preview prospect import")
        set_button_icon(self.preview_button, "eye", "text")
        self.preview_button.clicked.connect(self.preview)
        preview_row.addWidget(self.preview_button)
        self.summary = QLabel("Nothing has been checked or saved yet.")
        self.summary.setObjectName("sectionSubtitle")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        preview_row.addWidget(self.summary, 1)
        layout.addLayout(preview_row)

        self.notice = Alert("Preview is read-only. Use the confirmation button below to save new profiles.", "info")
        layout.addWidget(self.notice)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Row", "Profile", "Name", "Result", "Details"])
        self.table.setAccessibleName("Prospect import preview")
        set_table_defaults(self.table, badge_columns=[3], numeric_columns=[0], row_height=44)
        layout.addWidget(self.table, 1)

        footer = QFrame()
        footer.setObjectName("modalFooter")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 14, 24, 14)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.clicked.connect(self.reject)
        self.import_button = QPushButton("Preview first")
        self.import_button.setObjectName("primaryButton")
        self.import_button.setAccessibleName("Confirm adding previewed prospects")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self.persist)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.import_button)
        root.addWidget(footer)

        self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _input_changed(self) -> None:
        if self._loading_file:
            return
        self._file_rows = None
        self._source = "Pasted profiles"
        self._invalidate_preview("Input changed. Preview again before adding anything.")

    def _invalidate_preview(self, message: str) -> None:
        self._preview_rows = None
        self._preview_result = None
        self.table.setRowCount(0)
        self.summary.setText(message)
        self.import_button.setText("Preview first")
        self.import_button.setEnabled(False)

    def choose_file(self) -> None:
        path, _chosen = QFileDialog.getOpenFileName(
            self,
            "Choose prospect data",
            "",
            "Supported data (*.csv *.xlsx *.xlsm);;CSV files (*.csv);;Excel files (*.xlsx *.xlsm)",
        )
        if path:
            self.load_file(path)

    @property
    def is_reading(self) -> bool:
        return self._reader is not None

    def load_file(self, path: str) -> None:
        """Start reading ``path`` in the background; the preview follows when it is read."""
        self._read_token += 1
        self._reader = _FileReader(self._read_token, path)
        self._reader.signals.succeeded.connect(self._file_read)
        self._reader.signals.failed.connect(self._file_failed)
        for button in (self.file_button, self.preview_button, self.import_button):
            button.setEnabled(False)
        self.summary.setText(f"Reading {Path(path).name}…")
        QThreadPool.globalInstance().start(self._reader)

    def _file_failed(self, token: int, message: str) -> None:
        if token != self._read_token:
            return  # a newer file was chosen meanwhile
        self._reader = None
        self.file_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self.summary.setText("Nothing has been checked or saved yet.")
        show_message(self, title="Import prospects", heading="This file cannot be imported.", message=message,
                     level="warning")

    def _file_read(self, token: int, path: str, rows: list[Any]) -> None:
        if token != self._read_token:
            return
        self._reader = None
        self.file_button.setEnabled(True)
        self.preview_button.setEnabled(True)
        self._file_rows = rows
        self._source = f"Import: {Path(path).name}"[:120]
        self._loading_file = True
        try:
            self.input.setPlainText("\n".join("\t".join((row.linkedin_url or "", row.full_name or "",
                                                           row.company or "", row.job_title or ""))
                                                   for row in rows))
        finally:
            self._loading_file = False
        self._invalidate_preview(f"Loaded {len(rows)} rows from {Path(path).name}. Preview before adding them.")
        self.preview()

    def preview(self) -> None:
        rows = self._file_rows if self._file_rows is not None else prospects.rows_from_text(self.input.toPlainText())
        if not rows:
            self._invalidate_preview("Paste at least one LinkedIn profile before previewing.")
            return
        ok, result = attempt(
            self,
            self.context,
            lambda db, actor: prospects.check_rows(db, actor, rows),
            title="Preview prospects",
            commit=False,
        )
        if not ok or result is None:
            return
        self._preview_rows = list(rows)
        self._preview_result = result
        self._render_preview(result)

    def _render_preview(self, result: prospects.ImportPreview) -> None:
        entries: list[tuple[int, str, str, str, str]] = []
        entries.extend((row.row, row.url, row.full_name or "", "New", "Will be added") for row in result.new)
        entries.extend(
            (
                row.row,
                row.url,
                row.full_name or "",
                "Existing",
                f"Already a prospect{f' · assigned to {row.assigned_to}' if row.assigned_to else ''}",
            )
            for row in result.existing
        )
        entries.extend((row.row, row.value, "", "Repeated", row.reason) for row in result.repeated)
        entries.extend((row.row, row.value, "", "Rejected", row.reason) for row in result.rejected)
        entries.sort(key=lambda item: item[0])

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(entries))
        for row_index, values in enumerate(entries):
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if column_index == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column_index == 3:
                    item.setData(TONE_ROLE, self._TONES[str(value)])
                self.table.setItem(row_index, column_index, item)
        fit_columns(self.table, max_width=360, min_widths={1: 260, 4: 220}, keep_columns=(0, 3))
        self.table.setUpdatesEnabled(True)

        self.summary.setText(
            f"{len(result.new)} new · {len(result.existing)} existing · "
            f"{len(result.repeated)} repeated · {len(result.rejected)} rejected"
        )
        count = len(result.new)
        self.import_button.setText(f"Add {count} new prospect{'s' if count != 1 else ''}")
        self.import_button.setEnabled(count > 0)

    def persist(self) -> None:
        rows, preview = self._preview_rows, self._preview_result
        if rows is None or preview is None or not preview.new:
            return
        ok, result = attempt(
            self,
            self.context,
            lambda db, actor: prospects.import_rows(db, actor, rows, source=self._source),
            kind="prospect",
            title="Add prospects",
        )
        if ok and result is not None:
            self.result_value = result
            self.accept()


def prospect_view(db: Session, actor: Actor, record_id: str) -> DetailView:
    """The one authoritative prospect detail (facts, ownership, bounded history), shared by every outreach screen."""
    prospect = prospects.get_prospect(db, actor, record_id)
    assignment = prospects.open_assignment(db, prospect.id)
    timeline = prospects.history(db, actor, prospect, limit=HISTORY_LIMIT)
    status = label(PROSPECT_STATUSES, prospect.status)
    assignment_status = label(ASSIGNMENT_STATUSES, assignment.status) if assignment else "Unassigned"
    history_rows = [
        [
            local_time(entry.occurred_at, actor.timezone),
            entry.kind.replace("_", " ").title(),
            entry.title,
            text(entry.actor_name) or "System",
            text(entry.detail),
        ]
        for entry in timeline
    ]
    allowed = {"open"}
    if prospects.can_edit(db, actor, prospect):
        allowed.add("edit")
    if actor.can("outreach.record") and (actor.scope("outreach.record") is Scope.ALL
                                         or prospects.works_on(actor, assignment)):
        allowed.add("record")
    if actor.can("assignments.manage") and assignment is None:
        allowed.add("assign")
    return DetailView(
        prospect.id,
        _display_name(prospect),
        " · ".join(part for part in (text(prospect.job_title), text(prospect.company)) if part),
        fields=[
            ("LinkedIn", prospect.linkedin_url),
            ("Status", status),
            ("Assigned to", person(assignment.assignee) if assignment else "Unassigned"),
            ("Assignment", assignment_status),
            ("Last activity", local_time(prospect.last_activity_at, actor.timezone) or "No activity recorded"),
            ("Follow-up", local_time(prospect.next_follow_up_at, actor.timezone) or "None scheduled"),
            ("Source", text(prospect.source) or "—"),
            ("Added", local_time(prospect.created_at, actor.timezone)),
        ],
        tabs=[DetailTab(
            "History",
            ("When", "Type", "Activity", "By", "Details"),
            history_rows,
            "No outreach, assignment, or follow-up history yet.",
        )],
        allowed=allowed,
        data={
            "version": prospect.version,
            "prospect_id": prospect.id,
            "title": _display_name(prospect),
            "linkedin_url": prospect.linkedin_url,
            "values": {
                "linkedin_url": prospect.linkedin_url,
                "full_name": prospect.full_name,
                "company": prospect.company,
                "job_title": prospect.job_title,
                "notes": prospect.notes,
            },
        },
        badges=[(status, _status_tone(prospect.status)), (assignment_status, "info" if assignment else "neutral")],
        links={"LinkedIn": "linkedin"},
        notes=text(prospect.notes),
        notice=(f"Showing the latest {HISTORY_LIMIT} history entries." if len(timeline) == HISTORY_LIMIT else ""),
        closable=True,
    )


class ProspectsPage(RecordPage):
    """Authoritative prospect list and bounded operational history."""

    title = "Prospects"
    subtitle = "LinkedIn profiles, current ownership, recent activity, and scheduled follow-ups."
    noun = "prospect"
    plural = "prospects"
    columns = (
        Column("name", "Prospect", "name", strong=True),
        Column("company", "Company", "company"),
        Column("job_title", "Job title", muted=True),
        Column("status", "Status", "status", badge=True, tone="neutral", keep=True),
        Column("assignee", "Assigned to", avatar=True),
        Column("activity", "Last activity", "activity", keep=True),
        Column("follow_up", "Follow-up", "follow_up", keep=True, alert=True),
    )
    default_sort = "-added"
    create_permission = "prospects.create"

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self.records.table.setProperty("hoverNudge", True)
        self.import_button = QPushButton("Paste or import")
        self.import_button.setObjectName("secondaryButton")
        self.import_button.setAccessibleName("Paste or import LinkedIn prospects")
        set_button_icon(self.import_button, "upload", "text")
        self.import_button.clicked.connect(self.import_records)
        self.toolbar.addWidget(self.import_button)
        self.empty_state = self.records.set_empty_state(
            "No prospects match these filters",
            "Change the filters, add one prospect, or preview a pasted list.",
            ("New prospect", self.create_record),
            icon="target",
        )

    def build_filters(self, bar: QHBoxLayout) -> None:
        self.search.setMinimumWidth(160)
        self.status_filter = self.filter_combo(
            bar,
            "Prospect status",
            list(PROSPECT_STATUSES.items()),
            everything="All statuses",
        )
        self.assignee_filter = self.filter_combo(
            bar,
            "Prospect assignee",
            [("me", "Mine"), ("none", "Unassigned")],
            everything="Any assignee",
        )
        self.follow_up_filter = self.filter_combo(
            bar,
            "Prospect follow-up",
            list(prospects.FOLLOW_UP_FILTERS.items()),
            everything="Any follow-up",
        )
        for combo in (self.status_filter, self.assignee_filter, self.follow_up_filter):
            combo.setMinimumWidth(145)

    def list_filters(self) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if self.search.text().strip():
            filters["q"] = self.search.text().strip()
        for key, combo in (("status", self.status_filter), ("assignee", self.assignee_filter),
                           ("follow_up", self.follow_up_filter)):
            if combo.currentData():
                filters[key] = combo.currentData()
        return filters

    def set_filter_values(self, values: dict[str, str]) -> None:
        for combo, key in ((self.status_filter, "status"), (self.assignee_filter, "assignee"),
                           (self.follow_up_filter, "follow_up")):
            combo.blockSignals(True)
            self.set_combo(combo, values.get(key))
            combo.blockSignals(False)

    def fetch(self, db: Session, actor: Actor, request: PageRequest, filters: dict[str, Any]) -> RowPage:
        now = utcnow()
        found = prospects.list_prospects(db, actor, page=request, now=now, **filters)

        def row(item: prospects.ProspectListRow) -> Row:
            prospect = item.prospect
            follow_up = local_time(prospect.next_follow_up_at, actor.timezone)
            overdue = prospect.next_follow_up_at is not None and prospect.next_follow_up_at < now
            return Row(
                prospect.id,
                [
                    _display_name(prospect),
                    text(prospect.company) or "—",
                    text(prospect.job_title) or "—",
                    label(PROSPECT_STATUSES, prospect.status),
                    item.assignee_name or "Unassigned",
                    local_time(prospect.last_activity_at, actor.timezone) or "No activity",
                    follow_up + (" (overdue)" if overdue else "") if follow_up else "None scheduled",
                ],
                tooltip=prospect.linkedin_url,
                colors={6: "danger"} if overdue else {},
            )

        return RowPage.build(found, row)

    def describe(self, db: Session, actor: Actor, record_id: str) -> DetailView:
        return prospect_view(db, actor, record_id)

    def build_actions(self, panel: DetailPanel) -> None:
        self.open_button = panel.add_action("Open LinkedIn", self.open_profile, primary=True, icon="arrow-right")
        self.record_button = panel.add_action("Record outcome", self.record_outcome, icon="edit")
        self.assign_button = panel.add_action("Assign…", self.assign_current, icon="assign")
        self.edit_button = panel.add_action("Edit", self.edit_current, icon="edit")

    def update_actions(self, view: DetailView | None) -> None:
        allowed = view.allowed if view else set()
        self.open_button.setEnabled("open" in allowed)
        for button, key in ((self.edit_button, "edit"), (self.record_button, "record"), (self.assign_button, "assign")):
            button.setEnabled(key in allowed)
            button.setVisible(key in allowed)

    def record_outcome(self) -> None:
        from techset_leadgen.desktop.pages.outreach_pages import record_outcome

        view = self.current_view()
        if view is None or "record" not in view.allowed:
            return
        if record_outcome(self, self.context, view.id, title=view.data["title"], can_complete=False):
            self.after_change(view.id, "Outcome recorded")

    def assign_current(self) -> None:
        from techset_leadgen.desktop.pages.assignment_pages import BatchDialog

        view = self.current_view()
        if view is None or "assign" not in view.allowed:
            return
        dialog = BatchDialog(self, self.context, preselected=[view.id])
        if dialog.exec() and dialog.result_value:
            self.after_change(view.id, "Prospect assigned")

    def update_permissions(self) -> None:
        super().update_permissions()
        allowed = self.context.can("prospects.create")
        self.import_button.setVisible(allowed)
        for button in self.empty_state.findChildren(QPushButton):
            button.setVisible(allowed)

    def create_record(self) -> None:
        if not self.context.can("prospects.create"):
            return
        record_id = create_prospect(self, self.context)
        if record_id:
            self.after_change(record_id, "Prospect added")

    def import_records(self) -> None:
        if not self.context.can("prospects.create"):
            return
        dialog = ProspectImportDialog(self, self.context)
        if dialog.exec() and dialog.result_value is not None:
            result = dialog.result_value
            record_id = result.created[0] if result.created else None
            self.after_change(record_id, f"Added {len(result.created)} prospect{'s' if len(result.created) != 1 else ''}")

    def edit_current(self) -> None:
        view = self.current_view()
        if view is None or "edit" not in view.allowed:
            return

        def submit(dialog: FormDialog) -> None:
            changes = dialog.changed()
            if not changes:
                return
            data = parse(ProspectUpdate, {**changes, "version": view.data["version"]})
            self.context.write("prospect", lambda db, actor: prospects.update_prospect(db, actor, view.id, data))

        dialog = FormDialog(
            self,
            title="Prospect",
            heading=f"Edit {view.title}",
            fields=_prospect_fields(),
            values=view.data["values"],
            submit=submit,
            submit_text="Save changes",
        )
        if dialog.exec():
            self.after_change(view.id, "Prospect saved")

    def open_link(self, key: str) -> None:
        if key == "linkedin":
            self.open_profile()

    def open_profile(self) -> None:
        view = self.current_view()
        if view is None or "open" not in view.allowed:
            return
        url = str(view.data.get("linkedin_url") or "")
        if not url:
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            self.status_requested.emit("The LinkedIn profile could not be opened in your browser.")


__all__ = ["HISTORY_LIMIT", "ProspectImportDialog", "ProspectsPage", "create_prospect"]
