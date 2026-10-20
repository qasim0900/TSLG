"""
Funciones helper para adaptación de tema (claro/oscuro).

ARQUITECTURA (Flet 0.80.5+):
- Helpers básicos devuelven colores semánticos directamente
- Helpers especializados mantienen lógica condicional justificada
- Ver /theme/THEME_AGENTS.md para detalles del contrato
"""
import flet as ft


def is_dark_mode(page_or_theme_mode) -> bool:
    """
    Determina si el modo actual es oscuro.
    Acepta ft.Page o ft.ThemeMode directamente.
    """
    if isinstance(page_or_theme_mode, ft.Page):
        theme_mode = page_or_theme_mode.theme_mode
    else:
        theme_mode = page_or_theme_mode
    
    if isinstance(theme_mode, ft.ThemeMode):
        return theme_mode == ft.ThemeMode.DARK
    return str(theme_mode).lower() == "dark"


# ==========================================================
#   HELPERS BÁSICOS (Devuelven colores semánticos)
# ==========================================================

def get_text_color(page_or_theme_mode) -> str:
    """Obtiene el color de texto principal."""
    return ft.Colors.ON_SURFACE


def get_subtitle_color(page_or_theme_mode) -> str:
    """Obtiene el color de texto secundario."""
    return ft.Colors.ON_SURFACE_VARIANT


def get_card_color(page_or_theme_mode) -> str:
    """Obtiene el color de fondo de tarjetas."""
    return ft.Colors.SURFACE


def get_icon_color(page_or_theme_mode) -> str:
    """Obtiene el color de íconos."""
    return ft.Colors.PRIMARY


def get_container_translucent_bgcolor(page_or_theme_mode) -> str:
    """
    Color de fondo translúcido para contenedores.
    Usado en client_profile, client_form, client_empty_state.
    """
    if is_dark_mode(page_or_theme_mode):
        return ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE)
    else:
        return ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY)


# ==========================================================
#   HELPERS DE TEXTSTYLE (Reutilizables para campos)
# ==========================================================

def get_label_text_style(page_or_theme_mode) -> ft.TextStyle:
    """TextStyle para etiquetas de campos (label_style)."""
    return ft.TextStyle(color=get_subtitle_color(page_or_theme_mode))


def get_input_text_style(page_or_theme_mode) -> ft.TextStyle:
    """TextStyle para texto ingresado en campos (text_style)."""
    return ft.TextStyle(color=get_text_color(page_or_theme_mode))


# ==========================================================
#   HELPERS ESPECIALIZADOS (Lógica condicional justificada)
# ==========================================================
# Razones válidas para condicionales:
# - Contraste de gráficos
# - Diferenciación de paneles (BLUE vs AMBER)
# - Semántica funcional (verde/rojo)
# Ver /theme/THEME_AGENTS.md § 2.2 para detalles

def get_chart_palette(page_or_theme_mode) -> list:
    """
    Obtiene la paleta de colores para gráficos según el tema.
    """
    if is_dark_mode(page_or_theme_mode):
        return [
            ft.Colors.CYAN,
            ft.Colors.AMBER,
            ft.Colors.LIME,
            ft.Colors.PINK,
            ft.Colors.ORANGE,
            ft.Colors.INDIGO_200,
            ft.Colors.TEAL,
            ft.Colors.PURPLE_200,
            ft.Colors.GREEN_300,
            ft.Colors.DEEP_ORANGE_300,
        ]
    else:
        return [
            ft.Colors.BLUE_700,
            ft.Colors.RED_700,
            ft.Colors.GREEN_800,
            ft.Colors.PURPLE,
            ft.Colors.DEEP_ORANGE_900,
            ft.Colors.BROWN,
            ft.Colors.TEAL_700,
            ft.Colors.INDIGO_700,
            ft.Colors.PINK_700,
            ft.Colors.LIME_900,
        ]


def get_chart_label_color(page_or_theme_mode) -> str:
    return ft.Colors.BLACK if is_dark_mode(page_or_theme_mode) else ft.Colors.WHITE


def get_tops_chart_color(page_or_theme_mode, shade=None) -> str:
    """
    Obtiene el color para gráficos de 'Tops de Clientes' y 'Evolución de Ventas'.
    
    Este color es configurable en un solo lugar.
    
    Args:
        page_or_theme_mode: page o ThemeMode
        shade: tonalidad opcional (100, 200, 300, 400, 500, 600, 700, 800, 900)
               Si es None, usa el color base
    
    Returns:
        color en formato ft.Colors
    """
    # Color base: BLUE
    base_color = ft.Colors.BLUE
    
    if shade:
        shade_map = {
            100: ft.Colors.BLUE_100,
            200: ft.Colors.BLUE_200,
            300: ft.Colors.BLUE_300,
            400: ft.Colors.BLUE_400,
            500: ft.Colors.BLUE_500,
            600: ft.Colors.BLUE_600,
            700: ft.Colors.BLUE_700,
            800: ft.Colors.BLUE_800,
            900: ft.Colors.BLUE_900,
        }
        return shade_map.get(shade, base_color)
    
    return base_color


def get_tops_chart_palette(page_or_theme_mode, count=5) -> list:
    """
    Obtiene una paleta de tonalidades del color de tops/evolución.
    Útil para gráficos de barras con múltiples categorías.
    
    Args:
        page_or_theme_mode: page o ThemeMode
        count: número de tonalidades diferentes a generar
    
    Returns:
        lista de colores
    """
    
    if is_dark_mode(page_or_theme_mode):
        # En modo oscuro, usar tonalidades más claras
        shades = [ft.Colors.BLUE_200, ft.Colors.BLUE_300, ft.Colors.BLUE_400, 
                  ft.Colors.BLUE_500, ft.Colors.BLUE_600]
    else:
        # En modo claro, usar tonalidades del azul
        shades = [ft.Colors.BLUE_700, ft.Colors.BLUE_600, ft.Colors.BLUE_500,
                  ft.Colors.BLUE_400, ft.Colors.BLUE_300]
    
    return shades[:count]


# ==========================================================
#   PANELES (FilterPanel vs ComparePanel)
# ==========================================================
# Diferenciación visual: BLUE (filter) vs AMBER (compare)

def get_compare_panel_bgcolor(page_or_theme_mode) -> str:
    """
    Color de fondo del panel de comparación.
    Debe diferenciarse visualmente del FilterPanel,
    pero mantener coherencia con el tema.
    """
    if is_dark_mode(page_or_theme_mode):
        return ft.Colors.with_opacity(0.18, ft.Colors.AMBER_300)
    else:
        return ft.Colors.with_opacity(0.12, ft.Colors.AMBER_600)


def get_filter_panel_bgcolor(page_or_theme_mode) -> str:
    """Obtiene el color de fondo del panel de filtros según el tema."""
    if is_dark_mode(page_or_theme_mode):
        return ft.Colors.with_opacity(0.15, ft.Colors.BLUE_300)
    return ft.Colors.with_opacity(0.1, ft.Colors.BLUE_600)


# ==========================================================
#   DASHBOARD
# ==========================================================

def get_dashboard_card_colors(page_or_theme_mode) -> dict:
    """
    Obtiene diccionario completo de colores para las tarjetas del dashboard.

    MIGRADO: Usa colores semánticos que se adaptan automáticamente al theme.
    """
    return {
        "bg_card": ft.Colors.SURFACE_CONTAINER,  # Color semántico
        "icon": ft.Colors.PRIMARY,  # Color semántico
        "text": ft.Colors.ON_SURFACE,  # Color semántico
        "subtitle": ft.Colors.ON_SURFACE_VARIANT,  # Color semántico
    }


def get_action_tile_colors(page_or_theme_mode) -> dict:
    """
    Obtiene colores para los mosaicos de acción premium del Dashboard.

    EXCEPCIÓN JUSTIFICADA (THEME_AGENTS.md § 2.2 — diferenciación visual):
    Fondo azul marino profundo con icono dorado y texto blanco para máximo
    contraste e identidad visual premium. Los valores explícitos son
    intencionales para ambos modos.
    """
    return {
        "bg": ft.Colors.BLUE_900,
        "bg_hover": ft.Colors.BLUE_800,
        "icon": ft.Colors.AMBER_300,
        "text": ft.Colors.WHITE,
        "subtitle": ft.Colors.with_opacity(0.9, ft.Colors.WHITE),
    }


# ==========================================================
#   UTILIDADES RECURSIVAS (Legacy - Mantener por compatibilidad)
# ==========================================================
# NOTA: Con colores semánticos, estas funciones son menos necesarias
# Se mantienen para componentes que aún las usan

def update_container_theme(container: ft.Container, theme_mode: ft.ThemeMode, set_bg: bool = True):
    """Actualiza el tema de un contenedor y su contenido recursivamente."""
    if not container:
        return
    
    # Actualizar bgcolor del contenedor (opcional)
    if set_bg:
        container.bgcolor = get_container_translucent_bgcolor(theme_mode)
    
    # Actualizar contenido recursivamente
    if container.content:
        _update_controls_recursive(container.content, theme_mode)


def _update_controls_recursive(control, theme_mode: ft.ThemeMode):
    """Actualiza colores de controles recursivamente."""
    text_color = get_text_color(theme_mode)
    subtitle_color = get_subtitle_color(theme_mode)
    
    # Actualizar ft.Text
    if isinstance(control, ft.Text):
        # Si es título (bold/grande), usar text_color, sino subtitle
        if control.weight == ft.FontWeight.BOLD or (control.size and control.size >= 16):
            control.color = text_color
        else:
            control.color = subtitle_color
    
    # Actualizar ft.TextField
    elif isinstance(control, ft.TextField):
        control.border_color = subtitle_color
        control.label_style = ft.TextStyle(color=subtitle_color)
        control.text_style = ft.TextStyle(color=text_color)
    
    # Actualizar ft.Divider
    elif isinstance(control, ft.Divider):
        control.color = subtitle_color

    # Actualizar ft.DataTable (column labels + rows)
    elif isinstance(control, ft.DataTable):
        # Si tiene update_theme propio, usarlo en lugar de recursión genérica
        if hasattr(control, 'update_theme'):
            control.update_theme(theme_mode)
            return
        
        # Si no, hacer actualización recursiva manual en subcontroles
        # Column headers
        for col in getattr(control, "columns", []) or []:
            label = getattr(col, "label", None)
            if label is not None:
                _update_controls_recursive(label, theme_mode)

        # Row cells
        for row in getattr(control, "rows", []) or []:
            # DataRow expone 'cells'
            if hasattr(row, "cells"):
                for cell in row.cells:
                    if hasattr(cell, "content") and cell.content:
                        _update_controls_recursive(cell.content, theme_mode)
        
        return
    
    # Actualizar ft.IconButton (excepto los que tienen color específico como DELETE)
    elif isinstance(control, ft.IconButton):
        if control.icon_color != ft.Colors.RED:  # No cambiar botones de eliminar
            control.icon_color = text_color
    
    # Si tiene método update_theme propio, usarlo
    if hasattr(control, 'update_theme') and not isinstance(control, (ft.Text, ft.TextField, ft.Divider, ft.IconButton)):
        control.update_theme(theme_mode)
        return  # Ya actualizado recursivamente por el componente
    
    # Recursión en contenedores
    if hasattr(control, 'controls'):
        for child in control.controls:
            _update_controls_recursive(child, theme_mode)
    
    if hasattr(control, 'content') and control.content:
        _update_controls_recursive(control.content, theme_mode)
    
    # Para ft.Row específicamente (cells en DataRow, etc)
    if hasattr(control, 'cells'):
        for cell in control.cells:
            if hasattr(cell, 'content'):
                _update_controls_recursive(cell.content, theme_mode)


def update_component_theme_recursive(component, theme_mode: ft.ThemeMode):
    """Actualiza el tema de un componente y todos sus sub-componentes."""
    _update_controls_recursive(component, theme_mode)

# ==========================================================
#   COMPARE PANEL – COLORES SEMÁNTICOS
# ==========================================================

def get_compare_value_color(page_or_theme_mode, role: str) -> str:
    """
    Colores para valores A y B en comparación.
    
    role:
        - "A"
        - "B"
    """
    if role == "A":
        return ft.Colors.BLUE_300 if is_dark_mode(page_or_theme_mode) else ft.Colors.BLUE_700
    if role == "B":
        return ft.Colors.ORANGE_300 if is_dark_mode(page_or_theme_mode) else ft.Colors.ORANGE_700
    return get_text_color(page_or_theme_mode)


def get_compare_delta_color(page_or_theme_mode, delta: float) -> str:
    """
    Color del delta (↑ ↓ —) en comparación.
    """
    if delta > 0:
        return ft.Colors.GREEN_300 if is_dark_mode(page_or_theme_mode) else ft.Colors.GREEN_700
    if delta < 0:
        return ft.Colors.RED_300 if is_dark_mode(page_or_theme_mode) else ft.Colors.RED_700
    return ft.Colors.GREY_400 if is_dark_mode(page_or_theme_mode) else ft.Colors.GREY_700


def get_compare_state_color(page_or_theme_mode, state: str) -> str:
    """
    Colores para estados especiales del panel compare.
    
    state:
        - "partial"
        - "new"
        - "inactive"
        - "none"
    """
    if state == "partial":
        return ft.Colors.ORANGE_300 if is_dark_mode(page_or_theme_mode) else ft.Colors.ORANGE_700
    if state == "new":
        return ft.Colors.BLUE_300 if is_dark_mode(page_or_theme_mode) else ft.Colors.BLUE_700
    if state == "inactive":
        return ft.Colors.ORANGE_300 if is_dark_mode(page_or_theme_mode) else ft.Colors.ORANGE_700
    if state == "none":
        return ft.Colors.GREY_400 if is_dark_mode(page_or_theme_mode) else ft.Colors.GREY_600

    return get_subtitle_color(page_or_theme_mode)


def get_compare_bar_colors(page_or_theme_mode) -> dict:
    """
    Paleta de colores para gráfico comparativo CompareBarChart (A vs B).
    
    Retorna dict con claves:
    - "color_a": Color para barras del período A (AZUL)
    - "color_b": Color para barras del período B (NARANJA)
    """
    is_dark = is_dark_mode(page_or_theme_mode)
    return {
        "color_a": ft.Colors.BLUE_400 if is_dark else ft.Colors.BLUE,
        "color_b": ft.Colors.ORANGE_400 if is_dark else ft.Colors.ORANGE,
    }


# ==========================================================
#   KPI COMPARE – ESTILO OFICIAL
# ==========================================================
def get_compare_kpi_card_style(page_or_theme_mode) -> dict:
    """Estilo para tarjetas KPI en panel de comparación."""
    is_dark = is_dark_mode(page_or_theme_mode)

    if is_dark:
        return {
            "bgcolor": ft.Colors.SURFACE_CONTAINER_HIGHEST,  # Color semántico
            "border_color": ft.Colors.with_opacity(0.35, ft.Colors.OUTLINE),
            "radius": 14,
            "padding": 16,
            "shadow": None,  # Sin shadow en dark
            "title_color": ft.Colors.ON_SURFACE,  # Color semántico
            "meta_color": ft.Colors.ON_SURFACE_VARIANT,  # Color semántico
        }

    return {
        "bgcolor": ft.Colors.SURFACE,  # Color semántico
        "border_color": ft.Colors.with_opacity(0.4, ft.Colors.OUTLINE),
        "radius": 14,
        "padding": 16,
        "shadow": ft.BoxShadow(
            blur_radius=12,
            spread_radius=1,
            offset=ft.Offset(0, 4),
            color=ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE),
        ),
        "title_color": ft.Colors.ON_SURFACE_VARIANT,  # Color semántico
        "meta_color": ft.Colors.ON_SURFACE_VARIANT,  # Color semántico
    }

def get_compare_card_bgcolor(page_or_theme_mode):
    """Color de fondo para tarjetas de comparación."""
    # Usar color semántico para superficies
    return ft.Colors.SURFACE

