"""Central Techset design tokens and Qt palette/style management.

``tokens()`` holds the redesign's colour system for the light and dark themes
(the same names as the design's CSS variables). The global stylesheet, the
palette, painted widgets (badges, charts, icons) and the navigation all read
these values, so a colour is defined once and both themes stay in step.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from techset_leadgen.branding import FONT_ASSETS, FONT_FAMILY, MONO_FONT_ASSETS, MONO_FONT_FAMILY

# Brand values kept for modules that import them directly.
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
BRAND_GREEN = "#5DB84A"  # the redesign's brand green (logo artwork, accents, chart bars in dark mode)

TEXT_ON_DARK = "#F2F5F2"
# Error tone readable on the dark surfaces (#BA1A1A is about 2.5:1 there).
ERROR_ON_DARK = "#FFB4AB"
# Every bordered button, text or icon-only, on every screen: one height (borders included),
# the same as the inputs. Borderless glyphs, such as a dialog's close cross, keep 32 px.
BUTTON_HEIGHT = 40
_BUTTON_BOX = BUTTON_HEIGHT - 2  # a stylesheet's min-height excludes the 1 px borders

_LIGHT: dict[str, str] = {
    "brand": BRAND_GREEN, "primary": PRIMARY_DARK, "primaryHover": PRIMARY_HOVER, "onPrimary": "#FFFFFF",
    "gold": SECONDARY, "goldInk": "#7A5900", "goldChipInk": "#6E5000", "goldTint": "#FFF1CC",
    "bg": CANVAS, "surface": SURFACE, "surface2": "#FAFAF7", "muted": "#F5F5F4", "hover": "#F1F3F0",
    "rowHover": "#F8F8F4", "line": "#E7E9E6", "lineStrong": BORDER, "text": INK, "text2": MUTED,
    "tint": "#EEF7EB", "tint2": "#DFF1DA", "primaryInk": "#1F642A", "danger": ERROR, "dangerHover": "#9A1515",
    "dangerTint": "#FBE3E3", "onDanger": "#FFFFFF", "focus": PRIMARY_DARK, "chartA": "#4AA638",
    "chartB": "#936B00", "grid": "#DDE1E6", "tipBg": "#3F4945", "tipFg": "#FFFFFF", "failRow": "#FDF4F3",
    "infoBg": "#E2ECF8", "infoInk": "#1E4C7A", "warnBg": "#FFF1CC", "warnInk": "#6E5000",
    "toastBg": INK, "toastFg": TEXT_ON_DARK, "backdrop": "rgba(10, 20, 20, 0.45)",
}
_DARK: dict[str, str] = {
    "brand": BRAND_GREEN, "primary": BRAND_GREEN, "primaryHover": "#74C763", "onPrimary": INK,
    "gold": SECONDARY, "goldInk": "#FFD86E", "goldChipInk": "#FFD86E", "goldTint": "#3E3216",
    "bg": INK, "surface": "#0D1B19", "surface2": "#10201E", "muted": "#122321", "hover": "#1A2B28",
    "rowHover": "#122321", "line": "#26332F", "lineStrong": "#3F4945", "text": TEXT_ON_DARK, "text2": "#B7BDBA",
    "tint": "#1A2E22", "tint2": "#21402B", "primaryInk": "#9FDA8F", "danger": ERROR_ON_DARK,
    "dangerHover": "#FFCDC7", "dangerTint": "#4A2020", "onDanger": INK, "focus": "#74C763",
    "chartA": BRAND_GREEN, "chartB": SECONDARY, "grid": "#26332F", "tipBg": TEXT_ON_DARK, "tipFg": INK,
    "failRow": "#241615", "infoBg": "#1B3150", "infoInk": "#BBD5F4", "warnBg": "#3E3216", "warnInk": "#FFD86E",
    "toastBg": TEXT_ON_DARK, "toastFg": INK, "backdrop": "rgba(0, 0, 0, 0.62)",
}

_state = {"dark": False}

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def tokens(dark: bool | None = None) -> dict[str, str]:
    """Colour tokens of the active theme (or of the theme ``dark`` names)."""
    return dict(_DARK if (_state["dark"] if dark is None else dark) else _LIGHT)


def is_dark() -> bool:
    return _state["dark"]


def navigation_icon_colors(dark: bool) -> tuple[str, str]:
    """Return (normal, checked) icon colours matching the navigation button text."""
    values = tokens(dark)
    return values["text2"], values["primaryInk"]


def asset_path(name: str) -> Path:
    """Return an absolute path for a bundled application asset."""
    return (_PROJECT_ROOT / "assets" / name).resolve()


_registered: dict[str, str] = {}


def _register(assets: tuple[str, ...], fallback: str) -> str:
    """Register each weight file once; return the family name Qt reports."""
    family = fallback
    for asset in assets:
        if asset not in _registered:
            font_id = QFontDatabase.addApplicationFont(str(asset_path(asset)))
            families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
            _registered[asset] = families[0] if families else ""
        family = _registered[asset] or family
    return family


def load_application_font() -> str:
    """Register the bundled UI and monospace fonts and return the UI family name."""
    _register(MONO_FONT_ASSETS, MONO_FONT_FAMILY)
    return _register(FONT_ASSETS, FONT_FAMILY)


def mono_font(pixel_size: int = 12) -> QFont:
    """The monospace font used for record IDs, timestamps and file paths."""
    font = QFont(MONO_FONT_FAMILY)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(pixel_size)
    return font


def apply_mono(widget: QWidget, pixel_size: int = 12) -> None:
    """Show ``widget`` in the monospace font.

    ``setFont`` is not enough: the global stylesheet's font family wins over a
    widget's own font, so the family is set in the widget's stylesheet instead.
    """
    widget.setFont(mono_font(pixel_size))
    widget.setStyleSheet(f"font-family: '{MONO_FONT_FAMILY}', 'Consolas', monospace; font-size: {pixel_size}px;")


def _palette(dark: bool) -> QPalette:
    t = tokens(dark)
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: t["bg"],
        QPalette.ColorRole.WindowText: t["text"],
        QPalette.ColorRole.Base: t["surface"],
        QPalette.ColorRole.AlternateBase: t["surface2"],
        QPalette.ColorRole.ToolTipBase: t["tipBg"],
        QPalette.ColorRole.ToolTipText: t["tipFg"],
        QPalette.ColorRole.Text: t["text"],
        QPalette.ColorRole.PlaceholderText: t["text2"],
        QPalette.ColorRole.Button: t["surface"],
        QPalette.ColorRole.ButtonText: t["text"],
        QPalette.ColorRole.BrightText: "#FFFFFF",
        QPalette.ColorRole.Link: t["primary"],
        QPalette.ColorRole.Highlight: t["primary"],
        QPalette.ColorRole.HighlightedText: t["onPrimary"],
        QPalette.ColorRole.Light: t["surface"],
        QPalette.ColorRole.Midlight: t["line"],
        QPalette.ColorRole.Mid: t["lineStrong"],
        QPalette.ColorRole.Dark: t["lineStrong"],
        QPalette.ColorRole.Shadow: t["line"],
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(t["text2"]))
    return palette


def build_stylesheet(dark: bool = False) -> str:
    """Build one global stylesheet from the centralized design tokens."""
    t = tokens(dark)
    suffix = "dark" if dark else "light"
    chevron = asset_path(f"icons/chevron_down_{suffix}.svg").as_posix()
    chevron_disabled = asset_path("icons/chevron_down_disabled.svg").as_posix()
    check = asset_path(f"icons/check_{suffix}.svg").as_posix()
    calendar = asset_path(f"icons/calendar_{suffix}.svg").as_posix()
    # Focus rings need >= 3:1 against the pixels they replace (WCAG 2.2).
    focus = t["focus"]
    focus_on_fill = INK if dark else SECONDARY  # on green fills: 7.0:1 / 3.4:1
    focus_on_danger = TEXT_ON_DARK if dark else SECONDARY

    return f"""
    * {{
        font-family: "Plus Jakarta Sans", "Inter", "Segoe UI", sans-serif;
        color: {t['text']};
        selection-background-color: {t['primary']};
        selection-color: {t['onPrimary']};
    }}
    QMainWindow, QWidget#applicationRoot, QWidget#pageBody, QWidget#salesPageBody,
    QScrollArea#pageScrollArea, QStackedWidget#pageStack, QWidget#authFormSide {{
        background: {t['bg']};
    }}
    QScrollArea {{ border: 0; background: transparent; }}
    QDialog {{ background: {t['surface']}; }}

    /* ---------------------------------------------------------------- shell */
    QFrame#sidebar {{ background: {t['surface']}; border: 0; border-right: 1px solid {t['line']}; }}
    QFrame#topBar {{ background: {t['surface']}; border: 0; border-bottom: 1px solid {t['line']}; }}
    QPushButton#brandButton {{
        min-height: 63px; max-height: 63px; border: 0; border-radius: 0; padding: 0;
        border-bottom: 1px solid {t['line']}; background: transparent;
    }}
    QPushButton#brandButton:hover {{ background: {t['surface2']}; }}
    QLabel#productName {{ font-size: 17px; font-weight: 800; }}
    QLabel#productAccent {{ font-size: 17px; font-weight: 500; color: {t['primary']}; }}
    QLabel#productTagline {{ color: {t['text2']}; }}
    QLabel#taglineRule {{ background: {t['gold']}; border-radius: 1px; }}
    QScrollArea#navScroll, QScrollArea#navScroll > QWidget, QWidget#navArea {{ background: transparent; }}
    QLabel#navHeader {{ font-size: 11px; font-weight: 700; color: {t['text2']}; padding: 0 14px 4px 14px; }}
    QFrame#navDivider {{ background: {t['line']}; border: 0; max-height: 1px; min-height: 1px; }}
    QToolButton#navigationButton {{
        min-height: 42px; max-height: 42px; border: 0; border-radius: 10px; padding: 0 14px;
        background: transparent; color: {t['text2']}; font-size: 14px; font-weight: 500; text-align: left;
    }}
    QToolButton#navigationButton:hover {{ background: {t['hover']}; color: {t['text']}; }}
    QToolButton#navigationButton:checked {{ background: {t['tint']}; color: {t['primaryInk']}; font-weight: 700; }}
    QToolButton#navigationButton:focus {{ border: 2px solid {focus}; }}
    QToolButton#navigationButton[compact="true"] {{ padding: 0; }}
    QLabel#countPill {{
        font-size: 11px; font-weight: 700; color: {t['text2']}; background: {t['muted']};
        border-radius: 9px; padding: 1px 8px;
    }}
    QFrame#sideFootCard {{
        background: {t['surface2']}; border: 1px solid {t['line']}; border-radius: 12px;
    }}
    QLabel#sideFootTitle {{ font-size: 12px; font-weight: 700; }}
    QLabel#sideFootText {{ font-size: 12px; color: {t['text2']}; }}
    QLabel#crumb {{ font-size: 12px; font-weight: 600; color: {t['text2']}; }}
    QLabel#topTitle {{ font-size: 16px; font-weight: 800; }}
    QLabel#kbdHint {{
        font-size: 11px; font-weight: 600; color: {t['text2']}; background: {t['surface']};
        border: 1px solid {t['line']}; border-radius: 6px; padding: 1px 6px;
    }}
    QLineEdit#globalSearch {{ background: {t['surface2']}; padding-right: 56px; }}
    QToolButton#accountButton {{
        min-height: 38px; max-height: 38px; border: 1px solid {t['lineStrong']}; border-radius: 10px;
        padding: 0 10px 0 6px; background: {t['surface']};
    }}
    QToolButton#accountButton:hover {{ background: {t['hover']}; }}
    QToolButton#accountButton::menu-indicator {{ image: none; width: 0; }}
    QLabel#accountName {{ font-size: 13px; font-weight: 700; }}
    QLabel#accountRole {{ font-size: 11px; font-weight: 500; color: {t['text2']}; }}
    QLabel#avatar {{
        background: {t['tint2']}; color: {t['primaryInk']}; font-weight: 800;
    }}
    QWidget#menuHeader {{ border-bottom: 1px solid {t['line']}; }}
    QLabel#menuName {{ font-weight: 700; }}
    QLabel#menuEmail {{ font-size: 12px; color: {t['text2']}; }}
    QFrame#toast {{ background: {t['toastBg']}; border: 0; border-radius: 12px; }}
    QLabel#toastText {{ color: {t['toastFg']}; font-size: 13px; font-weight: 600; background: transparent; }}
    QFrame#toast[level="error"] {{ background: {t['danger']}; }}
    QLabel#toastText[level="error"] {{ color: {t['onDanger']}; }}

    /* ---------------------------------------------------------- modal shell */
    QDialog[modalChrome="true"] {{ background: transparent; }}
    QDialogButtonBox {{ button-layout: 3; }}  /* GNOME order: Cancel, then the action on the right */
    QProgressDialog {{ border: 1px solid {t['line']}; border-radius: 16px; }}
    QFrame#modalHeader {{ background: transparent; border: 0; border-bottom: 1px solid {t['line']}; }}
    QLabel#modalKicker {{ font-size: 12px; font-weight: 600; color: {t['text2']}; background: transparent; }}
    QFrame#modalFooter {{
        background: {t['surface2']}; border: 0; border-top: 1px solid {t['line']};
        border-bottom-left-radius: 15px; border-bottom-right-radius: 15px;
    }}
    QFrame#codeBox {{ background: {t['surface2']}; border: 1px dashed {t['lineStrong']}; border-radius: 12px; }}
    QFrame#countBox {{ background: {t['dangerTint']}; border: 0; border-radius: 12px; }}
    QLineEdit#codeField {{ background: transparent; border: 0; font-size: 22px; padding: 0; min-height: 34px; }}
    QLabel#confirmWord {{ background: {t['muted']}; border-radius: 5px; padding: 1px 6px; color: {t['text']}; }}

    /* ------------------------------------------------------------- headings */
    QLabel#pageTitle {{ font-size: 24px; font-weight: 800; }}
    QLabel#pageSubtitle, QLabel#sectionSubtitle, QLabel#dialogSubtitle, QLabel#filterSummary,
    QLabel#helperText, QLabel#helpText, QLabel#insightText, QLabel#metricNote, QLabel#metricLabel,
    QLabel#mutedText {{
        color: {t['text2']};
    }}
    QLabel#pageSubtitle {{ font-size: 13px; }}
    QLabel#sectionTitle {{ font-size: 15px; font-weight: 700; }}
    QLabel#sectionSubtitle, QLabel#filterSummary {{ font-size: 13px; }}
    QLabel#helperText, QLabel#helpText, QLabel#insightText {{ font-size: 12px; }}
    QLabel#dialogTitle {{ font-size: 19px; font-weight: 800; }}
    QLabel#dialogHeading {{ font-size: 16px; font-weight: 700; }}
    QLabel#metricLabel {{ font-size: 13px; font-weight: 600; }}
    QLabel#metricValue {{ font-size: 28px; font-weight: 800; }}
    QLabel#metricNote {{ font-size: 12px; }}
    QLabel#miniLabel {{ font-size: 12px; font-weight: 600; color: {t['text2']}; }}
    QLabel#miniValue {{ font-size: 22px; font-weight: 800; }}
    QLabel#miniValue[tone="success"] {{ color: {t['primaryInk']}; }}
    QFrame#meetingRow {{ background: transparent; border: 0; border-bottom: 1px solid {t['line']}; border-radius: 0; }}
    QFrame#dateBlock {{ background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 10px; }}
    QLabel#dateMonth {{
        background: {t['tint']}; color: {t['primaryInk']}; font-size: 11px; font-weight: 800; padding: 3px 0;
        border-top-left-radius: 9px; border-top-right-radius: 9px;
    }}
    QLabel#dateDay {{ font-size: 20px; font-weight: 800; padding: 2px 0 4px 0; background: transparent; }}
    QLabel#miniValue[tone="danger"] {{ color: {t['danger']}; }}
    QLabel#miniValue[tone="warning"] {{ color: {t['goldInk']}; }}
    QLabel#summaryValue {{ font-size: 18px; font-weight: 800; }}
    QLabel#fieldLabel {{ font-size: 12px; font-weight: 600; color: {t['text2']}; }}
    QLabel#requiredMark {{ font-size: 12px; font-weight: 700; color: {t['danger']}; }}
    QLabel#strongText {{ font-weight: 700; }}
    QLabel#detailTitle {{ font-size: 18px; font-weight: 800; }}
    QLabel#dlKey {{ color: {t['text2']}; font-weight: 600; }}
    QFrame#dlRule {{ background: {t['line']}; border: 0; min-height: 1px; max-height: 1px; }}
    QLabel#statusMessage {{ color: {t['text2']}; padding: 2px 0; }}
    QLabel#statusMessage[level="error"], QLabel#statusMessage[severity="error"],
    QLabel#formError {{ color: {t['danger']}; font-weight: 600; font-size: 12px; }}
    QLabel#statusMessage[level="warning"], QLabel#statusMessage[severity="warning"] {{
        color: {t['goldInk']}; font-weight: 600;
    }}
    QLabel#statusMessage[level="success"], QLabel#statusMessage[severity="success"] {{
        color: {t['primary']}; font-weight: 600;
    }}
    QLabel#emptyState {{
        color: {t['text2']}; background: transparent; border: 0; padding: 32px 20px;
    }}
    QLabel#emptyTitle {{ font-size: 15px; font-weight: 700; }}
    QLabel#iconChip {{ background: {t['tint']}; border-radius: 10px; }}
    QLabel#iconChip[tone="gold"] {{ background: {t['goldTint']}; }}
    QLabel#iconChip[tone="dark"] {{ background: #122321; border: 1px solid #26332F; }}
    QLabel#goldPill {{
        background: {SECONDARY}; color: {INK}; font-size: 11px; font-weight: 800;
        border-radius: 6px; padding: 3px 8px;
    }}
    QLabel#monoText {{ color: {t['text']}; }}
    QFrame#alert {{ border: 0; border-radius: 10px; background: {t['infoBg']}; }}
    QLabel#alertText {{ color: {t['infoInk']}; font-size: 13px; background: transparent; }}
    QFrame#alert[tone="warning"] {{ background: {t['warnBg']}; }}
    QLabel#alertText[tone="warning"] {{ color: {t['warnInk']}; }}
    QFrame#alert[tone="error"] {{ background: {t['dangerTint']}; }}
    QLabel#alertText[tone="error"] {{ color: {t['danger']}; font-weight: 600; }}
    QFrame#alert[tone="success"] {{ background: {t['tint']}; }}
    QLabel#alertText[tone="success"] {{ color: {t['primaryInk']}; }}

    /* ---------------------------------------------------------------- cards */
    QFrame#card, QFrame#metricCard, QFrame#panel, QGroupBox#card, QGroupBox {{
        background: {t['surface']};
        border: 1px solid {t['line']};
        border-radius: 14px;
    }}
    QFrame#metricCard:hover, QPushButton#metricTile:hover, QFrame#card:hover {{ border-color: {t['lineStrong']}; }}
    QFrame#metricCard[selected="true"] {{ border: 2px solid {t['brand']}; }}
    QFrame#cardHeader {{
        background: transparent; border: 0; border-bottom: 1px solid {t['line']}; border-radius: 0;
    }}
    QFrame#cardFooter {{
        background: transparent; border: 0; border-top: 1px solid {t['line']}; border-radius: 0;
    }}
    QFrame#tintCard {{ background: {t['tint']}; border: 1px solid {t['tint2']}; border-radius: 14px; }}
    QFrame#miniCell {{ background: transparent; border: 0; border-radius: 0; }}
    QFrame#rowDivider {{ background: {t['line']}; border: 0; min-height: 1px; max-height: 1px; }}
    QFrame#colDivider {{ background: {t['line']}; border: 0; min-width: 1px; max-width: 1px; }}
    QGroupBox {{ margin-top: 12px; padding-top: 12px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 5px; background: {t['surface']}; }}
    QPushButton#metricTile {{
        background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 14px;
        text-align: left; padding: 0; min-height: 92px;
    }}
    QPushButton#metricTile:focus {{ border: 2px solid {focus}; }}
    QPushButton#listRow {{
        border: 0; border-radius: 10px; background: transparent; text-align: left; padding: 0 0 0 56px;
        min-height: 48px; font-size: 14px; font-weight: 600;
    }}
    QPushButton#listRow:hover {{ background: {t['rowHover']}; }}

    /* -------------------------------------------------------------- buttons */
    QPushButton, QToolButton {{
        min-height: {_BUTTON_BOX}px;
        padding: 0 16px;
        border: 1px solid {t['lineStrong']};
        border-radius: 10px;
        background: {t['surface']};
        color: {t['text']};
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton:hover, QToolButton:hover {{ background: {t['hover']}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {t['muted']}; }}
    QPushButton:focus, QToolButton:focus {{ border: 2px solid {focus}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {t['text2']}; border-color: {t['line']}; }}
    QPushButton#primaryButton {{
        background: {t['primary']}; color: {t['onPrimary']}; border-color: {t['primary']};
    }}
    QPushButton#primaryButton:hover {{ background: {t['primaryHover']}; border-color: {t['primaryHover']}; }}
    QPushButton#primaryButton:disabled {{ background: {t['line']}; border-color: {t['line']}; color: {t['text2']}; }}
    QPushButton#secondaryButton {{ background: {t['surface']}; }}
    QPushButton#ghostButton, QToolButton#ghostButton {{
        background: transparent; border-color: transparent; color: {t['text2']};
    }}
    QPushButton#ghostButton:hover, QToolButton#ghostButton:hover {{ background: {t['hover']}; color: {t['text']}; }}
    QPushButton#linkButton {{
        background: transparent; border-color: transparent; color: {t['primaryInk']};
        padding: 0 8px;
    }}
    QPushButton#linkButton:hover {{ background: {t['hover']}; }}
    QPushButton#tertiaryButton, QPushButton#warningButton {{
        background: {SECONDARY}; color: {INK}; border-color: {SECONDARY};
    }}
    QPushButton#tertiaryButton:hover, QPushButton#warningButton:hover {{ background: #E2A900; border-color: #E2A900; }}
    QPushButton#dangerButton {{
        color: {t['onDanger']}; background: {t['danger']}; border-color: {t['danger']};
    }}
    QPushButton#dangerButton:hover {{ background: {t['dangerHover']}; border-color: {t['dangerHover']}; }}
    QPushButton#dangerButton:disabled {{ background: {t['line']}; border-color: {t['line']}; color: {t['text2']}; }}
    QPushButton#dangerOutlineButton {{ color: {t['danger']}; }}
    QPushButton#dangerOutlineButton:hover {{ background: {t['dangerTint']}; border-color: {t['danger']}; }}
    QPushButton#compactButton[alert="true"] {{
        color: {t['danger']}; border-color: {t['danger']}; background: {t['dangerTint']};
    }}
    QPushButton#iconButton, QToolButton#iconButton {{
        min-width: {_BUTTON_BOX}px; max-width: {_BUTTON_BOX}px;
        min-height: {_BUTTON_BOX}px; max-height: {_BUTTON_BOX}px; padding: 0;
    }}
    QPushButton#iconButtonSmall, QToolButton#iconButtonSmall {{
        min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px; padding: 0;
        border-color: transparent; background: transparent;
    }}
    QPushButton#iconButtonSmall:hover, QToolButton#iconButtonSmall:hover {{ background: {t['hover']}; }}
    QPushButton#chipButton {{
        min-height: {_BUTTON_BOX}px; border-radius: {BUTTON_HEIGHT // 2}px; border: 1px solid {t['line']};
        background: {t['surface2']};
        padding: 0 14px; font-weight: 500;
    }}
    QPushButton#chipButton:hover {{ border-color: {t['brand']}; background: {t['tint']}; }}
    QPushButton#chipButton:checked {{
        background: {t['tint']}; border-color: {t['brand']}; color: {t['primaryInk']}; font-weight: 700;
    }}
    QPushButton#pageButton {{
        min-width: {_BUTTON_BOX}px; max-width: {_BUTTON_BOX}px;
        min-height: {_BUTTON_BOX}px; max-height: {_BUTTON_BOX}px; padding: 0;
        border-radius: 10px; border-color: {t['line']};
    }}
    QPushButton#pageButton[current="true"] {{
        background: {t['tint']}; border-color: {t['brand']}; color: {t['primaryInk']}; font-weight: 800;
    }}
    QPushButton#navigationButton {{ text-align: left; }}
    QPushButton#primaryButton:focus, QToolButton#navigationButton:checked:focus {{ border: 2px solid {focus_on_fill}; }}
    QPushButton#tertiaryButton:focus, QPushButton#warningButton:focus {{ border: 2px solid {INK}; }}
    QPushButton#dangerButton:focus {{ border: 2px solid {focus_on_danger}; }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}

    /* --------------------------------------------------------------- inputs */
    QLineEdit, QComboBox, QDateEdit, QDateTimeEdit, QSpinBox, QDoubleSpinBox {{
        min-height: 38px;
        padding: 0 12px;
        border: 1px solid {t['lineStrong']};
        border-radius: 10px;
        background: {t['surface']};
        font-size: 13px;
    }}
    QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QDateTimeEdit:hover {{ border-color: {t['text2']}; }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDateTimeEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus {{
        border: 2px solid {focus}; padding: 0 11px;
    }}
    QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QDateTimeEdit:disabled {{
        color: {t['text2']}; background: {t['muted']}; border-color: {t['line']};
    }}
    QLineEdit:read-only {{ background: {t['surface2']}; }}
    QLineEdit[invalid="true"], QComboBox[invalid="true"], QPlainTextEdit[invalid="true"],
    QCheckBox[invalid="true"] {{ border: 2px solid {t['danger']}; }}
    QComboBox::drop-down, QDateEdit::drop-down, QDateTimeEdit::drop-down {{
        border: 0; width: 30px; subcontrol-origin: padding; subcontrol-position: center right;
    }}
    QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
    QDateEdit::down-arrow, QDateTimeEdit::down-arrow {{ image: url("{calendar}"); width: 16px; height: 16px; }}
    QComboBox::down-arrow:disabled, QDateEdit::down-arrow:disabled {{ image: url("{chevron_disabled}"); }}
    QComboBox QAbstractItemView {{
        background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 10px; padding: 6px;
        outline: 0; selection-background-color: {t['tint']}; selection-color: {t['primaryInk']};
    }}
    QPlainTextEdit, QTextEdit {{
        border: 1px solid {t['lineStrong']}; border-radius: 10px; background: {t['surface']}; padding: 6px 8px;
    }}
    QPlainTextEdit:focus, QTextEdit:focus {{ border: 2px solid {focus}; padding: 5px 7px; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox#fieldCheck {{ font-size: 12px; font-weight: 600; color: {t['text2']}; }}
    QListWidget#plainList {{ border: 0; border-radius: 0; padding: 8px 12px; }}
    QListWidget#plainList::item {{ min-height: 40px; border-bottom: 1px solid {t['line']}; border-radius: 0; }}
    QCheckBox::indicator, QTableView::indicator, QListView::indicator {{
        width: 16px; height: 16px; border: 2px solid {t['lineStrong']}; border-radius: 5px;
        background: {t['surface']};
    }}
    QCheckBox::indicator:hover {{ border-color: {t['primary']}; }}
    QCheckBox::indicator:checked, QTableView::indicator:checked, QListView::indicator:checked {{
        background: {t['primary']}; border-color: {t['primary']}; image: url("{check}");
    }}
    QCheckBox::indicator:disabled {{ background: {t['muted']}; border-color: {t['line']}; }}
    QRadioButton::indicator {{ width: 16px; height: 16px; }}

    /* --------------------------------------------------------------- tables */
    QTableWidget, QTableView, QListWidget, QTreeView {{
        font-size: 13px;
        background: {t['surface']};
        alternate-background-color: {t['surface']};
        border: 0;
        gridline-color: {t['line']};
        selection-background-color: {t['tint']};
        selection-color: {t['text']};
        outline: 0;
    }}
    QListWidget {{ border: 1px solid {t['line']}; border-radius: 10px; padding: 4px; }}
    QListWidget::item {{ min-height: 30px; border-radius: 6px; padding: 0 6px; }}
    QListWidget::item:selected {{ background: {t['tint']}; color: {t['text']}; }}
    QTableView::item {{ padding: 0 6px 0 14px; border-bottom: 1px solid {t['line']}; }}
    QTableView::item:selected {{ background: {t['tint']}; color: {t['text']}; }}
    QLabel#tableEmptyMessage {{ color: {t['text2']}; font-size: 13px; background: transparent; }}
    QHeaderView {{ background: {t['surface2']}; border: 0; }}
    QHeaderView::section {{
        background: {t['surface2']};
        color: {t['text2']};
        border: 0;
        border-bottom: 1px solid {t['line']};
        padding: 0 6px 0 14px;
        min-height: 40px;
        font-size: 12px;
        font-weight: 700;
    }}
    QHeaderView::section:hover {{ color: {t['text']}; }}
    /* Sort arrow above the label, so it never covers right-aligned (number) headings. */
    QHeaderView::up-arrow, QHeaderView::down-arrow {{
        subcontrol-origin: margin; subcontrol-position: top center; width: 8px; height: 8px;
    }}
    QTableCornerButton::section {{ background: {t['surface2']}; border: 0; }}

    /* ----------------------------------------------------------------- tabs */
    QTabWidget::pane {{ border: 0; border-top: 1px solid {t['line']}; background: transparent; top: -1px; }}
    QTabWidget::tab-bar {{ left: 12px; }}
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{
        min-height: 46px; padding: 0 14px; margin: 0 2px; border: 0;
        border-bottom: 3px solid transparent; background: transparent;
        color: {t['text2']}; font-size: 13px; font-weight: 600;
    }}
    QTabBar::tab:hover {{ color: {t['text']}; }}
    QTabBar::tab:selected {{ color: {t['text']}; border-bottom-color: {t['brand']}; }}
    QTabBar[animatedIndicator="true"]::tab:selected {{ border-bottom-color: transparent; }}
    QTabBar::tab:disabled {{ color: {t['line']}; }}
    QTabBar#settingsTabs[danger="true"]::tab:last {{ color: {t['danger']}; }}
    QTabBar QToolButton {{ min-height: 0; min-width: 22px; padding: 0; border-radius: 6px; }}

    /* ----------------------------------------------------- menus & tooltips */
    QMenu {{
        background: {t['surface']}; border: 1px solid {t['line']}; border-radius: 12px; padding: 8px;
    }}
    QMenu::item {{ min-height: 38px; padding: 0 12px 0 10px; border-radius: 8px; color: {t['text']}; }}
    QMenu::item:selected {{ background: {t['hover']}; }}
    QMenu::item:disabled {{ color: {t['text2']}; }}
    QMenu::separator {{ height: 1px; background: {t['line']}; margin: 6px 4px; }}
    QMenu::icon {{ padding-left: 8px; }}
    QMenu::section {{ color: {t['text2']}; font-size: 11px; font-weight: 700; padding: 6px 10px; }}
    QToolTip {{
        background: {t['tipBg']}; color: {t['tipFg']}; border: 0; border-radius: 7px; padding: 6px 10px;
        font-size: 12px; font-weight: 600;
    }}

    /* ------------------------------------------------------ misc. controls */
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['lineStrong']}; min-height: 30px; border-radius: 3px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t['lineStrong']}; min-width: 30px; border-radius: 3px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:horizontal {{ width: 16px; }}
    QSplitter::handle:vertical {{ height: 16px; }}
    QProgressBar {{
        min-height: 12px; max-height: 12px; color: transparent; background: {t['muted']};
        border: 0; border-radius: 6px; text-align: center;
    }}
    QProgressBar::chunk {{ background: {t['chartA']}; border-radius: 6px; }}
    QProgressBar[stage="meeting"]::chunk {{ background: {t['chartA']}; }}
    QProgressBar[stage="client"]::chunk {{ background: {t['primary']}; }}
    QStatusBar {{ background: {t['surface']}; border-top: 1px solid {t['line']}; }}
    QFrame#calendarFooter {{ background: {t['surface']}; border: 0; border-top: 1px solid {t['line']}; }}
    QPushButton#todayButton {{
        background: {t['tint']}; color: {t['primaryInk']}; border-color: {t['tint']}; font-weight: 700;
        padding: 0 16px;
    }}
    """


def calendar_stylesheet(dark: bool | None = None) -> str:
    """Date-picker styling, applied to each pop-up calendar itself (see ``desktop_ui.popups``).

    Kept out of the application stylesheet: rules scoped under ``QCalendarWidget``
    would be checked against every widget on every theme change.
    """
    t = tokens(dark)
    return f"""
    QCalendarWidget {{ background: {t['surface']}; }}
    QWidget#qt_calendar_navigationbar {{
        background: {t['surface']}; padding: 6px 6px 2px 6px;
    }}
    QToolButton {{
        min-height: {BUTTON_HEIGHT}px; border: 0; background: transparent; color: {t['text']}; font-size: 14px;
        font-weight: 700;
    }}
    QToolButton:hover {{ background: {t['hover']}; }}
    QToolButton#qt_calendar_prevmonth, QToolButton#qt_calendar_nextmonth {{
        min-width: {_BUTTON_BOX}px; max-width: {_BUTTON_BOX}px;
        min-height: {_BUTTON_BOX}px; max-height: {_BUTTON_BOX}px; padding: 0;
        border: 1px solid {t['line']}; border-radius: 10px;
    }}
    QToolButton::menu-indicator {{ image: none; width: 0; }}
    QSpinBox {{ min-height: 30px; }}
    QAbstractItemView {{
        background: {t['surface']}; color: {t['text']}; font-size: 13px; outline: 0; border: 0;
        selection-background-color: {t['primary']}; selection-color: {t['onPrimary']};
    }}
    QAbstractItemView:disabled {{ color: {t['lineStrong']}; }}
    QTableView::item {{ border: 0; padding: 0; }}
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
        _state["dark"] = self.dark
        # Fusion draws every control from the stylesheet the same way on Windows,
        # macOS and Linux; native styles ignore parts of it (e.g. combo pop-ups).
        # Set once: with a stylesheet active, style().name() no longer reads "fusion".
        if not self.app.property("fusionStyle"):
            self.app.setStyle("Fusion")
            self.app.setProperty("fusionStyle", True)
        font_family = load_application_font()
        font = QFont(font_family)
        font.setPixelSize(14)
        self.app.setFont(font)
        self.app.setPalette(_palette(self.dark))
        self.app.setStyleSheet(build_stylesheet(self.dark))
        self.settings.setValue("appearance/dark", self.dark)
        from techset_leadgen.desktop.icons import refresh_themed_icons
        from techset_leadgen.desktop.motion import install

        install(self.app)  # hover/press motion, the modal shell, and animated tab indicators
        refresh_themed_icons()
        self.theme_changed.emit(self.dark)

    def toggle(self) -> bool:
        self.apply(not self.dark)
        return self.dark
