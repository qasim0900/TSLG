"""Profile, password, organization, local-data and data-clearing settings for the signed-in user."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from techset_leadgen.branding import PRODUCT_NAME, PRODUCT_VERSION
from techset_leadgen.analytics.controllers.dashboard_controller import DashboardController
from techset_leadgen.database import migrations_util
from techset_leadgen.errors import ValidationFailed
from techset_leadgen.domain.scheduling import BUFFER_MODES, WEEKDAYS, SchedulingRules, clock_minutes
from techset_leadgen.services.schemas import (
    OrganizationUpdate,
    PasswordChange,
    ProfileUpdate,
    SchedulingRulesUpdate,
    parse,
)
from techset_leadgen.security.passwords import MIN_LENGTH
from techset_leadgen.services import auth, maintenance, meetings, users
from techset_leadgen.services.access import Actor
from techset_leadgen.services.pagination import PageRequest
from techset_leadgen.services.normalize import all_timezones
from techset_leadgen.domain.vocabulary import ROLES

from techset_leadgen.desktop.forms import FieldSpec, FormDialog
from techset_leadgen.desktop.icons import set_button_icon
from techset_leadgen.desktop.modal import ModalDialog
from techset_leadgen.desktop.motion import reduced_motion, set_reduced_motion
from techset_leadgen.desktop.session import AppContext
from techset_leadgen.desktop.support import attempt, label, local_time, report
from techset_leadgen.desktop.theme import apply_mono, tokens
from techset_leadgen.desktop.widgets import (
    Alert, Avatar, Card, DefinitionList, IconChip, PageHeader, SwitchButton, repolish,
)


@dataclass(frozen=True)
class _Snapshot:
    name: str
    email: str
    role: str
    timezone: str
    organization: str
    revision: str | None
    members: int
    organization_created: datetime | None = None
    administrators: str = ""
    business_timezone: str = "UTC"
    meeting_rules: SchedulingRules = field(default_factory=SchedulingRules)


_DANGER_ROWS = (
    ("sales", "Clear sales", "Removes every imported sales record."),
    ("leads", "Clear leads", "Removes every lead and its stage history."),
    ("clients", "Clear clients", "Removes every client and their linked sales."),
)


_CLEAR_DETAILS = {
    "sales": ("Clear all sales?", "Every imported sales record will be permanently removed. Clients and leads stay, "
              "but revenue, charts and reports will show no data.", "clear sales", "Clear sales"),
    "leads": ("Clear all leads?", "Every lead and its stage history will be permanently removed. Clients created "
              "from leads are kept.", "clear leads", "Clear leads"),
    "clients": ("Clear all clients?", "Every client profile will be permanently removed, together with all sales "
                "linked to those clients.", "clear clients", "Clear clients"),
}


class ClearDataDialog(ModalDialog):
    """The Danger zone confirmation: how much goes, a backup shortcut, and a typed confirmation."""

    def __init__(self, parent: QWidget, table: str, count: int, *, backup: object | None = None) -> None:
        super().__init__(parent)
        title, body, word, cta = _CLEAR_DETAILS[table]
        self.word = word
        self.setObjectName("clearDataDialog")
        self.setWindowTitle("Danger zone")
        self.setModal(True)
        self.setMinimumWidth(500)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(24, 22, 24, 22)
        main.setSpacing(16)
        root.addWidget(content)
        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(IconChip("trash", "danger", size=44, icon_size=20), 0, Qt.AlignmentFlag.AlignTop)
        copy = QVBoxLayout()
        copy.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("dialogTitle")
        text = QLabel(body)
        text.setObjectName("dialogSubtitle")
        text.setWordWrap(True)
        copy.addWidget(heading)
        copy.addWidget(text)
        top.addLayout(copy, 1)
        main.addLayout(top)
        count_box = QFrame()
        count_box.setObjectName("countBox")
        count_row = QHBoxLayout(count_box)
        count_row.setContentsMargins(16, 12, 16, 12)
        count_label = QLabel("Records to be removed")
        count_label.setObjectName("helperText")
        count_value = QLabel(f"{count:,}")
        count_value.setStyleSheet(f"font-size: 18px; font-weight: 800; color: {tokens()['danger']};")
        count_row.addWidget(count_label, 1)
        count_row.addWidget(count_value)
        main.addWidget(count_box)
        warning = Alert("This can't be undone. A backup lets you restore later.", "warning")
        if backup is not None:
            backup_button = QPushButton("Back up now")
            backup_button.setObjectName("compactButton")
            backup_button.clicked.connect(lambda _checked=False: backup())  # type: ignore[operator]
            warning.layout().addWidget(backup_button)  # type: ignore[union-attr]
        main.addWidget(warning)
        label_row = QHBoxLayout()
        label_row.setSpacing(4)
        prompt = QLabel("Type")
        prompt.setObjectName("fieldLabel")
        phrase = QLabel(word)
        phrase.setObjectName("confirmWord")
        apply_mono(phrase, 12)
        rest = QLabel("to confirm")
        rest.setObjectName("fieldLabel")
        mark = QLabel("*")
        mark.setObjectName("requiredMark")
        for widget in (prompt, phrase, rest, mark):
            label_row.addWidget(widget)
        label_row.addStretch(1)
        main.addLayout(label_row)
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setPlaceholderText(word)
        self.confirm_edit.setAccessibleName(f"Type {word} to confirm")
        prompt.setBuddy(self.confirm_edit)
        main.addWidget(self.confirm_edit)
        footer = QFrame()
        footer.setObjectName("modalFooter")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 14, 24, 14)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.confirm_button = QPushButton(cta)
        self.confirm_button.setObjectName("dangerButton")
        set_button_icon(self.confirm_button, "trash", "onDanger")
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.confirm_button)
        root.addWidget(footer)
        self.confirm_edit.textChanged.connect(
            lambda value: self.confirm_button.setEnabled(value.strip().lower() == self.word))
        cancel.setDefault(True)
        self.confirm_edit.setFocus()  # ready to type the phrase; Enter still means Cancel


class SettingsPage(QWidget):
    status_requested = Signal(str)
    sign_out_requested = Signal()
    data_changed = Signal()

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self.setObjectName("settingsPage")
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
        centre = QHBoxLayout(body)
        centre.setContentsMargins(28, 24, 28, 40)
        column = QWidget()
        column.setMaximumWidth(1024)
        centre.addStretch(1)
        centre.addWidget(column, 100)
        centre.addStretch(1)
        root = QVBoxLayout(column)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(20)
        root.addWidget(PageHeader("Settings", "Your account, organization and local data."))

        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        card_layout.addWidget(self.tabs)
        root.addWidget(card)
        root.addStretch(1)

        # Your account
        account, account_layout = self._panel()
        identity = QHBoxLayout()
        identity.setSpacing(16)
        self.avatar = Avatar("", 60)
        identity.addWidget(self.avatar)
        who = QVBoxLayout()
        who.setSpacing(4)
        self.profile_name = QLabel()
        self.profile_name.setObjectName("detailTitle")
        self.profile_name.setTextFormat(Qt.TextFormat.PlainText)
        role_row = QHBoxLayout()
        role_row.setSpacing(8)
        self.role_pill = QLabel()
        self.role_pill.setObjectName("goldPill")
        self.org_caption = QLabel()
        self.org_caption.setObjectName("helperText")
        self.role_pill.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        role_row.addWidget(self.role_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        role_row.addWidget(self.org_caption, 0, Qt.AlignmentFlag.AlignVCenter)
        role_row.addStretch(1)
        who.addStretch(1)
        who.addWidget(self.profile_name)
        who.addLayout(role_row)
        who.addStretch(1)
        identity.addLayout(who, 1)
        account_layout.addLayout(identity)
        self.profile_list = DefinitionList()
        account_layout.addWidget(self.profile_list)
        motion_row = QHBoxLayout()
        motion_row.setSpacing(14)
        self.reduce_motion = SwitchButton()
        self.reduce_motion.setAccessibleName("Reduce motion")
        self.reduce_motion.setChecked(reduced_motion())
        self.reduce_motion.toggled.connect(set_reduced_motion)
        motion_copy = QVBoxLayout()
        motion_copy.setSpacing(2)
        motion_title = QLabel("Reduce motion")
        motion_title.setObjectName("strongText")
        motion_title.setBuddy(self.reduce_motion)
        motion_hint = QLabel("Show pages, charts and dialogs without animation on this computer.")
        motion_hint.setObjectName("sectionSubtitle")
        motion_copy.addWidget(motion_title)
        motion_copy.addWidget(motion_hint)
        motion_row.addWidget(self.reduce_motion, 0, Qt.AlignmentFlag.AlignTop)
        motion_row.addLayout(motion_copy, 1)
        account_layout.addLayout(motion_row)
        self.profile_buttons = self._actions(account_layout, [
            ("Edit profile…", "edit", self.edit_profile, ""),
            ("Change password…", "lock", self.change_password, ""),
            ("Sign out", "logout", self.sign_out_requested.emit, "danger"),
        ])
        self.tabs.addTab(account, "Your account")

        # Organization
        organization, organization_layout = self._panel()
        org_identity = QHBoxLayout()
        org_identity.setSpacing(14)
        mark = QLabel("TS")
        mark.setFixedSize(40, 40)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setStyleSheet("background: #5DB84A; color: #0A1414; border-radius: 11px; font-weight: 800;"
                           " font-size: 15px;")
        org_identity.addWidget(mark)
        org_names = QVBoxLayout()
        org_names.setSpacing(2)
        self.org_title = QLabel()
        self.org_title.setObjectName("detailTitle")
        self.org_title.setTextFormat(Qt.TextFormat.PlainText)
        self.org_caption_created = QLabel()
        self.org_caption_created.setObjectName("helperText")
        org_names.addWidget(self.org_title)
        org_names.addWidget(self.org_caption_created)
        org_identity.addLayout(org_names, 1)
        organization_layout.addLayout(org_identity)
        self.organization_list = DefinitionList()
        organization_layout.addWidget(self.organization_list)
        self.organization_buttons = self._actions(organization_layout, [
            ("Edit organization…", "edit", self.rename_organization, ""),
            ("Meeting scheduling…", "calendar", self.edit_meeting_rules, ""),
        ])
        self.tabs.addTab(organization, "Organization")

        # Data & backups
        storage, storage_layout = self._panel()
        self.storage_list = DefinitionList()
        storage_layout.addWidget(self.storage_list)
        self.storage_buttons = self._actions(storage_layout, [
            ("Back up now…", "database", self.backup, "primary"),
            ("Open folder", "folder", self.open_folder, ""),
        ])
        self.tabs.addTab(storage, "Data && backups")

        # Danger zone
        danger = QWidget()
        danger_layout = QVBoxLayout(danger)
        danger_layout.setContentsMargins(0, 20, 0, 4)
        danger_layout.setSpacing(0)
        warning = Alert("These actions permanently clear local records and cannot be undone. Back up first.",
                        "warning")
        warning_holder = QHBoxLayout()
        warning_holder.setContentsMargins(20, 0, 20, 4)
        warning_holder.addWidget(warning)
        danger_layout.addLayout(warning_holder)
        self.clear_buttons: dict[str, QPushButton] = {}
        for index, (key, title, text) in enumerate(_DANGER_ROWS):
            row = QFrame()
            row.setObjectName("cardFooter" if index else "plainRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(20, 16, 20, 16)
            copy = QVBoxLayout()
            copy.setSpacing(2)
            heading = QLabel(title)
            heading.setObjectName("strongText")
            detail = QLabel(text)
            detail.setObjectName("sectionSubtitle")
            copy.addWidget(heading)
            copy.addWidget(detail)
            row_layout.addLayout(copy, 1)
            button = QPushButton(f"{title}…")
            button.setObjectName("dangerOutlineButton")
            button.setMinimumWidth(160)
            set_button_icon(button, "trash", "danger")
            button.clicked.connect(lambda _checked=False, table=key: self.clear_data(table))
            row_layout.addWidget(button)
            danger_layout.addWidget(row)
            self.clear_buttons[key] = button
        danger_layout.addStretch(1)
        self.danger_index = self.tabs.addTab(danger, "Danger zone")
        self.tabs.tabBar().setObjectName("settingsTabs")  # its last tab is red while that is the Danger zone

        # Kept for code that addressed the former sections by name.
        self.profile = {"card": account, "buttons": self.profile_buttons}
        self.organization = {"card": organization, "buttons": self.organization_buttons}
        self.storage = {"card": storage, "buttons": self.storage_buttons}
        self.loaded = False
        self.organization_name = ""
        self.business_timezone = "UTC"
        self.meeting_rules = SchedulingRules()

    @staticmethod
    def _panel() -> tuple[QWidget, QVBoxLayout]:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        return panel, layout

    @staticmethod
    def _actions(panel: QVBoxLayout, actions: list[tuple[str, str, object, str]]) -> dict[str, QPushButton]:
        row = QHBoxLayout()
        row.setSpacing(8)
        buttons: dict[str, QPushButton] = {}
        for text, icon_name, handler, variant in actions:
            button = QPushButton(text)
            if variant == "primary":
                button.setObjectName("primaryButton")
                set_button_icon(button, icon_name, "onPrimary")
            elif variant == "danger":
                button.setObjectName("dangerOutlineButton")
                set_button_icon(button, icon_name, "danger")
            else:
                set_button_icon(button, icon_name)
            button.clicked.connect(lambda _checked=False, h=handler: h())
            row.addWidget(button)
            buttons[text] = button
        row.addStretch(1)
        panel.addLayout(row)
        return buttons

    def ensure_loaded(self) -> None:
        if not self.loaded:
            self.refresh()

    def refresh(self) -> None:
        settings = self.context.settings

        def work(db: Session, actor: Actor) -> _Snapshot:
            me = users.get_user(db, actor, actor.user_id)
            organization = users.get_organization(db)
            current, _head = migrations_util.current_and_head(db.connection())
            members = 0
            administrators = ""
            if actor.can("users.view"):
                listing = users.list_users(db, actor, page=PageRequest(page=1, page_size=200))
                members = listing.total
                administrators = ", ".join(user.full_name for user in listing.items
                                           if user.role == "super_admin" and user.is_active)
            return _Snapshot(me.full_name, me.email, me.role, me.timezone, organization.name, current, members,
                             organization.created_at, administrators, organization.timezone,
                             meetings.scheduling_rules(db))

        ok, data = attempt(self, self.context, work)
        if not ok or data is None:
            return
        self.organization_name = data.organization
        self.business_timezone = data.business_timezone
        self.meeting_rules = data.meeting_rules
        actor = self.context.actor
        role = label(ROLES, data.role)
        self.avatar.set_name(data.name)
        self.profile_name.setText(data.name)
        self.role_pill.setText(role.upper())
        self.org_caption.setText(data.organization)
        self.profile_list.set_rows([("Name", data.name), ("Email", data.email), ("Role", role),
                                    ("Time zone", f"{data.timezone} — used for due dates and “today”")])
        self.org_title.setText(data.organization)
        zone = actor.timezone if actor is not None else "UTC"
        created = local_time(data.organization_created, zone) if data.organization_created else ""
        self.org_caption_created.setText(f"Organization set up {created}" if created else "")
        rows: list[tuple[str, str | QWidget]] = [("Name", data.organization),
                                                 ("Business time zone", data.business_timezone),
                                                 ("Meeting buffer", data.meeting_rules.summary()),
                                                 ("Meeting hours", f"{data.meeting_rules.hours_text()} "
                                                                   "(offered as free slots)")]
        if data.administrators:
            rows.append(("Administrator", data.administrators))
        if data.members:
            rows.append(("Members", str(data.members)))
        self.organization_list.set_rows(rows)
        location = QWidget()
        location_layout = QVBoxLayout(location)
        location_layout.setContentsMargins(0, 11, 0, 11)
        location_layout.setSpacing(2)
        server = settings.is_server
        path = QLabel(settings.display_database if server else str(settings.database_path))
        apply_mono(path, 12)
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        where = QLabel("Shared by every computer of the team" if server else "Local file on this computer")
        where.setObjectName("helperText")
        location_layout.addWidget(path)
        location_layout.addWidget(where)
        self.storage_list.set_rows([
            ("Location", location),
            ("Holds", "Prospects, assignments, outreach history, follow-ups, tasks, accounts, and the audit log"),
            ("Data format version", data.revision or "—"),
            ("Backups", "Made on the server by the administrator (see the deployment guide)") if server else
            ("Last automatic backup", str(self.context.last_backup) if self.context.last_backup else
             "None needed this session (taken before every schema upgrade)"),
            ("Signed in from", self.context.client_host),
            ("Application", f"{PRODUCT_NAME} {PRODUCT_VERSION}"),
            ("Session", f"Ends after {settings.session_idle_minutes} minutes without activity, "
                        f"and after {settings.session_absolute_hours} hours at most."),
        ])
        can_manage = actor is not None and actor.can("org.manage")
        self.organization_buttons["Edit organization…"].setVisible(can_manage)
        self.organization_buttons["Meeting scheduling…"].setVisible(can_manage)
        # A file backup and the clearing of the retired analytics tables work on the local file only.
        self.storage_buttons["Back up now…"].setVisible(can_manage and not server)
        self.storage_buttons["Open folder"].setVisible(not server)
        can_clear = actor is not None and actor.can("data.clear") and not server
        self.tabs.setTabVisible(self.danger_index, can_clear)
        bar = self.tabs.tabBar()
        if bar.property("danger") != can_clear:  # the red last tab is the Danger zone only, never the one before it
            bar.setProperty("danger", can_clear)
            repolish(bar)
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
                                              searchable=True, hint="Used for due dates and “today”.")])
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

        actor = self.context.actor
        owner = (actor.email, actor.full_name) if actor is not None else ("", "")
        dialog = FormDialog(self, title="Password", heading="Change your password", columns=1, submit=submit,
                            note=f"Use at least {MIN_LENGTH} characters: not only numbers, not a common password, "
                                 "and not like your name or email. Your other sign-ins (other computers) "
                                 "end when the password changes.",
                            fields=[FieldSpec("current_password", "Current password", "password", required=True),
                                    FieldSpec("new_password", "New password", "password", required=True,
                                              rules=True, rules_owner=owner),
                                    FieldSpec("confirm", "Repeat new password", "password", required=True)],
                            submit_text="Change password")
        if dialog.exec():
            ended = dialog.result_value or 0
            self.status_requested.emit(f"Password changed. {ended} other session{'s' if ended != 1 else ''} ended.")

    def rename_organization(self) -> None:
        def submit(dialog: FormDialog) -> None:
            data = parse(OrganizationUpdate, dialog.values())
            self.context.write("organization", lambda db, actor: users.update_organization(db, actor, data))

        dialog = FormDialog(self, title="Organization", heading="Edit the organization", columns=1,
                            submit=submit, values={"name": self.organization_name,
                                                   "timezone": self.business_timezone},
                            fields=[FieldSpec("name", "Organization name", required=True,
                                              hint="Shown in the sidebar, reports and the audit log."),
                                    FieldSpec("timezone", "Business time zone", "choice",
                                              [(zone, zone) for zone in all_timezones()], blank=None,
                                              searchable=True, hint="The team's working day: “today” on the "
                                              "dashboard and the end-of-day summary follow it.")])
        if dialog.exec():
            self.refresh()
            self.status_requested.emit("Organization saved")

    def edit_meeting_rules(self) -> None:
        rules = self.meeting_rules
        times = [(str(minutes), clock_minutes(minutes)) for minutes in range(0, 24 * 60, 30)]
        buffers = [(str(minutes), "None" if minutes == 0 else f"{minutes} minutes")
                   for minutes in (0, 15, 30, 45, 60, 90, 120, 180, 240)]
        if not any(value == str(rules.buffer_minutes) for value, _text in buffers):
            buffers.append((str(rules.buffer_minutes), f"{rules.buffer_minutes} minutes"))

        def submit(dialog: FormDialog) -> None:
            values = dialog.values()
            data = parse(SchedulingRulesUpdate, {
                "buffer_mode": values["buffer_mode"], "buffer_minutes": int(values["buffer_minutes"] or 0),
                "day_start": int(values["day_start"] or 0),
                "day_end": int(values["day_end"]) if values["day_end"] else 24 * 60,
                "work_days": values["work_days"]})
            self.context.write("organization", lambda db, actor: meetings.update_scheduling_rules(db, actor, data))

        dialog = FormDialog(
            self, title="Meeting scheduling", heading="Meeting scheduling rules", columns=1, submit=submit,
            note="Checked whenever a meeting is created, edited, or rescheduled, for the client and every attendee. "
                 "Meetings that already exist are kept; any that clash under new rules are listed as scheduling "
                 "conflicts on the Meetings page.",
            values={"buffer_mode": rules.buffer_mode, "buffer_minutes": str(rules.buffer_minutes),
                    "day_start": str(rules.day_start), "day_end": str(rules.day_end),
                    "work_days": list(rules.work_days)},
            fields=[
                FieldSpec("buffer_mode", "Buffer", "choice", list(BUFFER_MODES.items()), blank=None,
                          hint="After each meeting: the next one may start once the buffer has passed. Before and "
                               "after: each meeting also keeps the buffer free before it, so meetings are two "
                               "buffers apart."),
                FieldSpec("buffer_minutes", "Buffer length", "choice", buffers, blank=None),
                FieldSpec("day_start", "Business day starts", "choice", times, blank=None),
                FieldSpec("day_end", "Business day ends", "choice", times[1:] + [("1440", "Midnight")], blank=None,
                          hint="Suggested free times fit inside these hours. Meetings outside them are still "
                               "allowed and are marked as outside business hours."),
                FieldSpec("work_days", "Working days", "multi", list(WEEKDAYS.items())),
            ],
            submit_text="Save rules")
        if dialog.exec():
            self.refresh()
            self.status_requested.emit("Meeting scheduling rules saved")

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

    def open_folder(self) -> None:
        """Show the folder holding the database in the system file manager."""
        folder = Path(self.context.settings.database_path).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def clear_data(self, table: str) -> None:
        snapshot = DashboardController.get_dashboard_kpi_snapshot()
        count = {"sales": snapshot.sales_rows, "leads": snapshot.total_leads, "clients": snapshot.clients_rows}[table]
        dialog = ClearDataDialog(self, table, count, backup=self.backup if self.context.can("org.manage") else None)
        if not dialog.exec():
            return
        operation = {
            "sales": DashboardController.clear_sales,
            "leads": DashboardController.clear_leads,
            "clients": DashboardController.clear_clients,
        }[table]
        try:
            success, outcome = self.context.guarded(
                "data.clear", f"data.cleared_{table}", operation, kind="data", entity_type="data",
                changes=lambda result: {"table": table, "result": result[1]} if result[0] else None,
            )
        except Exception as exc:
            report(self, exc, title="Data maintenance")
            return
        if success:
            self.status_requested.emit(outcome.lstrip("✔ "))
            self.data_changed.emit()
        else:
            report(self, RuntimeError(outcome), title="Data maintenance")


__all__ = ["SettingsPage"]
