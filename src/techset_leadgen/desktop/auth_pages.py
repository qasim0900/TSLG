from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QFont, QIcon, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import SQLAlchemyError

from techset_leadgen.branding import LOGO_ASSET, PARENT_BRAND, PRODUCT_NAME, PRODUCT_TAGLINE, PRODUCT_VERSION, WORDMARK_PARTS
from techset_leadgen.errors import DomainError, ValidationFailed

from techset_leadgen.desktop.icons import ThemedIconLabel, pixmap, set_button_icon
from techset_leadgen.desktop.support import explain
from techset_leadgen.desktop.session import AppContext, ConnectionProblem
from techset_leadgen.desktop.theme import BRAND_GREEN, INK, SECONDARY, TEXT_ON_DARK, apply_mono, asset_path, mono_font
from techset_leadgen.desktop.widgets import Alert, PasswordRules, RevealButton, set_shown

_BRAND_MUTED = "#B7BDBA"
_FEATURES = (
    ("assignments", "Clear ownership every day", "Distribute LinkedIn profiles and see what remains."),
    ("followups", "Follow-ups do not disappear", "Keep due and overdue commitments tied to each prospect."),
    ("lock", "Controlled and auditable", "Role-based access and a durable history protect team work."),
)


class BrandPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("authBrand")
        self.setStyleSheet(f"QFrame#authBrand {{ background: {INK}; border: 0; }}"
                           f"QFrame#authBrand QLabel {{ color: {TEXT_ON_DARK}; background: transparent; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 48, 56, 48)
        layout.setSpacing(40)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(QIcon(str(asset_path(LOGO_ASSET))).pixmap(QSize(40, 40)))
        logo.setFixedSize(40, 40)
        logo.setAccessibleName("Techset Solutions logo")
        brand.addWidget(logo)
        words = QVBoxLayout()
        words.setSpacing(7)
        name = QLabel(f'<span style="font-weight:800">{WORDMARK_PARTS[0]}</span>'
                      f'<span style="font-weight:500; color:{BRAND_GREEN}">&nbsp;{WORDMARK_PARTS[1]}</span>')
        name.setTextFormat(Qt.TextFormat.RichText)
        name.setAccessibleName(PRODUCT_NAME)
        name.setStyleSheet("font-size: 22px;")
        tagline_row = QHBoxLayout()
        tagline_row.setSpacing(8)
        rule = QLabel()
        rule.setFixedSize(18, 2)
        rule.setStyleSheet(f"background: {SECONDARY}; border-radius: 1px;")
        tagline = QLabel(PRODUCT_TAGLINE.upper())
        font = QFont(tagline.font())
        font.setPixelSize(10)
        font.setWeight(QFont.Weight.Bold)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        tagline.setFont(font)
        tagline.setStyleSheet(f"color: {_BRAND_MUTED};")
        tagline_row.addWidget(rule, 0, Qt.AlignmentFlag.AlignVCenter)
        tagline_row.addWidget(tagline)
        tagline_row.addStretch(1)
        words.addWidget(name)
        words.addLayout(tagline_row)
        brand.addLayout(words, 1)
        layout.addLayout(brand)
        layout.addStretch(1)

        headline = QLabel(
            f'Every assignment and follow-up in <span style="color:{BRAND_GREEN}">one clear workflow.</span>')
        headline.setTextFormat(Qt.TextFormat.RichText)
        headline.setWordWrap(True)
        headline.setMaximumWidth(520)
        headline.setStyleSheet("font-size: 38px; font-weight: 800;")
        layout.addWidget(headline)

        self.features = QWidget()
        features = QVBoxLayout(self.features)
        features.setContentsMargins(0, 0, 0, 0)
        features.setSpacing(18)
        for icon_name, title, text in _FEATURES:
            row = QHBoxLayout()
            row.setSpacing(14)
            chip = QLabel()
            chip.setFixedSize(40, 40)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setPixmap(pixmap(icon_name, BRAND_GREEN, 18))
            chip.setStyleSheet("background: #122321; border: 1px solid #26332F; border-radius: 11px;")
            row.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
            copy = QVBoxLayout()
            copy.setSpacing(2)
            heading = QLabel(title)
            heading.setStyleSheet("font-size: 14px; font-weight: 700;")
            detail = QLabel(text)
            detail.setWordWrap(True)
            detail.setStyleSheet(f"font-size: 13px; color: {_BRAND_MUTED};")
            copy.addWidget(heading)
            copy.addWidget(detail)
            row.addLayout(copy, 1)
            features.addLayout(row)
        layout.addWidget(self.features)
        layout.addStretch(1)
        footer = QLabel(f"{PARENT_BRAND} · v{PRODUCT_VERSION}")
        footer.setStyleSheet(f"font-size: 12px; color: {_BRAND_MUTED};")
        layout.addWidget(footer)


class _CenteredCard(QWidget):
    def __init__(self, heading: str, intro: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.brand_panel = BrandPanel()
        self.brand_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self.brand_panel, 105)

        scroll = QScrollArea()
        scroll.setObjectName("pageScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        side = QWidget()
        side.setObjectName("authFormSide")
        scroll.setWidget(side)
        outer.addWidget(scroll, 100)
        centre = QVBoxLayout(side)
        centre.setContentsMargins(24, 40, 24, 40)
        centre.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.card = QWidget()
        self.card.setMaximumWidth(400)
        self.card.setMinimumWidth(300)
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(self.card, 10)
        row.addStretch(1)
        centre.addLayout(row)
        centre.addStretch(1)

        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(20)
        title_block = QVBoxLayout()
        title_block.setSpacing(6)
        self.heading = QLabel(heading)
        self.heading.setObjectName("dialogTitle")
        self.heading.setStyleSheet("font-size: 26px; font-weight: 800;")
        self.heading.setWordWrap(True)
        title_block.addWidget(self.heading)
        self.intro = QLabel(intro)
        self.intro.setObjectName("pageSubtitle")
        self.intro.setStyleSheet("font-size: 14px;")
        self.intro.setWordWrap(True)
        self.intro.setTextFormat(Qt.TextFormat.PlainText)
        title_block.addWidget(self.intro)
        self.body.addLayout(title_block)
        set_shown(self.intro, bool(intro))
        self.notice = Alert("", "info")
        self.error = Alert("", "error")
        self.error.setAccessibleName("Error")
        self.body.addWidget(self.notice)
        self.body.addWidget(self.error)
        self._inputs: dict[str, QLineEdit] = {}
        self._blocks: dict[str, QWidget] = {}
        self._rule_updaters: list[Callable[[], None]] = []

    def refresh_rules(self, *, tried: bool = False) -> None:
        for editor in self._inputs.values():
            if editor.property("rulesUpdate"):
                editor.setProperty("tried", tried)
        for update in self._rule_updaters:
            update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.brand_panel.setVisible(event.size().width() >= 900)
        self.brand_panel.features.setVisible(event.size().height() >= 640)

    def field(self, name: str, label: str, *, password: bool = False, placeholder: str = "",
              required: bool = True, rules: QLineEdit | None = None, rules_name: QLineEdit | None = None,
              rules_always: bool = True) -> QLineEdit:
        container = QWidget()
        block = QVBoxLayout(container)
        block.setContentsMargins(0, 0, 0, 0)
        block.setSpacing(6)
        caption_row = QHBoxLayout()
        caption_row.setSpacing(4)
        caption = QLabel(label)
        caption.setObjectName("fieldLabel")
        caption_row.addWidget(caption)
        if required:
            mark = QLabel("*")
            mark.setObjectName("requiredMark")
            mark.setAccessibleName("required")
            caption_row.addWidget(mark)
        caption_row.addStretch(1)
        editor = QLineEdit()
        editor.setPlaceholderText(placeholder)
        editor.setAccessibleName(label)
        if password:
            editor.setEchoMode(QLineEdit.EchoMode.Password)
            self._add_reveal(editor)
        caption.setBuddy(editor)
        block.addLayout(caption_row)
        block.addWidget(editor)
        if rules is not None:
            checklist = PasswordRules()
            block.addWidget(checklist)
            email = rules

            def update(_text: str = "") -> None:
                value = editor.text()
                checklist.set_owner(email.text(), rules_name.text() if rules_name else "")
                checklist.update_rules(value, tried=bool(editor.property("tried")))
                set_shown(checklist, rules_always or bool(value) or bool(editor.property("tried")))

            editor.textChanged.connect(update)
            email.textChanged.connect(update)
            if rules_name is not None:
                rules_name.textChanged.connect(update)
            editor.setProperty("rulesUpdate", True)
            self._rule_updaters.append(update)
            update()
        self.body.addWidget(container)
        self._inputs[name] = editor
        self._blocks[name] = container
        return editor

    def field_block(self, name: str) -> QWidget:
        return self._blocks[name]

    @staticmethod
    def _add_reveal(editor: QLineEdit) -> None:
        RevealButton(editor)

    def button(self, text: str, handler: Callable[[], object], *, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("primaryButton" if primary else "secondaryButton")
        button.clicked.connect(lambda _checked=False: handler())
        self.body.addWidget(button)
        return button

    def link(self, text: str, handler: Callable[[], object]) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("linkButton")
        button.setFlat(True)
        button.clicked.connect(lambda _checked=False: handler())
        self.body.addWidget(button)
        return button

    def location_row(self) -> QLabel:
        holder = QFrame()
        holder.setObjectName("cardFooter")
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 16, 0, 0)
        row.setSpacing(10)
        row.addWidget(ThemedIconLabel("database", "text2", 16), 0, Qt.AlignmentFlag.AlignTop)
        label = QLabel()
        label.setObjectName("helperText")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(label, 1)
        self.body.addWidget(holder)
        return label

    @staticmethod
    def show_location(label: QLabel, location: str, *, server: bool = False) -> None:
        mono = mono_font(11).family()
        safe = location.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        label.setTextFormat(Qt.TextFormat.RichText)
        kind = "Team database" if server else "Local database"
        label.setText(f'{kind} · <span style="font-family:\'{mono}\'; font-size:11px">{safe}</span>')
        label.setToolTip(location)

    def show_error(self, exc: BaseException | str) -> None:
        if isinstance(exc, str):
            text = exc
        else:
            heading, details = explain(exc)
            text = heading + (f"\n{details}" if details else "")
        self.error.set_message(text)

    def show_notice(self, text: str) -> None:
        self.notice.set_message(text)

    def clear_messages(self) -> None:
        self.error.set_message("")
        self.notice.set_message("")

    def clear_passwords(self) -> None:
        for editor in self._inputs.values():
            if editor.property("revealAction"):
                editor.clear()
                editor.setEchoMode(QLineEdit.EchoMode.Password)
                reveal = editor.findChild(RevealButton)
                if reveal is not None:
                    reveal.sync()


class ConnectionPage(_CenteredCard):
    retry_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(f"{PRODUCT_NAME} cannot open its database", "", parent)
        self.details = QLabel()
        self.details.setObjectName("statusMessage")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        apply_mono(self.details, 12)
        self.body.addWidget(self.details)
        self.retry_button = self.button("Try again", self.retry_requested.emit, primary=True)

    def show_problem(self, problem: ConnectionProblem) -> None:
        self.heading.setText(problem.message)
        self.intro.setText("Nothing was changed. The details below help your administrator; "
                           "backups are kept in the data folder's backups subfolder.")
        self.intro.show()
        self.details.setText(problem.details)
        self.retry_button.setVisible(problem.retry)


class SetupPage(_CenteredCard):
    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(
            f"Welcome to {PRODUCT_NAME}",
            "Create the first administrator account (Super Admin) to start. Your existing sales, leads, "
            "and clients stay as they are. You can invite colleagues afterwards and give each a role.",
            parent,
        )
        self.context = context
        self.organization = self.field("organization_name", "Organization name", placeholder=PARENT_BRAND)
        self.name = self.field("admin_name", "Your full name", placeholder="e.g. Ayesha Malik")
        self.email = self.field("admin_email", "Your work email", placeholder="name@company.com")
        self.password = self.field("password", "Password", password=True, rules=self.email, rules_name=self.name)
        self.confirm = self.field("confirm", "Repeat password", password=True)
        self.confirm.returnPressed.connect(self.submit)
        self.create_button = self.button("Create organization and sign in", self.submit, primary=True)
        self.location = self.location_row()

    def prepare(self) -> None:
        self.clear_messages()
        self.show_location(self.location, self.context.settings.display_database,
                           server=self.context.is_server)

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
        super().__init__("Sign in", "Use the account your administrator created for you.", parent)
        self.context = context
        self.email = self.field("email", "Email", placeholder="name@company.com")
        self.password = self.field("password", "Password", password=True, placeholder="Enter your password")
        self.password.returnPressed.connect(self.submit)
        self.email.returnPressed.connect(self.password.setFocus)
        self.sign_in_button = self.button("Sign in", self.submit, primary=True)
        self.code_button = self.link("I have an activation or password-reset code", self.code_requested.emit)
        hint = QLabel("Forgot your password? Ask an administrator for a reset code.")
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        self.body.addWidget(hint)
        self.location = self.location_row()
        self.body.setSpacing(18)

    def prepare(self, notice: str = "") -> None:
        self.clear_messages()
        self.clear_passwords()
        if notice and "sign in" not in notice.casefold():
            notice = f"{notice.rstrip('.')}. Sign in again to continue."
        self.show_notice(notice)
        self.show_location(self.location, self.context.settings.display_database,
                           server=self.context.is_server)
        (self.password if self.email.text() else self.email).setFocus(Qt.FocusReason.OtherFocusReason)

    def submit(self) -> bool:
        self.clear_messages()
        try:
            self.context.sign_in(self.email.text(), self.password.text())
        except (DomainError, ConnectionProblem, SQLAlchemyError) as exc:
            self.password.clear()
            self.show_error(exc)
            self.refresh_rules(tried=True)
            return False
        self.clear_passwords()
        self.refresh_rules(tried=False)
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
        self.code = self.field("code", "One-time code", placeholder="e.g. 7KQ2-M9XD")
        apply_mono(self.code, 14)
        self.code.returnPressed.connect(self.check_code)
        self.check_button = self.button("Continue", self.check_code, primary=True)
        self.who = QLabel()
        self.who.setObjectName("sectionTitle")
        self.who.setWordWrap(True)
        self.who.setTextFormat(Qt.TextFormat.PlainText)
        self.body.addWidget(self.who)
        self._account_email = QLineEdit(self)
        self._account_email.hide()
        self._account_name = QLineEdit(self)
        self._account_name.hide()
        self.password = self.field("password", "New password", password=True, rules=self._account_email,
                                   rules_name=self._account_name)
        self.confirm = self.field("confirm", "Repeat new password", password=True)
        self.confirm.returnPressed.connect(self.submit)
        self.save_button = self.button("Set password and sign in", self.submit, primary=True)
        self.link("Back to sign-in", self.back_requested.emit)
        self._password_rows = [self.field_block("password"), self.field_block("confirm"),
                               self.save_button, self.who]

    def prepare(self) -> None:
        self.clear_messages()
        self.clear_passwords()
        self.code.clear()
        self.code.setReadOnly(False)
        self.check_button.show()
        for widget in self._password_rows:
            widget.hide()
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
        self._account_email.setText(info.email)
        self._account_name.setText(info.full_name)
        for widget in self._password_rows:
            widget.show()
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


__all__ = ["BrandPanel", "CodePage", "ConnectionPage", "SetupPage", "SignInPage"]

