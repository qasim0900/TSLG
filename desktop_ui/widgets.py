"""Small reusable, accessible Qt widgets for the branded desktop UI.

These are the building blocks of the redesign: page headers, cards with a
header row, KPI cards with an icon chip, badges, avatars, alerts, the search
field, a switch, a toast, a definition list, and a bar chart. Colours come from
:func:`desktop_ui.theme.tokens` (painted widgets) or the global stylesheet.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import Shiboken

from .icons import ThemedIconLabel, pixmap
from .motion import EASE, EASE_OUT, SPRING, animate, clear_effect, reduced_motion
from .theme import BRAND_GREEN, BUTTON_HEIGHT, ERROR, PRIMARY, SECONDARY, tokens

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
    layout.setSpacing(6)
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


def initials(name: str) -> str:
    """Two-letter initials for an avatar ("Osama Yaseen" -> "OY", "system" -> "SY")."""
    words = [word for word in name.replace("/", " ").split() if word[:1].isalnum()]
    if not words:
        return "—"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


def set_shown(widget: QWidget, shown: bool) -> None:
    """``setVisible`` that never shows a widget which has no parent yet.

    ``setVisible(True)`` on a parentless widget opens it as a separate window
    (a brief flash that also takes focus from the main window); left alone, it
    appears with the parent it is added to later.
    """
    if not shown:
        widget.hide()
    elif widget.parentWidget() is not None:
        widget.show()


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property used by a selector changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


# ------------------------------------------------------------------ containers


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)  # the border darkens under the mouse


class SectionCard(Card):
    """A card with a header row (title, optional subtitle, actions on the right) and a body.

    ``body`` is the layout for the card's content; pass ``padded=False`` when the
    content (a table, a tab bar) should run edge to edge.
    """

    def __init__(self, title: str = "", subtitle: str = "", *, padded: bool = True, divider: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        self.card_layout = outer
        self.header = QFrame()
        self.header.setObjectName("cardHeader" if divider else "plainHeader")
        header_row = QHBoxLayout(self.header)
        header_row.setContentsMargins(20, 15, 20, 15)
        self.header_layout = header_row
        header_row.setSpacing(12)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("sectionTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("sectionSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setTextFormat(Qt.TextFormat.PlainText)
        set_shown(self.subtitle_label, bool(subtitle))
        heading.addWidget(self.title_label)
        heading.addWidget(self.subtitle_label)
        header_row.addLayout(heading, 1)
        self.actions_row = QHBoxLayout()  # not "actions": that would hide QWidget.actions()
        self.actions_row.setSpacing(8)
        header_row.addLayout(self.actions_row)
        outer.addWidget(self.header)
        set_shown(self.header, bool(title))
        self.body_widget = QWidget()
        self.body = QVBoxLayout(self.body_widget)
        if padded:
            self.body.setContentsMargins(19, 16, 19, 18)
        else:
            self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(14)
        outer.addWidget(self.body_widget, 1)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        set_shown(self.subtitle_label, bool(text))

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions_row.addWidget(widget)
        return widget


class PageHeader(QWidget):
    """Page title and subtitle on the left, the page's main actions on the right."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        heading = QVBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        self.title_label.setAccessibleName(title)
        self.title_label.setWordWrap(True)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("pageSubtitle")
        self.subtitle_label.setWordWrap(True)
        set_shown(self.subtitle_label, bool(subtitle))
        heading.addWidget(self.title_label)
        heading.addWidget(self.subtitle_label)
        row.addLayout(heading, 1)
        self.actions_row = QHBoxLayout()
        self.actions_row.setSpacing(8)
        row.addLayout(self.actions_row)
        row.setAlignment(self.actions_row, Qt.AlignmentFlag.AlignBottom)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)
        self.title_label.setAccessibleName(title)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        set_shown(self.subtitle_label, bool(text))

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions_row.addWidget(widget)
        return widget


# ------------------------------------------------------------------ small parts


class IconChip(QWidget):
    """A rounded square holding an icon: green tint, or gold for the secondary accent.

    ``set_hover`` scales and tilts it (the design's KPI hover: scale 1.12, rotate -4deg).
    """

    def __init__(self, name: str, tone: str = "green", size: int = 34, icon_size: int = 16,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("iconChip")
        self._name = name
        self._tone = tone
        self._icon_size = icon_size
        self._radius = max(8, round(size * 0.29))
        self._hover = 0.0
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_icon(self, name: str, tone: str | None = None) -> None:
        self._name = name
        if tone is not None:
            self._tone = tone
        self.update()

    def set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        t = tokens()
        background, ink = {
            "gold": (t["goldTint"], t["goldChipInk"]),
            "dark": ("#122321", BRAND_GREEN),
            "info": (t["infoBg"], t["infoInk"]),
            "danger": (t["dangerTint"], t["danger"]),
        }.get(self._tone, (t["tint"], t["primaryInk"]))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        side = min(self.width(), self.height()) / (1 + 0.12 * max(self._hover, 0))
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(1 + 0.12 * self._hover, 1 + 0.12 * self._hover)
        painter.rotate(-4 * self._hover)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(QRectF(-side / 2, -side / 2, side, side), self._radius, self._radius)
        image = pixmap(self._name, ink, self._icon_size)
        painter.drawPixmap(QPointF(-self._icon_size / 2, -self._icon_size / 2), image)
        painter.end()


class Avatar(QWidget):
    """Initials in a tinted circle; grows slightly under the mouse (design: scale 1.08)."""

    def __init__(self, name: str = "", size: int = 32, parent: QWidget | None = None, *,
                 neutral: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("avatar")
        self._size = size
        self._neutral = neutral
        self._hover = 0.0
        self._text = ""
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.set_name(name)

    def set_name(self, name: str) -> None:
        self._text = initials(name) if name else ""
        self.setAccessibleName(name)
        self.update()

    def text(self) -> str:
        return self._text

    def _set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.HoverEnter:
            animate(self._hover, 1.0, 200, self._set_hover, curve=SPRING, owner=self)
        elif event.type() == QEvent.Type.HoverLeave:
            animate(self._hover, 0.0, 200, self._set_hover, curve=SPRING, owner=self)
        return super().event(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        if not self._text:
            return
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = 1 + 0.08 * self._hover
        diameter = self._size / 1.08 * scale
        center = QPointF(self.width() / 2, self.height() / 2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t["muted"] if self._neutral else t["tint2"]))
        painter.drawEllipse(center, diameter / 2, diameter / 2)
        font = QFont(self.font())
        font.setPixelSize(max(9, round(self._size * 0.34 * scale)))
        font.setWeight(QFont.Weight.ExtraBold)
        painter.setFont(font)
        painter.setPen(QColor(t["text2"] if self._neutral else t["primaryInk"]))
        painter.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()


_BADGE_TONES: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "neutral": (("#ECEEF0", "#3A4046"), ("#2B3533", "#D8DEDB")),
    "info": (("#E2ECF8", "#1E4C7A"), ("#1B3150", "#BBD5F4")),
    "success": (("#DFF1E3", "#1D5E28"), ("#183C22", "#A9E2B4")),
    "warning": (("#FFF1CC", "#6E5000"), ("#3E3216", "#FFD86E")),
    "danger": (("#FBE3E3", "#8E1B1B"), ("#4A2020", "#FFB4AB")),
}


def badge_colors(tone: str, dark: bool) -> tuple[str, str]:
    """(background, text) of a badge tone on the light or dark theme; every pair is >= 4.5:1."""
    return _BADGE_TONES.get(tone, _BADGE_TONES["neutral"])[1 if dark else 0]


def paint_badge(painter: QPainter, rect: QRectF, text: str, tone: str, dark: bool, font: QFont,
                *, dot: bool = True) -> float:
    """Draw a badge pill (dot + bold text) left-aligned in ``rect``; returns its width."""
    background, foreground = badge_colors(tone, dark)
    painter.save()
    bold = QFont(font)
    bold.setPixelSize(12)
    bold.setWeight(QFont.Weight.Bold)
    painter.setFont(bold)
    metrics = painter.fontMetrics()
    dot_space = 12 if dot else 0
    width = min(metrics.horizontalAdvance(text) + 20 + dot_space, max(rect.width(), 24))
    height = min(24.0, rect.height())
    pill = QRectF(rect.left(), rect.top() + (rect.height() - height) / 2, width, height)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(background))
    painter.drawRoundedRect(pill, height / 2, height / 2)
    color = QColor(foreground)
    if dot:
        dot_color = QColor(color)
        dot_color.setAlphaF(0.85)
        painter.setBrush(dot_color)
        painter.drawEllipse(QPointF(pill.left() + 13, pill.center().y()), 3, 3)
    painter.setPen(color)
    text_rect = pill.adjusted(10 + dot_space, 0, -10, 0)
    shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(text_rect.width()) + 1)
    painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shown)
    painter.restore()
    return width


class Badge(QWidget):
    """A coloured status label ("Open", "High", "Super Admin") with a leading dot."""

    def __init__(self, text: str = "", tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text
        self._tone = tone
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(text)

    def set_badge(self, text: str, tone: str) -> None:
        self._text, self._tone = text, tone
        self.setAccessibleName(text)
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setWeight(QFont.Weight.Bold)
        return QSize(QFontMetrics(font).horizontalAdvance(self._text) + 34, 24)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        if not self._text:
            return
        painter = QPainter(self)
        from .theme import is_dark

        paint_badge(painter, QRectF(self.rect()), self._text, self._tone, is_dark(), self.font())
        painter.end()


class Alert(QFrame):
    """An inline message with an icon: info (blue), warning (gold), error (red), success (green)."""

    _ICONS = {"info": "info", "warning": "warning", "error": "alert", "success": "check-circle"}
    _ROLES = {"info": "infoInk", "warning": "warnInk", "error": "danger", "success": "primaryInk"}

    def __init__(self, text: str = "", tone: str = "info", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("alert")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 11, 14, 11)
        row.setSpacing(10)
        self.icon = ThemedIconLabel(self._ICONS["info"], "infoInk", 16)
        self.icon.setFixedSize(18, 18)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        self.label = QLabel()
        self.label.setObjectName("alertText")
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.label, 1)
        self.set_message(text, tone)

    def set_message(self, text: str, tone: str | None = None) -> None:
        if tone is not None:
            self.setProperty("tone", tone)
            self.label.setProperty("tone", tone)
            self.icon.set_icon(self._ICONS.get(tone, "info"), self._ROLES.get(tone, "infoInk"))
            repolish(self)
            repolish(self.label)
        appearing = bool(text) and self.isHidden()
        self.label.setText(text)
        set_shown(self, bool(text))
        if appearing and self.isVisible():
            from .motion import fade_in

            fade_in(self)  # the design's alert fade-in

    def text(self) -> str:
        return self.label.text()


class SearchField(QLineEdit):
    """A line edit with a leading search icon and an optional keyboard hint ("Ctrl K")."""

    def __init__(self, placeholder: str = "Search", hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self._icon = ThemedIconLabel("search", "text2", 16, self)
        self._icon.setFixedSize(18, 18)
        self.setTextMargins(26, 0, 0, 0)
        self.hint = QLabel(hint, self)
        self.hint.setObjectName("kbdHint")
        self.hint.setVisible(bool(hint))
        self.hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._icon.move(12, (self.height() - self._icon.height()) // 2)
        if not self.hint.isHidden():
            self.hint.adjustSize()
            self.hint.move(self.width() - self.hint.width() - 8, (self.height() - self.hint.height()) // 2)


class SwitchButton(QCheckBox):
    """A checkbox drawn as an on/off switch (42 × 24) whose knob springs across."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._knob = 0.0
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(42, 24)

    def hitButton(self, pos: Any) -> bool:  # noqa: N802 - Qt API
        return self.rect().contains(pos)

    def _set_knob(self, value: float) -> None:
        self._knob = value
        self.update()

    def _animate(self, checked: bool) -> None:
        animate(self._knob, 1.0 if checked else 0.0, 240, self._set_knob, curve=SPRING, owner=self)

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt API
        super().setChecked(checked)
        if self.signalsBlocked():  # no toggled signal: jump to the new state
            self._knob = 1.0 if checked else 0.0
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(0, 0, 42, 24)
        painter.setPen(Qt.PenStyle.NoPen)
        level = max(0.0, min(1.0, self._knob))
        painter.setBrush(_mix(QColor(t["lineStrong"]), QColor(t["primary"]), level))
        if not self.isEnabled():
            painter.setOpacity(0.5)
        painter.drawRoundedRect(track, 12, 12)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawEllipse(QRectF(3 + 18 * self._knob, 4, 18, 18))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(3 + 18 * self._knob, 3, 18, 18))
        if self.hasFocus():
            pen = QPen(QColor(t["focus"]), 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(track.adjusted(1, 1, -1, -1), 11, 11)
        painter.end()


def _mix(first: QColor, second: QColor, amount: float) -> QColor:
    return QColor(
        round(first.red() + (second.red() - first.red()) * amount),
        round(first.green() + (second.green() - first.green()) * amount),
        round(first.blue() + (second.blue() - first.blue()) * amount),
    )


class DefinitionList(QWidget):
    """Label/value rows separated by hairlines (the design's ``dl``)."""

    def __init__(self, key_width: int = 170, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._key_width = key_width
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(0)
        self._grid.setColumnStretch(1, 1)
        self.value_labels: dict[str, QLabel] = {}

    def set_rows(self, rows: Sequence[tuple[str, str | QWidget]]) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.value_labels = {}
        for index, (name, value) in enumerate(rows):
            key = QLabel(name)
            key.setObjectName("dlKey")
            key.setMinimumWidth(self._key_width)
            key.setMaximumWidth(self._key_width)
            key.setWordWrap(True)
            if isinstance(value, QWidget):
                shown: QWidget = value
            else:
                label = QLabel(value or "—")
                label.setWordWrap(True)
                label.setTextFormat(Qt.TextFormat.PlainText)  # values are user-entered
                label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                self.value_labels[name] = label
                shown = label
            row = index * 2
            key.setContentsMargins(0, 11, 0, 11)
            if isinstance(shown, QLabel):
                shown.setContentsMargins(0, 11, 0, 11)
            self._grid.addWidget(key, row, 0, Qt.AlignmentFlag.AlignTop)
            self._grid.addWidget(shown, row, 1)
            rule = QFrame()
            rule.setObjectName("dlRule")
            self._grid.addWidget(rule, row + 1, 0, 1, 2)


class EmptyState(QWidget):
    """A centred empty state: icon chip, title, a short explanation, and optional actions."""

    def __init__(self, title: str, message: str = "", icon: str = "file", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 48, 24, 48)
        layout.setSpacing(10)
        layout.addStretch(1)
        self.chip = IconChip(icon, size=52, icon_size=22)
        layout.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = QLabel(title)
        self.title.setObjectName("emptyTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        set_shown(self.title, bool(title))
        self.message = QLabel(message)
        self.message.setObjectName("sectionSubtitle")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setMaximumWidth(380)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.title)
        # Centred by stretches, not an alignment flag: an aligned label is sized from its
        # one-line hint, which cut a wrapped second line in half.
        message_row = QHBoxLayout()
        message_row.addStretch(1)
        message_row.addWidget(self.message, 100)
        message_row.addStretch(1)
        layout.addLayout(message_row)
        self.actions_row = QHBoxLayout()
        self.actions_row.setSpacing(8)
        self.actions_row.addStretch(1)
        self.actions_row.addStretch(1)
        layout.addSpacing(4)
        layout.addLayout(self.actions_row)
        layout.addStretch(1)

    def add_action(self, text: str, handler: Any, *, primary: bool = False, icon: str | None = None) -> QPushButton:
        from .icons import set_button_icon

        button = QPushButton(text)
        button.setObjectName("primaryButton" if primary else "secondaryButton")
        if icon:
            set_button_icon(button, icon, "onPrimary" if primary else "text")
        button.clicked.connect(lambda _checked=False: handler())
        self.actions_row.insertWidget(self.actions_row.count() - 1, button)
        return button

    def set_text(self, title: str, message: str = "") -> None:
        self.title.setText(title)
        set_shown(self.title, bool(title))
        self.message.setText(message)


# ------------------------------------------------------------------ KPI cards


class KpiCard(Card):
    """A metric: label and icon chip on top, a large value, and a short note."""

    clicked = Signal()

    def __init__(
        self,
        title: str,
        value: str = "—",
        detail: str = "",
        accent: str = PRIMARY,
        compact: bool = False,
        parent: QWidget | None = None,
        *,
        icon: str | None = None,
        clickable: bool = False,
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
        self._clickable = clickable
        self._lift = 0.0
        self._lift_base: QPoint | None = None
        self._chip_hover = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(96 if compact else 128)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(16, 14, 16, 14) if compact else (20, 18, 20, 18))
        layout.setSpacing(10 if compact else 12)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricLabel")
        top.addWidget(self.title_label, 1)
        self.icon_chip: IconChip | None = None
        if icon:
            self.icon_chip = IconChip(icon, "gold" if semantic_accent == "gold" else "green")
            top.addWidget(self.icon_chip, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if compact:
            self.value_label.setStyleSheet("font-size: 22px;")
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("metricNote")
        self.detail_label.setWordWrap(True)
        set_shown(self.detail_label, bool(detail))
        # Compatibility aliases keep existing page/test integrations stable as
        # their former private KPI widgets are consolidated onto this one.
        self.label = self.title_label
        self.value = self.value_label
        self.note = self.detail_label
        self._title = self.title_label
        self._value = self.value_label
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)
        layout.addStretch(1)
        self.set_value(value, detail)

    def set_value(self, value: str, detail: str = "") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        set_shown(self.detail_label, bool(detail))
        description = f"{self.title_label.text()}: {value}"
        if detail:
            description += f". {detail}"
        self.setAccessibleDescription(description)
        self.setToolTip(detail)

    def set_metric(self, value: str, note: str = "") -> None:
        """Update a metric using the API retained from the Sales KPI widget."""
        self.set_value(value, note)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        super().mouseReleaseEvent(event)
        if self._clickable and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        if self._clickable and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ hover lift

    def enterEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        super().enterEvent(event)
        if self._lift_base is None:
            self._lift_base = QPoint(self.pos())
        animate(self._lift, 1.0, 250, self._set_lift, curve=EASE, owner=self)
        if self.icon_chip is not None:
            animate(self._chip_hover, 1.0, 250, self._set_chip, curve=SPRING, owner=self)

    def leaveEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        super().leaveEvent(event)
        animate(self._lift, 0.0, 250, self._set_lift, curve=EASE, owner=self, done=self._end_lift)
        if self.icon_chip is not None:
            animate(self._chip_hover, 0.0, 250, self._set_chip, curve=SPRING, owner=self)

    def _set_chip(self, value: float) -> None:
        self._chip_hover = value
        if self.icon_chip is not None:
            self.icon_chip.set_hover(value)

    def _set_lift(self, value: float) -> None:
        base = self._lift_base
        if base is None:
            return
        expected = base.y() - round(3 * self._lift)
        if abs(self.y() - expected) > 1:  # a layout pass moved the card: follow it
            base = QPoint(self.x(), self.y() + round(3 * self._lift))
            self._lift_base = base
        self._lift = value
        self.move(base.x(), base.y() - round(3 * value))
        effect = self.graphicsEffect()
        if value > 0.01:
            if not isinstance(effect, QGraphicsDropShadowEffect):
                effect = QGraphicsDropShadowEffect(self)
                self.setGraphicsEffect(effect)
            effect.setBlurRadius(28 * value)
            effect.setOffset(0, 10 * value)
            effect.setColor(QColor(0, 0, 0, round(115 * value)) if tokens()["bg"] == "#0A1414"
                            else QColor(10, 20, 20, round(26 * value)))
        elif isinstance(effect, QGraphicsDropShadowEffect):
            clear_effect(self)

    def _end_lift(self) -> None:
        if self._lift_base is not None and self._lift <= 0.01:
            self.move(self._lift_base)
            self._lift_base = None
            if isinstance(self.graphicsEffect(), QGraphicsDropShadowEffect):
                clear_effect(self)


class MiniMetric(QFrame):
    """One cell of a metric grid: a small label and a value (optionally coloured)."""

    def __init__(self, title: str, value: str = "—", tone: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("miniCell")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("miniLabel")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("miniValue")
        self.value_label.setProperty("tone", tone)
        self.value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addStretch(1)
        self.setAccessibleName(title)
        # Aliases shared with KpiCard so pages can treat both alike.
        self.label = self.title_label
        self.value = self.value_label

    def set_value(self, value: str, description: str = "") -> None:
        self.value_label.setText(value)
        self.setToolTip(description)
        self.setAccessibleDescription(f"{self.title_label.text()}: {value}")


class MetricGrid(Card):
    """Mini metrics in a grid with hairlines between the cells (the design's ``mini`` card)."""

    def __init__(self, columns: int = 4, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns = columns
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(1, 1, 1, 1)
        self._grid.setSpacing(0)
        self.cells: list[MiniMetric] = []

    def add(self, cell: MiniMetric) -> MiniMetric:
        self.cells.append(cell)
        self._relayout()
        return cell

    def set_columns(self, columns: int) -> None:
        if columns != self._columns:
            self._columns = columns
            self._relayout()

    def _relayout(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None and widget not in self.cells:
                widget.deleteLater()
        rows = (len(self.cells) + self._columns - 1) // self._columns
        for index, cell in enumerate(self.cells):
            row, column = divmod(index, self._columns)
            self._grid.addWidget(cell, row * 2, column * 2)
            if column < self._columns - 1 and index < len(self.cells) - 1:
                divider = QFrame()
                divider.setObjectName("colDivider")
                self._grid.addWidget(divider, row * 2, column * 2 + 1)
        for row in range(rows - 1):
            rule = QFrame()
            rule.setObjectName("rowDivider")
            self._grid.addWidget(rule, row * 2 + 1, 0, 1, self._columns * 2 - 1)
        for column in range(self._columns):
            self._grid.setColumnStretch(column * 2, 1)


# ------------------------------------------------------------------ feedback


class Toast(QFrame):
    """A short confirmation floating at the bottom centre of a window (springs in, fades out)."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        self.label = QLabel()
        self.label.setObjectName("toastText")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.label, 1)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        host.installEventFilter(self)
        self._opacity: QGraphicsOpacityEffect | None = None

    def text(self) -> str:
        return self.label.text()

    def show_message(self, message: str, level: str = "info", milliseconds: int = 4000) -> None:
        t = tokens()
        error = level == "error"
        self.setProperty("level", level)
        self.label.setProperty("level", level)
        repolish(self)
        repolish(self.label)
        ink = t["onDanger"] if error else BRAND_GREEN
        self.icon.setPixmap(pixmap("alert" if error else "check-circle", ink, 18))
        self.label.setText(message)
        self._place()
        self.show()
        self.raise_()
        self._timer.start(milliseconds)
        if reduced_motion():
            return
        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        final = QPoint(self.pos())

        def step(value: float) -> None:
            if self._opacity is not None and Shiboken.isValid(self._opacity):
                self._opacity.setOpacity(min(1.0, max(0.0, value * 1.6)))
            self.move(final.x(), final.y() + round(18 * (1 - value)))

        animate(0.0, 1.0, 400, step, curve=SPRING, owner=self, done=lambda: clear_effect(self))

    def _fade_out(self) -> None:
        if reduced_motion() or not self.isVisible():
            self.hide()
            return
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        animate(1.0, 0.0, 220, lambda value: effect.setOpacity(value) if Shiboken.isValid(effect) else None,
                curve=EASE, owner=self, done=self._hidden)

    def _hidden(self) -> None:
        if Shiboken.isValid(self):
            self.hide()
            clear_effect(self)

    def _place(self) -> None:
        host = self.parentWidget()
        if host is None:
            return
        natural = self.label.fontMetrics().horizontalAdvance(self.label.text()) + 18 + 10 + 32 + 4
        self.setFixedWidth(min(natural, max(host.width() - 48, 240)))
        layout = self.layout()
        if layout is not None and layout.hasHeightForWidth():
            self.setFixedHeight(layout.heightForWidth(self.width()))
        else:
            self.setFixedHeight(self.sizeHint().height())
        self.move((host.width() - self.width()) // 2, host.height() - self.height() - 24)

    def eventFilter(self, watched: Any, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self._place()
        return False


# ------------------------------------------------------------------ charts


class BarChart(QWidget):
    """Vertical bars (optionally A/B pairs) with a light grid; bars grow in, one after another."""

    def __init__(self, accessible_name: str = "Bar chart", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(accessible_name)
        self.setMinimumHeight(228)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._labels: list[str] = []
        self._values: list[float] = []
        self._values_b: list[float] | None = None
        self._format: Any = str
        self._empty = "No data yet."
        self._progress = 1.0
        self.setMouseTracking(True)

    def set_data(self, labels: Sequence[str], values: Sequence[float], *, values_b: Sequence[float] | None = None,
                 value_format: Any = str, empty: str = "No data yet.") -> None:
        self._labels = list(labels)
        self._values = [float(value) for value in values]
        self._values_b = [float(value) for value in values_b] if values_b is not None else None
        self._format = value_format
        self._empty = empty
        parts = []
        for index, label in enumerate(self._labels):
            text = f"{label} {value_format(self._values[index])}"
            if self._values_b is not None:
                text += f" / {value_format(self._values_b[index])}"
            parts.append(text)
        self.setAccessibleDescription(", ".join(parts) or empty)
        self.replay()

    def has_data(self) -> bool:
        return bool(self._values) and max(self._values + (self._values_b or [0.0])) > 0

    def replay(self) -> None:
        """Grow the bars from the axis (the design's growy, 0.8 s with a 0.05 s stagger)."""
        span = 800 + 50 * max(len(self._values) - 1, 0)
        animate(0.0, 1.0, span, self._set_progress, curve=EASE_OUT, owner=self)

    def _set_progress(self, value: float) -> None:
        self._progress = value
        self.update()

    def _bar_progress(self, index: int) -> float:
        count = max(len(self._values), 1)
        span = 800 + 50 * (count - 1)
        start = 50 * index / span
        local = (self._progress - start) / (800 / span)
        return max(0.0, min(1.0, EASE_OUT.valueForProgress(max(0.0, min(1.0, local)))))

    def _area(self) -> QRectF:
        return QRectF(self.rect()).adjusted(4, 8, -4, -28)

    def _bar_rects(self) -> list[list[QRectF]]:
        area = self._area()
        count = len(self._values)
        if not count:
            return []
        series = [self._values] + ([self._values_b] if self._values_b is not None else [])
        top = max(max(values) for values in series)
        top = max(top, 1.0)
        gap = 10.0
        slot = (area.width() - gap * (count - 1)) / count
        width = min(34.0, slot if len(series) == 1 else (slot - 3) / 2)
        group = width * len(series) + 3 * (len(series) - 1)
        result = []
        for index in range(count):
            left = area.left() + index * (slot + gap) + (slot - group) / 2
            grow = self._bar_progress(index)
            rects = []
            for number, values in enumerate(series):
                height = area.height() * values[index] / top
                height = max(height, 2.0 if values[index] > 0 else 0.0) * grow
                x = left + number * (width + 3)
                rects.append(QRectF(x, area.bottom() - height, width, height))
            result.append(rects)
        return result

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self._area()
        painter.setPen(QPen(QColor(t["grid"]), 1))
        for step in range(5):
            y = area.top() + area.height() * step / 4
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        if not self.has_data():
            painter.setPen(QColor(t["text2"]))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, self._empty)
            painter.end()
            return
        painter.setPen(Qt.PenStyle.NoPen)
        colors = (QColor(t["chartA"]), QColor(t["chartB"]))
        for rects in self._bar_rects():
            for number, rect in enumerate(rects):
                if rect.height() <= 0:
                    continue
                painter.setBrush(colors[number])
                radius = min(6.0, rect.height() / 2, rect.width() / 2)
                painter.drawRoundedRect(rect, radius, radius)
                painter.drawRect(rect.adjusted(0, max(rect.height() - 2, 0), 0, 0))
        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor(t["text2"]))
        count = len(self._values)
        slot = (area.width() - 10 * (count - 1)) / count
        metrics = painter.fontMetrics()
        widest = max((metrics.horizontalAdvance(label) for label in self._labels), default=0) + 12
        every = max(1, -(-widest // max(int(slot + 10), 1)))  # show every n-th label so none overlap
        for index, label in enumerate(self._labels):
            if index % every:
                continue
            centre = area.left() + index * (slot + 10) + slot / 2
            box = QRectF(centre - widest / 2, area.bottom() + 6, widest, 18)
            painter.drawText(box, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)
        painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        point = event.position()
        for index, rects in enumerate(self._bar_rects()):
            for number, rect in enumerate(rects):
                if rect.adjusted(-3, -400, 3, 0).contains(point):
                    values = self._values if number == 0 else (self._values_b or [])
                    prefix = "" if self._values_b is None else ("A: " if number == 0 else "B: ")
                    self.setToolTip(f"{self._labels[index]} · {prefix}{self._format(values[index])}")
                    return
        self.setToolTip("")


class BarRow:
    """One row of a :class:`HBarList`."""

    def __init__(self, label: str, fraction: float, value: str, detail: str = "", *, avatar: str = "",
                 color: str = "chartA", tooltip: str = "") -> None:
        self.label = label
        self.fraction = max(0.0, min(1.0, fraction))
        self.value = value
        self.detail = detail
        self.avatar = avatar
        self.color = color
        self.tooltip = tooltip


class HBarList(QWidget):
    """Label | track with a fill | value rows (products, top clients, the funnel); fills sweep in."""

    def __init__(self, accessible_name: str, *, label_width: int = 220, value_width: int = 170, track: int = 10,
                 row_height: int = 22, gap: int = 14, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName(accessible_name)
        self.rows: list[BarRow] = []
        self._label_width = label_width
        self._value_width = value_width
        self._track = track
        self._row_height = row_height
        self._gap = gap
        self._progress = 1.0
        self._empty = ""
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_rows(self, rows: Sequence[BarRow], *, empty: str = "") -> None:
        self.rows = list(rows)
        self._empty = empty
        self.setAccessibleDescription("; ".join(f"{row.label} {row.value}" + (f" · {row.detail}" if row.detail else "")
                                                for row in self.rows) or empty)
        self.updateGeometry()
        self.replay()

    def replay(self) -> None:
        """Sweep the fills in from the left (the design's reveal, 1 s with a 0.1 s stagger)."""
        span = 1000 + 100 * max(len(self.rows) - 1, 0)
        animate(0.0, 1.0, span, self._set_progress, curve=EASE_OUT, owner=self)

    def _set_progress(self, value: float) -> None:
        self._progress = value
        self.update()

    def _row_progress(self, index: int) -> float:
        span = 1000 + 100 * max(len(self.rows) - 1, 0)
        local = (self._progress - 100 * index / span) / (1000 / span)
        return EASE_OUT.valueForProgress(max(0.0, min(1.0, local)))

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        rows = max(len(self.rows), 1)
        return QSize(520, rows * self._row_height + (rows - 1) * self._gap)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return QSize(260, self.sizeHint().height())

    def _label_column(self) -> float:
        return min(self._label_width, max(140.0, self.width() * 0.3))

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.rows:
            painter.setPen(QColor(t["text2"]))
            painter.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self._empty)
            painter.end()
            return
        label_column = self._label_column()
        value_column = min(self._value_width, self.width() * 0.3)
        track_left = label_column + 14
        track_right = self.width() - value_column - 14
        bold = QFont(self.font())
        bold.setPixelSize(13)
        bold.setWeight(QFont.Weight.DemiBold)
        regular = QFont(bold)
        regular.setWeight(QFont.Weight.Normal)
        strong = QFont(bold)
        strong.setWeight(QFont.Weight.Bold)
        for index, row in enumerate(self.rows):
            top = index * (self._row_height + self._gap)
            middle = top + self._row_height / 2
            text_left = 0.0
            if row.avatar:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(t["tint2"]))
                painter.drawEllipse(QPointF(13, middle), 13, 13)
                small = QFont(bold)
                small.setPixelSize(10)
                small.setWeight(QFont.Weight.ExtraBold)
                painter.setFont(small)
                painter.setPen(QColor(t["primaryInk"]))
                painter.drawText(QRectF(0, middle - 13, 26, 26), Qt.AlignmentFlag.AlignCenter, initials(row.avatar))
                text_left = 36.0
            painter.setFont(bold)
            painter.setPen(QColor(t["text"]))
            label_box = QRectF(text_left, top, label_column - text_left, self._row_height)
            painter.drawText(label_box, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             painter.fontMetrics().elidedText(row.label, Qt.TextElideMode.ElideRight,
                                                              int(label_box.width())))
            track = QRectF(track_left, middle - self._track / 2, max(track_right - track_left, 10), self._track)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t["muted"]))
            painter.drawRoundedRect(track, self._track / 2, self._track / 2)
            fill = QRectF(track.left(), track.top(), track.width() * row.fraction * self._row_progress(index),
                          track.height())
            if fill.width() > 0.5:
                painter.setBrush(QColor(t.get(row.color, row.color)))
                painter.drawRoundedRect(fill, self._track / 2, self._track / 2)
            value_box = QRectF(self.width() - value_column, top, value_column, self._row_height)
            detail = f" · {row.detail}" if row.detail else ""
            painter.setFont(regular)
            detail_width = painter.fontMetrics().horizontalAdvance(detail)
            painter.setPen(QColor(t["text2"]))
            painter.drawText(value_box, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, detail)
            painter.setFont(strong)
            painter.setPen(QColor(t["text"]))
            painter.drawText(value_box.adjusted(0, 0, -detail_width, 0),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, row.value)
        painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        index = int(event.position().y() // (self._row_height + self._gap))
        if 0 <= index < len(self.rows):
            row = self.rows[index]
            self.setToolTip(row.tooltip or f"{row.label}: {row.value}" + (f" · {row.detail}" if row.detail else ""))
        else:
            self.setToolTip("")



class CountChip(QPushButton):
    """A pill button showing a count and a label ("1 Overdue", "5 Open tasks").

    With a tone the count sits in a coloured badge (overdue: red, due today: gold);
    otherwise it is bold. ``text()`` stays the plain sentence for screen readers.
    """

    def __init__(self, label: str, tone: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chipButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._label = label
        self._tone = tone
        self._count = "0"
        self.setFixedHeight(BUTTON_HEIGHT)

    def set_count(self, count: int, text: str) -> None:
        self._count = str(count)
        self.setText(text)
        self.setAccessibleName(text)
        self.updateGeometry()
        self.update()

    def _fonts(self) -> tuple[QFont, QFont]:
        label = QFont(self.font())
        label.setPixelSize(13)
        label.setWeight(QFont.Weight.Medium)
        count = QFont(label)
        count.setWeight(QFont.Weight.Bold)
        if self._tone:
            count.setPixelSize(12)
        return label, count

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        label, count = self._fonts()
        count_width = QFontMetrics(count).horizontalAdvance(self._count) + (30 if self._tone else 0)
        return QSize(14 + count_width + 8 + QFontMetrics(label).horizontalAdvance(self._label) + 14, 40)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt API
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = self.underMouse()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(t["brand"] if hovered else t["line"]), 1))
        painter.setBrush(QColor(t["tint"] if hovered else t["surface2"]))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        label_font, count_font = self._fonts()
        x = 14.0
        if self._tone:
            from .theme import is_dark

            width = paint_badge(painter, QRectF(x, 0, 200, self.height()), self._count, self._tone, is_dark(),
                                self.font())
            x += width + 8
        else:
            painter.setFont(count_font)
            painter.setPen(QColor(t["text"]))
            width = painter.fontMetrics().horizontalAdvance(self._count)
            painter.drawText(QRectF(x, 0, width + 2, self.height()), Qt.AlignmentFlag.AlignVCenter, self._count)
            x += width + 8
        painter.setFont(label_font)
        painter.setPen(QColor(t["text"]))
        painter.drawText(QRectF(x, 0, self.width() - x, self.height()), Qt.AlignmentFlag.AlignVCenter, self._label)
        if self.hasFocus():
            painter.setPen(QPen(QColor(t["focus"]), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), rect.height() / 2 - 1, rect.height() / 2 - 1)
        painter.end()


class Pager(QWidget):
    """Previous / numbered pages (with "…") / next, as in the design's table footers."""

    page_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(4)
        self.previous_button = self._button("", "Previous page", "chevron-left")
        self.next_button = self._button("", "Next page", "chevron-right")
        self._page = 1
        self._pages = 1
        self._numbers: list[QWidget] = []
        self.previous_button.clicked.connect(lambda: self.page_requested.emit(self._page - 1))
        self.next_button.clicked.connect(lambda: self.page_requested.emit(self._page + 1))
        self._row.addWidget(self.previous_button)
        self._row.addWidget(self.next_button)

    @staticmethod
    def _button(text: str, name: str, icon: str | None = None) -> QPushButton:
        from .icons import set_button_icon

        button = QPushButton(text)
        button.setObjectName("pageButton")
        button.setAccessibleName(name)
        button.setToolTip(name)
        if icon:
            set_button_icon(button, icon, "text", 16)
        return button

    @staticmethod
    def numbers(page: int, pages: int) -> list[int | None]:
        """Page numbers to show; ``None`` is an ellipsis (1 … 4 5 6 … 12)."""
        if pages <= 7:
            return list(range(1, pages + 1))
        shown: list[int | None] = [1]
        start, end = max(2, page - 1), min(pages - 1, page + 1)
        if start > 2:
            shown.append(None)
        shown.extend(range(start, end + 1))
        if end < pages - 1:
            shown.append(None)
        shown.append(pages)
        return shown

    def set_state(self, page: int, pages: int) -> None:
        self._page, self._pages = page, max(pages, 1)
        for widget in self._numbers:
            self._row.removeWidget(widget)
            widget.deleteLater()
        self._numbers = []
        for position, number in enumerate(self.numbers(page, self._pages), start=1):
            if number is None:
                gap = QLabel("…")
                gap.setObjectName("mutedText")
                gap.setFixedWidth(28)
                gap.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell: QWidget = gap
            else:
                button = self._button(str(number), f"Page {number}")
                button.setProperty("current", number == page)
                button.clicked.connect(lambda _checked=False, target=number: self.page_requested.emit(target))
                cell = button
            self._row.insertWidget(position, cell)
            self._numbers.append(cell)
        self.previous_button.setEnabled(page > 1)
        self.next_button.setEnabled(page < self._pages)


class PasswordRules(QWidget):
    """A live checklist of the password policy.

    It runs the services' own rule checks (``crm.security.passwords``), so it can never
    disagree with what is enforced when the password is saved. ``email`` and ``name``
    are the account's, for the "not like your name or email" rule.
    """

    def __init__(self, parent: QWidget | None = None, *, email: str = "", name: str = "") -> None:
        super().__init__(parent)
        from crm.security.passwords import RULES

        self._rules = RULES
        self._email = email
        self._name = name
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self._rows: list[tuple[QLabel, QLabel]] = []
        for index, rule in enumerate(self._rules):
            text = rule.label
            mark = QLabel()
            mark.setFixedSize(14, 14)
            label = QLabel(text)
            label.setObjectName("ruleText")
            cell = QHBoxLayout()
            cell.setSpacing(6)
            cell.addWidget(mark)
            cell.addWidget(label, 1)
            grid.addLayout(cell, index // 2, index % 2)
            self._rows.append((mark, label))
        self.setAccessibleName("Password requirements")
        self.update_rules("")

    def set_owner(self, email: str = "", name: str = "") -> None:
        """The account the password is for (its email and name), used by later checks."""
        self._email, self._name = email, name

    def _broken(self, value: str, email: str | None, name: str | None) -> set[str]:
        from crm.security.passwords import broken_rules

        if not value:  # nothing typed yet: no rule is met
            return {rule.key for rule in self._rules}
        owner_email = self._email if email is None else email
        owner_name = self._name if name is None else name
        return {rule.key for rule in broken_rules(value, email=owner_email, names=(owner_name,))}

    def met(self, value: str, email: str | None = None, name: str | None = None) -> bool:
        return not self._broken(value, email, name)

    def update_rules(self, value: str, email: str | None = None, *, name: str | None = None,
                     tried: bool = False) -> None:
        t = tokens()
        broken = self._broken(value, email, name)
        for (mark, label), rule in zip(self._rows, self._rules):
            text = rule.label
            ok = rule.key not in broken
            color = t["primaryInk"] if ok else t["danger"] if tried else t["text2"]
            mark.setPixmap(pixmap("check" if ok else "dot", color, 14, 2.4 if ok else 1.8))
            label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 600;")
            label.setAccessibleDescription("met" if ok else "not met")
            label.setText(text)


class RevealButton(QToolButton):
    """The eye button at the right of a password field (kept centred as the field resizes)."""

    def __init__(self, editor: QLineEdit) -> None:
        super().__init__(editor)
        self.editor = editor
        self.setObjectName("iconButtonSmall")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.clicked.connect(self.toggle)
        editor.setTextMargins(0, 0, 34, 0)
        editor.installEventFilter(self)
        editor.setProperty("revealAction", True)
        self.sync()

    def toggle(self) -> None:
        hidden = self.editor.echoMode() == QLineEdit.EchoMode.Password
        self.editor.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.sync()

    def sync(self) -> None:
        from .icons import set_button_icon

        shown = self.editor.echoMode() == QLineEdit.EchoMode.Normal
        set_button_icon(self, "eye-off" if shown else "eye", "text2", 18)
        label = "Hide password" if shown else "Show password"
        self.setToolTip(label)
        self.setAccessibleName(label)

    def eventFilter(self, watched: Any, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if watched is self.editor and event.type() == QEvent.Type.Resize:
            self.move(self.editor.width() - self.width() - 5, (self.editor.height() - self.height()) // 2)
        return False


def set_table_defaults(table: QTableWidget, **options: Any) -> None:
    """The shared table style (see ``desktop_ui.tables.prepare_table``) with content-sized columns."""
    from .tables import prepare_table

    prepare_table(table, **options)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)


def icon_pixmap_label(name: str, role: str = "text2", size: int = 16) -> ThemedIconLabel:
    """A small theme-following icon (alias kept short for page code)."""
    return ThemedIconLabel(name, role, size)


__all__ = [
    "Alert", "Avatar", "Badge", "BarChart", "BarRow", "Card", "CountChip", "DefinitionList", "EmptyState",
    "HBarList", "IconChip", "KpiCard", "MetricGrid", "MiniMetric", "PageHeader", "Pager", "PasswordRules",
    "RevealButton", "SearchField", "SectionCard", "SORT_ROLE", "SortableItem", "SwitchButton", "Toast", "badge_colors", "bulk_table_update", "icon_pixmap_label", "initials",
    "labeled_field", "paint_badge", "pixmap", "repolish", "set_shown", "set_table_defaults", "sortable_item",
]
