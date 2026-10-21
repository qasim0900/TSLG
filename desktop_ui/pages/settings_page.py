"""Profile, password, organization, and local-data settings for the signed-in user."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from branding import PRODUCT_NAME, PRODUCT_VERSION
from crm import migrations_util
from crm.errors import ValidationFailed
from crm.schemas import OrganizationUpdate, PasswordChange, ProfileUpdate, parse
from crm.security.passwords import MIN_LENGTH
from crm.services import auth, maintenance, users
from crm.services.access import Actor
from crm.services.normalize import all_timezones
from crm.vocabulary import ROLES

from ..widgets import Card
from ..support import attempt, label
from ..session import AppContext
from ..forms import FieldSpec, FormDialog


@dataclass(frozen=True)
class _Snapshot:
    name: str
    email: str
    role: str
    timezone: str
    organization: str
    revision: str | None


class SettingsPage(QWidget):
    status_requested = Signal(str)
    sign_out_requested = Signal()

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("settingsPage")
        self._forms: list[QFormLayout] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("pageScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("pageBody")
        scroll.setWidget(body)
        outer.addWidget(scroll)
        root = QVBoxLayout(body)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(14)
        title = QLabel("Settings")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        self.profile = self._section(root, "Your account", [
            ("Edit profile…", self.edit_profile), ("Change password…", self.change_password),
            ("Sign out", self.sign_out_requested.emit),
        ])
        self.organization = self._section(root, "Organization", [("Rename…", self.rename_organization)])
        self.storage = self._section(root, "Data & backups", [("Back up now…", self.backup)])
        root.addStretch(1)
        self.loaded = False
        self.organization_name = ""
        self._update_form_layout()

    def _section(self, root: QVBoxLayout, heading: str, actions: list[tuple[str, object]]) -> dict[str, object]:
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        title = QLabel(heading)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._forms.append(form)
        layout.addLayout(form)
        row = QHBoxLayout()
        buttons: dict[str, QPushButton] = {}
        for text, handler in actions:
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, h=handler: h())
            row.addWidget(button)
            buttons[text] = button
        row.addStretch(1)
        layout.addLayout(row)
        root.addWidget(card)
        return {"card": card, "form": form, "buttons": buttons}

    @staticmethod
    def _show(section: dict[str, object], rows: list[tuple[str, str]]) -> None:
        form = section["form"]
        assert isinstance(form, QFormLayout)
        while form.rowCount():
            form.removeRow(0)
        for name, value in rows:
            key = QLabel(name)
            key.setObjectName("fieldLabel")
            shown = QLabel(value)
            shown.setWordWrap(True)
            shown.setTextFormat(Qt.TextFormat.PlainText)
            shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            shown.setSizePolicy(shown.sizePolicy().Policy.Expanding, shown.sizePolicy().Policy.Preferred)
            shown.setMinimumWidth(0)
            form.addRow(key, shown)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._update_form_layout()

    def _update_form_layout(self) -> None:
        """Stack labels over values when the Settings page is narrow."""
        policy = (
            QFormLayout.RowWrapPolicy.WrapAllRows
            if self.width() < 760
            else QFormLayout.RowWrapPolicy.DontWrapRows
        )
        for form in self._forms:
            form.setRowWrapPolicy(policy)

    def ensure_loaded(self) -> None:
        if not self.loaded:
            self.refresh()

    def refresh(self) -> None:
        settings = self.context.settings

        def work(db: Session, actor: Actor) -> _Snapshot:
            me = users.get_user(db, actor, actor.user_id)
            organization = users.get_organization(db)
            current, _head = migrations_util.current_and_head(db.connection())
            return _Snapshot(me.full_name, me.email, me.role, me.timezone, organization.name, current)

        ok, data = attempt(self, self.context, work)
        if not ok or data is None:
            return
        revision = data.revision
        self.organization_name = data.organization
        actor = self.context.actor
        self._show(self.profile, [("Name", data.name), ("Email", data.email), ("Role", label(ROLES, data.role)),
                                  ("Time zone", f"{data.timezone} (used for due dates and “today”)")])
        self._show(self.organization, [("Name", data.organization)])
        self._show(self.storage, [
            ("Location", settings.display_database),
            ("Holds", "Sales, clients, leads, contacts, tasks, accounts, and the audit log"),
            ("Data format version", revision or "—"),
            ("Last automatic backup", str(self.context.last_backup) if self.context.last_backup else
             "None needed this session (taken before every schema upgrade)"),
            ("Signed in from", self.context.client_host),
            ("Application", f"{PRODUCT_NAME} {PRODUCT_VERSION}"),
            ("Session", f"Ends after {settings.session_idle_minutes} minutes without activity, "
                        f"and after {settings.session_absolute_hours} hours at most."),
        ])
        can_manage = actor is not None and actor.can("org.manage")
        self.organization["buttons"]["Rename…"].setVisible(can_manage)  # type: ignore[index]
        self.storage["buttons"]["Back up now…"].setVisible(can_manage)  # type: ignore[index]
        self.loaded = True

    # ------------------------------------------------------------ actions

    def edit_profile(self) -> None:
        actor = self.context.actor
        if actor is None:
            return

        def submit(dialog: FormDialog) -> None:
            data = parse(ProfileUpdate, dialog.changed())
            self.context.write("user", lambda db, actor: users.update_profile(db, actor, data))

        dialog = FormDialog(self, title="Profile", heading="Edit your profile", columns=1, submit=submit,
                            values={"full_name": actor.full_name, "timezone": actor.timezone},
                            fields=[FieldSpec("full_name", "Full name", required=True),
                                    FieldSpec("timezone", "Time zone", "choice",
                                              [(zone, zone) for zone in all_timezones()], blank=None,
                                              searchable=True)])
        if dialog.exec():
            self.refresh()
            self.status_requested.emit("Profile saved")

    def change_password(self) -> None:
        session_id = self.context.session_id

        def submit(dialog: FormDialog) -> int:
            values = dialog.values()
            if values["new_password"] != values["confirm"]:
                raise ValidationFailed("The new passwords do not match.", fields={"confirm": "Type the same password twice."})
            data = parse(PasswordChange, {"current_password": values["current_password"],
                                          "new_password": values["new_password"]})
            return self.context.run(lambda db, actor: auth.change_password(
                db, actor, current_session_id=session_id, current_password=data.current_password,
                new_password=data.new_password))

        dialog = FormDialog(self, title="Password", heading="Change your password", columns=1, submit=submit,
                            note=f"Use at least {MIN_LENGTH} characters. Your other sign-ins (other computers) "
                                 "end when the password changes.",
                            fields=[FieldSpec("current_password", "Current password", "password", required=True),
                                    FieldSpec("new_password", "New password", "password", required=True),
                                    FieldSpec("confirm", "Repeat new password", "password", required=True)],
                            submit_text="Change password")
        if dialog.exec():
            ended = dialog.result_value or 0
            self.status_requested.emit(f"Password changed. {ended} other session{'s' if ended != 1 else ''} ended.")

    def rename_organization(self) -> None:
        def submit(dialog: FormDialog) -> None:
            data = parse(OrganizationUpdate, dialog.values())
            self.context.write("organization", lambda db, actor: users.update_organization(db, actor, data))

        dialog = FormDialog(self, title="Organization", heading="Rename the organization", columns=1,
                            submit=submit, values={"name": self.organization_name},
                            fields=[FieldSpec("name", "Organization name", required=True)])
        if dialog.exec():
            self.refresh()
            self.status_requested.emit("Organization renamed")

    def backup(self) -> None:
        settings = self.context.settings
        suggested = f"techset-leadgen-backup-{datetime.now():%Y%m%d-%H%M}.db"
        path, _filter = QFileDialog.getSaveFileName(
            self, "Back up application data", suggested, "Backup file (*.db)"
        )
        if not path:
            return
        ok, written = attempt(self, self.context,
                              lambda db, actor: maintenance.backup(db, actor, settings, path), title="Backup")
        if ok and isinstance(written, Path):
            self.status_requested.emit(f"Backup saved to {written}")


__all__ = ["SettingsPage"]
