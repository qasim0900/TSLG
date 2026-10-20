# components/chart_builder_helpers.py
"""
Helpers para construcción de gráficos BarChart (Flet 0.80.5).

Extrae lógica común de _build_chart() en GraficoEvolucion.
Permite reutilización y pruebas independientes.

IMPORTANTE: Este archivo es HELPER SIN ESTADO (funciones puras).
No contiene lógica de negocio ni acceso a BD.
"""

import flet as ft
from flet_charts import (
    BarChart, BarChartGroup, BarChartRod, BarChartRodTooltip,
    BarChartTooltip, ChartAxis, ChartAxisLabel, ChartGridLines
)
from theme import get_text_color


def build_rod_list(labels, values, palette, rod_width, theme_mode):
    """
    Construye la lista de BarChartRod (barras individuales).
    
    Cada rod incluye:
    - Color de la paleta adaptada al theme
    - Tooltip con texto bold y color explícito (máxima legibilidad)
    - Width adaptativo según densidad
    
    Args:
        labels: List[str] — Etiquetas para cada barra
        values: List[float] — Valores numéricos
        palette: List[str] — Paleta de colores (una por barra)
        rod_width: int — Ancho adaptativo en pixels
        theme_mode: ThemeMode — Dark o Light
    
    Returns:
        List[Tuple[BarChartRod, int]] — [(rod, group_idx), ...] para referencia
    """
    rods_by_group = {}
    chart_groups = []
    
    tooltip_text_color = (
        ft.Colors.WHITE if theme_mode == ft.ThemeMode.DARK 
        else ft.Colors.BLACK
    )
    
    for idx, (label, value) in enumerate(zip(labels, values)):
        rod = BarChartRod(
            to_y=float(value) if value else 0.0,
            width=rod_width,
            color=palette[idx % len(palette)],
            border_radius=4,
            tooltip=BarChartRodTooltip(
                text_style=ft.TextStyle(
                    color=tooltip_text_color,
                    weight=ft.FontWeight.BOLD,
                    size=12
                )
            ),
        )
        
        group = BarChartGroup(x=idx, rods=[rod])
        
        chart_groups.append(group)
        rods_by_group[idx] = [rod]  # Referencia para update_theme()
    
    return chart_groups, rods_by_group


def build_x_labels(labels, label_interval, theme_mode):
    """
    Construye etiquetas del eje X con intervalo selectivo.
    
    Previene superposición en datasets densos.
    
    Args:
        labels: List[str] — Etiquetas para cada posición
        label_interval: int — Mostrar cada N labels
        theme_mode: ThemeMode — Para color de texto
    
    Returns:
        List[ChartAxisLabel] — Labels para el eje X
    """
    text_color = get_text_color(theme_mode)
    
    return [
        ChartAxisLabel(
            value=idx,
            label=ft.Text(
                label if idx % label_interval == 0 else "",
                size=11,
                color=text_color
            )
        )
        for idx, label in enumerate(labels)
    ]


def build_base_chart_config(
    chart_groups, x_labels, max_y, theme_mode, expand=False, width=None, height=None
):
    """
    Construye configuración base de BarChart (sin crear la instancia aún).
    
    Usado por both branches (>20 bars y <=20 bars).
    
    Args:
        chart_groups: List[BarChartGroup] — Barras agrupadas
        x_labels: List[ChartAxisLabel] — Etiquetas X
        max_y: float — Valor máximo para eje Y
        theme_mode: ThemeMode — Dark o Light
        expand: bool — Si True, chart ocupa espacio disponible
        width: Optional[int] — Ancho fijo si se especifica
        height: Optional[int] — Alto fijo (default 350)
    
    Returns:
        Dict — Configuración para BarChart(**config)
    """
    text_color = get_text_color(theme_mode)
    tooltip_bgcolor = (
        ft.Colors.BLACK if theme_mode == ft.ThemeMode.DARK 
        else ft.Colors.WHITE
    )
    
    config = {
        "groups": chart_groups,
        "left_axis": ChartAxis(
            label_size=40,
            title=ft.Text("Sales (€)", size=12, color=text_color),
            title_size=40
        ),
        "bottom_axis": ChartAxis(
            labels=x_labels,
            label_size=40,
            show_labels=True
        ),
        "horizontal_grid_lines": ChartGridLines(
            color=ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE),
            width=1,
        ),
        "max_y": max_y,
        "tooltip": BarChartTooltip(
            bgcolor=tooltip_bgcolor,
            border_radius=8,
            padding=8,
        ),
    }
    
    # Dimensiones
    if expand:
        config["expand"] = True
    if width is not None:
        config["width"] = width
    if height is not None:
        config["height"] = height
    else:
        config["height"] = 350  # Default
    
    return config
