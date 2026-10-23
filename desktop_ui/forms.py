"""Declarative record forms with inline, per-field validation messages.

A ``FormDialog`` is built from ``FieldSpec`` items. Saving calls the page's
``submit`` function inside the dialog; a ``DomainError`` raised by the business
service keeps the dialog open and shows each field's message under that field,
so validation rules live in one place (the service layer), not in the screens.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from PySide6.QtCore import QDate, QDateTime, Qt, QTime
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from crm.errors import DomainError
from crm.services.auth import SessionEnded

from .modal import ModalDialog
from .support import report
from .widgets import PasswordRules, RevealButton

Options = Sequence[tuple[str, str]]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: str = "text"  # text, password, multiline, choice, multi, tags, int, bool, date, datetime
    options: Options = ()
    required: bool = False
    hint: str = ""
    placeholder: str = ""
    span: bool = False  # use the full width of a two-column form
    blank: str | None = "—"  # label of the empty choice; None when a value is mandatory
    searchable: bool = False  # type-to-filter for long choice lists
    read_only: bool = False
    rules: bool = False  # a new password: show the live password-policy checklist under it
    rules_owner: tuple[str, str] = ("", "")  # (email, name) of the account, for the similarity rule


def _set_text(label: str) -> str:
    """ "Set a due date", "Set a meeting date": the checkbox that turns an optional date on."""
    words = label.strip().lower()
    return f"Set a {words}" if "date" in words else f"Set a {words} date"


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class _Field:
    def __init__(self, spec: FieldSpec, timezone: str) -> None:
        self.spec = spec
        self.timezone = timezone
        self.label: QLabel | None = None
        self.editor = self._build()
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.hide()
        self.error.setAccessibleName(f"{spec.label} error")
        self.rules = PasswordRules(email=spec.rules_owner[0], name=spec.rules_owner[1]) if spec.rules else None

    # --------------------------------------------------------------- widgets

    def _build(self) -> QWidget:
        spec = self.spec
        if spec.kind in ("text", "password", "tags", "int"):
            editor = QLineEdit()
            editor.setPlaceholderText(spec.placeholder or ("Comma-separated" if spec.kind == "tags" else ""))
            if spec.kind == "password":
                editor.setEchoMode(QLineEdit.EchoMode.Password)
                RevealButton(editor)  # the eye button shows or hides what was typed
            if spec.kind == "int":
                editor.setValidator(QIntValidator(0, 100, editor))
            editor.setReadOnly(spec.read_only)
            return editor
        if spec.kind == "multiline":
            area = QPlainTextEdit()
            area.setPlaceholderText(spec.placeholder)
            area.setTabChangesFocus(True)
            area.setMinimumHeight(84)
            area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            return area
        if spec.kind == "choice":
            combo = QComboBox()
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(14)
            if spec.searchable:
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                completer = combo.completer()
                if completer is not None:
                    completer.setFilterMode(Qt.MatchFlag.MatchContains)
                    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
                line = combo.lineEdit()
                if line is not None:
                    line.setPlaceholderText(spec.placeholder or "Type to search")
            self._fill(combo, spec.options)
            combo.setEnabled(not spec.read_only)
            return combo
        if spec.kind == "multi":
            listing = QListWidget()
            for value, text in spec.options:
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, value)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                listing.addItem(item)
            listing.setMaximumHeight(150)
            return listing
        if spec.kind == "bool":
            box = QCheckBox(spec.label)
            box.setEnabled(not spec.read_only)
            return box
        if spec.kind == "date":
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            self.enabled_box = QCheckBox(_set_text(spec.label))
            self.enabled_box.setAccessibleName(f"Set {spec.label}")
            self.date_picker = QDateEdit(QDate.currentDate())
            self.date_picker.setCalendarPopup(True)
            self.date_picker.setDisplayFormat("dd MMM yyyy")
            self.date_picker.setEnabled(False)
            self.enabled_box.toggled.connect(self.date_picker.setEnabled)
            row.addWidget(self.enabled_box)
            row.addWidget(self.date_picker, 1)
            return holder
        if spec.kind == "datetime":
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            self.enabled_box = QCheckBox(_set_text(spec.label))
            self.enabled_box.setAccessibleName(f"Set {spec.label}")
            self.picker = QDateTimeEdit()
            self.picker.setCalendarPopup(True)
            self.picker.setDisplayFormat("dd MMM yyyy  HH:mm")
            # The picker shows wall-clock time in the user's profile time zone.
            tomorrow = datetime.now(ZoneInfo(self.timezone)) + timedelta(days=1)
            self._show_local(tomorrow.replace(hour=9, minute=0))
            self.picker.setEnabled(False)
            self.enabled_box.toggled.connect(self.picker.setEnabled)
            row.addWidget(self.enabled_box)
            row.addWidget(self.picker, 1)
            return holder
        raise ValueError(f"Unknown field kind {spec.kind!r}")

    def _fill(self, combo: QComboBox, options: Options) -> None:
        combo.clear()
        if self.spec.blank is not None:
            combo.addItem(self.spec.blank, None)
        for value, text in options:
            combo.addItem(text, value)

    def set_options(self, options: Options) -> None:
        assert isinstance(self.editor, QComboBox)
        current = self.value()
        self.editor.blockSignals(True)
        self._fill(self.editor, options)
        self.editor.blockSignals(False)
        self.set_value(current)

    # ---------------------------------------------------------------- values

    def value(self) -> Any:
        kind, editor = self.spec.kind, self.editor
        if kind in ("text", "password"):
            assert isinstance(editor, QLineEdit)
            return editor.text() if kind == "password" else _clean(editor.text())
        if kind == "int":
            assert isinstance(editor, QLineEdit)
            return int(editor.text()) if editor.text().strip() else None
        if kind == "tags":
            assert isinstance(editor, QLineEdit)
            return [part.strip() for part in editor.text().split(",") if part.strip()]
        if kind == "multiline":
            assert isinstance(editor, QPlainTextEdit)
            return _clean(editor.toPlainText())
        if kind == "choice":
            assert isinstance(editor, QComboBox)
            index = editor.currentIndex()
            if editor.isEditable() and editor.currentText() != editor.itemText(index):
                return None  # typed text that matches no option
            return editor.itemData(index) if index >= 0 else None
        if kind == "multi":
            assert isinstance(editor, QListWidget)
            return [editor.item(row).data(Qt.ItemDataRole.UserRole) for row in range(editor.count())
                    if editor.item(row).checkState() == Qt.CheckState.Checked]
        if kind == "bool":
            assert isinstance(editor, QCheckBox)
            return editor.isChecked()
        if kind == "date":
            if not self.enabled_box.isChecked():
                return None
            return self.date_picker.date().toString(Qt.DateFormat.ISODate)  # YYYY-MM-DD
        if kind == "datetime":
            if not self.enabled_box.isChecked():
                return None
            chosen = self.picker.dateTime()
            day, clock = chosen.date(), chosen.time()
            return datetime(day.year(), day.month(), day.day(), clock.hour(), clock.minute(),
                            tzinfo=ZoneInfo(self.timezone))
        return None

    def set_value(self, value: Any) -> None:
        kind, editor = self.spec.kind, self.editor
        if kind in ("text", "password", "int"):
            assert isinstance(editor, QLineEdit)
            editor.setText("" if value is None else str(value))
        elif kind == "tags":
            assert isinstance(editor, QLineEdit)
            editor.setText(", ".join(value or []))
        elif kind == "multiline":
            assert isinstance(editor, QPlainTextEdit)
            editor.setPlainText(value or "")
        elif kind == "choice":
            assert isinstance(editor, QComboBox)
            index = editor.findData(None if value is None else str(value))
            if index < 0 and value is not None:
                index = editor.findData(value)
            editor.setCurrentIndex(max(index, 0))
        elif kind == "multi":
            assert isinstance(editor, QListWidget)
            chosen = set(value or [])
            for row in range(editor.count()):
                item = editor.item(row)
                item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in chosen
                                   else Qt.CheckState.Unchecked)
        elif kind == "bool":
            assert isinstance(editor, QCheckBox)
            editor.setChecked(bool(value))
        elif kind == "date":
            parsed = QDate.fromString(str(value or "")[:10], Qt.DateFormat.ISODate)
            self.enabled_box.setChecked(parsed.isValid())
            if parsed.isValid():
                self.date_picker.setDate(parsed)
        elif kind == "datetime":
            self.enabled_box.setChecked(value is not None)
            if isinstance(value, datetime):
                self._show_local(value.astimezone(ZoneInfo(self.timezone)))

    def _show_local(self, local: datetime) -> None:
        self.picker.setDateTime(QDateTime(QDate(local.year, local.month, local.day), QTime(local.hour, local.minute)))

    def focus_target(self) -> QWidget:
        return self.enabled_box if self.spec.kind in ("date", "datetime") else self.editor

    def set_error(self, message: str | None) -> None:
        self.error.setText(message or "")
        self.error.setVisible(bool(message))
        target = self.focus_target()
        target.setProperty("invalid", bool(message))
        target.style().unpolish(target)  # re-apply the stylesheet for the new property value
        target.style().polish(target)


class FormDialog(ModalDialog):
    """A record form. ``submit(dialog)`` saves; raising ``DomainError`` keeps the dialog open."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        heading: str,
        fields: Sequence[FieldSpec],
        submit: Callable[[FormDialog], Any],
        values: Mapping[str, Any] | None = None,
        submit_text: str = "Save",
        note: str = "",
        timezone: str = "UTC",
        columns: int = 2,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("formDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setAccessibleName(heading)
        self._submit = submit
        self.result_value: Any = None
        self._fields: dict[str, _Field] = {spec.name: _Field(spec, timezone) for spec in fields}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(24, 20, 24, 18)
        main.setSpacing(12)
        root.addWidget(content, 1)
        heading_label = QLabel(heading)
        heading_label.setObjectName("dialogTitle")
        heading_label.setTextFormat(Qt.TextFormat.PlainText)
        heading_label.setWordWrap(True)
        main.addWidget(heading_label)
        if note:
            note_label = QLabel(note)
            note_label.setObjectName("dialogSubtitle")
            note_label.setWordWrap(True)
            note_label.setTextFormat(Qt.TextFormat.PlainText)
            main.addWidget(note_label)
        self.general_error = QLabel()
        self.general_error.setObjectName("formError")
        self.general_error.setWordWrap(True)
        self.general_error.setTextFormat(Qt.TextFormat.PlainText)
        self.general_error.hide()
        main.addWidget(self.general_error)

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 4, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        row = column = 0
        for field in self._fields.values():
            cell = self._cell(field)
            span = field.spec.span or columns == 1 or field.spec.kind in ("multiline", "multi")
            if span and column:
                row, column = row + 1, 0
            grid.addWidget(cell, row, column, 1, columns if span else 1)
            if span or column == columns - 1:
                row, column = row + 1, 0
            else:
                column += 1
        grid.setRowStretch(row + 1, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        main.addWidget(scroll, 1)

        # The design's footer: the safe choice first, the action on the right.
        footer = QFrame()
        footer.setObjectName("modalFooter")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 14, 24, 14)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        self.save_button = QPushButton(submit_text)
        self.save_button.setObjectName("primaryButton")
        self.save_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("secondaryButton")
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        self.save_button.clicked.connect(self._save)
        self.cancel_button.clicked.connect(self.reject)
        root.addWidget(footer)
        for field in self._fields.values():
            if field.rules is not None and isinstance(field.editor, QLineEdit):
                field.rules.update_rules("")
                field.editor.textChanged.connect(field.rules.update_rules)

        self._initial: dict[str, Any] = {}
        for name, value in (values or {}).items():
            if name in self._fields:
                self._fields[name].set_value(value)
        self._initial = self.values()

        width = 640 if columns > 1 else 480
        self.setMinimumWidth(min(width, 900))
        screen = self.screen()
        available = screen.availableGeometry().height() - 80 if screen else 900
        body.adjustSize()
        self.resize(width, min(body.sizeHint().height() + 210, available))
        first = next(iter(self._fields.values()), None)
        if first is not None:
            first.focus_target().setFocus(Qt.FocusReason.OtherFocusReason)

    def _cell(self, field: _Field) -> QWidget:
        cell = QWidget()
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setSpacing(6)
        spec = field.spec
        if spec.kind != "bool":
            caption = QHBoxLayout()
            caption.setSpacing(4)
            field.label = QLabel(spec.label)
            field.label.setObjectName("fieldLabel")
            field.label.setBuddy(field.focus_target())
            caption.addWidget(field.label)
            if spec.required:
                mark = QLabel("*")
                mark.setObjectName("requiredMark")
                mark.setAccessibleName("required")
                caption.addWidget(mark)
            caption.addStretch(1)
            layout.addLayout(caption)
        field.focus_target().setAccessibleName(spec.label)
        layout.addWidget(field.editor)
        if field.rules is not None:
            layout.addWidget(field.rules)
        if spec.hint:
            hint = QLabel(spec.hint)
            hint.setObjectName("helperText")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        layout.addWidget(field.error)
        return cell

    # ---------------------------------------------------------------- API

    def editor(self, name: str) -> QWidget:
        return self._fields[name].editor

    def value(self, name: str) -> Any:
        return self._fields[name].value()

    def set_value(self, name: str, value: Any) -> None:
        self._fields[name].set_value(value)

    def values(self) -> dict[str, Any]:
        return {name: field.value() for name, field in self._fields.items()}

    def changed(self) -> dict[str, Any]:
        """Only the fields the user changed (updates send nothing else)."""
        return {name: value for name, value in self.values().items() if value != self._initial.get(name)}

    def set_options(self, name: str, options: Options) -> None:
        self._fields[name].set_options(options)

    def on_change(self, name: str, callback: Callable[[FormDialog, Any], None]) -> None:
        """Call ``callback(dialog, value)`` when field ``name`` changes.

        The dialog is passed in (held weakly here) rather than captured by the
        caller's lambda: a Qt connection holding a lambda that references its
        dialog keeps the dialog alive after it closes (DEF-026).
        """
        editor = self._fields[name].editor
        dialog_ref = weakref.ref(self)

        def changed(*_args: Any) -> None:
            dialog = dialog_ref()
            if dialog is not None:
                callback(dialog, dialog.value(name))

        if isinstance(editor, QComboBox):
            editor.currentIndexChanged.connect(changed)
        elif isinstance(editor, QCheckBox):
            editor.toggled.connect(changed)

    def set_label(self, name: str, text: str) -> None:
        field = self._fields[name]
        if field.label is not None:
            field.label.setText(text)

    def set_visible(self, name: str, visible: bool) -> None:
        field = self._fields[name]
        container = field.editor.parentWidget()
        if container is not None:
            container.setVisible(visible)

    def show_errors(self, exc: DomainError) -> None:
        for field in self._fields.values():
            field.set_error(None)
        unplaced: list[str] = []
        first: _Field | None = None
        for name, message in exc.fields.items():
            target = self._fields.get(name)
            if target is None:
                unplaced.append(message)
                continue
            target.set_error(message)
            first = first or target
        general = exc.message
        if unplaced:
            general += "\n" + "\n".join(f"• {message}" for message in unplaced)
        self.general_error.setText(general)
        self.general_error.show()
        (first.focus_target() if first else self.save_button).setFocus(Qt.FocusReason.OtherFocusReason)

    def field_error(self, name: str) -> str:
        field = self._fields[name]
        return field.error.text() if field.error.isVisibleTo(self) else ""

    def _save(self) -> None:
        try:
            self.result_value = self._submit(self)
        except SessionEnded:
            self.reject()
        except DomainError as exc:
            self.show_errors(exc)
        except Exception as exc:  # database or unexpected errors: reported and logged, the form stays open
            report(self, exc)
        else:
            self.accept()


__all__ = ["FieldSpec", "FormDialog", "Options"]
