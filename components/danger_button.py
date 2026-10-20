"""components.danger_button
Helper para crear botones de acción peligrosa (vaciar/eliminar) que
responden al `theme_mode` actual.

Provee:
- `get_danger_button_style(theme_mode)` -> `ft.ButtonStyle`
- `create_danger_button(text, on_click, page_or_theme_mode=None)` -> `ft.ElevatedButton`
  El botón expone `update_theme(page_or_theme_mode)` para mutar estilo en caliente.
"""

import flet as ft


def get_danger_button_style(theme_mode: ft.ThemeMode | None):
    """Devuelve un `ft.ButtonStyle` apropiado para el `theme_mode`.

    Args:
        theme_mode: `ft.ThemeMode.DARK` o `ft.ThemeMode.LIGHT` (o None → LIGHT)
    """
    return ft.ButtonStyle(
        bgcolor={
            ft.ControlState.DEFAULT: ft.Colors.ERROR_CONTAINER,
            ft.ControlState.HOVERED: ft.Colors.ERROR,
        },
        color={
            ft.ControlState.DEFAULT: ft.Colors.ON_ERROR_CONTAINER,
            ft.ControlState.HOVERED: ft.Colors.ON_ERROR,
        },
        icon_color={
            ft.ControlState.DEFAULT: ft.Colors.ON_ERROR_CONTAINER,
            ft.ControlState.HOVERED: ft.Colors.ON_ERROR,
        },
    )


def _resolve_theme_mode(page_or_theme_mode):
    if page_or_theme_mode is None:
        return ft.ThemeMode.LIGHT
    # If a Page-like object provided
    if hasattr(page_or_theme_mode, "theme_mode"):
        return page_or_theme_mode.theme_mode
    # Assume it's already a ThemeMode
    return page_or_theme_mode


def create_danger_button(text: str, on_click=None, page_or_theme_mode=None):
    """Crea un `ft.ElevatedButton` para acciones peligrosas y lo hace theme-aware.

    Args:
        text: Texto a mostrar
        on_click: callback
        page_or_theme_mode: opcional `ft.Page` o `ft.ThemeMode` para calcular estilo inicial

    Returns:
        `ft.ElevatedButton` con método `update_theme(page_or_theme_mode)`.
    """
    theme_mode = _resolve_theme_mode(page_or_theme_mode)
    style = get_danger_button_style(theme_mode)

    btn = ft.Button(
        content=ft.Row([ft.Icon(ft.Icons.DELETE_SWEEP), ft.Text(text)], spacing=8),
        on_click=on_click,
        style=style,
    )

    def update_theme(new_page_or_theme_mode):
        try:
            tm = _resolve_theme_mode(new_page_or_theme_mode)
            btn.style = get_danger_button_style(tm)
        except Exception:
            pass

    # Exponer helper para que el caller pueda mutar el estilo cuando cambie el theme
    btn.update_theme = update_theme

    return btn
