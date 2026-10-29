from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRectF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)
from shiboken6 import Shiboken
from sqlalchemy.orm import Session

from techset_leadgen.branding import FAVICON_ASSET, LOGO_ASSET, PARENT_BRAND, PRODUCT_NAME, PRODUCT_TAGLINE, WORDMARK_PARTS
from techset_leadgen.analytics.controllers.dashboard_controller import DashboardController
from techset_leadgen.services import assignments, notifications, search, tasks
from techset_leadgen.services.access import Actor
from techset_leadgen.domain.vocabulary import LEAD_STATUSES, ROLES

from techset_leadgen.desktop.auth_pages import CodePage, ConnectionPage, SetupPage, SignInPage
from techset_leadgen.desktop.dialogs import ask_confirmation, show_message
from techset_leadgen.desktop.icons import ThemedIconLabel, icon, pixmap, set_button_icon
from techset_leadgen.desktop.importing import ImportCoordinator
from techset_leadgen.desktop.motion import EASE, SPRING, animate, cross_fade, enter, page_entrance, pop_window, slide_in
from techset_leadgen.desktop.pages import ClientsPage, DashboardPage, LeadsPage, SalesPage
from techset_leadgen.desktop.pages.admin_pages import AuditPage, UsersPage
from techset_leadgen.desktop.pages.assignment_pages import AssignmentsPage
from techset_leadgen.desktop.pages.operational_dashboard_page import OperationalDashboardPage
from techset_leadgen.desktop.pages.outreach_pages import FollowUpsPage, MyWorkPage
from techset_leadgen.desktop.pages.prospects_page import ProspectsPage
from techset_leadgen.desktop.pages.meetings_page import MeetingsPage
from techset_leadgen.desktop.pages.team_pages import NotificationsPage, TeamPage
from techset_leadgen.desktop.pages.settings_page import SettingsPage
from techset_leadgen.desktop.pages.tasks_page import TasksPage
from techset_leadgen.desktop.records import RecordPage
from techset_leadgen.desktop.search_dialog import SearchDialog
from techset_leadgen.desktop.session import AppContext, ConnectionProblem, InputMonitor
from techset_leadgen.desktop.support import attempt, report
from techset_leadgen.desktop.theme import ThemeManager, asset_path, navigation_icon_colors, tokens
from techset_leadgen.desktop.widgets import Avatar, SearchField, Toast, repolish

SESSION_CHECK_MS = 60_000
SIDEBAR_WIDTH = 252
SIDEBAR_COLLAPSED = 76
COMPACT_BELOW = 980


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    permission: str | None
    group: str = ""
    icon: str = ""
    local_only: bool = False


SECTIONS = (
    Section("dashboard", "Dashboard", None, "Overview"),
    Section("my_work", "My Work", "outreach.record", "Overview"),
    Section("notifications", "Notifications", None, "Overview"),
    Section("assignments", "Daily Assignments", "assignments.manage", "Outreach"),
    Section("meetings", "Meetings", "meetings.view", "Outreach"),
    Section("prospects", "Prospects", "prospects.view", "Outreach"),
    Section("followups", "Follow-ups", "prospects.view", "Outreach"),
    Section("tasks", "Tasks", "tasks.view", "Outreach"),
    Section("team", "Team performance", "team.view", "Manage", icon="performance"),
    Section("users", "Users & roles", "users.view", "Manage"),
    Section("audit", "Audit log", "audit.view", "Manage"),
    Section("settings", "Settings", None, "Manage"),
    Section("sales_overview", "Sales overview", "archive.view", "Archive", icon="dashboard", local_only=True),
    Section("sales", "Sales", "archive.view", "Archive", local_only=True),
    Section("leads", "Leads", "archive.view", "Archive", local_only=True),
    Section("clients", "Clients", "archive.view", "Archive", local_only=True),
)
GROUPS = ("Overview", "Outreach", "Manage", "Archive")


class NavButton(QAbstractButton):
    def __init__(self, label: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(label)
        self.icon_name = icon_name
        self.count = ""
        self.compact = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(42)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._hover = 0.0

    def _set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    def set_count(self, value: int | None) -> None:
        self.count = "" if value is None else str(value)
        self.update()

    def set_compact(self, compact: bool) -> None:
        self.compact = compact
        self.setToolTip(self.text() if compact else "")
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(48 if self.compact else 220, 42)

    def minimumSizeHint(self) -> QSize:
        return QSize(48, 42)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.HoverEnter:
            animate(self._hover, 1.0, 220, self._set_hover, curve=SPRING, owner=self)
        elif event.type() == QEvent.Type.HoverLeave:
            animate(self._hover, 0.0, 220, self._set_hover, curve=SPRING, owner=self)
        return super().event(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        t = tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect())
        checked = self.isChecked()
        hovered = self.underMouse()
        if checked or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(t["tint"] if checked else t["hover"]))
            painter.drawRoundedRect(area, 10, 10)
        color = t["primaryInk"] if checked else t["text"] if hovered else t["text2"]
        if self.compact:
            icon_left = (area.width() - 18) / 2
        else:
            icon_left = 14
        image = pixmap(self.icon_name, color, 18)
        scale = 1 + 0.12 * self._hover
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(icon_left + 9, area.height() / 2)
        painter.scale(scale, scale)
        painter.drawPixmap(-9, -9, image)
        painter.restore()
        if not self.compact:
            font = QFont(self.font())
            font.setPixelSize(14)
            font.setWeight(QFont.Weight.Bold if checked else QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(QColor(color))
            right = area.right() - 14
            if self.count:
                small = QFont(font)
                small.setPixelSize(11)
                small.setWeight(QFont.Weight.Bold)
                painter.setFont(small)
                pill_width = painter.fontMetrics().horizontalAdvance(self.count) + 16
                pill = QRectF(area.right() - 14 - pill_width, (area.height() - 20) / 2, pill_width, 20)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(t["muted"]))
                painter.drawRoundedRect(pill, 10, 10)
                painter.setPen(QColor(t["text2"]))
                painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, self.count)
                painter.setFont(font)
                painter.setPen(QColor(color))
                right = pill.left() - 8
            text_rect = QRectF(icon_left + 18 + 12, 0, right - (icon_left + 30), area.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             painter.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight,
                                                              int(text_rect.width())))
        if self.hasFocus():
            painter.setPen(QPen(QColor(t["focus"]), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(area.adjusted(1, 1, -1, -1), 9, 9)
        painter.end()


class AccountButton(QToolButton):
    def sizeHint(self) -> QSize:
        layout = self.layout()
        return layout.sizeHint() if layout is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


class Sidebar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.current: NavButton | None = None
        self.marker = 1.0
        self.clip: QWidget | None = None

    def set_marker(self, value: float) -> None:
        self.marker = value
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        button = self.current
        if button is None or not button.isVisible():
            return
        top_left = button.mapTo(self, button.rect().topLeft())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.clip is not None:
            area = self.clip.geometry()
            painter.setClipRect(area.adjusted(-8, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens()["brand"]))
        full = button.height() - 18
        height = full * max(0.0, self.marker)
        marker = QRectF(-4, top_left.y() + 9 + (full - height) / 2, 8, height)
        if height > 0.5:
            painter.drawRoundedRect(marker, 4, 4)
        painter.end()


class MainWindow(QMainWindow):
    _PAGE_ORDER = tuple(section.key for section in SECTIONS)
    _PAGE_LABELS = {section.key: section.label for section in SECTIONS}
    _PAGE_GROUPS = {section.key: section.group for section in SECTIONS}

    def __init__(self, theme_manager: ThemeManager, context: AppContext | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.context = context or AppContext(parent=self)
        self.setWindowTitle(PRODUCT_NAME)
        self.setWindowIcon(QIcon(str(asset_path(FAVICON_ASSET))))
        self.resize(1440, 900)
        self.setMinimumSize(760, 600)
        self.setAccessibleName(PRODUCT_NAME)

        self.import_coordinator = ImportCoordinator(self)
        self._nav_buttons: dict[str, NavButton] = {}
        self._group_headers: dict[str, QLabel] = {}
        self._pages: dict[str, QWidget] = {}
        self._page_factories: dict[str, Callable[[], QWidget]] = {}
        self._dirty_pages: set[str] = set()
        self._current_page = "dashboard"
        self._compact_navigation = False
        self._user_collapsed = bool(QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, PARENT_BRAND,
                                              PRODUCT_NAME).value("appearance/sidebarCollapsed", False, type=bool))
        self._overdue = 0

        self._build_ui()
        self._connect_signals()
        self._monitor = InputMonitor()
        self._session_timer = QTimer(self)
        self._session_timer.setInterval(SESSION_CHECK_MS)
        self._session_timer.timeout.connect(self.check_session)
        self.start()


    def _build_ui(self) -> None:
        self.root_stack = QStackedWidget()
        self.setCentralWidget(self.root_stack)

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

        self.sidebar = Sidebar()
        self.sidebar.setFixedWidth(SIDEBAR_WIDTH)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 16)
        sidebar_layout.setSpacing(0)
        sidebar_layout.addWidget(self._build_brand())

        self.nav_area = QWidget()
        nav_layout = QVBoxLayout(self.nav_area)
        self._nav_layout = nav_layout
        nav_layout.setContentsMargins(12, 16, 12, 0)
        nav_layout.setSpacing(18)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._group_boxes: dict[str, QWidget] = {}
        self._group_dividers: dict[str, QFrame] = {}
        for group in GROUPS:
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(2)
            divider = QFrame()
            divider.setObjectName("navDivider")
            divider.hide()
            box_layout.addWidget(divider)
            header = QLabel(group.upper())
            header.setObjectName("navHeader")
            header.setAccessibleName(group)
            font = QFont(header.font())
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.9)
            header.setFont(font)
            box_layout.addWidget(header)
            self._group_headers[group] = header
            self._group_dividers[group] = divider
            for section in (item for item in SECTIONS if item.group == group):
                button = NavButton(section.label, section.icon or section.key)
                button.setCheckable(True)
                button.setAccessibleName(f"Open {section.label}")
                button.clicked.connect(lambda _checked=False, target=section.key: self.navigate(target))
                self._nav_group.addButton(button)
                box_layout.addWidget(button)
                self._nav_buttons[section.key] = button
            self._group_boxes[group] = box
            nav_layout.addWidget(box)
        nav_layout.addStretch(1)
        self.nav_area.setObjectName("navArea")
        self.nav_scroll = QScrollArea()
        self.nav_scroll.setObjectName("navScroll")
        self.nav_scroll.setWidgetResizable(True)
        self.nav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_scroll.setWidget(self.nav_area)
        self.nav_scroll.verticalScrollBar().valueChanged.connect(lambda _value: self.sidebar.update())
        self.sidebar.clip = self.nav_scroll
        sidebar_layout.addWidget(self.nav_scroll, 1)
        self._apply_navigation_icons(self.theme_manager.dark)

        foot = QWidget()
        foot_layout = QVBoxLayout(foot)
        foot_layout.setContentsMargins(12, 0, 12, 0)
        foot_layout.setSpacing(8)
        self.database_card = QFrame()
        self.database_card.setObjectName("sideFootCard")
        card_row = QHBoxLayout(self.database_card)
        card_row.setContentsMargins(12, 12, 12, 12)
        card_row.setSpacing(10)
        card_row.addWidget(ThemedIconLabel("database", "primaryInk", 16), 0, Qt.AlignmentFlag.AlignTop)
        card_text = QVBoxLayout()
        card_text.setSpacing(1)
        title = QLabel("Local database")
        title.setObjectName("sideFootTitle")
        self.database_title = title
        self.backup_label = QLabel()
        self.backup_label.setObjectName("sideFootText")
        self.backup_label.setWordWrap(True)
        card_text.addWidget(title)
        card_text.addWidget(self.backup_label)
        card_row.addLayout(card_text, 1)
        foot_layout.addWidget(self.database_card)
        self.collapse_button = NavButton("Collapse sidebar", "sidebar")
        self.collapse_button.setAccessibleName("Collapse or expand the sidebar")
        self.collapse_button.clicked.connect(self.toggle_sidebar)
        foot_layout.addWidget(self.collapse_button)
        sidebar_layout.addWidget(foot)
        self.theme_manager.theme_changed.connect(self._apply_navigation_icons)
        self.theme_manager.theme_changed.connect(self._sync_theme_button)
        layout.addWidget(self.sidebar)

        content_column = QWidget()
        content_layout = QVBoxLayout(content_column)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        layout.addWidget(content_column, 1)
        content_layout.addWidget(self._build_top_bar())

        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        context = self.context
        self._page_factories = {
            "dashboard": lambda: OperationalDashboardPage(context, on_navigate=self.navigate),
            "my_work": lambda: MyWorkPage(context),
            "notifications": lambda: NotificationsPage(context, on_navigate=self.navigate),
            "assignments": lambda: AssignmentsPage(context),
            "meetings": lambda: MeetingsPage(context),
            "prospects": lambda: ProspectsPage(context),
            "followups": lambda: FollowUpsPage(context),
            "tasks": lambda: TasksPage(context),
            "team": lambda: TeamPage(context),
            "users": lambda: UsersPage(context),
            "audit": lambda: AuditPage(context),
            "settings": lambda: SettingsPage(context),
            "sales_overview": lambda: DashboardPage(context=context, on_navigate=self.navigate,
                                                    on_import_requested=self._request_import),
            "sales": lambda: SalesPage(on_import_requested=self._request_import,
                                       on_status=lambda message: self.show_status(message, "info"),
                                       context=context),
            "leads": lambda: LeadsPage(context=context),
            "clients": lambda: ClientsPage(context=context),
        }
        content_layout.addWidget(self.stack, 1)

        self.toast = Toast(self)
        self._shortcuts = [
            QShortcut(QKeySequence(f"Ctrl+{number}"), self, lambda number=number: self._open_numbered(number))
            for number in range(1, 10)
        ]
        self._shortcuts += [
            QShortcut(QKeySequence("Ctrl+I"), self, self._request_import),
            QShortcut(QKeySequence("Ctrl+K"), self, self._focus_search),
        ]
        self._apply_sidebar_mode()

    def _build_brand(self) -> QWidget:
        self.brand_row = QPushButton()
        self.brand_row.setObjectName("brandButton")
        self.brand_row.setAccessibleName(f"{PRODUCT_NAME}, go to Dashboard")
        self.brand_row.setToolTip(PRODUCT_NAME)
        self.brand_row.setCursor(Qt.CursorShape.PointingHandCursor)
        self.brand_row.clicked.connect(lambda: self.navigate("dashboard"))
        brand_layout = QHBoxLayout(self.brand_row)
        self._brand_layout = brand_layout
        brand_layout.setContentsMargins(22, 0, 10, 0)
        brand_layout.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(QIcon(str(asset_path(LOGO_ASSET))).pixmap(QSize(32, 32)))
        logo.setFixedSize(32, 32)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setAccessibleName("Techset Solutions logo")
        self.brand_logo = logo
        self.brand_copy = QWidget()
        copy_layout = QVBoxLayout(self.brand_copy)
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(3)
        name_row = QHBoxLayout()
        name_row.setSpacing(3)
        product = QLabel(WORDMARK_PARTS[0])
        product.setObjectName("productName")
        product.setAccessibleName(PRODUCT_NAME)
        accent = QLabel(WORDMARK_PARTS[1])
        accent.setObjectName("productAccent")
        name_row.addWidget(product)
        name_row.addWidget(accent)
        name_row.addStretch(1)
        tagline_row = QHBoxLayout()
        tagline_row.setSpacing(6)
        rule = QLabel()
        rule.setObjectName("taglineRule")
        rule.setFixedSize(10, 2)
        tagline = QLabel(PRODUCT_TAGLINE.upper())
        tagline.setObjectName("productTagline")
        tagline.setAccessibleName(PRODUCT_TAGLINE)
        tagline_font = QFont(tagline.font())
        tagline_font.setPixelSize(9)
        tagline_font.setWeight(QFont.Weight.Bold)
        tagline_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.7)
        tagline.setFont(tagline_font)
        tagline_row.addWidget(rule, 0, Qt.AlignmentFlag.AlignVCenter)
        tagline_row.addWidget(tagline)
        tagline_row.addStretch(1)
        copy_layout.addLayout(name_row)
        copy_layout.addLayout(tagline_row)
        for child in (logo, self.brand_copy, product, accent, tagline, rule):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        brand_layout.addWidget(logo)
        brand_layout.addWidget(self.brand_copy, 1, Qt.AlignmentFlag.AlignVCenter)
        return self.brand_row

    def _build_top_bar(self) -> QWidget:
        top_bar = QFrame()
        self.top_bar = top_bar
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(64)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(24, 0, 24, 0)
        top_layout.setSpacing(12)
        heading = QVBoxLayout()
        heading.setSpacing(0)
        heading.addStretch(1)
        self.crumb_label = QLabel("Overview")
        self.crumb_label.setObjectName("crumb")
        self.section_label = QLabel("Dashboard")
        self.section_label.setObjectName("topTitle")
        heading.addWidget(self.crumb_label)
        heading.addWidget(self.section_label)
        heading.addStretch(1)
        top_layout.addLayout(heading, 1)
        self.task_badge = QPushButton()
        self.task_badge.setObjectName("compactButton")
        self.task_badge.setToolTip("Your open tasks that are overdue or due today")
        self.task_badge.clicked.connect(self._open_due_tasks)
        set_button_icon(self.task_badge, "clock", "danger", 15)
        self.task_badge.hide()
        top_layout.addWidget(self.task_badge)
        self.search_field = SearchField("Search prospects…", "Ctrl K")
        self.search_field.setObjectName("globalSearch")
        self.search_field.setAccessibleName("Search clients, contacts, and leads")
        self.search_field.setClearButtonEnabled(False)
        self.search_field.setMinimumWidth(180)
        self.search_field.setMaximumWidth(340)
        self.search_field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search_field.returnPressed.connect(self.run_search)
        top_layout.addWidget(self.search_field, 1)
        self.theme_button = QToolButton()
        self.theme_button.setObjectName("iconButton")
        self.theme_button.setCheckable(True)
        self.theme_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.theme_button.setAccessibleName("Toggle light and dark theme")
        self.theme_button.clicked.connect(self._toggle_theme)
        top_layout.addWidget(self.theme_button)
        self._sync_theme_button()
        top_layout.addWidget(self._build_account_button())
        return top_bar

    def _build_account_button(self) -> QToolButton:
        self.account_button = AccountButton()
        self.account_button.setObjectName("accountButton")
        self.account_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.account_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        row = QHBoxLayout(self.account_button)
        self._account_layout = row
        row.setContentsMargins(6, 0, 10, 0)
        row.setSpacing(10)
        self.account_avatar = Avatar("", 26)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.account_name = QLabel()
        self.account_name.setObjectName("accountName")
        self.account_role = QLabel()
        self.account_role.setObjectName("accountRole")
        text.addWidget(self.account_name)
        text.addWidget(self.account_role)
        chevron = ThemedIconLabel("chevron-down", "text", 16)
        row.addWidget(self.account_avatar)
        row.addLayout(text, 1)
        row.addWidget(chevron)
        for child in (self.account_avatar, self.account_name, self.account_role, chevron):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.account_menu = QMenu(self.account_button)
        self.account_menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.account_menu.setWindowFlags(self.account_menu.windowFlags() | Qt.WindowType.FramelessWindowHint
                                         | Qt.WindowType.NoDropShadowWindowHint)
        self.account_menu.setMinimumWidth(300)
        self.account_menu.aboutToShow.connect(self._refresh_account_menu_icons)
        self.account_menu.aboutToShow.connect(
            lambda: QTimer.singleShot(0, lambda: pop_window(self.account_menu, dy=-6, duration=180)))
        self.account_button.setMenu(self.account_menu)
        return self.account_button

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


    def start(self) -> None:
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
        visible = [section for section in SECTIONS
                   if (section.permission is None or actor.can(section.permission))
                   and not (section.local_only and self.context.is_server)]
        for section in SECTIONS:
            self._nav_buttons[section.key].setVisible(section in visible)
        for group, box in self._group_boxes.items():
            box.setVisible(any(section.group == group for section in visible))
        role = ROLES.get(actor.role, actor.role)
        self.account_name.setText(actor.full_name)
        self.account_role.setText(role)
        self.account_avatar.set_name(actor.full_name)
        self.account_button.setText("")
        self.account_button.setToolTip(f"{actor.full_name} ({role})")
        self.account_button.setAccessibleName(f"Account menu for {actor.full_name}, {role}")
        self._account_layout.invalidate()
        self.account_button.updateGeometry()
        self._build_account_menu(actor.full_name, actor.email, role)
        self.search_field.setVisible(actor.can("prospects.view") or actor.can("clients.view")
                                     or actor.can("leads.view"))
        archive = any(section.group == "Archive" for section in visible)
        self.search_field.setPlaceholderText("Search prospects, leads, clients…" if archive else "Search prospects…")
        if self.context.is_server:
            self.database_title.setText("Team database")
            self.backup_label.setText(f"Shared · {self.context.settings.display_database.split(' on ')[-1]}")
        else:
            self.database_title.setText("Local database")
            self.backup_label.setText("Last backup: before schema upgrade" if self.context.last_backup
                                      else "Stored on this computer")
        self.root_stack.setCurrentWidget(self.app_root)
        self._monitor.install()
        self._session_timer.start()
        self.navigate(visible[0].key)
        self.refresh_task_badge()
        self.refresh_counts()
        self.show_status(f"Signed in as {actor.full_name}", "success")
        QTimer.singleShot(0, self._shell_entrance)

    def _shell_entrance(self) -> None:
        enter(self.sidebar, dx=-16, dy=0, duration=500)
        enter(self.top_bar, dy=-10, duration=450)
        buttons = [button for button in self._nav_buttons.values() if button.isVisible()]
        slide_in(buttons, dx=-16, step=50, start=100, duration=450)

    def _build_account_menu(self, name: str, email: str, role: str) -> None:
        menu = self.account_menu
        menu.clear()
        header = QWidget()
        header.setObjectName("menuHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(10, 10, 10, 12)
        row.setSpacing(10)
        row.addWidget(Avatar(name, 32))
        text = QVBoxLayout()
        text.setSpacing(0)
        name_label = QLabel(name)
        name_label.setObjectName("menuName")
        email_label = QLabel(email)
        email_label.setObjectName("menuEmail")
        email_label.setToolTip(f"Signed in as {email} · {role}")
        text.addWidget(name_label)
        text.addWidget(email_label)
        row.addLayout(text, 1)
        header_action = QWidgetAction(menu)
        header_action.setDefaultWidget(header)
        header_action.setEnabled(False)
        header_action.setText(f"Signed in as {email} · {role}")
        menu.addAction(header_action)
        menu.addSeparator()
        self._settings_action = menu.addAction("Account settings", lambda: self.navigate("settings"))
        self._theme_action = menu.addAction("Dark mode", self._toggle_theme)
        self._sign_out_action = menu.addAction("Sign out", self.confirm_sign_out)
        self._refresh_account_menu_icons()

    def _refresh_account_menu_icons(self) -> None:
        if not hasattr(self, "_settings_action"):
            return
        t = tokens()
        self._settings_action.setIcon(icon("user", t["text"], 16))
        dark = self.theme_manager.dark
        self._theme_action.setText("Light mode" if dark else "Dark mode")
        self._theme_action.setIcon(icon("sun" if dark else "moon", t["text"], 16))
        self._sign_out_action.setIcon(icon("logout", t["danger"], 16))

    def confirm_sign_out(self) -> bool:
        actor = self.context.actor
        who = actor.email if actor is not None else "this account"
        if not ask_confirmation(
            self, title="Sign out", heading=f"Sign out of {PRODUCT_NAME}?",
            message=f"You're signed in as {who}. You'll need your password to sign in again. "
                    "Anything not yet saved in an open form will be lost.",
            confirm_text="Sign out", cancel_text="Stay signed in", destructive=True, icon="logout",
        ):
            return False
        self.context.sign_out()
        return True

    def _signed_out(self, reason: str) -> None:
        self._session_timer.stop()
        self._monitor.remove()
        for dialog in self.findChildren(QDialog):
            if dialog.isVisible():
                dialog.reject()
        for page in self._pages.values():
            self.stack.removeWidget(page)
            page.deleteLater()
        self._pages.clear()
        self._dirty_pages.clear()
        self.search_field.clear()
        self.task_badge.hide()
        self._show_sign_in(reason)

    def check_session(self) -> None:
        if self._monitor.take():
            self.context.note_input()
        if self.context.verify():
            self.refresh_task_badge()


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
        if isinstance(page, OperationalDashboardPage):
            page.status_requested.connect(self.show_status)
        elif isinstance(page, TeamPage):
            page.status_requested.connect(lambda message: self.show_status(message, "info"))
        elif isinstance(page, DashboardPage):
            page.status_requested.connect(self.show_status)
            page.data_changed.connect(lambda: self._mark_dataset_changed(source=name))
        elif isinstance(page, (LeadsPage, ClientsPage)):
            page.notification_requested.connect(self.show_status)
            page.data_changed.connect(lambda: self._mark_dataset_changed(source=name))
        elif isinstance(page, (RecordPage, SettingsPage)):
            page.status_requested.connect(lambda message: self.show_status(message, "info"))
            if isinstance(page, SettingsPage):
                page.sign_out_requested.connect(self.confirm_sign_out)
                page.data_changed.connect(lambda: self._mark_dataset_changed(source=name))

    def _open_numbered(self, number: int) -> None:
        shown = [key for key in self._PAGE_ORDER if self._nav_buttons[key].isVisibleTo(self.sidebar)]
        if self.context.is_signed_in and number <= len(shown):
            self.navigate(shown[number - 1])

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
        self.crumb_label.setText(self._PAGE_GROUPS[page])
        button = self._nav_buttons[page]
        button.setChecked(True)
        self.nav_scroll.ensureWidgetVisible(button, 0, 8)
        changed = self.sidebar.current is not button
        self.sidebar.current = button
        if changed:
            animate(0.0, 1.0, 350, self.sidebar.set_marker, curve=SPRING, owner=self.sidebar)
        self.sidebar.update()
        QTimer.singleShot(0, lambda target=active: self._page_entered(target))
        if filters is not None and isinstance(active, RecordPage):
            self._dirty_pages.discard(page)
            active.apply_filters(filters)
        elif not created and page in self._dirty_pages:
            self._refresh_page(page, dataset_changed=True)
        elif hasattr(active, "ensure_loaded"):
            active.ensure_loaded()
        return active

    def _page_entered(self, page: QWidget) -> None:
        if Shiboken.isValid(page) and self.stack.currentWidget() is page:
            page_entrance(page)

    def show_status(self, message: str, level: str = "info") -> None:
        if level == "error":
            show_message(self, title=PRODUCT_NAME, heading=message, level="error")
            return
        self.toast.show_message(message, level)

    def _record_changed(self, kind: str) -> None:
        self._dirty_pages.update(name for name in self._pages if name != self._current_page)
        if kind in ("task", "lead"):
            self.refresh_task_badge()
        self.refresh_counts()

    def _mark_dataset_changed(self, *, source: str | None) -> None:
        self._dirty_pages.update(self._pages)
        if source is not None:
            self._dirty_pages.discard(source)
        if self._current_page in self._dirty_pages:
            self._refresh_page(self._current_page, dataset_changed=True)
        self.refresh_counts()

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
        for name in tuple(self._pages):
            self._refresh_page(name, dataset_changed=True)


    def _request_import(self) -> None:
        if not self.context.can("data.import"):
            show_message(self, title=PRODUCT_NAME, heading="Your role cannot import data.",
                         message="Ask a Sales Manager or an administrator to import the file.", level="info")
            return
        try:
            self.context.run(lambda db, actor: actor.require("data.import"))
        except Exception as exc:
            report(self, exc, title="Import")
            return
        self.import_coordinator.select_and_import(self)

    def _import_succeeded(self, message: str) -> None:
        self.show_status(message, "success")
        try:
            self.context.record("data.imported", entity_type="data", changes={"result": message[:500]})
        except Exception as exc:
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

        archive = self._nav_buttons["leads"].isVisibleTo(self.sidebar)

        def work(db: Session, actor: Actor) -> list[tuple[str, str, str, str]]:
            from techset_leadgen.services.leads import display_title

            found = search.search(db, actor, query)
            prospect_rows = [("prospects", prospect.id, prospect.full_name or prospect.linkedin_key,
                              " · ".join(part for part in (prospect.job_title, prospect.company) if part)
                              or prospect.linkedin_url) for prospect in found.prospects]
            if not archive:
                return prospect_rows
            return prospect_rows + (
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
        if kind == "prospects":
            page = self.navigate("prospects")
            if isinstance(page, ProspectsPage):
                page.show_record(record_id)
        elif kind == "leads":
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

        def work(db: Session, actor: Actor) -> tuple[dict[str, int], dict[str, int]]:
            return tasks.counts(db, actor, kind="follow_up"), tasks.counts(db, actor, kind="task")

        try:
            follow_ups, general = self.context.run(work, busy=False, touch=False)
        except Exception:
            return
        overdue, today = follow_ups["overdue"] + general["overdue"], follow_ups["today"] + general["today"]
        self._overdue = overdue
        self._due_target = "followups" if follow_ups["overdue"] or follow_ups["today"] else "tasks"
        parts = []
        if overdue:
            parts.append(f"{overdue} overdue")
        if today:
            parts.append(f"{today} due today")
        self.task_badge.setText(", ".join(parts))
        self.task_badge.setProperty("alert", bool(overdue))
        repolish(self.task_badge)
        self.task_badge.setVisible(bool(parts))
        self._nav_buttons["tasks"].set_count(general["open"] or None)
        self._nav_buttons["followups"].set_count((follow_ups["overdue"] + follow_ups["today"]) or None)

    def refresh_counts(self) -> None:
        if not self.context.is_signed_in:
            return

        def work(db: Session, actor: Actor) -> tuple[int, int]:
            open_work = assignments.open_count(db, actor) if actor.can("outreach.record") else 0
            return open_work, notifications.unread_count(db, actor)

        try:
            open_work, unread = self.context.run(work, busy=False, touch=False)
        except Exception:
            return
        self._nav_buttons["my_work"].set_count(open_work or None)
        self._nav_buttons["notifications"].set_count(unread or None)
        if self._nav_buttons["leads"].isVisibleTo(self.sidebar):
            snapshot = DashboardController.get_dashboard_kpi_snapshot()
            self._nav_buttons["leads"].set_count(snapshot.total_leads or None)
            self._nav_buttons["clients"].set_count(snapshot.clients_rows or None)

    def _open_due_tasks(self) -> None:
        due = "overdue" if self._overdue else "today"
        if getattr(self, "_due_target", "tasks") == "followups":
            self.navigate("followups", {"due": due})
        else:
            self.navigate("tasks", {"view": "mine", "due": due})


    def _toggle_theme(self) -> None:
        cross_fade(self, self.theme_manager.toggle, duration=300)
        self._sync_theme_button()

    def _apply_navigation_icons(self, dark: bool) -> None:
        color, checked_color = navigation_icon_colors(dark)
        for button in self._nav_buttons.values():
            button.setIcon(icon(button.icon_name, color, 18, checked_color=checked_color))
            button.update()
        self.sidebar.update()

    def _sync_theme_button(self, _dark: bool | None = None) -> None:
        is_dark = self.theme_manager.dark
        self.theme_button.setChecked(is_dark)
        self.theme_button.setText("Light mode" if is_dark else "Dark mode")
        self.theme_button.setToolTip("Switch to light mode" if is_dark else "Switch to dark mode")
        set_button_icon(self.theme_button, "sun" if is_dark else "moon", "text", 18)
        self._refresh_account_menu_icons()

    def toggle_sidebar(self) -> None:
        self._user_collapsed = not self._user_collapsed
        QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, PARENT_BRAND,
                  PRODUCT_NAME).setValue("appearance/sidebarCollapsed", self._user_collapsed)
        self._apply_sidebar_mode(animated=True)

    def _apply_sidebar_mode(self, *, animated: bool = False) -> None:
        compact = self._compact_navigation or self._user_collapsed
        target = SIDEBAR_COLLAPSED if compact else SIDEBAR_WIDTH
        start = self.sidebar.width()
        if animated and start != target:
            if compact:
                animate(start, target, 300, lambda value: self.sidebar.setFixedWidth(round(value)),
                        curve=EASE, owner=self.sidebar, done=lambda: self._apply_sidebar_mode())
                return
            self._apply_sidebar_labels(compact)
            animate(start, target, 300, lambda value: self.sidebar.setFixedWidth(round(value)),
                    curve=EASE, owner=self.sidebar)
            return
        self.sidebar.setFixedWidth(target)
        self._apply_sidebar_labels(compact)

    def _apply_sidebar_labels(self, compact: bool) -> None:
        self.brand_copy.setVisible(not compact)
        self._brand_layout.setContentsMargins(*(0, 0, 0, 0) if compact else (22, 0, 10, 0))
        self._brand_layout.setAlignment(self.brand_logo, Qt.AlignmentFlag.AlignCenter if compact
                                        else Qt.AlignmentFlag.AlignVCenter)
        self._nav_layout.setContentsMargins(*(14, 16, 14, 0) if compact else (12, 16, 12, 0))
        self._nav_layout.setSpacing(14 if compact else 18)
        for group in GROUPS:
            self._group_headers[group].setVisible(not compact)
            self._group_dividers[group].setVisible(compact and group != GROUPS[0])
        for button in self._nav_buttons.values():
            button.set_compact(compact)
        self.database_card.setVisible(not compact)
        self.collapse_button.set_compact(compact)
        self.collapse_button.setText("Expand sidebar" if self._user_collapsed else "Collapse sidebar")
        self.collapse_button.setVisible(not self._compact_navigation)
        self.sidebar.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        compact = event.size().width() < COMPACT_BELOW
        if compact == self._compact_navigation:
            return
        self._compact_navigation = compact
        self._apply_sidebar_mode()

    def closeEvent(self, event: QCloseEvent) -> None:
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
        self.context.shutdown()
        super().closeEvent(event)

