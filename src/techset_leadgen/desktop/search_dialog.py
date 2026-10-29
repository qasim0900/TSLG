from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from techset_leadgen.desktop.modal import ModalDialog
from techset_leadgen.desktop.tables import fit_columns
from techset_leadgen.desktop.widgets import set_table_defaults

_KINDS = {"prospects": "Prospect", "clients": "Client", "contacts": "Contact", "leads": "Lead"}


class SearchDialog(ModalDialog):
    def __init__(self, parent: QWidget | None, results: list[tuple[str, str, str, str]], query: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Search")
        self.setModal(True)
        self.setMinimumSize(640, 420)
        self.chosen: tuple[str, str] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        heading = QLabel(f"{len(results)} result{'s' if len(results) != 1 else ''} for “{query}”")
        heading.setObjectName("dialogHeading")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(heading)
        self.table = QTableWidget(len(results), 3)
        self.table.setHorizontalHeaderLabels(["Type", "Name", "Details"])
        self.table.setAccessibleName("Search results")
        set_table_defaults(self.table, empty_text=(
            "Nothing found. Search matches prospect names, companies, job titles and LinkedIn addresses, "
            "plus the legacy records your role may view."))
        for row, (kind, record_id, name, details) in enumerate(results):
            kind_item = QTableWidgetItem(_KINDS.get(kind, kind))
            destination = kind if kind in {"prospects", "leads"} else "clients"
            kind_item.setData(Qt.ItemDataRole.UserRole, (destination, record_id))
            self.table.setItem(row, 0, kind_item)
            self.table.setItem(row, 1, QTableWidgetItem(name))
            details_item = QTableWidgetItem(details)
            details_item.setToolTip(details)
            self.table.setItem(row, 2, details_item)
        fit_columns(self.table)
        self.table.itemActivated.connect(self._item_activated)
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox()
        open_button = QPushButton("Open")
        open_button.setObjectName("primaryButton")
        open_button.clicked.connect(self._open_current)
        open_button.setEnabled(bool(results))
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addButton(open_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(close, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)
        if results:
            self.table.selectRow(0)
            self.table.setFocus()

    def _item_activated(self, item: QTableWidgetItem) -> None:
        self.open_row(item.row())

    def _open_current(self) -> None:
        self.open_row(self.table.currentRow())

    def open_row(self, row: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        self.chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()


__all__ = ["SearchDialog"]

