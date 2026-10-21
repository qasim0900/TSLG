"""Main window: sign-in, one sidebar for every work area, and the shared top bar."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from branding import FAVICON_ASSET, LOGO_ASSET, PRODUCT_NAME, PRODUCT_TAGLINE
from crm.services import search, tasks
from crm.services.access import Actor
from crm.vocabulary import LEAD_STATUSES, ROLES

from .auth_pages import CodePage, ConnectionPage, SetupPage, SignInPage
from .dialogs import show_message
from .icons import navigation_icon
from .importing import ImportCoordinator
from .pages import ClientsPage, DashboardPage, LeadsPage, SalesPage
from .pages.admin_pages import AuditPage, UsersPage
from .pages.settings_page import SettingsPage
from .pages.tasks_page import TasksPage
from .records import RecordPage
from .search_dialog import SearchDialog
from .session import AppContext, ConnectionProblem, InputMonitor
from .support import attempt, report
from .theme import ThemeManager, asset_path, navigation_icon_colors

SESSION_CHECK_MS = 60_000


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    permission: str | None  # needed to see the entry; None means every signed-in user


SECTIONS = (
    Section("dashboard", "Dashboard", "sales.view"),
    Section("sales", "Sales", "sales.view"),
    Section("leads", "Leads", "leads.view"),
    Section("clients", "Clients", "clients.view"),
    Section("tasks", "Tasks", "tasks.view"),
    Section("users", "Users", "users.view"),
    Section("audit", "Audit log", "audit.view"),
    Section("settings", "Settings", None),
)


class MainWindow(QMainWindow):
    """Branded, responsive shell. Nothing but the sign-in screens is shown until someone signs in."""

    _PAGE_ORDER = tuple(section.key for section in SECTIONS)
    _PAGE_LABELS = {section.key: section.label for section in SECTIONS}

    def __init__(self, theme_manager: ThemeManager, context: AppContext | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.context = context or AppContext(parent=self)
        self.setWindowTitle(PRODUCT_NAME)
        self.setWindowIcon(QIcon(str(asset_path(FAVICON_ASSET))))
        self.resize(1360, 860)
        self.setMinimumSize(760, 600)
        self.setAccessibleName(PRODUCT_NAME)

        self.import_coordinator = ImportCoordinator(self)
        self._nav_buttons: dict[str, QToolButton] = {}
        self._pages: dict[str, QWidget] = {}
        self._page_factories: dict[str, Callable[[], QWidget]] = {}
        self._dirty_pages: set[str] = set()
        self._current_page = "dashboard"
        self._compact_navigation = False
        self._overdue = 0

        self._build_ui()
        self._connect_signals()
        self._monitor = InputMonitor()
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(SESSION_CHECK_MS)
        self._session_timer.timeout.connect(self.check_session)
        self.start()

    # ------------------------------------------------------------------ layout

    def _build_ui(self) -> None:
        self.root_stack = QStackedWidget()
        self.setCentralWidget(self.root_stack)

        # Sign-in area: shown until someone signs in, and again after signing out.
        self.auth_stack = QStackedWidget()
        self.auth_stack.setObjectName("applicationRoot")
        self.connection_page = ConnectionPage()
        self.setup_page = SetupPage(self.context)
        self.sign_in_page = SignInPage(self.context)
        self.code_page = CodePage(self.context)
        for page in (self.connection_page, self.setup_page, self.sign_in_page, self.code_page):
            self.auth_stack.addWidget(page)
        self.root_stack.addWidget(self.auth_stack)

        root = QWidget()
        root.setObjectName("applicationRoot")
        self.app_root = root
        self.root_stack.addWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(72)
        self.sidebar.setMaximumWidth(238)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 16)
        sidebar_layout.setSpacing(6)

        self.brand_row = QWidget()
        brand_layout = QHBoxLayout(self.brand_row)
        brand_layout.setContentsMargins(2, 0, 2, 12)
        brand_layout.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(QIcon(str(asset_path(LOGO_ASSET))).pixmap(QSize(36, 36)))
        logo.setFixedSize(40, 40)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setAccessibleName("Techset Solutions logo")
        self.brand_copy = QWidget()
        copy_layout = QVBoxLayout(self.brand_copy)
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(0)
        product = QLabel(PRODUCT_NAME)
        product.setObjectName("productName")
        tagline = QLabel(PRODUCT_TAGLINE)
        tagline.setObjectName("productTagline")
        tagline.setWordWrap(True)
        copy_layout.addWidget(product)
        copy_layout.addWidget(tagline)
        brand_layout.addWidget(logo)
        brand_layout.addWidget(self.brand_copy, 1)
        sidebar_layout.addWidget(self.brand_row)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for section in SECTIONS:
            button = QToolButton()
            button.setObjectName("navigationButton")
            button.setText(section.label)
            button.setIconSize(QSize(20, 20))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setAccessibleName(f"Open {section.label}")
            button.clicked.connect(lambda _checked=False, target=section.key: self.navigate(target))
            self._nav_group.addButton(button)
            sidebar_layout.addWidget(button)
            self._nav_buttons[section.key] = button
        sidebar_layout.addStretch(1)
        self._apply_navigation_icons(self.theme_manager.dark)
        self.theme_manager.theme_changed.connect(self._apply_navigation_icons)
        self.theme_manager.theme_changed.connect(self._sync_theme_button)
        layout.addWidget(self.sidebar)

        content_column = QWidget()
        content_layout = QVBoxLayout(content_column)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        layout.addWidget(content_column, 1)

        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(22, 10, 18, 10)
        top_layout.setSpacing(10)
        self.section_label = QLabel("Dashboard")
        self.section_label.setObjectName("sectionTitle")
        top_layout.addWidget(self.section_label)
        top_layout.addStretch(1)
        self.task_badge = QPushButton()
        self.task_badge.setObjectName("compactButton")
        self.task_badge.setToolTip("Your open tasks that are overdue or due today")
        self.task_badge.clicked.connect(self._open_due_tasks)
        self.task_badge.hide()
        top_layout.addWidget(self.task_badge)
        self.search_field = QLineEdit()
        self.search_field.setObjectName("globalSearch")
        self.search_field.setPlaceholderText("Search (Ctrl+K)")
        self.search_field.setAccessibleName("Search clients, contacts, and leads")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.setMinimumWidth(150)
        self.search_field.setMaximumWidth(280)
        self.search_field.returnPressed.connect(self.run_search)
        top_layout.addWidget(self.search_field)
        self.account_button = QToolButton()
        self.account_button.setObjectName("accountButton")
        self.account_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.account_menu = QMenu(self.account_button)
        self.account_button.setMenu(self.account_menu)
        top_layout.addWidget(self.account_button)
        self.theme_button = QToolButton()
        self.theme_button.setCheckable(True)
        self.theme_button.setAccessibleName("Toggle light and dark theme")
        self.theme_button.clicked.connect(self._toggle_theme)
        self._sync_theme_button()
        top_layout.addWidget(self.theme_button)
        content_layout.addWidget(top_bar)

        self.stack = QStackedWidget()
        context = self.context
        self._page_factories = {
            "dashboard": lambda: DashboardPage(context=context, on_navigate=self.navigate,
                                               on_import_requested=self._request_import),
            "sales": lambda: SalesPage(on_import_requested=self._request_import,
                                       on_status=lambda message: self.show_status(message, "info"),
                                       context=context),
            "leads": lambda: LeadsPage(context=context),
            "clients": lambda: ClientsPage(context=context),
            "tasks": lambda: TasksPage(context),
            "users": lambda: UsersPage(context),
            "audit": lambda: AuditPage(context),
            "settings": lambda: SettingsPage(context),
        }
        content_layout.addWidget(self.stack, 1)

        self.statusBar().showMessage("Ready")
        self._shortcuts = [
            QShortcut(QKeySequence(f"Ctrl+{index}"), self, lambda key=key: self.navigate(key))
            for index, key in enumerate(self._PAGE_ORDER, start=1)
        ]
        self._shortcuts += [
            QShortcut(QKeySequence("Ctrl+I"), self, self._request_import),
            QShortcut(QKeySequence("Ctrl+K"), self, self._focus_search),
        ]

    def _connect_signals(self) -> None:
        self.import_coordinator.started.connect(lambda: self.show_status("Importing data in the background…", "info"))
        self.import_coordinator.succeeded.connect(self._import_succeeded)
        self.import_coordinator.failed.connect(lambda message: self.show_status(message, "error"))
        self.import_coordinator.dataset_changed.connect(lambda: self._mark_dataset_changed(source=None))
        self.connection_page.retry_requested.connect(self.start)
        self.sign_in_page.code_requested.connect(self._show_code_page)
        self.code_page.back_requested.connect(lambda: self._show_sign_in(""))
        self.context.signed_in.connect(self._signed_in)
        self.context.signed_out.connect(self._signed_out)
        self.context.data_changed.connect(self._record_changed)

    # ------------------------------------------------------------------ sign-in

    def start(self) -> None:
        """Open the database and show first-run setup or sign-in."""
        self.root_stack.setCurrentWidget(self.auth_stack)
        try:
            if not self.context.is_open:
                self.context.open()
            first_run = not self.context.has_users()
        except ConnectionProblem as problem:
            self.connection_page.show_problem(problem)
            self.auth_stack.setCurrentWidget(self.connection_page)
            return
        if first_run:
            self.setup_page.prepare()
            self.auth_stack.setCurrentWidget(self.setup_page)
        else:
            self._show_sign_in("")

    def _show_sign_in(self, notice: str) -> None:
        self.sign_in_page.prepare(notice)
        self.root_stack.setCurrentWidget(self.auth_stack)
        self.auth_stack.setCurrentWidget(self.sign_in_page)

    def _show_code_page(self) -> None:
        self.code_page.prepare()
        self.auth_stack.setCurrentWidget(self.code_page)

    def _signed_in(self) -> None:
        actor = self.context.actor
        assert actor is not None
        visible = [section for section in SECTIONS if section.permission is None or actor.can(section.permission)]
        for section in SECTIONS:
            self._nav_buttons[section.key].setVisible(section in visible)
        role = ROLES.get(actor.role, actor.role)
        self.account_button.setText(actor.full_name)
        self.account_button.setToolTip(f"{actor.full_name} ({role})")
        self.account_button.setAccessibleName(f"Account menu for {actor.full_name}, {role}")
        self.account_menu.clear()
        signed_in = self.account_menu.addAction(f"Signed in as {actor.email} · {role}")
        signed_in.setEnabled(False)
        self.account_menu.addAction("Settings", lambda: self.navigate("settings"))
        self.account_menu.addSeparator()
        self.account_menu.addAction("Sign out", lambda: self.context.sign_out())
        self.search_field.setVisible(actor.can("clients.view") or actor.can("leads.view"))
        self.root_stack.setCurrentWidget(self.app_root)
        self._monitor.install()
        self._session_timer.start()
        self.navigate(visible[0].key)
        self.refresh_task_badge()
        self.show_status(f"Signed in as {actor.full_name}", "success")

    def _signed_out(self, reason: str) -> None:
        self._session_timer.stop()
        self._monitor.remove()
        for dialog in self.findChildren(QDialog):  # forms the previous session left open
            if dialog.isVisible():
                dialog.reject()
        for page in self._pages.values():  # they hold the previous user's data
            self.stack.removeWidget(page)
            page.deleteLater()
        self._pages.clear()
        self._dirty_pages.clear()
        self.search_field.clear()
        self.task_badge.hide()
        self._show_sign_in(reason)
        self.statusBar().showMessage(reason, 8000)

    def check_session(self) -> None:
        if self._monitor.take():
            self.context.note_input()
        if self.context.verify():
            self.refresh_task_badge()

    # ------------------------------------------------------------------ navigation

    def _ensure_page(self, name: str) -> tuple[QWidget, bool]:
        page = self._pages.get(name)
        if page is not None:
            return page, False
        page = self._page_factories[name]()
        self._pages[name] = page
        self.stack.addWidget(page)
        self._connect_page_signals(name, page)
        self._dirty_pages.discard(name)
        return page, True

    def _connect_page_signals(self, name: str, page: QWidget) -> None:
        if isinstance(page, DashboardPage):
            page.status_requested.connect(self.show_status)
            page.data_changed.connect(lambda: self._mark_dataset_changed(source=name))
        elif isinstance(page, (LeadsPage, ClientsPage)):
            page.notification_requested.connect(self.show_status)
            page.data_changed.connect(lambda: self._mark_dataset_changed(source=name))
        elif isinstance(page, (RecordPage, SettingsPage)):
            page.status_requested.connect(lambda message: self.show_status(message, "info"))
            if isinstance(page, SettingsPage):
                page.sign_out_requested.connect(lambda: self.context.sign_out())

    def navigate(self, page: str, filters: dict[str, str] | None = None) -> QWidget | None:
        if page not in self._PAGE_ORDER or not self.context.is_signed_in:
            return None
        if not self._nav_buttons[page].isVisibleTo(self.sidebar):
            self.show_status("Your role does not include that area.", "info")
            return None
        active, created = self._ensure_page(page)
        self._current_page = page
        self.stack.setCurrentWidget(active)
        self.section_label.setText(self._PAGE_LABELS[page])
        self._nav_buttons[page].setChecked(True)
        if filters is not None and isinstance(active, RecordPage):
            self._dirty_pages.discard(page)
            active.apply_filters(filters)
        elif not created and page in self._dirty_pages:
            self._refresh_page(page, dataset_changed=True)
        elif hasattr(active, "ensure_loaded"):
            active.ensure_loaded()
        return active

    def show_status(self, message: str, level: str = "info") -> None:
        self.statusBar().showMessage(message, 8000)
        if level == "error":
            # Single owner of error pop-ups for every page; messages can contain
            # imported names, so never let Qt interpret them as rich text.
            show_message(self, title=PRODUCT_NAME, heading=message, level="error")

    def _record_changed(self, kind: str) -> None:
        """A change saved through the services: other pages refresh when next shown."""
        self._dirty_pages.update(name for name in self._pages if name != self._current_page)
        if kind in ("task", "lead"):
            self.refresh_task_badge()

    def _mark_dataset_changed(self, *, source: str | None) -> None:
        """Invalidate loaded pages and refresh only the visible one."""
        self._dirty_pages.update(self._pages)
        if source is not None:
            self._dirty_pages.discard(source)
        if self._current_page in self._dirty_pages:
            self._refresh_page(self._current_page, dataset_changed=True)

    def _refresh_page(self, name: str, *, dataset_changed: bool = False) -> None:
        page = self._pages.get(name)
        if page is None:
            return
        if isinstance(page, SalesPage):
            if dataset_changed:
                page.refresh_after_import()
            else:
                page.reload_data(announce=False)
        elif hasattr(page, "refresh"):
            page.refresh()
        self._dirty_pages.discard(name)

    def _refresh_all(self) -> None:
        """Explicit maintenance hook; refresh only pages already constructed."""
        for name in tuple(self._pages):
            self._refresh_page(name, dataset_changed=True)

    # ------------------------------------------------------------------ import, search, tasks

    def _request_import(self) -> None:
        if not self.context.can("data.import"):
            show_message(self, title=PRODUCT_NAME, heading="Your role cannot import data.",
                         message="Ask a Sales Manager or an administrator to import the file.", level="info")
            return
        try:  # re-checked against the database: the role may have changed elsewhere
            self.context.run(lambda db, actor: actor.require("data.import"))
        except Exception as exc:
            report(self, exc, title="Import")
            return
        self.import_coordinator.select_and_import(self)

    def _import_succeeded(self, message: str) -> None:
        self.show_status(message, "success")
        try:
            self.context.record("data.imported", entity_type="data", changes={"result": message[:500]})
        except Exception as exc:  # the data is imported; say that the audit entry is missing
            report(self, exc, title="Import audit")

    def _focus_search(self) -> None:
        if self.search_field.isVisible():
            self.search_field.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self.search_field.selectAll()

    def run_search(self) -> None:
        query = self.search_field.text().strip()
        if len(query) < search.MIN_QUERY:
            self.show_status(f"Type at least {search.MIN_QUERY} characters to search.", "info")
            return

        def work(db: Session, actor: Actor) -> list[tuple[str, str, str, str]]:
            from crm.services.leads import display_title

            found = search.search(db, actor, query)
            return (
                [("clients", client.id, client.name, " · ".join(part for part in (client.id, client.primary_domain)
                                                                  if part)) for client in found.clients]
                + [("contacts", contact.client_id, contact.full_name, f"Contact at {contact.client.name}"
                    + (f" · {contact.job_title}" if contact.job_title else "")) for contact in found.contacts]
                + [("leads", lead.id, display_title(lead), LEAD_STATUSES.get(lead.status, lead.status)
                    + (f" · {lead.client.name}" if lead.client else "")) for lead in found.leads]
            )

        ok, results = attempt(self, self.context, work, title="Search")
        if not ok or results is None:
            return
        dialog = SearchDialog(self, results, query)
        if dialog.exec() and dialog.chosen is not None:
            self.open_record(*dialog.chosen)

    def open_record(self, kind: str, record_id: str) -> None:
        """Open a search result where it lives: a lead or a client profile."""
        if kind == "leads":
            page = self.navigate("leads")
            if isinstance(page, LeadsPage):
                page.open_lead(record_id)
        else:
            page = self.navigate("clients")
            if isinstance(page, ClientsPage):
                page.show_client_profile(record_id)

    def refresh_task_badge(self) -> None:
        if not self.context.is_signed_in or not self.context.can("tasks.view"):
            self.task_badge.hide()
            return
        try:
            counts = self.context.run(lambda db, actor: tasks.counts(db, actor), busy=False, touch=False)
        except Exception:  # a convenience; the periodic check reports real problems
            return
        self._overdue = counts["overdue"]
        parts = []
        if counts["overdue"]:
            parts.append(f"{counts['overdue']} overdue")
        if counts["today"]:
            parts.append(f"{counts['today']} due today")
        self.task_badge.setText(", ".join(parts))
        self.task_badge.setProperty("alert", bool(counts["overdue"]))
        self.task_badge.style().unpolish(self.task_badge)
        self.task_badge.style().polish(self.task_badge)
        self.task_badge.setVisible(bool(parts))

    def _open_due_tasks(self) -> None:
        self.navigate("tasks", {"view": "mine", "due": "overdue" if self._overdue else "today"})

    # ------------------------------------------------------------------ appearance

    def _toggle_theme(self) -> None:
        self.theme_manager.toggle()
        self._sync_theme_button()

    def _apply_navigation_icons(self, dark: bool) -> None:
        color, checked_color = navigation_icon_colors(dark)
        for name, button in self._nav_buttons.items():
            button.setIcon(navigation_icon(name, color, checked_color))

    def _sync_theme_button(self, _dark: bool | None = None) -> None:
        """Label the button with the theme it switches to, matching the persisted state."""
        is_dark = self.theme_manager.dark
        self.theme_button.setChecked(is_dark)
        self.theme_button.setText("Light mode" if is_dark else "Dark mode")

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        compact = event.size().width() < 980
        if compact == self._compact_navigation:
            return
        self._compact_navigation = compact
        self.sidebar.setMaximumWidth(78 if compact else 238)
        self.brand_copy.setVisible(not compact)
        for name, button in self._nav_buttons.items():
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly if compact else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            button.setToolTip(self._PAGE_LABELS[name] if compact else "")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if self.import_coordinator.is_busy:
            show_message(
                self,
                title="Import in progress",
                heading="An import is still running",
                message=f"Wait for it to finish, then close {PRODUCT_NAME}.",
                level="info",
            )
            event.ignore()
            return
        self.import_coordinator.shutdown()
        self._session_timer.stop()
        self._monitor.remove()
        self.context.shutdown()  # ends the session in the database
        super().closeEvent(event)
