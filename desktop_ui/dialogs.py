"""Branded message and confirmation dialogs.

``QMessageBox`` always fixes its window size. Under Qt's Wayland client-side
decorations a fixed-size window is shown 20 px narrower and 20 px shorter than
requested (a 387 × 122 box appeared as 367 × 102), which cut off the message
and sliced the buttons in half. ``MessageDialog`` is sized by its layout
instead: it wraps long text, reflows when the user resizes it, follows the
light/dark theme, and names the confirming action ("Delete sales", not "Yes").
"""

from __future__ import annotations

import re
from typing import Literal

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPalette, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import ERROR, ERROR_ON_DARK, INK, PRIMARY, PRIMARY_DARK, SECONDARY

Level = Literal["info", "question", "warning", "error", "danger"]

_BADGE_SIZE = 40
_MIN_WIDTH = 420
_MAX_TEXT_WIDTH = 440  # wrap long lines at a comfortable reading width

# glyph, fill (light, dark), glyph colour (light, dark); every pair is >= 4.5:1
_BADGES: dict[str, tuple[str, str, str, str, str]] = {
    "info": ("i", PRIMARY_DARK, PRIMARY, "#FFFFFF", INK),
    "question": ("?", PRIMARY_DARK, PRIMARY, "#FFFFFF", INK),
    "warning": ("!", SECONDARY, SECONDARY, INK, INK),
    "error": ("!", ERROR, ERROR_ON_DARK, "#FFFFFF", INK),
    "danger": ("!", ERROR, ERROR_ON_DARK, "#FFFFFF", INK),
}
_LEVEL_NAMES = {
    "info": "Information",
    "question": "Question",
    "warning": "Warning",
    "error": "Error",
    "danger": "Warning",
}


def _badge(level: Level, dark: bool) -> QPixmap:
    glyph, light_fill, dark_fill, light_ink, dark_ink = _BADGES[level]
    scale = 2  # crisp on high-DPI screens
    pixmap = QPixmap(_BADGE_SIZE * scale, _BADGE_SIZE * scale)
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(dark_fill if dark else light_fill))
    area = QRectF(0, 0, _BADGE_SIZE, _BADGE_SIZE)
    painter.drawEllipse(area)
    font = QFont(painter.font())
    font.setBold(True)
    font.setPixelSize(int(_BADGE_SIZE * 0.55))
    painter.setFont(font)
    painter.setPen(QColor(dark_ink if dark else light_ink))
    painter.drawText(area, Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return pixmap


class MessageDialog(QDialog):
    """Resizable, layout-sized replacement for ``QMessageBox``.

    With ``confirm_text`` it asks a question; ``exec()`` returns ``Accepted``
    only when the user chooses the named action. Destructive confirmations
    make Cancel the default, so Enter or Escape never deletes anything.
    """

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
    ) -> None:
        super().__init__(parent)
        self.setObjectName("messageDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setAccessibleName(heading)
        self.setAccessibleDescription(message)
        self._heading = heading
        self._message = message
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128

        root = QVBoxLayout(self)
        # The dialog manages its own minimum size from height-for-width (see
        # resizeEvent); the default constraint would impose a taller, non-wrapping
        # minimum and leave a gap under the heading.
        root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(20)
        body = QHBoxLayout()
        root.addLayout(body)
        body.setSpacing(16)
        badge = QLabel()
        badge.setPixmap(_badge(level, dark))
        badge.setFixedSize(_BADGE_SIZE, _BADGE_SIZE)
        badge.setAccessibleName(_LEVEL_NAMES[level])
        body.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        text_column = QVBoxLayout()
        body.addLayout(text_column, 1)
        text_column.setSpacing(6)
        self.heading_label = self._text_label(heading, "dialogHeading")
        self.message_label = self._text_label(message, "dialogMessage")
        self.message_label.setVisible(bool(message))
        text_column.addWidget(self.heading_label)
        text_column.addWidget(self.message_label)
        text_column.addStretch(1)  # extra height goes below the text, not between lines

        self.buttons = QDialogButtonBox()
        root.addWidget(self.buttons)
        self.cancel_button: QPushButton | None = None
        if confirm_text:
            # AcceptRole even when destructive: the action *is* the affirmative
            # answer, so each platform orders it the native way (GNOME/macOS:
            # Cancel then Delete; Windows: Delete then Cancel).
            self.confirm_button = self._add_button(
                confirm_text,
                QDialogButtonBox.ButtonRole.AcceptRole,
                "dangerButton" if destructive else "primaryButton",
            )
            self.cancel_button = self._add_button(
                cancel_text, QDialogButtonBox.ButtonRole.RejectRole, "secondaryButton"
            )
            self.cancel_button.clicked.connect(self.reject)
            default = self.cancel_button if destructive else self.confirm_button
        else:
            self.confirm_button = self._add_button(
                "OK", QDialogButtonBox.ButtonRole.AcceptRole, "primaryButton"
            )
            default = self.confirm_button
        # Bound methods only: a lambda capturing the dialog would keep it alive
        # after exec() hands its ownership to Python (see DEF-026).
        self.confirm_button.clicked.connect(self.accept)
        default.setDefault(True)
        default.setFocus(Qt.FocusReason.OtherFocusReason)

        self._fit_to_content()

    def _add_button(self, text: str, role: QDialogButtonBox.ButtonRole, object_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setAutoDefault(False)  # only the safe default answers Enter
        self.buttons.addButton(button, role)
        return button

    @staticmethod
    def _text_label(text: str, object_name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setTextFormat(Qt.TextFormat.PlainText)  # may contain client names
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        return label

    def _fit_to_content(self) -> None:
        """Open at a readable width and exactly the height the wrapped text needs."""
        self.ensurePolished()
        layout = self.layout()
        assert layout is not None
        margins = layout.contentsMargins()
        chrome = margins.left() + margins.right() + _BADGE_SIZE + 16
        labels = (self.heading_label, self.message_label)
        natural = max(
            label.fontMetrics().horizontalAdvance(line)
            for label in labels
            for line in (label.text().splitlines() or [""])
        )
        # Lines wrap at spaces and "/"; a longer unbreakable token (for example
        # a Windows path) widens the minimum instead of being clipped.
        longest_token = max(
            (label.fontMetrics().horizontalAdvance(token) for label in labels for token in re.split(r"[\s/]+", label.text())),
            default=0,
        )
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry().width() - 80 if screen else 1200
        minimum = min(max(_MIN_WIDTH, chrome + longest_token + 4), available)
        width = min(max(minimum, chrome + min(natural, _MAX_TEXT_WIDTH) + 4), available)
        self.setMinimumWidth(minimum)
        layout.activate()
        height = layout.totalHeightForWidth(width)
        self.setMinimumHeight(height)
        self.resize(width, height)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        # Narrower windows wrap more lines; never let the window clip them.
        layout = self.layout()
        if layout is not None and layout.hasHeightForWidth():
            needed = layout.totalHeightForWidth(self.width())
            if needed != self.minimumHeight():
                self.setMinimumHeight(needed)

    # QMessageBox-compatible accessors, used by tests and assistive tooling.
    def text(self) -> str:
        return self._heading

    def informativeText(self) -> str:  # noqa: N802 - mirrors QMessageBox
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
) -> bool:
    """Ask before acting; return True only when the user chose ``confirm_text``."""
    dialog = MessageDialog(
        parent,
        title=title,
        heading=heading,
        message=message,
        level=level or ("danger" if destructive else "question"),
        confirm_text=confirm_text,
        destructive=destructive,
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
