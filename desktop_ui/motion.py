"""The redesign's motion layer: entrances, hover and press feedback, and transitions.

The design animates only position, scale, and opacity (never layout, colour
meaning, or content), with three curves:

* ``EASE`` – cubic-bezier(.22, .61, .36, 1) for entrances and colour glides;
* ``EASE_OUT`` – cubic-bezier(.2, .8, .2, 1) for charts and pop-overs;
* ``SPRING`` – cubic-bezier(.34, 1.56, .64, 1), a small overshoot for toggles and markers.

Every helper here is a no-op when motion is reduced: the user turned off
animations in the operating system (Windows "Show animations in Windows"),
``TSLG_REDUCED_MOTION`` is set (the test suite sets it so results never depend
on timing), or the Settings "Reduce motion" switch is on. Widgets then simply
appear in their final state, as the design's ``prefers-reduced-motion`` rule does.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable, Sequence

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QSettings,
    QTimer,
    QVariantAnimation,
    Qt,
)
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QPushButton, QWidget
from shiboken6 import Shiboken

from branding import PARENT_BRAND, PRODUCT_NAME

_EFFECT_PROPERTY = "_motionEffect"
_RUNNING_PROPERTY = "_motionRunning"


def _curve(x1: float, y1: float, x2: float, y2: float) -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1, 1))
    return curve


EASE = _curve(0.22, 0.61, 0.36, 1)
EASE_OUT = _curve(0.2, 0.8, 0.2, 1)
SPRING = _curve(0.34, 1.56, 0.64, 1)

_state: dict[str, bool | None] = {"override": None}


def _windows_animations_off() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        enabled = ctypes.c_bool(True)
        # SPI_GETCLIENTAREAANIMATION: Settings > Accessibility > Visual effects > Animation effects.
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)  # type: ignore[attr-defined]
        return not enabled.value
    except Exception:  # pragma: no cover - platform dependent
        return False


def _settings() -> QSettings:
    return QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, PARENT_BRAND, PRODUCT_NAME)


def reduced_motion() -> bool:
    """True when animations should be skipped (OS setting, environment, or Settings switch)."""
    if os.environ.get("TSLG_REDUCED_MOTION", "").strip() not in ("", "0"):
        return True
    if _state["override"] is not None:
        return bool(_state["override"])
    value = bool(_settings().value("appearance/reduceMotion", False, type=bool))
    _state["override"] = value or _windows_animations_off()
    return bool(_state["override"])


def set_reduced_motion(reduce: bool) -> None:
    """Remember the Settings switch (and apply it to this session at once)."""
    _settings().setValue("appearance/reduceMotion", bool(reduce))
    _state["override"] = bool(reduce) or _windows_animations_off()


def animate(start: float, end: float, duration: int, apply: Callable[[float], None], *,
            curve: QEasingCurve = EASE, delay: int = 0, done: Callable[[], None] | None = None,
            owner: QObject | None = None) -> QVariantAnimation | None:
    """Run ``apply(value)`` from ``start`` to ``end``; returns the animation (None when reduced)."""
    if reduced_motion():
        apply(end)
        if done is not None:
            done()
        return None
    animation = QVariantAnimation(owner)
    animation.setStartValue(float(start))
    animation.setEndValue(float(end))
    animation.setDuration(max(1, duration))
    animation.setEasingCurve(curve)

    def step(value: object) -> None:
        try:
            apply(float(value))  # type: ignore[arg-type]
        except RuntimeError:  # the widget was deleted mid-animation
            animation.stop()

    animation.valueChanged.connect(step)
    if done is not None:
        animation.finished.connect(done)
    apply(float(start))
    if delay > 0:
        QTimer.singleShot(delay, lambda: animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
                          if Shiboken.isValid(animation) else None)
    else:
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


# ------------------------------------------------------------------ entrances


def clear_effect(widget: QWidget) -> None:
    """Remove a widget's graphics effect (PySide accepts None; its type stubs do not say so)."""
    widget.setGraphicsEffect(None)  # type: ignore[arg-type]


def _opacity_effect(widget: QWidget) -> QGraphicsOpacityEffect | None:
    """An opacity effect for the entrance; never replaces another effect (a shadow)."""
    current = widget.graphicsEffect()
    if current is not None and not isinstance(current, QGraphicsOpacityEffect):
        return None
    effect = current if isinstance(current, QGraphicsOpacityEffect) else QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    return effect


def _finish_entrance(widget: QWidget, origin: QPoint | None) -> None:
    if not Shiboken.isValid(widget):
        return
    effect = widget.graphicsEffect()
    if isinstance(effect, QGraphicsOpacityEffect):
        clear_effect(widget)  # a lasting effect would re-render the widget off-screen forever
    if origin is not None and widget.property(_RUNNING_PROPERTY):
        widget.move(origin)
    widget.setProperty(_RUNNING_PROPERTY, False)
    parent = widget.parentWidget()
    layout = parent.layout() if parent is not None else None
    if layout is not None:
        layout.invalidate()  # the layout puts the widget back exactly where it belongs


def enter(widget: QWidget, *, dx: int = 0, dy: int = 14, duration: int = 550, delay: int = 0,
          curve: QEasingCurve = EASE, fade: bool = True) -> None:
    """Fade ``widget`` in while it slides ``dx``/``dy`` pixels into place (the design's rise/slidein)."""
    if reduced_motion() or not Shiboken.isValid(widget) or not widget.isVisible():
        return
    if widget.property(_RUNNING_PROPERTY):
        return
    widget.setProperty(_RUNNING_PROPERTY, True)
    origin = QPoint(widget.pos())
    effect = _opacity_effect(widget) if fade else None

    def step(progress: float) -> None:
        if not Shiboken.isValid(widget):
            return
        if effect is not None and Shiboken.isValid(effect):
            effect.setOpacity(max(0.0, min(1.0, progress)))
        offset = 1.0 - progress
        widget.move(origin.x() + round(dx * offset), origin.y() + round(dy * offset))

    animate(0.0, 1.0, duration, step, curve=curve, delay=delay, owner=widget,
            done=lambda: _finish_entrance(widget, origin))
    if delay and effect is not None:
        effect.setOpacity(0.0)


def rise(widgets: Iterable[QWidget], *, step: int = 60, start: int = 0, duration: int = 550,
         dy: int = 14, limit: int = 6) -> None:
    """Rise a group of widgets one after another (the design's staggered page entrance)."""
    for index, widget in enumerate(widgets):
        enter(widget, dy=dy, duration=duration, delay=start + step * min(index, limit))


def slide_in(widgets: Sequence[QWidget], *, dx: int = -16, step: int = 50, start: int = 0,
             duration: int = 450) -> None:
    for index, widget in enumerate(widgets):
        enter(widget, dx=dx, dy=0, duration=duration, delay=start + step * index)


def fade_in(widget: QWidget, *, duration: int = 400, delay: int = 0) -> None:
    enter(widget, dy=0, duration=duration, delay=delay)


def visible_children(container: QWidget) -> list[QWidget]:
    """The child widgets a layout shows, in layout order (one level into nested layouts,
    so the cards of a KPI grid rise one by one, as in the design)."""
    layout = container.layout()
    if layout is None:
        return []
    result: list[QWidget] = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item is None:
            continue
        widget = item.widget()
        if widget is not None:
            if widget.isVisible():
                result.append(widget)
            continue
        inner = item.layout()
        if inner is not None:
            for position in range(inner.count()):
                child = inner.itemAt(position)
                child_widget = child.widget() if child is not None else None
                if child_widget is not None and child_widget.isVisible():
                    result.append(child_widget)
    return result


def page_sections(page: QWidget) -> list[QWidget]:
    """The sections of a page in reading order: its own hook, a scroll area's body, or itself."""
    hook = getattr(page, "entrance_widgets", None)
    if callable(hook):
        return list(hook())
    from PySide6.QtWidgets import QScrollArea

    for scroll in page.findChildren(QScrollArea):
        body = scroll.widget()
        if scroll.parentWidget() is page and body is not None and body.layout() is not None:
            return visible_children(body)
    return visible_children(page)


def page_entrance(page: QWidget) -> None:
    """The design's page entrance: sections rise 14 px with a 60 ms stagger; charts grow again."""
    if reduced_motion():
        return
    rise(page_sections(page), step=60, duration=550, dy=14)
    replay_charts(page)


def replay_charts(root: QWidget) -> None:
    for child in root.findChildren(QWidget):
        replay = getattr(child, "replay", None)
        if callable(replay) and child.isVisible():
            replay()


# ------------------------------------------------------------------ windows


def pop_window(window: QWidget, *, dy: int = 18, duration: int = 340) -> None:
    """Fade a top-level window in while it rises into place (modals, menus)."""
    if reduced_motion() or not window.isWindow():
        return
    origin = QPoint(window.pos())

    def step(progress: float) -> None:
        if Shiboken.isValid(window):
            window.setWindowOpacity(max(0.0, min(1.0, progress * 1.4)))
            window.move(origin.x(), origin.y() + round(dy * (1 - progress)))

    animate(0.0, 1.0, duration, step, curve=EASE_OUT, owner=window,
            done=lambda: window.setWindowOpacity(1.0) if Shiboken.isValid(window) else None)


def cross_fade(host: QWidget, change: Callable[[], object], *, duration: int = 300) -> None:
    """Run ``change`` (a theme switch) and fade from a snapshot of the old look to the new one."""
    if reduced_motion() or not host.isVisible():
        change()
        return
    snapshot = host.grab()
    change()
    cover = _Snapshot(host, snapshot)
    cover.show()
    cover.raise_()
    animate(1.0, 0.0, duration, cover.set_opacity, curve=EASE, owner=cover, done=cover.deleteLater)


class _Snapshot(QWidget):
    def __init__(self, host: QWidget, pixmap: QPixmap) -> None:
        super().__init__(host)
        self._pixmap = pixmap
        self._opacity = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(host.rect())

    def set_opacity(self, value: float) -> None:
        if Shiboken.isValid(self):
            self._opacity = value
            self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.end()


# ------------------------------------------------------------------ hover and press


class ButtonMotion(QObject):
    """App-wide hover lift (1 px) and press dip for push buttons, as in the design.

    The button is nudged inside its layout and returned to the place the layout
    gave it; the next layout pass would put it back anyway.
    """

    _LIFT = "_motionLift"

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        kind = event.type()
        if kind not in (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.MouseButtonPress,
                        QEvent.Type.MouseButtonRelease):
            return False
        if not isinstance(watched, QPushButton) or reduced_motion() or not watched.isEnabled():
            return False
        if watched.objectName() in ("listRow", "brandButton", "pageButton") or watched.isFlat():
            return False
        try:
            if kind == QEvent.Type.Enter and not watched.property(self._LIFT):
                watched.setProperty(self._LIFT, QPoint(watched.pos()))
                watched.move(watched.x(), watched.y() - 1)
            elif kind == QEvent.Type.Leave:
                origin = watched.property(self._LIFT)
                watched.setProperty(self._LIFT, None)
                if isinstance(origin, QPoint) and watched.pos() == QPoint(origin.x(), origin.y() - 1):
                    watched.move(origin)
            elif kind == QEvent.Type.MouseButtonPress:
                _press(watched, True)
            elif kind == QEvent.Type.MouseButtonRelease:
                _press(watched, False)
        except RuntimeError:
            pass
        return False


def _press(button: QPushButton, down: bool) -> None:
    """Shrink the button by 4% around its centre while pressed (the design's scale(.96))."""
    rect = button.geometry()
    if down:
        button.setProperty("_motionPress", rect)
        dx, dy = round(rect.width() * 0.02), round(rect.height() * 0.02)
        button.setGeometry(rect.adjusted(dx, dy, -dx, -dy))
    else:
        saved = button.property("_motionPress")
        button.setProperty("_motionPress", None)
        if saved is not None:
            button.setGeometry(saved)


class _AppEvents(QObject):
    """One app-wide event filter that hands each event only to the handlers that need it.

    (Four separate application filters were each called for every event: a theme
    change alone sends some 90,000 events.)
    """

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        from .modal import FocusTrap
        from .popups import PopupStyler
        from .tab_motion import TabMotion

        self.buttons = ButtonMotion(self)
        self.trap = FocusTrap(self)  # keyboard stays inside a dialog open in the window
        self.tabs = TabMotion(self)
        self.popups = PopupStyler(self)  # drop-down lists and date pickers (not motion, but app-wide)
        kind = QEvent.Type
        pointer: tuple[QObject, ...] = (self.buttons,)
        trap: tuple[QObject, ...] = (self.trap,)
        self._routes: dict[QEvent.Type, tuple[QObject, ...]] = {
            kind.Enter: pointer, kind.Leave: pointer,
            kind.MouseButtonPress: pointer, kind.MouseButtonRelease: pointer,
            kind.KeyPress: trap, kind.Shortcut: trap, kind.FocusIn: trap,
            kind.Polish: (self.popups,),
            kind.Show: (self.tabs, self.popups),
        }

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        handlers = self._routes.get(event.type())
        if handlers:
            for handler in handlers:
                if handler.eventFilter(watched, event):
                    return True  # swallowed (a window shortcut while a dialog is open)
        return False


_installed: dict[str, QObject] = {}


def install(app: QApplication) -> None:
    """Install the app-wide motion, dialog focus and pop-up handling once."""
    if "events" in _installed:
        return
    _installed["events"] = _AppEvents(app)
    app.installEventFilter(_installed["events"])
    if not reduced_motion():  # Qt's own fades for menus, combo lists and tooltips
        for effect in (Qt.UIEffect.UI_AnimateMenu, Qt.UIEffect.UI_FadeMenu, Qt.UIEffect.UI_AnimateCombo,
                       Qt.UIEffect.UI_AnimateTooltip, Qt.UIEffect.UI_FadeTooltip):
            QApplication.setEffectEnabled(effect, True)


__all__ = [
    "EASE", "EASE_OUT", "SPRING", "ButtonMotion", "animate", "clear_effect", "cross_fade", "enter", "fade_in", "install",
    "page_entrance", "page_sections", "pop_window", "reduced_motion", "replay_charts", "rise",
    "set_reduced_motion", "slide_in", "visible_children",
]
