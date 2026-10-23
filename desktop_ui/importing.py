"""Qt-native import picker, schema preview, and worker-signal bridge."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QProgressDialog,
    QVBoxLayout,
    QWidget,
)

from controllers.file_import_controller import FileImportController
from core.importer import inspect_import_file

from .dialogs import show_message
from .modal import ModalDialog, embed

logger = logging.getLogger(__name__)


class _InspectionSignals(QObject):
    """Signals owned by a runnable so results return to Qt's UI thread."""

    succeeded = Signal(int, str, object)
    failed = Signal(int, str)
    finished = Signal(int)


class _InspectionWorker(QRunnable):
    """Inspect a potentially large spreadsheet without blocking the event loop."""

    def __init__(self, token: int, file_path: str) -> None:
        super().__init__()
        self.token = token
        self.file_path = file_path
        self.signals = _InspectionSignals()

    @Slot()
    def run(self) -> None:
        try:
            inspection = inspect_import_file(self.file_path)
        except Exception as exc:
            logger.exception("Could not inspect import file %s", self.file_path)
            self.signals.failed.emit(self.token, str(exc))
        else:
            self.signals.succeeded.emit(self.token, self.file_path, inspection)
        finally:
            self.signals.finished.emit(self.token)


class ImportPreviewDialog(ModalDialog):
    """Read-only confirmation dialog for a detected import schema."""

    def __init__(self, file_path: str, inspection: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import preview")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setAccessibleName("Import file preview")

        root = QVBoxLayout(self)
        title = QLabel("Review before importing")
        title.setObjectName("dialogTitle")
        description = QLabel(
            "Techset LeadGen detected the file structure below. No data has been written yet."
        )
        description.setObjectName("dialogSubtitle")
        description.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(description)

        form = QFormLayout()
        file_label = QLabel(Path(file_path).name)
        file_label.setTextFormat(Qt.TextFormat.PlainText)  # file names are user data
        form.addRow("File", file_label)
        detected = str(inspection.get("detected_type", "invalid")).replace("_", " ").title()
        form.addRow("Detected type", QLabel(detected))
        form.addRow("Data rows", QLabel(str(inspection.get("row_count", 0))))
        root.addLayout(form)

        columns = QPlainTextEdit()
        columns.setReadOnly(True)
        columns.setMaximumHeight(100)
        columns.setPlainText(", ".join(str(item) for item in inspection.get("headers", [])))
        columns.setAccessibleName("Detected columns")
        root.addWidget(QLabel("Columns"))
        root.addWidget(columns)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import data")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


class ImportCoordinator(QObject):
    """Keep the existing import engine while safely crossing into Qt's UI thread."""

    started = Signal()
    succeeded = Signal(str)
    failed = Signal(str)
    dataset_changed = Signal()
    _worker_succeeded = Signal(str)
    _worker_failed = Signal(str)
    _worker_started = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker_started.connect(self._on_started)
        self._worker_succeeded.connect(self._on_succeeded)
        self._worker_failed.connect(self._on_failed)
        self.controller = FileImportController(
            on_success=self._worker_succeeded.emit,
            on_error=self._worker_failed.emit,
            on_start=self._worker_started.emit,
        )
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(1)
        self._inspection_token = 0
        self._inspection_running = False
        self._inspection_cancelled = False
        self._progress: QProgressDialog | None = None
        self._inspection_worker: _InspectionWorker | None = None

    @property
    def is_busy(self) -> bool:
        """Return whether file inspection or a database import is in progress."""
        return self._inspection_running or self.controller.is_running

    def select_and_import(self, parent: QWidget | None = None) -> bool:
        path, _selected_filter = QFileDialog.getOpenFileName(
            parent,
            "Import sales, leads, or marketing data",
            "",
            "Supported data (*.csv *.xlsx *.xlsm);;CSV files (*.csv);;Excel files (*.xlsx *.xlsm)",
        )
        if not path:
            return False

        if self.is_busy:
            self.failed.emit("An import is already running. Wait for it to finish.")
            return False

        self._inspection_token += 1
        token = self._inspection_token
        self._inspection_running = True
        self._inspection_cancelled = False
        progress = QProgressDialog(
            "Inspecting the selected file…",
            "Cancel",
            0,
            0,
            parent,
        )
        progress.setWindowTitle("Preparing import")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumWidth(380)
        progress.canceled.connect(lambda: self._cancel_inspection(token))
        self._progress = progress
        embed(progress)  # a card centred in the window, like the other dialogs
        progress.show()

        worker = _InspectionWorker(token, path)
        worker.signals.succeeded.connect(self._on_inspection_succeeded)
        worker.signals.failed.connect(self._on_inspection_failed)
        worker.signals.finished.connect(self._on_inspection_finished)
        self._inspection_worker = worker
        self._thread_pool.start(worker)
        return True

    @Slot(int, str, object)
    def _on_inspection_succeeded(
        self,
        token: int,
        path: str,
        inspection: object,
    ) -> None:
        if token != self._inspection_token or self._inspection_cancelled:
            return
        self._close_progress()
        if not isinstance(inspection, dict):
            self.failed.emit("The import inspector returned an invalid result.")
            return
        if not inspection.get("valid"):
            owner = self.parent()
            dialog_parent = owner if isinstance(owner, QWidget) else None
            if not inspection.get("headers"):
                # Unreadable file: the inspector reports the read error itself.
                problem = next(iter(inspection.get("missing_sales") or []), "The file has no column headers.")
                show_message(
                    dialog_parent,
                    title="Unsupported import file",
                    heading="This file can't be read",
                    message=f"{problem}\n\nSave it as CSV or Excel (.xlsx) and try again.",
                    level="warning",
                )
                return
            details = []
            for key, label in (
                ("missing_sales", "Sales"),
                ("missing_leads", "Leads"),
                ("missing_marketing_spend", "Marketing spend"),
            ):
                missing = inspection.get(key) or []
                if missing:
                    details.append(f"• {label}: {', '.join(map(str, missing))}")
            show_message(
                dialog_parent,
                title="Unsupported import file",
                heading="This file doesn't match a supported import format",
                message=(
                    "Columns missing for each import type:\n" + "\n".join(details)
                    + "\n\nDownload a template from the Dashboard to see the expected columns."
                ),
                level="warning",
            )
            return

        owner = self.parent()
        dialog_parent = owner if isinstance(owner, QWidget) else None
        if ImportPreviewDialog(path, inspection, dialog_parent).exec() != QDialog.DialogCode.Accepted:
            return

        detected_type = inspection.get("detected_type")
        if detected_type == "sales":
            self.controller.import_sales(path)
        elif detected_type == "leads":
            self.controller.import_leads(path)
        elif detected_type == "mixed":
            self.controller.import_both(path)
        elif detected_type == "marketing_spend":
            self.controller.import_marketing_spend(path)
        else:
            self.failed.emit("Unsupported import type")
            return

    @Slot(int, str)
    def _on_inspection_failed(self, token: int, message: str) -> None:
        if token != self._inspection_token or self._inspection_cancelled:
            return
        self._close_progress()
        self.failed.emit(f"Could not inspect the selected file: {message}")

    @Slot(int)
    def _on_inspection_finished(self, token: int) -> None:
        if token != self._inspection_token:
            return
        self._inspection_running = False
        self._inspection_worker = None
        self._close_progress()

    def _cancel_inspection(self, token: int) -> None:
        if token != self._inspection_token:
            return
        self._inspection_cancelled = True
        self._close_progress()

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.blockSignals(True)
            self._progress.close()
            self._progress.deleteLater()
            self._progress = None

    def shutdown(self, timeout_ms: int = 3000) -> bool:
        """Drain inspection workers when the shell closes cleanly."""
        self._inspection_cancelled = True
        self._close_progress()
        inspections_done = self._thread_pool.waitForDone(timeout_ms)
        imports_done = self.controller.wait_for_completion(timeout_ms / 1000)
        return inspections_done and imports_done

    @Slot()
    def _on_started(self) -> None:
        self.started.emit()

    @Slot(str)
    def _on_succeeded(self, message: str) -> None:
        self.succeeded.emit(message)
        self.dataset_changed.emit()

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.failed.emit(message)
