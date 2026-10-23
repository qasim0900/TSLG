"""Theme-aware line icons, drawn from one 24 × 24 stroke set with QtSvg.

Every icon in the desktop UI comes from ``_PATHS`` (the redesign's icon set:
1.8 px rounded strokes), rendered in a colour taken from the active theme.
Widgets that show an icon register it with ``set_button_icon`` /
``ThemedIconLabel``; ``refresh_themed_icons`` re-tints them all when the theme
changes, so no icon is ever drawn in the previous theme's colours.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget

_SCALE = 2  # render at 2x for high-DPI screens
_ICON_PROPERTY = "themedIcon"
_ROLE_PROPERTY = "themedIconRole"
_SIZE_PROPERTY = "themedIconSize"

_PATHS: dict[str, str] = {
    # Navigation
    "dashboard": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>'
                 '<rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "sales": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "leads": '<path d="M3 4h18l-7 8.5V19l-4 2v-8.5L3 4z"/>',
    "clients": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.4 3.4-5.5 6.5-5.5s5.7 2.1 6.5 5.5"/>'
               '<path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M18 14.8c1.8.7 3 2.6 3.5 5.2"/>',
    "tasks": '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M8 12l3 3 5-6"/>',
    "users": '<circle cx="10" cy="8" r="4"/><path d="M3 20c.9-3.6 3.7-6 7-6 1.3 0 2.5.3 3.5.9"/>'
             '<path d="M18 14l3 1.2v2.3c0 1.8-1.3 3.2-3 3.5-1.7-.3-3-1.7-3-3.5v-2.3L18 14z"/>',
    "audit": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z"/><path d="M14 3v5h5"/>'
             '<path d="M9 13h6M9 17h4"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1'
                'M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
    # Shell
    "database": '<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13"/>'
                '<path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9 4v16"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2'
           'M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-left": '<path d="M15 6l-6 6 6 6"/>',
    "chevron-right": '<path d="M9 6l6 6-6 6"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4.2-6.5 8-6.5s7 2.5 8 6.5"/>',
    "guest": '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6"/>',
    "logout": '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5M5 12h11"/>',
    # Actions
    "refresh": '<path d="M20 11a8 8 0 0 0-14.6-4.5L3 9"/><path d="M3 4v5h5"/>'
               '<path d="M4 13a8 8 0 0 0 14.6 4.5L21 15"/><path d="M21 20v-5h-5"/>',
    "upload": '<path d="M12 15V3M7 8l5-5 5 5"/><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>',
    "download": '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "merge": '<path d="M6 3v6a6 6 0 0 0 6 6h6"/><path d="M15 12l3 3-3 3"/><path d="M6 21v-4"/>',
    "assign": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.4 3.4-5.5 6.5-5.5s5.7 2.1 6.5 5.5"/>'
              '<path d="M19 8v6M16 11h6"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2.5"/>'
            '<path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "check": '<path d="M5 12l5 5 9-10"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M3 3l18 18"/><path d="M10.6 5.1A10.6 10.6 0 0 1 12 5c6.4 0 10 7 10 7a17.7 17.7 0 0 1-3.2 4.1"/>'
               '<path d="M6.6 6.6C3.9 8.4 2 12 2 12s3.6 7 10 7a10 10 0 0 0 5.4-1.6"/>'
               '<path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    "lock": '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5z"/><path d="M14 3v5h5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    # Status and metrics
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.01"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5v.01"/>',
    "warning": '<path d="M12 3l9.5 17h-19L12 3z"/><path d="M12 10v4M12 17.5v.01"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "receipt": '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3z"/><path d="M9 8h6M9 12h6"/>',
    "receipt-plain": '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3z"/>',
    "people": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.4 3.4-5.5 6.5-5.5s5.7 2.1 6.5 5.5"/>'
              '<path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "box": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
    "money": '<circle cx="12" cy="12" r="9"/><path d="M14.5 9.5c-.4-.9-1.4-1.5-2.5-1.5-1.5 0-2.5.8-2.5 2s1 1.7 2.5 2'
             ' 2.5.8 2.5 2-1 2-2.5 2c-1.1 0-2.1-.6-2.5-1.5M12 6.5v11"/>',
    "chart": '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    "dot": '<circle cx="12" cy="12" r="4"/>',
    "arrow-right": '<path d="M5 12h14M13 6l6 6-6 6"/>',
}

NAVIGATION_ICON_NAMES = ("dashboard", "sales", "leads", "clients", "tasks", "users", "audit", "settings")


def icon_names() -> tuple[str, ...]:
    return tuple(_PATHS)


def _svg(name: str, color: QColor, stroke: float) -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color.name()}" stroke-opacity="{color.alphaF():.3f}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>'
    ).encode()


def pixmap(name: str, color: str | QColor, size: int = 18, stroke: float = 1.8, *, gap: int = 0) -> QPixmap:
    """Render icon ``name`` as a transparent pixmap ``size`` logical pixels square.

    ``gap`` adds transparent space on the right: Qt puts a fixed 4 px between a
    button's icon and its text, and the design wants 8 px.
    """
    renderer = QSvgRenderer(QByteArray(_svg(name, QColor(color), stroke)))
    image = QPixmap((size + gap) * _SCALE, size * _SCALE)
    image.setDevicePixelRatio(_SCALE)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def icon(name: str, color: str | QColor, size: int = 18, *, checked_color: str | QColor | None = None,
         disabled_color: str | QColor | None = None, gap: int = 0) -> QIcon:
    """A QIcon in ``color``; optionally another colour when checked or disabled."""
    result = QIcon()
    normal = pixmap(name, color, size, gap=gap)
    on = pixmap(name, checked_color, size, gap=gap) if checked_color is not None else normal
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
        result.addPixmap(normal, mode, QIcon.State.Off)
        result.addPixmap(on, mode, QIcon.State.On)
    if disabled_color is not None:
        faded = pixmap(name, disabled_color, size, gap=gap)
        result.addPixmap(faded, QIcon.Mode.Disabled, QIcon.State.Off)
        result.addPixmap(faded, QIcon.Mode.Disabled, QIcon.State.On)
    return result


def navigation_icon(name: str, color: str, checked_color: str, size: int = 18) -> QIcon:
    """Return an icon drawn in ``color``, and in ``checked_color`` when its button is checked."""
    return icon(name, color, size, checked_color=checked_color)


# ---------------------------------------------------------------- theme-following icons


def _role_color(role: str) -> str:
    from .theme import tokens

    values = tokens()
    return values.get(role, values["text"])


def set_button_icon(button: QAbstractButton, name: str | None, role: str = "text", size: int = 16) -> None:
    """Give ``button`` icon ``name`` in the theme colour ``role``; it follows theme changes.

    ``role`` is a token name from :func:`desktop_ui.theme.tokens` ("text", "text2",
    "onPrimary", "primaryInk", "danger", ...). ``None`` removes the icon.
    """
    button.setProperty(_ICON_PROPERTY, name)
    button.setProperty(_ROLE_PROPERTY, role)
    button.setProperty(_SIZE_PROPERTY, size)
    _apply_button_icon(button)


def _apply_button_icon(button: QAbstractButton) -> None:
    from .theme import tokens

    name = button.property(_ICON_PROPERTY)
    if not name:
        button.setIcon(QIcon())
        return
    size = int(button.property(_SIZE_PROPERTY) or 16)
    gap = 4 if button.text() else 0
    button.setIcon(icon(name, _role_color(str(button.property(_ROLE_PROPERTY) or "text")), size,
                        disabled_color=tokens()["text2"], gap=gap))
    button.setIconSize(QSize(size + gap, size))


class ThemedIconLabel(QLabel):
    """A QLabel showing one icon in a theme colour (re-tinted on theme changes)."""

    def __init__(self, name: str, role: str = "text2", size: int = 16, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty(_ICON_PROPERTY, name)
        self.setProperty(_ROLE_PROPERTY, role)
        self.setProperty(_SIZE_PROPERTY, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.refresh_icon()

    def set_icon(self, name: str, role: str | None = None) -> None:
        self.setProperty(_ICON_PROPERTY, name)
        if role is not None:
            self.setProperty(_ROLE_PROPERTY, role)
        self.refresh_icon()

    def refresh_icon(self) -> None:
        name = self.property(_ICON_PROPERTY)
        size = int(self.property(_SIZE_PROPERTY) or 16)
        if name:
            self.setPixmap(pixmap(str(name), _role_color(str(self.property(_ROLE_PROPERTY))), size))


def refresh_themed_icons() -> None:
    """Re-tint every registered icon after the theme changed."""
    for widget in QApplication.allWidgets():
        try:
            if widget.property(_ICON_PROPERTY) is None:
                continue
            if isinstance(widget, ThemedIconLabel):
                widget.refresh_icon()
            elif isinstance(widget, QAbstractButton):
                _apply_button_icon(widget)
        except RuntimeError:  # a widget being destroyed
            continue


__all__ = [
    "NAVIGATION_ICON_NAMES", "ThemedIconLabel", "icon", "icon_names", "navigation_icon", "pixmap",
    "refresh_themed_icons", "set_button_icon",
]
