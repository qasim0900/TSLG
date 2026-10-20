"""Estilos y helpers de tema para tarjetas KPI."""
import flet as ft
from .theme_utils import is_dark_mode


def get_kpi_card_style(theme_mode, accent_color: ft.Colors):
    """
    Estilo para tarjetas KPI con colores semánticos.
    
    MIGRADO: Usa colores semánticos de Material 3 que se adaptan automáticamente.
    Mantiene lógica condicional solo para ajustes visuales específicos (shadow, opacity).
    """
    is_dark = is_dark_mode(theme_mode)

    # Dark mode: elevación sutil
    # Light mode: fondo con sombra
    if is_dark:
        bgcolor = ft.Colors.SURFACE_CONTAINER
        border = ft.Border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.OUTLINE))
        shadow_color = ft.Colors.with_opacity(0.18, ft.Colors.ON_SURFACE)
        blur_radius = 18
    else:
        bgcolor = ft.Colors.SURFACE
        border = ft.Border.all(1, ft.Colors.with_opacity(0.08, ft.Colors.OUTLINE))
        shadow_color = ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE)
        blur_radius = 12

    return {
        "bgcolor": bgcolor,
        "border": border,
        "shadow": ft.BoxShadow(
            spread_radius=1,
            blur_radius=blur_radius,
            offset=ft.Offset(0, 2),
            color=shadow_color,
        ),
        "icon_bg": ft.Colors.with_opacity(0.15 if is_dark else 0.1, accent_color),
        "icon_color": accent_color,
        "value_color": ft.Colors.ON_SURFACE,  # Color semántico
        "title_color": ft.Colors.ON_SURFACE_VARIANT,  # Color semántico
        "subtitle_color": ft.Colors.ON_SURFACE_VARIANT,  # Color semántico
    }
