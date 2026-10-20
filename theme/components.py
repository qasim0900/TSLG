"""
Componentes UI reutilizables con estilos consistentes.
"""
import flet as ft
from .theme_utils import is_dark_mode, get_text_color, get_card_color
from domain.filter_options import ALL_FILTER_KEY


def date_filter_chip(text: str, page_or_theme_mode):
    """
    Crea un chip informativo para mostrar fechas seleccionadas.
    Adapta colores según el modo claro/oscuro.
    
    NOTA: Mantiene lógica condicional porque usa BLUE para diferenciación semántica
    (indicar que es un filtro activo), no solo por el theme.
    """
    is_dark = is_dark_mode(page_or_theme_mode)
    
    if is_dark:
        bg_color = ft.Colors.with_opacity(0.2, ft.Colors.BLUE_200)
        text_color = ft.Colors.BLUE_100
        icon_color = ft.Colors.BLUE_300
    else:
        bg_color = ft.Colors.with_opacity(0.15, ft.Colors.BLUE_600)
        text_color = ft.Colors.BLUE_900
        icon_color = ft.Colors.BLUE_700

    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.CALENDAR_TODAY, size=16, color=icon_color),
                ft.Text(text, size=13, color=text_color, weight=ft.FontWeight.W_500),
            ],
            spacing=5,
        ),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border_radius=20,
        bgcolor=bg_color,
        border=ft.Border.all(1, icon_color),
    )

def date_picker_chip(
    label: str,
    value: str | None,
    is_start: bool,
    page: ft.Page | None,
    on_click,
):
    """
    Chip interactivo para selección de fechas.
    - Muestra la fecha seleccionada
    - Abre DatePicker al hacer click
    - Respeta theme mode
    
    NOTA: Mantiene GREEN/RED porque es semántica funcional (inicio/fin),
    no solo visual del theme.
    Usa WHITE/BLACK para máximo contraste (coherente con FilterPanel).
    """
    # Manejar page=None durante construcción (se actualizará en did_mount)
    is_dark = is_dark_mode(page) if page else False
    
    # Colores EXACTAMENTE iguales a FilterPanel._build_date_chip()
    if is_dark:
        bg_color = ft.Colors.GREEN_700 if is_start else ft.Colors.RED_700
        text_color = ft.Colors.WHITE
        icon_color = ft.Colors.WHITE
    else:
        bg_color = ft.Colors.GREEN_200 if is_start else ft.Colors.RED_200
        text_color = ft.Colors.BLACK
        icon_color = ft.Colors.BLACK

    text_value = value if value else "–"

    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.CALENDAR_MONTH, color=icon_color),
                ft.Text(
                    f"{label}: {text_value}",
                    size=12,
                    color=text_color,
                    weight=ft.FontWeight.W_500,
                ),
            ],
            spacing=5,
        ),
        bgcolor=bg_color,
        border_radius=20,
        padding=ft.Padding.symmetric(horizontal=12, vertical=6),
        on_click=on_click,
    )

def styled_button(text: str, icon=None, on_click=None):
    """
    Un botón bonito, moderno y consistente con el diseño.
    """
    return ft.Button(
        text,
        icon=icon,
        on_click=on_click,
        style=ft.ButtonStyle(
            padding=20,
            shape=ft.RoundedRectangleBorder(radius=12),
            elevation={"hovered": 8, "default": 3},
        ),
    )


def clear_filter_button_style():
    """Estilo para el botón de limpiar filtros."""
    return ft.ButtonStyle(
        bgcolor={
            "default": ft.Colors.TRANSPARENT,
            "hovered": ft.Colors.with_opacity(0.12, ft.Colors.ERROR)
        },
        color={
            "default": ft.Colors.ERROR,
            "hovered": ft.Colors.ERROR,
        }
    )


def delete_button_style():
    """Estilo para botones de eliminar (similar a limpiar filtros)."""
    return ft.ButtonStyle(
        bgcolor={
            "default": ft.Colors.TRANSPARENT,
            "hovered": ft.Colors.with_opacity(0.12, ft.Colors.ERROR)
        },
        color={
            "default": ft.Colors.ERROR,
            "hovered": ft.Colors.ERROR,
        }
    )


def card_container(content, page_or_theme_mode):
    """
    Contenedor tipo "tarjeta" elegante, con sombras y bordes redondos.
    Adaptado al tema actual.
    
    MIGRADO: Usa colores semánticos.
    """
    is_dark = is_dark_mode(page_or_theme_mode)
    
    return ft.Container(
        content=content,
        padding=20,
        border_radius=16,
        bgcolor=ft.Colors.SURFACE,  # Color semántico
        shadow=ft.BoxShadow(
            blur_radius=10,
            spread_radius=1,
            color=ft.Colors.with_opacity(0.08 if not is_dark else 0.3, ft.Colors.ON_SURFACE),
        ),
    )


def styled_dropdown(label: str, options: list, on_change=None, page_or_theme_mode=ft.ThemeMode.LIGHT):
    """
    Crea un dropdown con estilo consistente de la app.
    Compatible con Flet 0.80.5
    
    NOTA: Mantiene colores BLUE condicionales porque es parte del estilo
    de marca (no solo theme), pero usa helpers para texto.
    """
    is_dark = is_dark_mode(page_or_theme_mode)
    text_color = get_text_color(page_or_theme_mode)  # Ya devuelve semántico

    if is_dark:
        bgcolor = ft.Colors.BLUE_300
        border_color = ft.Colors.BLUE_300
        focused_border_color = ft.Colors.BLUE_100
    else:
        bgcolor = ft.Colors.BLUE_600
        border_color = ft.Colors.BLUE_600
        focused_border_color = ft.Colors.BLUE_800

    dropdown = ft.Dropdown(
        expand=True,
        label=label,
        label_style=ft.TextStyle(
            size=13,
            weight=ft.FontWeight.BOLD,
            color=text_color,
        ),
        options=options,
        value=ALL_FILTER_KEY,
        border_radius=10,
        border="outline",
        border_width=2.5,
        border_color=border_color,
        focused_border_color=focused_border_color,
        filled=True,
        bgcolor=bgcolor,
        text_style=ft.TextStyle(
            size=12,
            color=text_color,
        ),
        content_padding=ft.Padding.symmetric(horizontal=14, vertical=10),
    )

    # Asignar el handler después de construir el dropdown para compatibilidad
    # con diferentes versiones de Flet (Constructor no acepta on_change en algunas versiones).
    if on_change:
        dropdown.on_select = on_change


    return dropdown


def update_styled_dropdown(dropdown: ft.Dropdown, page_or_theme_mode):
    """
    Actualiza un dropdown ya creado con styled_dropdown
    para adaptarlo al theme actual.
    
    MIGRADO: Usa helpers que devuelven colores semánticos.
    """
    is_dark = is_dark_mode(page_or_theme_mode)
    text_color = get_text_color(page_or_theme_mode)  # Ya devuelve semántico

    if is_dark:
        bgcolor = ft.Colors.BLUE_300
        border_color = ft.Colors.BLUE_300
        focused_border_color = ft.Colors.BLUE_100
    else:
        bgcolor = ft.Colors.BLUE_600
        border_color = ft.Colors.BLUE_600
        focused_border_color = ft.Colors.BLUE_800

    dropdown.label_style = ft.TextStyle(
        size=13,
        weight=ft.FontWeight.BOLD,
        color=text_color,
    )
    dropdown.text_style = ft.TextStyle(
        size=12,
        color=text_color,
    )
    dropdown.bgcolor = bgcolor
    dropdown.border_color = border_color
    dropdown.focused_border_color = focused_border_color
