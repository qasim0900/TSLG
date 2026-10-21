"""Small reusable, accessible Qt widgets for the branded desktop UI."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .theme import ERROR, PRIMARY, SECONDARY

# Dedicated role for sort keys; pages already use UserRole for record IDs.
SORT_ROLE = Qt.ItemDataRole.UserRole + 64


class SortableItem(QTableWidgetItem):
    """Table item that sorts by its raw key, e.g. ``1500.0`` rather than "€1,500.00".

    ``QTableWidgetItem`` compares display text, so "106" sorts before "60" and
    "€9,000" after "€10,000". Items without a key fall back to text order.
    """

    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(SORT_ROLE)
        right = other.data(SORT_ROLE)
        if left is not None and right is not None:
            try:
                return bool(left < right)
            except TypeError:
                pass
        # Not super().__lt__(): PySide routes that call back into this override.
        return self.text() < other.text()


def labeled_field(label_text: str, editor: QWidget) -> QWidget:
    """Stack a visible label above ``editor`` and make it the label's buddy."""
    field = QWidget()
    layout = QVBoxLayout(field)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    label = QLabel(label_text)
    label.setObjectName("fieldLabel")
    label.setBuddy(editor)
    layout.addWidget(label)
    layout.addWidget(editor)
    return field


def sortable_item(text: str, sort_key: Any = None) -> QTableWidgetItem:
    """Return a numeric-aware item, or a plain (natively sorted) item for text."""
    if sort_key is None:
        return QTableWidgetItem(text)
    item = SortableItem(text)
    item.setData(SORT_ROLE, sort_key)
    return item


@contextmanager
def bulk_table_update(table: QTableWidget, *, stretch_column: int, fixed_columns: dict[int, int] | None = None,
                      min_widths: dict[int, int] | None = None) -> Iterator[None]:
    """Fill ``table`` in linear time, then size and sort it once.

    With ``ResizeToContents`` sections, every ``setItem`` on a visible table
    re-measures the whole column, making a refresh quadratic in the row count
    (400 clients took 0.4 s, 200 rows with a Python delegate took 11 s).
    """
    header = table.horizontalHeader()
    table.setSortingEnabled(False)
    table.setUpdatesEnabled(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    try:
        yield
    finally:
        from .tables import fit_columns  # columns sized once, capped, and still resizable by the user

        fit_columns(table, stretch_column=stretch_column, fixed_columns=fixed_columns, min_widths=min_widths)
        table.setSortingEnabled(True)
        table.setUpdatesEnabled(True)


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        heading.setAccessibleName(title)
        copy = QLabel(subtitle)
        copy.setObjectName("pageSubtitle")
        copy.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(copy)


class KpiCard(Card):
    def __init__(
        self,
        title: str,
        value: str = "—",
        detail: str = "",
        accent: str = PRIMARY,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        semantic_accent = {
            PRIMARY.lower(): "green",
            SECONDARY.lower(): "gold",
            ERROR.lower(): "red",
            "green": "green",
            "gold": "gold",
            "red": "red",
            "blue": "blue",
        }.get(accent.lower(), "green")
        self.setProperty("accent", semantic_accent)
        self.setProperty("compact", compact)
        self.setMinimumHeight(90 if compact else 110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(16, 12, 16, 12) if compact else (18, 14, 18, 14))
        layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricLabel")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("metricNote")
        self.detail_label.setWordWrap(True)
        self.detail_label.setVisible(bool(detail))
        # Compatibility aliases keep existing page/test integrations stable as
        # their former private KPI widgets are consolidated onto this one.
        self.label = self.title_label
        self.value = self.value_label
        self.note = self.detail_label
        self._title = self.title_label
        self._value = self.value_label
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)
        self.set_value(value, detail)

    def set_value(self, value: str, detail: str = "") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        self.detail_label.setVisible(bool(detail))
        description = f"{self.title_label.text()}: {value}"
        if detail:
            description += f". {detail}"
        self.setAccessibleDescription(description)
        self.setToolTip(detail)

    def set_metric(self, value: str, note: str = "") -> None:
        """Update a metric using the API retained from the Sales KPI widget."""
        self.set_value(value, note)


class EmptyState(Card):
    def __init__(self, title: str, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        body = QLabel(message)
        body.setObjectName("pageSubtitle")
        body.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(body)


def set_table_defaults(table: QTableWidget, **options: Any) -> None:
    """The shared table style (see ``desktop_ui.tables.prepare_table``) with content-sized columns."""
    from .tables import prepare_table

    prepare_table(table, **options)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
