"""Role-aware operational dashboard for the LinkedIn outreach workflow."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from techset_leadgen.services import team

from techset_leadgen.desktop.icons import set_button_icon
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.desktop.support import report
from techset_leadgen.desktop.theme import ERROR, PRIMARY, SECONDARY
from techset_leadgen.desktop.widgets import KpiCard, PageHeader, SectionCard, bulk_table_update, set_table_defaults


class OperationalDashboardPage(QWidget):
    """Actionable counts for a manager or the signed-in contributor."""

    status_requested = Signal(str, str)

    def __init__(self, context: AppContext, *, on_navigate: Callable[..., object] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._on_navigate = on_navigate
        self._columns = 0
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("pageScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setAccessibleName("Scrollable outreach dashboard")
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("pageBody")
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(28, 24, 28, 40)
        self.body_layout.setSpacing(20)
        scroll.setWidget(body)

        actor = self.context.actor
        manager = actor is not None and actor.can("team.view")
        subtitle = ("Team assignments, follow-ups and deadlines—calculated from recorded work."
                    if manager else "Your assignments, follow-ups and deadlines for today.")
        self.header = PageHeader("Dashboard", subtitle)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondaryButton")
        refresh.setAccessibleName("Refresh operational dashboard")
        set_button_icon(refresh, "refresh")
        refresh.clicked.connect(self.refresh)
        self.header.add_action(refresh)
        self.body_layout.addWidget(self.header)

        definitions: tuple[tuple[str, str, str, str, str], ...] = (
            ("active_members", "Active members", "people", PRIMARY, "users"),
            ("assigned_today", "Profiles assigned today", "assignments", PRIMARY, "assignments"),
            ("completed_today", "Assignments completed today", "check-circle", PRIMARY, "assignments"),
            ("outstanding_assignments", "Outstanding assignments", "my_work", SECONDARY, "my_work"),
            ("pending_follow_ups", "Pending follow-ups", "followups", SECONDARY, "followups"),
            ("overdue_follow_ups", "Overdue follow-ups", "alert", ERROR, "followups"),
            ("overdue_tasks", "Overdue tasks", "tasks", ERROR, "tasks"),
            ("unassigned_prospects", "Prospects not assigned", "prospects", SECONDARY, "prospects"),
        )
        if not manager:
            definitions = tuple(item for item in definitions if item[0] not in {"active_members",
                                                                                "unassigned_prospects"})
            definitions += (("due_today_follow_ups", "Follow-ups due today", "clock", SECONDARY, "followups"),)
        self.cards: dict[str, KpiCard] = {}
        self.targets: dict[str, str] = {}
        self.kpi_grid = QGridLayout()
        self.kpi_grid.setHorizontalSpacing(16)
        self.kpi_grid.setVerticalSpacing(16)
        for key, title, icon, accent, target in definitions:
            card = KpiCard(title, "—", accent=accent, icon=icon, clickable=True)
            card.clicked.connect(lambda destination=target: self._navigate(destination))
            self.cards[key] = card
            self.targets[key] = target
        self.body_layout.addLayout(self.kpi_grid)
        self._place_cards(4)

        quick = SectionCard("Start work", "The common outreach actions, one click away.", divider=False)
        quick_row = QHBoxLayout()
        quick_row.setSpacing(10)
        for text, destination, primary in (
            ("Open my work", "my_work", True),
            ("Review follow-ups", "followups", False),
            ("Browse prospects", "prospects", False),
        ):
            button = QPushButton(text)
            button.setObjectName("primaryButton" if primary else "secondaryButton")
            button.clicked.connect(lambda _checked=False, target=destination: self._navigate(target))
            quick_row.addWidget(button)
        quick_row.addStretch(1)
        quick.body.addLayout(quick_row)
        self.body_layout.addWidget(quick)

        self.workload_card = SectionCard(
            "Team workload", "Open assignments, today's completions and overdue follow-ups per active member.",
            padded=False,
        )
        self.workload_table = QTableWidget(0, 4)
        self.workload_table.setHorizontalHeaderLabels(
            ["Member", "Open assignments", "Completed today", "Overdue follow-ups"])
        self.workload_table.setAccessibleName("Team workload")
        set_table_defaults(self.workload_table, empty_text="No active team workload yet.")
        self.workload_card.body.addWidget(self.workload_table)
        self.workload_card.setVisible(manager)
        self.body_layout.addWidget(self.workload_card)
        self.timezone_label = QLabel()
        self.timezone_label.setObjectName("pageSubtitle")
        self.timezone_label.setTextFormat(Qt.TextFormat.PlainText)
        self.body_layout.addWidget(self.timezone_label)
        self.body_layout.addStretch(1)

    def _place_cards(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        for card in self.cards.values():
            self.kpi_grid.removeWidget(card)
        for index, card in enumerate(self.cards.values()):
            self.kpi_grid.addWidget(card, index // columns, index % columns)
        for column in range(4):  # a column left over from a wider layout must not keep its share
            self.kpi_grid.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._place_cards(4 if event.size().width() >= 1120 else 2 if event.size().width() >= 650 else 1)

    def _navigate(self, target: str) -> None:
        if self._on_navigate is not None:
            self._on_navigate(target)

    def refresh(self) -> None:
        if not self.context.is_signed_in:
            return
        try:
            snapshot = self.context.run(lambda db, actor: team.summary(db, actor), busy=False)
        except Exception as exc:
            report(self, exc, title="Dashboard")
            return
        details = {
            "assigned_today": f"Business day in {snapshot.timezone}",
            "completed_today": "Completion timestamp today",
            "outstanding_assignments": "Assigned or in progress",
            "pending_follow_ups": "Open scheduled obligations",
            "overdue_follow_ups": "Still open after their due time",
            "due_today_follow_ups": f"Due today in {snapshot.timezone}",
            "overdue_tasks": "General tasks past their due time",
            "active_members": "Active application accounts",
            "unassigned_prospects": "No planned or active owner",
        }
        for key, card in self.cards.items():
            card.set_value(str(getattr(snapshot, key)), details.get(key, ""))
        with bulk_table_update(self.workload_table, stretch_column=0,
                               fixed_columns={1: 150, 2: 150, 3: 160}):
            self.workload_table.setRowCount(len(snapshot.workload))
            for row, item in enumerate(snapshot.workload):
                values = (item.name, str(item.open_assignments), str(item.completed_today),
                          str(item.overdue_follow_ups))
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if column:
                        cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.workload_table.setItem(row, column, cell)
        self.timezone_label.setText(
            f"Today is calculated in {snapshot.timezone}. Outcomes are counted only when a user records them.")


__all__ = ["OperationalDashboardPage"]
