"""Central Techset design tokens and Qt palette/style management."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from branding import FONT_ASSET, FONT_FAMILY


PRIMARY = "#39B54A"
PRIMARY_DARK = "#287D35"
PRIMARY_HOVER = "#1F642A"
SECONDARY = "#FFCB4A"
INK = "#0A1414"
CANVAS = "#FBFAF8"
SURFACE = "#FFFFFF"
SURFACE_SOFT = "#F5F5F5"
MUTED = "#62637A"
BORDER = "#C3C6CE"
ERROR = "#BA1A1A"
SUCCESS = "#287D35"

TEXT_ON_DARK = "#F2F5F2"
# Error tone readable on the dark surfaces (#BA1A1A is about 2.5:1 there).
ERROR_ON_DARK = "#FFB4AB"

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def navigation_icon_colors(dark: bool) -> tuple[str, str]:
    """Return (normal, checked) icon colours matching the navigation button text."""
    return (TEXT_ON_DARK, INK) if dark else (INK, "#FFFFFF")


def asset_path(name: str) -> Path:
    """Return an absolute path for a bundled application asset."""
    return (_PROJECT_ROOT / "assets" / name).resolve()


def load_application_font() -> str:
    """Register the bundled Inter font and return the usable family name."""
    font_id = QFontDatabase.addApplicationFont(str(asset_path(FONT_ASSET)))
    if font_id >= 0:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            return families[0]
    return FONT_FAMILY


def _palette(dark: bool) -> QPalette:
    palette = QPalette()
    if dark:
        window = QColor(INK)
        base = QColor("#0D1B19")
        alternate = QColor("#122321")
        text = QColor("#F2F5F2")
        muted = QColor("#B7BDBA")
        button = QColor("#122321")
        highlight = QColor(PRIMARY)
        highlighted_text = QColor(INK)
    else:
        window = QColor(CANVAS)
        base = QColor(SURFACE)
        alternate = QColor("#F8F8F4")
        text = QColor(INK)
        muted = QColor(MUTED)
        button = QColor(SURFACE)
        highlight = QColor(PRIMARY_DARK)
        highlighted_text = QColor("#FFFFFF")

    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, alternate)
    palette.setColor(QPalette.ColorRole.ToolTipBase, base)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, muted)
    palette.setColor(QPalette.ColorRole.Button, button)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Link, highlight)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, highlighted_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, muted)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, muted)
    return palette


def build_stylesheet(dark: bool = False) -> str:
    """Build one global stylesheet from the centralized brand tokens."""
    canvas = INK if dark else CANVAS
    surface = "#122321" if dark else SURFACE
    surface_soft = "#0D1B19" if dark else SURFACE_SOFT
    surface_high = "#0A1D3B" if dark else "#ECEFEB"  # official dark surface (bg-[#0a1d3b])
    text = TEXT_ON_DARK if dark else INK
    muted = "#B7BDBA" if dark else MUTED
    border = "#3F4945" if dark else BORDER
    primary = PRIMARY if dark else PRIMARY_DARK
    primary_text = INK if dark else "#FFFFFF"
    selection = PRIMARY if dark else PRIMARY_DARK
    selection_text = INK if dark else "#FFFFFF"
    hover_surface = "#203633" if dark else "#E6EEE7"
    sidebar = "#081311" if dark else "#FFFFFF"
    error_text = ERROR_ON_DARK if dark else ERROR
    # Focus rings need >= 3:1 against the pixels they replace (WCAG 2.2).
    # Gold on white is ~1.5:1, so light mode rings outlined controls in green.
    focus = SECONDARY if dark else PRIMARY_DARK
    focus_on_fill = INK if dark else SECONDARY  # on green fills: 7.0:1 / 3.4:1
    focus_on_danger = TEXT_ON_DARK if dark else SECONDARY  # on red: 5.9:1 / 4.3:1
    chevron = asset_path(f"icons/chevron_down_{'dark' if dark else 'light'}.svg").as_posix()
    chevron_disabled = asset_path("icons/chevron_down_disabled.svg").as_posix()
    warning_text = "#FFCB4A" if dark else "#7A5900"

    return f"""
    * {{
        font-family: "Inter", "Segoe UI", sans-serif;
        color: {text};
        selection-background-color: {selection};
        selection-color: {selection_text};
    }}
    QMainWindow, QWidget#applicationRoot, QWidget#pageBody,
    QWidget#salesPageBody, QScrollArea#pageScrollArea {{
        background: {canvas};
    }}
    QFrame#sidebar {{
        background: {sidebar};
        border-right: 1px solid {border};
    }}
    QFrame#topBar {{
        background: {surface};
        border-bottom: 1px solid {border};
    }}
    QLabel#productName {{ font-size: 18px; font-weight: 700; }}
    QLabel#productTagline {{ font-size: 12px; }}
    QLabel#productTagline, QLabel#pageSubtitle, QLabel#metricLabel,
    QLabel#metricNote, QLabel#filterSummary, QLabel#dialogSubtitle {{
        color: {muted};
    }}
    QLabel#pageTitle {{ font-size: 28px; font-weight: 700; }}
    QLabel#dialogTitle {{ font-size: 22px; font-weight: 700; }}
    QLabel#dialogHeading {{ font-size: 16px; font-weight: 700; }}
    QLabel#metricValue {{ font-size: 25px; font-weight: 700; }}
    QLabel#summaryValue {{ font-size: 18px; font-weight: 700; }}
    QLabel#sectionTitle {{ font-size: 17px; font-weight: 650; }}
    QLabel#statusMessage {{ color: {muted}; padding: 4px 0; }}
    QLabel#statusMessage[level="error"], QLabel#statusMessage[severity="error"],
    QLabel#formError {{ color: {error_text}; font-weight: 600; }}
    QLabel#statusMessage[level="warning"] {{ color: {warning_text}; font-weight: 600; }}
    QLabel#fieldLabel {{ font-weight: 600; }}

    QFrame#card, QFrame#metricCard, QGroupBox#card, QGroupBox {{
        background: {surface};
        border: 1px solid {border};
        border-radius: 14px;
    }}
    QGroupBox {{
        margin-top: 12px;
        padding-top: 12px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 14px;
        padding: 0 5px;
        background: {surface};
    }}
    QFrame#metricCard[accent="green"] {{ border-top: 3px solid {PRIMARY}; }}
    QFrame#metricCard[accent="gold"] {{ border-top: 3px solid {SECONDARY}; }}
    QFrame#metricCard[accent="red"] {{ border-top: 3px solid {ERROR}; }}
    QFrame#metricCard[accent="blue"] {{ border-top: 3px solid {border}; }}

    QPushButton, QToolButton {{
        min-height: 36px;
        padding: 4px 14px;
        border: 1px solid {border};
        border-radius: 18px;
        background: {surface};
        font-weight: 600;
    }}
    QPushButton:hover, QToolButton:hover {{ background: {hover_surface}; }}
    QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus,
    QDateEdit:focus, QTableWidget:focus, QListWidget:focus {{
        border: 2px solid {focus};
    }}
    QPushButton#primaryButton {{
        background: {primary}; color: {primary_text}; border-color: {primary};
    }}
    QPushButton#primaryButton:hover {{ background: {PRIMARY_HOVER}; color: #FFFFFF; }}
    QPushButton#secondaryButton {{
        background: {surface_soft}; color: {text};
    }}
    QPushButton#tertiaryButton {{
        background: {SECONDARY}; color: {INK}; border-color: {SECONDARY};
    }}
    QPushButton#dangerButton {{
        color: #FFFFFF; background: {ERROR}; border-color: {ERROR};
    }}
    QPushButton:disabled, QToolButton:disabled {{ color: {muted}; background: {surface_high}; }}

    QToolButton#navigationButton {{
        border: 0; border-radius: 10px; min-height: 42px;
        text-align: left; padding: 4px 14px;
    }}
    QToolButton#navigationButton:checked {{
        background: {primary}; color: {primary_text};
    }}
    QToolButton#navigationButton:checked:hover {{ background: {primary}; }}
    /* ID selectors outrank the generic :focus rule above, so each filled
       variant restates its focus ring or it is drawn in the fill colour. */
    QToolButton#navigationButton:focus {{ border: 2px solid {focus}; }}
    QToolButton#navigationButton:checked:focus,
    QPushButton#primaryButton:focus {{ border: 2px solid {focus_on_fill}; }}
    QPushButton#tertiaryButton:focus {{ border: 2px solid {INK}; }}
    QPushButton#dangerButton:focus {{ border: 2px solid {focus_on_danger}; }}

    QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox {{
        min-height: 36px;
        padding: 2px 10px;
        border: 1px solid {border};
        border-radius: 8px;
        background: {surface};
    }}
    QComboBox::drop-down {{ border: 0; width: 26px; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{
        image: url("{chevron}"); width: 12px; height: 12px;
    }}
    QComboBox::down-arrow:disabled, QDateEdit::down-arrow:disabled {{
        image: url("{chevron_disabled}");
    }}
    QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled {{
        color: {muted}; background: {surface_soft};
    }}
    QDateEdit::drop-down {{
        border: 0; width: 26px;
        subcontrol-origin: padding; subcontrol-position: center right;
    }}
    QPushButton#compactButton {{
        min-height: 30px; padding: 2px 14px; border-radius: 15px; font-weight: 500;
    }}
    QTableWidget, QTableView, QListWidget {{
        background: {surface};
        alternate-background-color: {surface_soft};
        border: 1px solid {border};
        border-radius: 10px;
        gridline-color: {border};
    }}
    QHeaderView::section {{
        background: {surface_high};
        color: {text};
        border: 0;
        border-bottom: 1px solid {border};
        padding: 9px;
        font-weight: 650;
    }}
    QTabWidget::pane {{ border: 1px solid {border}; border-radius: 10px; background: {surface}; }}
    QTabBar::tab {{ padding: 9px 16px; border-bottom: 3px solid transparent; }}
    QTabBar::tab:selected {{ border-bottom-color: {PRIMARY}; font-weight: 650; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {border}; min-height: 30px; border-radius: 5px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QStatusBar {{ background: {surface}; border-top: 1px solid {border}; }}
    QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 5px; }}
    """


class ThemeManager(QObject):
    """Apply and persist the application's light/dark theme."""

    theme_changed = Signal(bool)

    def __init__(self, app: QApplication, *, settings: QSettings | None = None) -> None:
        super().__init__()
        self.app = app
        # Explicit defaultFormat(): native in production, but honours a test's
        # QSettings.setDefaultFormat()/setPath() redirect, which the plain
        # (organization, application) constructor ignores.
        self.settings = settings or QSettings(
            QSettings.defaultFormat(),
            QSettings.Scope.UserScope,
            "Techset Solutions",
            "Techset LeadGen",
        )
        self.dark = bool(self.settings.value("appearance/dark", False, type=bool))

    def apply(self, dark: bool | None = None) -> None:
        if dark is not None:
            self.dark = bool(dark)
        self.app.setPalette(_palette(self.dark))
        self.app.setStyleSheet(build_stylesheet(self.dark))
        font_family = load_application_font()
        self.app.setFont(QFont(font_family, 10))
        self.settings.setValue("appearance/dark", self.dark)
        self.theme_changed.emit(self.dark)

    def toggle(self) -> bool:
        self.apply(not self.dark)
        return self.dark
