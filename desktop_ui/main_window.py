"""Main native Qt application shell and navigation."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCloseEvent, QIcon, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from branding import FAVICON_ASSET, LOGO_ASSET, PRODUCT_NAME, PRODUCT_TAGLINE

from .dialogs import show_message
from .icons import navigation_icon
from .importing import ImportCoordinator
from .pages import ClientsPage, DashboardPage, LeadsPage, SalesPage
from .theme import ThemeManager, asset_path, navigation_icon_colors

AppPage = DashboardPage | SalesPage | LeadsPage | ClientsPage


class MainWindow(QMainWindow):
    """Branded, responsive shell around the four existing work areas."""

    _PAGE_ORDER = ("dashboard", "sales", "leads", "clients")
    _PAGE_LABELS = {
        "dashboard": "Dashboard",
        "sales": "Sales",
        "leads": "Leads",
        "clients": "Clients",
    }

    def __init__(self, theme_manager: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.setWindowTitle(PRODUCT_NAME)
        self.setWindowIcon(QIcon(str(asset_path(FAVICON_ASSET))))
        self.resize(1360, 860)
        self.setMinimumSize(760, 600)
        self.setAccessibleName(PRODUCT_NAME)

        self.import_coordinator = ImportCoordinator(self)
        self._nav_buttons: dict[str, QToolButton] = {}
        self._pages: dict[str, AppPage] = {}
        self._page_factories: dict[str, Callable[[], AppPage]] = {}
        self._dirty_pages: set[str] = set()
        self._current_page = "dashboard"
        self._compact_navigation = False

        self._build_ui()
        self._connect_signals()
        self.navigate("dashboard")

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("applicationRoot")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(72)
        self.sidebar.setMaximumWidth(238)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 16)
        sidebar_layout.setSpacing(8)

        self.brand_row = QWidget()
        brand_layout = QHBoxLayout(self.brand_row)
        brand_layout.setContentsMargins(2, 0, 2, 14)
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

        nav_group = QButtonGroup(self)
        nav_group.setExclusive(True)
        for name in self._PAGE_ORDER:
            button = QToolButton()
            button.setObjectName("navigationButton")
            button.setText(self._PAGE_LABELS[name])
            button.setIconSize(QSize(20, 20))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setAccessibleName(f"Open {self._PAGE_LABELS[name]}")
            button.clicked.connect(lambda _checked=False, target=name: self.navigate(target))
            nav_group.addButton(button)
            sidebar_layout.addWidget(button)
            self._nav_buttons[name] = button
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
        self.section_label = QLabel("Dashboard")
        self.section_label.setObjectName("sectionTitle")
        top_layout.addWidget(self.section_label)
        top_layout.addStretch(1)
        self.theme_button = QToolButton()
        self.theme_button.setCheckable(True)
        self.theme_button.setAccessibleName("Toggle light and dark theme")
        self.theme_button.clicked.connect(self._toggle_theme)
        self._sync_theme_button()
        top_layout.addWidget(self.theme_button)
        content_layout.addWidget(top_bar)

        self.stack = QStackedWidget()
        self._page_factories = {
            "dashboard": lambda: DashboardPage(
                on_navigate=self.navigate,
                on_import_requested=self._request_import,
            ),
            "sales": lambda: SalesPage(
                on_import_requested=self._request_import,
                on_status=lambda message: self.show_status(message, "info"),
            ),
            "leads": LeadsPage,
            "clients": ClientsPage,
        }
        content_layout.addWidget(self.stack, 1)

        self.statusBar().showMessage("Ready")
        self._shortcuts = [
            QShortcut(QKeySequence("Ctrl+1"), self, lambda: self.navigate("dashboard")),
            QShortcut(QKeySequence("Ctrl+2"), self, lambda: self.navigate("sales")),
            QShortcut(QKeySequence("Ctrl+3"), self, lambda: self.navigate("leads")),
            QShortcut(QKeySequence("Ctrl+4"), self, lambda: self.navigate("clients")),
            QShortcut(QKeySequence("Ctrl+I"), self, self._request_import),
        ]

    def _connect_signals(self) -> None:
        self.import_coordinator.started.connect(
            lambda: self.show_status("Importing data in the background…", "info")
        )
        self.import_coordinator.succeeded.connect(
            lambda message: self.show_status(message, "success")
        )
        self.import_coordinator.failed.connect(lambda message: self.show_status(message, "error"))
        self.import_coordinator.dataset_changed.connect(
            lambda: self._mark_dataset_changed(source=None)
        )

    def _ensure_page(self, name: str) -> tuple[AppPage, bool]:
        page = self._pages.get(name)
        if page is not None:
            return page, False
        page = self._page_factories[name]()
        self._pages[name] = page
        self.stack.addWidget(page)
        self._connect_page_signals(name, page)
        self._dirty_pages.discard(name)
        return page, True

    def _connect_page_signals(self, name: str, page: AppPage) -> None:
        if isinstance(page, DashboardPage):
            page.status_requested.connect(self.show_status)
            page.data_changed.connect(lambda: self._mark_dataset_changed(source=name))
        elif isinstance(page, (LeadsPage, ClientsPage)):
            page.notification_requested.connect(self.show_status)
            page.data_changed.connect(lambda: self._mark_dataset_changed(source=name))

    def navigate(self, page: str) -> None:
        if page not in self._PAGE_ORDER:
            return
        active, created = self._ensure_page(page)
        self._current_page = page
        self.stack.setCurrentWidget(active)
        self.section_label.setText(self._PAGE_LABELS[page])
        self._nav_buttons[page].setChecked(True)
        if not created and page in self._dirty_pages:
            self._refresh_page(page, dataset_changed=True)

    def show_status(self, message: str, level: str = "info") -> None:
        self.statusBar().showMessage(message, 8000)
        if level == "error":
            # Single owner of error pop-ups for every page; messages can contain
            # imported names, so never let Qt interpret them as rich text.
            show_message(self, title=PRODUCT_NAME, heading=message, level="error")

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
        elif isinstance(page, DashboardPage):
            page.refresh()
        elif isinstance(page, LeadsPage):
            page.refresh()
        elif isinstance(page, ClientsPage):
            page.refresh()
        self._dirty_pages.discard(name)

    def _refresh_all(self) -> None:
        """Explicit maintenance hook; refresh only pages already constructed."""
        for name in tuple(self._pages):
            self._refresh_page(name, dataset_changed=True)

    def _request_import(self) -> None:
        self.import_coordinator.select_and_import(self)

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
                Qt.ToolButtonStyle.ToolButtonIconOnly
                if compact
                else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
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
        super().closeEvent(event)
