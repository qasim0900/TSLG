"""Helpers for driving real Qt modal dialogs from headless GUI tests.

Application code opens ``QMessageBox``, ``QFileDialog`` and custom ``QDialog``
instances with ``exec()``, which runs a nested event loop. ``ModalPilot`` polls
for the active modal widget from inside that loop, records what the user would
have seen, and answers it with a scripted action. Tests therefore exercise the
production dialogs instead of monkeypatching them away.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDialog,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QWidget,
)

from desktop_ui.dialogs import MessageDialog

ModalAction = Callable[[QWidget], None]


def wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> bool:
    """Process events until ``predicate`` holds (PySide6's QTest has no qWaitFor).

    Sleeps with ``time.sleep`` rather than ``QTest.qWait``: qWait keeps the GIL,
    which starved the Python import worker thread (a 0.4 s import never
    finished in 60 s), so tests of background work would time out.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return predicate()


@dataclass(frozen=True)
class SeenModal:
    kind: str
    title: str
    text: str


class ModalPilot:
    """Answer modal dialogs in FIFO order and remember each one shown.

    Dialogs without a scripted action are rejected, so an unexpected modal can
    never hang a headless test run.
    """

    _HANDLED_PROPERTY = "_modalPilotHandled"

    def __init__(self, *actions: ModalAction) -> None:
        self.actions: list[ModalAction] = list(actions)
        self.seen: list[SeenModal] = []
        self._timer = QTimer()
        self._timer.setInterval(15)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def __enter__(self) -> ModalPilot:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def stop(self) -> None:
        self._timer.stop()
        # The connection references self._poll; drop it so the pilot (and
        # anything it touched) can be freed instead of living until exit.
        try:
            self._timer.timeout.disconnect(self._poll)
        except (RuntimeError, TypeError):
            pass

    @property
    def message_boxes(self) -> list[SeenModal]:
        return [item for item in self.seen if item.kind in ("QMessageBox", "MessageDialog")]

    def _poll(self) -> None:
        modal = QApplication.activeModalWidget()
        if modal is None or not modal.isVisible():
            return
        # Mark the dialog itself rather than keeping a Python reference to it:
        # after exec() PySide hands a parented dialog's ownership to Python,
        # so a retained wrapper leaves it owned twice and can crash at exit.
        if modal.property(self._HANDLED_PROPERTY):
            return
        modal.setProperty(self._HANDLED_PROPERTY, True)
        text = modal.text() if isinstance(modal, (QMessageBox, MessageDialog)) else ""
        self.seen.append(SeenModal(type(modal).__name__, modal.windowTitle(), text))
        if isinstance(modal, QProgressDialog):
            # Transient busy indicator: observe it, but let the workflow close it.
            return
        action = self.actions.pop(0) if self.actions else reject
        QTimer.singleShot(0, lambda: action(modal))


def reject(widget: QWidget) -> None:
    if isinstance(widget, QDialog):
        widget.reject()
    else:
        widget.close()


def click_button(label: str) -> ModalAction:
    """Click the visible dialog button whose text matches ``label``."""

    def action(widget: QWidget) -> None:
        for button in widget.findChildren(QAbstractButton):
            if button.text().replace("&", "") == label and button.isVisible():
                button.click()
                return
        reject(widget)
        raise AssertionError(f"No button labelled {label!r} in {widget.windowTitle()!r}")

    return action


def choose_file(path: str | Path) -> ModalAction:
    """Type ``path`` into a Qt file dialog and press Return, as a user would.

    ``QFileDialog.selectFile()`` + ``accept()`` is unreliable here because the
    widget-based dialog validates against an asynchronously populated model.
    """

    def action(widget: QWidget) -> None:
        assert isinstance(widget, QFileDialog), type(widget)
        editor = widget.findChild(QLineEdit, "fileNameEdit")
        assert editor is not None, "Expected Qt's widget-based file dialog"
        editor.setText(str(path))
        editor.returnPressed.emit()

    return action
