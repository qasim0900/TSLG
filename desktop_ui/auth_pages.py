"""Screens shown before the CRM opens: connection problems, first-run setup, sign-in, codes."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from branding import PRODUCT_NAME
from crm.errors import DomainError, ValidationFailed
from crm.security.passwords import MIN_LENGTH

from .support import explain
from .session import AppContext, ConnectionProblem


class _CenteredCard(QWidget):
    """A narrow card centred in the CRM area, with a heading, text, form rows, and an error line."""

    def __init__(self, heading: str, intro: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setMaximumWidth(480)
        self.card.setMinimumWidth(340)
        row.addWidget(self.card, 3)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)
        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(28, 24, 28, 22)
        self.body.setSpacing(10)
        self.heading = QLabel(heading)
        self.heading.setObjectName("dialogTitle")
        self.heading.setWordWrap(True)
        self.body.addWidget(self.heading)
        self.intro = QLabel(intro)
        self.intro.setObjectName("dialogSubtitle")
        self.intro.setWordWrap(True)
        self.intro.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(self.intro)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.hide()
        self.notice = QLabel()
        self.notice.setObjectName("statusMessage")
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.hide()
        self.body.addWidget(self.notice)
        self.body.addWidget(self.error)
        self._inputs: dict[str, QLineEdit] = {}

    def field(self, name: str, label: str, *, password: bool = False, placeholder: str = "") -> QLineEdit:
        caption = QLabel(label)
        caption.setObjectName("fieldLabel")
        editor = QLineEdit()
        editor.setPlaceholderText(placeholder)
        editor.setAccessibleName(label)
        if password:
            editor.setEchoMode(QLineEdit.EchoMode.Password)
        caption.setBuddy(editor)
        self.body.addWidget(caption)
        self.body.addWidget(editor)
        self._inputs[name] = editor
        return editor

    def button(self, text: str, handler: Callable[[], object], *, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("primaryButton" if primary else "secondaryButton")
        button.clicked.connect(lambda _checked=False: handler())
        self.body.addWidget(button)
        return button

    def link(self, text: str, handler: Callable[[], object]) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("compactButton")
        button.setFlat(True)
        button.clicked.connect(lambda _checked=False: handler())
        self.body.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
        return button

    def show_error(self, exc: BaseException | str) -> None:
        if isinstance(exc, str):
            text = exc
        else:
            heading, details = explain(exc)
            text = heading + (f"\n{details}" if details else "")
        self.error.setText(text)
        self.error.show()

    def show_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def clear_messages(self) -> None:
        self.error.hide()
        self.notice.hide()

    def clear_passwords(self) -> None:
        for editor in self._inputs.values():
            if editor.echoMode() == QLineEdit.EchoMode.Password:
                editor.clear()


class ConnectionPage(_CenteredCard):
    retry_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Techset LeadGen cannot open its database", "", parent)
        self.details = QLabel()
        self.details.setObjectName("statusMessage")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.addWidget(self.details)
        self.retry_button = self.button("Try again", self.retry_requested.emit, primary=True)

    def show_problem(self, problem: ConnectionProblem) -> None:
        self.heading.setText(problem.message)
        self.intro.setText("Nothing was changed. The details below help your administrator; "
                           "backups are kept in the data folder's backups subfolder.")
        self.details.setText(problem.details)
        self.retry_button.setVisible(problem.retry)


class SetupPage(_CenteredCard):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(
            "Welcome to Techset LeadGen",
            "Create the first administrator account (Super Admin) to start. Your existing sales, leads, "
            "and clients stay as they are. You can invite colleagues afterwards and give each a role.",
            parent,
        )
        self.context = context
        self.location = QLabel()
        self.location.setObjectName("statusMessage")
        self.location.setWordWrap(True)
        self.body.insertWidget(2, self.location)
        self.organization = self.field("organization_name", "Organization name", placeholder="Techset Solutions")
        self.name = self.field("admin_name", "Your full name")
        self.email = self.field("admin_email", "Your work email")
        self.password = self.field("password", f"Password (at least {MIN_LENGTH} characters)", password=True)
        self.confirm = self.field("confirm", "Repeat password", password=True)
        self.confirm.returnPressed.connect(self.submit)
        self.create_button = self.button("Create organization and sign in", self.submit, primary=True)

    def prepare(self) -> None:
        self.clear_messages()
        self.location.setText(f"Data will be stored in: {self.context.settings.display_database}")

    def submit(self) -> bool:
        self.clear_messages()
        if self.password.text() != self.confirm.text():
            self.show_error("The passwords do not match.")
            return False
        try:
            self.context.create_organization(
                organization_name=self.organization.text(), admin_name=self.name.text(),
                email=self.email.text(), password=self.password.text(),
            )
        except (DomainError, ConnectionProblem, SQLAlchemyError) as exc:
            if isinstance(exc, ValidationFailed) and exc.fields:
                self.show_error(exc.message + "\n" + "\n".join(f"• {self._label(name)}: {message}"
                                                               for name, message in exc.fields.items()))
            else:
                self.show_error(exc)
            return False
        self.clear_passwords()
        return True

    @staticmethod
    def _label(name: str) -> str:
        return {"organization_name": "Organization name", "admin_name": "Your full name",
                "admin_email": "Your work email", "password": "Password"}.get(name, name)


class SignInPage(_CenteredCard):
    code_requested = Signal()

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(f"Sign in to {PRODUCT_NAME}", "", parent)
        self.context = context
        self.email = self.field("email", "Email")
        self.password = self.field("password", "Password", password=True)
        self.password.returnPressed.connect(self.submit)
        self.email.returnPressed.connect(self.password.setFocus)
        self.sign_in_button = self.button("Sign in", self.submit, primary=True)
        self.link("I have an activation or password-reset code", self.code_requested.emit)
        self.location = QLabel()
        self.location.setObjectName("statusMessage")
        self.location.setWordWrap(True)
        self.body.addWidget(self.location)

    def prepare(self, notice: str = "") -> None:
        self.clear_messages()
        self.clear_passwords()
        self.show_notice(notice)
        self.intro.setText("Use the account your administrator created for you. "
                           "Forgot your password? Ask an administrator for a reset code.")
        self.location.setText(f"Database: {self.context.settings.display_database}")
        (self.password if self.email.text() else self.email).setFocus(Qt.FocusReason.OtherFocusReason)

    def submit(self) -> bool:
        self.clear_messages()
        try:
            self.context.sign_in(self.email.text(), self.password.text())
        except (DomainError, ConnectionProblem, SQLAlchemyError) as exc:
            self.password.clear()
            self.show_error(exc)
            return False
        self.clear_passwords()
        return True


class CodePage(_CenteredCard):
    back_requested = Signal()

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(
            "Activate your account or reset your password",
            "Enter the one-time code your administrator gave you, then choose your password.",
            parent,
        )
        self.context = context
        self.code = self.field("code", "One-time code")
        self.code.returnPressed.connect(self.check_code)
        self.check_button = self.button("Continue", self.check_code, primary=True)
        self.who = QLabel()
        self.who.setObjectName("sectionTitle")
        self.who.setWordWrap(True)
        self.who.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(self.who)
        self.password = self.field("password", f"New password (at least {MIN_LENGTH} characters)", password=True)
        self.confirm = self.field("confirm", "Repeat new password", password=True)
        self.confirm.returnPressed.connect(self.submit)
        self.save_button = self.button("Set password and sign in", self.submit, primary=True)
        self.link("Back to sign-in", self.back_requested.emit)
        self._password_rows = [self.password, self.confirm, self.save_button, self.who]

    def prepare(self) -> None:
        self.clear_messages()
        self.clear_passwords()
        self.code.clear()
        self.code.setReadOnly(False)
        self.check_button.show()
        for widget in self._password_rows:
            widget.hide()
        for label in self.card.findChildren(QLabel):
            if label.buddy() in (self.password, self.confirm):
                label.hide()
        self.code.setFocus(Qt.FocusReason.OtherFocusReason)

    def check_code(self) -> bool:
        self.clear_messages()
        try:
            info = self.context.describe_code(self.code.text())
        except (DomainError, ConnectionProblem, SQLAlchemyError) as exc:
            self.show_error(exc)
            return False
        action = "Activate the account" if info.purpose == "invite" else "Reset the password"
        self.who.setText(f"{action} for {info.full_name} ({info.email})")
        self.code.setReadOnly(True)
        self.check_button.hide()
        for widget in self._password_rows:
            widget.show()
        for label in self.card.findChildren(QLabel):
            if label.buddy() in (self.password, self.confirm):
                label.show()
        self.password.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def submit(self) -> bool:
        self.clear_messages()
        if self.password.text() != self.confirm.text():
            self.show_error("The passwords do not match.")
            return False
        try:
            self.context.redeem_code(self.code.text(), self.password.text())
        except (DomainError, ConnectionProblem, SQLAlchemyError) as exc:
            self.show_error(exc)
            return False
        self.clear_passwords()
        return True


__all__ = ["CodePage", "ConnectionPage", "SetupPage", "SignInPage"]
