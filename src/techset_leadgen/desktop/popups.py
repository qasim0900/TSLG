from __future__ import annotations

from PySide6.QtCore import QDate, QEvent, QModelIndex, QObject, QPersistentModelIndex, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
)
from shiboken6 import Shiboken

from techset_leadgen.desktop.icons import pixmap, set_button_icon
from techset_leadgen.desktop.theme import calendar_stylesheet, is_dark, tokens


class ComboDelegate(QStyledItemDelegate):
    def __init__(self, combo: QComboBox) -> None:
        super().__init__(combo)

    def sizeHint(self, option: QStyleOptionViewItem,
                 index: QModelIndex | QPersistentModelIndex) -> QSize:
        hint = super().sizeHint(option, index)
        return QSize(hint.width() + 36, max(hint.height(), 38))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex | QPersistentModelIndex) -> None:
        t = tokens()
        combo = self.parent()
        chosen = isinstance(combo, QComboBox) and index.row() == combo.currentIndex()
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver) or bool(
            option.state & QStyle.StateFlag.State_Selected)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        rect = QRectF(option.rect).adjusted(0, 1, 0, -1)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if chosen or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t["tint"] if chosen else t["hover"]))
            painter.drawRoundedRect(rect, 8, 8)
        font = QFont(option.font)
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Bold if chosen else QFont.Weight.Normal)
        painter.setFont(font)
        color = t["primaryInk"] if chosen else t["text"] if enabled else t["text2"]
        painter.setPen(QColor(color))
        shift = 2 if hovered and not chosen else 0
        text_rect = rect.adjusted(10 + shift, 0, -34, 0)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(text_rect.width())))
        if chosen:
            image = pixmap("check", t["primaryInk"], 16, 2.2)
            painter.drawPixmap(int(rect.right() - 26), int(rect.center().y() - 8), image)
        painter.restore()


class _CalendarFooter(QFrame):
    def __init__(self, calendar: QCalendarWidget, editor: QDateEdit) -> None:
        super().__init__(calendar)
        self.setObjectName("calendarFooter")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 10)
        row.setSpacing(8)
        clear = QPushButton("Clear")
        clear.setObjectName("ghostButton")
        today = QPushButton("Today")
        today.setObjectName("todayButton")
        optional = bool(editor.specialValueText())
        clear.setVisible(optional)
        row.addWidget(clear)
        row.addStretch(1)
        row.addWidget(today)

        def close_with(value: QDate) -> None:
            if not Shiboken.isValid(editor):
                return
            editor.setDate(value)
            calendar.window().hide()

        clear.clicked.connect(lambda: close_with(editor.minimumDate()))
        today.clicked.connect(lambda: close_with(QDate.currentDate()))


def style_calendar(calendar: QCalendarWidget, editor: QDateEdit | None = None) -> None:
    if calendar.property("designCalendar"):
        return
    calendar.setProperty("designCalendar", True)
    calendar.setGridVisible(False)
    calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
    calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
    calendar.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
    calendar.setMinimumSize(300, 320)
    refresh_calendar(calendar)
    for name, icon_name in (("qt_calendar_prevmonth", "chevron-left"), ("qt_calendar_nextmonth", "chevron-right")):
        button = calendar.findChild(QToolButton, name)
        if button is not None:
            set_button_icon(button, icon_name, "text", 16)
    layout = calendar.layout()
    if editor is not None and layout is not None:
        layout.addWidget(_CalendarFooter(calendar, editor))


def refresh_calendar(calendar: QCalendarWidget) -> None:
    t = tokens()
    header = QTextCharFormat()
    header.setForeground(QColor(t["text2"]))
    header.setFontWeight(QFont.Weight.Bold)
    calendar.setHeaderTextFormat(header)
    plain = QTextCharFormat()
    plain.setForeground(QColor(t["text"]))
    for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
        calendar.setWeekdayTextFormat(day, plain)
    today = QTextCharFormat()
    today.setForeground(QColor(t["primaryInk"]))
    today.setFontWeight(QFont.Weight.ExtraBold)
    today.setBackground(QColor(t["tint"]))
    calendar.setDateTextFormat(QDate.currentDate(), today)
    dark = is_dark()
    if calendar.property("calendarDark") != dark:
        calendar.setProperty("calendarDark", dark)
        calendar.setStyleSheet(calendar_stylesheet(dark))


class PopupStyler(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        try:
            if kind == QEvent.Type.Polish:
                if isinstance(watched, QComboBox) and not isinstance(watched.view().itemDelegate(), ComboDelegate):
                    watched.view().setItemDelegate(ComboDelegate(watched))
                elif isinstance(watched, QCalendarWidget) and not watched.property("designCalendar"):
                    editor = watched.window().parentWidget()
                    style_calendar(watched, editor if isinstance(editor, QDateEdit) else None)
            elif kind == QEvent.Type.Show and isinstance(watched, QCalendarWidget) \
                    and watched.property("calendarDark") != is_dark():
                calendar = watched
                QTimer.singleShot(0, lambda: refresh_calendar(calendar) if Shiboken.isValid(calendar) else None)
        except RuntimeError:
            pass
        return False


__all__ = ["ComboDelegate", "PopupStyler", "refresh_calendar", "style_calendar"]

