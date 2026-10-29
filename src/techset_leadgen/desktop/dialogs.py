from __future__ import annotations

import re
from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from techset_leadgen.desktop.icons import set_button_icon
from techset_leadgen.desktop.modal import ModalDialog
from techset_leadgen.desktop.widgets import IconChip

Level = Literal["info", "question", "warning", "error", "danger"]

_BADGE_SIZE = 44
_MIN_WIDTH = 440
_MAX_TEXT_WIDTH = 400
_BODY_MARGINS = (24, 24, 24, 22)

_BADGES: dict[str, tuple[str, str]] = {
    "info": ("info", "info"),
    "question": ("info", "info"),
    "warning": ("warning", "gold"),
    "error": ("alert", "danger"),
    "danger": ("warning", "danger"),
}
_LEVEL_NAMES = {
    "info": "Information",
    "question": "Question",
    "warning": "Warning",
    "error": "Error",
    "danger": "Warning",
}


class MessageDialog(ModalDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        heading: str,
        message: str = "",
        level: Level = "info",
        confirm_text: str | None = None,
        cancel_text: str = "Cancel",
        destructive: bool = False,
        icon: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("messageDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setAccessibleName(heading)
        self.setAccessibleDescription(message)
        self._heading = heading
        self._message = message

        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._body = QWidget()
        body = QHBoxLayout(self._body)
        body.setContentsMargins(*_BODY_MARGINS)
        body.setSpacing(16)
        root.addWidget(self._body, 1)
        glyph, tone = _BADGES[level]
        badge = IconChip(icon or glyph, tone, size=_BADGE_SIZE, icon_size=20)
        badge.setAccessibleName(_LEVEL_NAMES[level])
        body.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        text_column = QVBoxLayout()
        body.addLayout(text_column, 1)
        text_column.setSpacing(6)
        self.heading_label = self._text_label(heading, "dialogTitle")
        self.message_label = self._text_label(message, "dialogSubtitle")
        text_column.addWidget(self.heading_label)
        text_column.addWidget(self.message_label)
        text_column.addStretch(1)
        if not message:
            self.message_label.hide()

        self.footer = QFrame()
        self.footer.setObjectName("modalFooter")
        buttons = QHBoxLayout(self.footer)
        buttons.setContentsMargins(24, 14, 24, 14)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        root.addWidget(self.footer)
        self.cancel_button: QPushButton | None = None
        if confirm_text:
            self.cancel_button = self._add_button(buttons, cancel_text, "secondaryButton")
            self.cancel_button.clicked.connect(self.reject)
            self.confirm_button = self._add_button(
                buttons, confirm_text, "dangerButton" if destructive else "primaryButton"
            )
            if icon and destructive:
                set_button_icon(self.confirm_button, icon, "onDanger")
            default = self.cancel_button if destructive else self.confirm_button
        else:
            self.confirm_button = self._add_button(buttons, "OK", "primaryButton")
            default = self.confirm_button
        self.confirm_button.clicked.connect(self.accept)
        default.setDefault(True)
        default.setFocus(Qt.FocusReason.OtherFocusReason)

        self._fit_to_content()

    @staticmethod
    def _add_button(row: QHBoxLayout, text: str, object_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setAutoDefault(False)
        row.addWidget(button)
        return button

    @staticmethod
    def _text_label(text: str, object_name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        label.setSizePolicy(policy)
        return label

    def _fit_to_content(self) -> None:
        self.ensurePolished()
        layout = self.layout()
        assert layout is not None
        margins = layout.contentsMargins()
        chrome = margins.left() + margins.right() + _BODY_MARGINS[0] + _BODY_MARGINS[2] + _BADGE_SIZE + 16
        labels = (self.heading_label, self.message_label)
        natural = max(
            label.fontMetrics().horizontalAdvance(line)
            for label in labels
            for line in (label.text().splitlines() or [""])
        )
        longest_token = max(
            (label.fontMetrics().horizontalAdvance(token) for label in labels for token in re.split(r"[\s/]+", label.text())),
            default=0,
        )
        footer = margins.left() + margins.right() + self.footer.sizeHint().width()
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry().width() - 80 if screen else 1200
        minimum = min(max(_MIN_WIDTH, chrome + longest_token + 4, footer), available)
        width = min(max(minimum, chrome + min(natural, _MAX_TEXT_WIDTH) + 4), available)
        self.setMinimumWidth(minimum)
        layout.activate()
        height = layout.totalHeightForWidth(width)
        self.setMinimumHeight(height)
        self.resize(width, height)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        layout = self.layout()
        if layout is not None and layout.hasHeightForWidth():
            needed = layout.totalHeightForWidth(self.width())
            if needed != self.minimumHeight():
                self.setMinimumHeight(needed)

    def text(self) -> str:
        return self._heading

    def informativeText(self) -> str:
        return self._message


def ask_confirmation(
    parent: QWidget | None,
    *,
    title: str,
    heading: str,
    message: str,
    confirm_text: str,
    destructive: bool = False,
    level: Level | None = None,
    cancel_text: str = "Cancel",
    icon: str | None = None,
) -> bool:
    dialog = MessageDialog(
        parent,
        title=title,
        heading=heading,
        message=message,
        level=level or ("danger" if destructive else "question"),
        confirm_text=confirm_text,
        cancel_text=cancel_text,
        destructive=destructive,
        icon=icon,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted


def show_message(
    parent: QWidget | None,
    *,
    title: str,
    heading: str,
    message: str = "",
    level: Level = "info",
) -> None:
    MessageDialog(parent, title=title, heading=heading, message=message, level=level).exec()


__all__ = ["MessageDialog", "ask_confirmation", "show_message"]

