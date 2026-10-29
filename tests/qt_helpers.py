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

from techset_leadgen.desktop.dialogs import MessageDialog
from techset_leadgen.desktop.modal import current_modal

ModalAction = Callable[[QWidget], None]


def wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> bool:
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
        try:
            self._timer.timeout.disconnect(self._poll)
        except (RuntimeError, TypeError):
            pass

    @property
    def message_boxes(self) -> list[SeenModal]:
        return [item for item in self.seen if item.kind in ("QMessageBox", "MessageDialog")]

    def _poll(self) -> None:
        modal = QApplication.activeModalWidget()
        embedded = current_modal()
        if embedded is not None and (modal is None or modal is embedded.window()):
            modal = embedded
        if modal is None or not modal.isVisible():
            return
        if modal.property(self._HANDLED_PROPERTY):
            return
        modal.setProperty(self._HANDLED_PROPERTY, True)
        text = modal.text() if isinstance(modal, (QMessageBox, MessageDialog)) else ""
        self.seen.append(SeenModal(type(modal).__name__, modal.windowTitle(), text))
        if isinstance(modal, QProgressDialog):
            return
        action = self.actions.pop(0) if self.actions else reject
        QTimer.singleShot(0, lambda: action(modal))


def reject(widget: QWidget) -> None:
    if isinstance(widget, QDialog):
        widget.reject()
    else:
        widget.close()


def click_button(label: str) -> ModalAction:
    def action(widget: QWidget) -> None:
        for button in widget.findChildren(QAbstractButton):
            if button.text().replace("&", "") == label and button.isVisible():
                button.click()
                return
        reject(widget)
        raise AssertionError(f"No button labelled {label!r} in {widget.windowTitle()!r}")

    return action


def choose_file(path: str | Path) -> ModalAction:
    def action(widget: QWidget) -> None:
        assert isinstance(widget, QFileDialog), type(widget)
        editor = widget.findChild(QLineEdit, "fileNameEdit")
        assert editor is not None, "Expected Qt's widget-based file dialog"
        editor.setText(str(path))
        editor.returnPressed.emit()

    return action


TEST_ADMIN_EMAIL = "test.admin@techset.example"
TEST_PASSWORD = "correct horse battery staple"


def sign_in_window(window) -> None:
    if window.auth_stack.currentWidget() is window.setup_page:
        page = window.setup_page
        page.organization.setText("Techset Solutions")
        page.name.setText("Test Admin")
        page.email.setText(TEST_ADMIN_EMAIL)
        page.password.setText(TEST_PASSWORD)
        page.confirm.setText(TEST_PASSWORD)
        assert page.submit(), page.error.text()
    else:
        page = window.sign_in_page
        page.email.setText(TEST_ADMIN_EMAIL)
        page.password.setText(TEST_PASSWORD)
        assert page.submit(), page.error.text()
    assert window.context.is_signed_in


def signed_in_context(database: Path):
    from techset_leadgen.config import load_settings
    from techset_leadgen.desktop.session import AppContext

    context = AppContext(load_settings({}, database_path=database))
    context.open()
    context.create_organization(organization_name="Techset Solutions", admin_name="Test Admin",
                                email=TEST_ADMIN_EMAIL, password=TEST_PASSWORD)
    return context

