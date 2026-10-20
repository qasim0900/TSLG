"""Paleta de colores principal (marca FDT).

Este archivo contiene:
1. Colores primarios para theme seeds
2. Funciones de colores para botones (jerarquía visual)

NOTA: Para colores de texto, fondos y tarjetas, usar colores semánticos:
- ft.Colors.ON_SURFACE (texto)
- ft.Colors.SURFACE (fondos/tarjetas)
- ft.Colors.PRIMARY (primario)
"""
import flet as ft


# ============================================================
#   COLORES PRIMARIOS (Theme Seeds)
# ============================================================

PRIMARY_COLOR = ft.Colors.BLUE_600
PRIMARY_DARK = ft.Colors.BLUE_300

# ============================================================
#   COLORES DE BOTONES (jerarquía visual)
# ============================================================

def get_apply_filter_colors(is_dark_mode: bool):
    """Colores para botón 'Aplicar filtro' (acción principal)."""
    # Migrado a tokens ft.Colors en Flet 0.80.5
    # '#1E88E5' -> ft.Colors.BLUE_600, '#1976D2' -> ft.Colors.BLUE_700, '#1565C0' -> ft.Colors.BLUE_800
    return {
        'bgcolor': ft.Colors.BLUE_700,
        'hover_bgcolor': ft.Colors.BLUE_800,
        'color': ft.Colors.WHITE,
        'elevation': 5,
        'hover_elevation': 6,
    }


def get_compare_colors(is_dark_mode: bool):
    """Colores para botón 'Comparar' (acción secundaria potente)."""
    # Migrado a tokens ft.Colors en Flet 0.80.5
    # '#388E3C' -> ft.Colors.GREEN_700, '#427C45' -> ft.Colors.GREEN_600, '#1B5E20' -> ft.Colors.GREEN_900
    return {
        'bgcolor': ft.Colors.GREEN_800,
        'hover_bgcolor': ft.Colors.GREEN_900,
        'color': ft.Colors.WHITE,
        'elevation': 4,
        'hover_elevation': 5,
    }


def get_export_colors(is_dark_mode: bool):
    """Colores para botón 'Exportar HTML' (acción final/premium)."""
    # Migrado a tokens ft.Colors en Flet 0.80.5
    # '#673AB7' -> ft.Colors.PURPLE_700, '#5E35B1' -> ft.Colors.PURPLE_600, '#512DA8' -> ft.Colors.PURPLE_800, '#4527A0' -> ft.Colors.PURPLE_900
    return {
        'bgcolor': ft.Colors.PURPLE_700 if is_dark_mode else ft.Colors.PURPLE_600,
        'hover_bgcolor': ft.Colors.PURPLE_800 if is_dark_mode else ft.Colors.PURPLE_900,
        'color': ft.Colors.WHITE,
        'elevation': 4,
        'hover_elevation': 5,
    }


def get_visualization_colors(is_dark_mode: bool):
    """Colores para botones 'Mostrar resumen' y 'Ver gráficos'."""
    # Migrado a tokens ft.Colors en Flet 0.80.5
    # '#607D8B' -> ft.Colors.BLUE_GREY_400, '#546E7A' -> ft.Colors.BLUE_GREY_500, '#455A64' -> ft.Colors.BLUE_GREY_700
    return {
        'bgcolor': ft.Colors.BLUE_GREY_700 if is_dark_mode else ft.Colors.BLUE_GREY_600,
        'hover_bgcolor': ft.Colors.BLUE_GREY_800,
        'color': ft.Colors.WHITE,
        'elevation': 2,
        'hover_elevation': 3,
    }


def get_import_colors(is_dark_mode: bool):
    """Colores para botón 'Importar archivo' (utilitario)."""
    # Migrado a tokens ft.Colors en Flet 0.80.5
    # '#424242' -> ft.Colors.GREY_800, '#E0E0E0' -> ft.Colors.GREY_300, '#535353' -> ft.Colors.GREY_700, '#D5D5D5' -> ft.Colors.GREY_200
    return {
        'bgcolor': ft.Colors.GREY_800 if is_dark_mode else ft.Colors.GREY_300,
        'hover_bgcolor': ft.Colors.GREY_700 if is_dark_mode else ft.Colors.GREY_200,
        'color': ft.Colors.GREY_300 if is_dark_mode else ft.Colors.GREY_800,
        'elevation': 0,
        'hover_elevation': 1,
    }