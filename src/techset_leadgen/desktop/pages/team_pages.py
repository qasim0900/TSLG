from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from techset_leadgen.services import notifications, team
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import PageRequest

from techset_leadgen.desktop.icons import set_button_icon
from techset_leadgen.desktop.records import Column, DetailPanel, DetailView, RecordPage, Row, RowPage
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.desktop.support import attempt, date_text, local_time, text
from techset_leadgen.desktop.widgets import PageHeader, SectionCard, bulk_table_update, set_table_defaults


class TeamPage(QWidget):
    status_requested = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.summary: team.DailySummary | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(20)
        self.header = PageHeader("Team performance",
                                 "Assignments, recorded outcomes, and follow-ups per person for one business day.")
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("dd MMM yyyy")
        self.day.setAccessibleName("Business day")
        self.day.dateChanged.connect(lambda _day: self.refresh())
        self.header.add_action(self.day)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondaryButton")
        set_button_icon(refresh, "refresh", "text")
        refresh.clicked.connect(self.refresh)
        self.header.add_action(refresh)
        self.export_button = QPushButton("Export CSV…")
        self.export_button.setObjectName("secondaryButton")
        set_button_icon(self.export_button, "download", "text")
        self.export_button.clicked.connect(self.export)
        self.header.add_action(self.export_button)
        root.addWidget(self.header)

        card = SectionCard("End-of-day summary", "", padded=False)
        labels = ["Team member", *(team.COLUMN_LABELS[name] for name in team.COUNT_FIELDS)]
        self.table = QTableWidget(0, len(labels))
        self.table.setHorizontalHeaderLabels(labels)
        self.table.setAccessibleName("End-of-day summary per team member")
        set_table_defaults(self.table, numeric_columns=list(range(1, len(labels))),
                           empty_text="No team members to summarise.")
        card.body.addWidget(self.table)
        root.addWidget(card, 1)
        self.note = QLabel()
        self.note.setObjectName("pageSubtitle")
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        self._loaded = False

    def _chosen_day(self) -> date:
        return cast(date, self.day.date().toPython())

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.refresh()

    def refresh(self) -> None:
        self.export_button.setVisible(self.context.can("data.export"))
        day = self._chosen_day()
        ok, summary = attempt(self, self.context, lambda db, actor: team.daily_summary(db, actor, day),
                              commit=False, title="Team performance")
        if not ok or summary is None:
            return
        self._loaded = True
        self.summary = summary
        rows = [*summary.rows, summary.totals] if summary.rows else []
        longest = max((self.table.fontMetrics().horizontalAdvance(row.name) for row in rows), default=0)
        with bulk_table_update(self.table, stretch_column=0, sortable=False,
                               fixed_columns={0: max(longest + 48, 160)}):
            self.table.setRowCount(len(rows))
            for index, row in enumerate(rows):
                values = [row.name, *(str(getattr(row, name)) for name in team.COUNT_FIELDS)]
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if column:
                        cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if row is rows[-1] and len(rows) > 1:
                        font = QFont(cell.font())
                        font.setBold(True)
                        cell.setFont(font)
                    self.table.setItem(index, column, cell)
        self.note.setText(
            f"Business day {date_text(summary.day.isoformat())} in {summary.timezone}. Outcomes count only when someone "
            "recorded them; open assignments, open tasks, and overdue follow-ups are as of now.")

    def export(self) -> None:
        if not self.context.can("data.export"):
            return
        day = self._chosen_day()
        path, _ = QFileDialog.getSaveFileName(self, "Export end-of-day summary",
                                              f"team-summary-{day.isoformat()}.csv", "CSV files (*.csv)")
        if not path:
            return
        ok, result = attempt(self, self.context, lambda db, actor: team.export_daily_summary(db, actor, day),
                             title="Export")
        if not ok or result is None:
            return
        try:
            Path(path).write_text(result[1], encoding="utf-8-sig")
        except OSError as exc:
            self.status_requested.emit(f"The file could not be saved: {exc.strerror or exc}")
            return
        self.status_requested.emit(f"Summary exported to {Path(path).name}")


_TARGETS = {"prospect_assignment": "my_work", "task": "followups", "meeting": "meetings"}


class NotificationsPage(RecordPage):
    title = "Notifications"
    subtitle = "Profiles assigned or reassigned to you, follow-ups scheduled for you, and completed work."
    noun = "notification"
    plural = "notifications"
    columns = (
        Column("title", "Notification", strong=True),
        Column("body", "Details", muted=True),
        Column("when", "When", "created", keep=True),
        Column("state", "Status", badge=True, keep=True, tone="info"),
    )
    default_sort = "-created"

    def __init__(self, context: AppContext, *, on_navigate: Callable[..., Any] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self._on_navigate = on_navigate
        self.read_all_button = QPushButton("Mark all read")
        self.read_all_button.setObjectName("secondaryButton")
        set_button_icon(self.read_all_button, "check", "text")
        self.read_all_button.clicked.connect(self.mark_all_read)
        self.toolbar.addWidget(self.read_all_button)
        self.search.hide()
        self.records.set_empty_state("No notifications", "You are notified when someone gives you work.",
                                     icon="notifications")

    def build_filters(self, bar: QHBoxLayout) -> None:
        self.unread_filter = self.filter_combo(bar, "Show", [("unread", "Unread only")], everything="All")

    def list_filters(self) -> dict[str, Any]:
        return {"unread": True} if self.unread_filter.currentData() else {}

    def fetch(self, db: Session, actor: Actor, request: PageRequest, filters: dict[str, Any]) -> RowPage:
        found = notifications.list_notifications(db, actor, page=request, **filters)
        return RowPage.build(found, lambda item: Row(str(item.id), [
            item.title, text(item.body) or "—", local_time(item.created_at, actor.timezone),
            "Unread" if item.read_at is None else "Read"], emphasis="" if item.read_at is None else "muted"))

    def describe(self, db: Session, actor: Actor, record_id: str) -> DetailView:
        item = notifications.get_notification(db, actor, int(record_id))
        allowed = {"read"} if item.read_at is None else set()
        if item.entity_type in _TARGETS and item.entity_id:
            allowed.add("open")
        return DetailView(str(item.id), item.title, local_time(item.created_at, actor.timezone),
                          fields=[("Details", text(item.body) or "—"),
                                  ("Status", "Unread" if item.read_at is None else
                                   f"Read {local_time(item.read_at, actor.timezone)}")],
                          allowed=allowed, data={"entity_type": item.entity_type, "entity_id": item.entity_id,
                                                        "kind": item.kind},
                          closable=True)

    def build_actions(self, panel: DetailPanel) -> None:
        self.open_button = panel.add_action("Open", self.open_related, primary=True, icon="arrow-right")
        self.read_button = panel.add_action("Mark read", self.mark_read, icon="check")

    def update_actions(self, view: DetailView | None) -> None:
        allowed = view.allowed if view else set()
        self.open_button.setEnabled("open" in allowed)
        self.read_button.setEnabled("read" in allowed)

    def edit_current(self) -> None:
        self.open_related()

    def mark_read(self) -> None:
        view = self.current_view()
        if view is None or "read" not in view.allowed:
            return
        ok, _ = attempt(self, self.context, lambda db, actor: notifications.mark_read(db, actor, [int(view.id)]),
                        kind="notification", title="Notifications")
        if ok:
            self.after_change(view.id, "Marked as read")

    def mark_all_read(self) -> None:
        ok, count = attempt(self, self.context, lambda db, actor: notifications.mark_read(db, actor),
                            kind="notification", title="Notifications")
        if ok:
            self.after_change(None, f"{count or 0} notification{'s' if count != 1 else ''} marked as read")

    def open_related(self) -> None:
        view = self.current_view()
        if view is None or "open" not in view.allowed or self._on_navigate is None:
            return
        if "read" in view.allowed:
            attempt(self, self.context, lambda db, actor: notifications.mark_read(db, actor, [int(view.id)]),
                    kind="notification", title="Notifications")
        target = _TARGETS[str(view.data["entity_type"])]
        record_id = str(view.data["entity_id"])
        if target == "my_work" and (view.data["kind"] == "assignment_completed"
                                    or not self.context.can("outreach.record")):
            target = "assignments"
        page = self._on_navigate(target)
        if isinstance(page, RecordPage):
            page.show_record(record_id)


__all__ = ["NotificationsPage", "TeamPage"]

