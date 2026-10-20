# theme/chart_helpers.py
"""
Helpers de theme/styling para gráficos y componentes relacionados.

Responsabilidades:
- Generar paletas de colores según tema
- Estilos para botones de grouped by (Día, Semana, Mes, etc.)
- Configuraciones visuales reutilizables
"""

import flet as ft
from theme import is_dark_mode


def get_chart_palette(theme_mode: ft.ThemeMode | str, count: int) -> list[str]:
    """
    Genera paleta de colores para gráficos según tema.
    
    Args:
        theme_mode: ft.ThemeMode.LIGHT / DARK o "light"/"dark"
        count: Número de barras a colorear (para ciclar si es necesario)
    
    Returns:
        Lista de colores Flet (se ciclará si count > len(palette))
    
    Nota:
        - Dark mode: Colores claros (BLUE_100 - BLUE_800)
        - Light mode: Colores oscuros (BLUE_800 - BLUE_100) invertidos
    """
    if is_dark_mode(theme_mode):
        # Dark mode: Colores claros para mejor contraste sobre fondo oscuro
        palette = [
            ft.Colors.BLUE_100,
            ft.Colors.BLUE_200,
            ft.Colors.BLUE_300,
            ft.Colors.BLUE_400,
            ft.Colors.BLUE_500,
            ft.Colors.BLUE_600,
            ft.Colors.BLUE_700,
            ft.Colors.BLUE_800,
        ]
    else:
        # Light mode: Colores oscuros para mejor contraste sobre fondo claro
        palette = [
            ft.Colors.BLUE_800,
            ft.Colors.BLUE_700,
            ft.Colors.BLUE_600,
            ft.Colors.BLUE_500,
            ft.Colors.BLUE_400,
            ft.Colors.BLUE_300,
            ft.Colors.BLUE_200,
            ft.Colors.BLUE_100,
        ]
    return palette


def get_grouping_button_style(is_active: bool, theme_mode: ft.ThemeMode | str) -> ft.ButtonStyle:
    """
    Retorna estilo para botones de agrupación (Día, Semana, Mes, Trimestre, Año).
    
    Args:
        is_active: True si botón está seleccionado, False si inactivo
        theme_mode: ft.ThemeMode.LIGHT / DARK
    
    Returns:
        ft.ButtonStyle configurado
    
    Nota:
        - Activo: Usa color primario (tema-dependiente)
        - Inactivo Dark: WHITE_24 + WHITE (traslúcido + texto blanco)
        - Inactivo Light: BLUE_GREY_100 + BLACK (muy claro + texto negro)
    """
    from theme import get_tops_chart_color
    
    if is_active:
        # ✅ Botón activo: Color primario con texto blanco
        return ft.ButtonStyle(
            bgcolor=get_tops_chart_color(theme_mode),
            color=ft.Colors.WHITE,  # Blanco puro para máximo contraste
            padding=10,
        )
    else:
        # ✅ Botón inactivo: Basado en ejemplos oficiales de Flet
        is_dark = is_dark_mode(theme_mode)
        
        if is_dark:
            # Dark mode: WHITE_24 (traslúcido) + WHITE (texto) - patrón oficial
            return ft.ButtonStyle(
                bgcolor=ft.Colors.WHITE_24,  # Muy traslúcido, legible
                color=ft.Colors.WHITE,       # Blanco puro
                padding=10,
            )
        else:
            # Light mode: BLUE_GREY_100 (muy claro) + BLACK (texto) - patrón oficial
            return ft.ButtonStyle(
                bgcolor=ft.Colors.BLUE_GREY_100,  # Muy claro
                color=ft.Colors.BLACK,            # Negro puro
                padding=10,
            )
