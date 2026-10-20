"""
Componente: Gráfico de barras — distribución de leads por fuente de origen.

Exporta:
  build_source_chart(sources_data, theme_mode) → BarChart | ft.Text

No realiza queries. Recibe sources_data calculado por analysis.leads_analysis.group_leads_by_source().
"""
import flet as ft
from flet_charts import (
    BarChart,
    BarChartGroup,
    BarChartRod,
    BarChartRodTooltip,
    BarChartTooltip,
    ChartAxis,
    ChartAxisLabel,
    ChartGridLines,
)


def build_source_chart(sources_data: dict, theme_mode=None) -> ft.Control:
    """
    Construye un BarChart con la distribución de leads por fuente.

    Args:
        sources_data: dict[source] = {"total", "meetings", "clients"}
                      — resultado de group_leads_by_source().
        theme_mode: ft.ThemeMode — para colores adaptativos de tooltip.

    Returns:
        BarChart con etiquetas de porcentaje, o ft.Text si no hay datos.
    """
    _is_dark = theme_mode == ft.ThemeMode.DARK
    _tooltip_text = ft.Colors.WHITE if _is_dark else ft.Colors.BLACK
    _tooltip_bg   = ft.Colors.BLACK if _is_dark else ft.Colors.WHITE
    labeled = sorted(
        [(src, d["total"]) for src, d in sources_data.items()],
        key=lambda x: x[1],
        reverse=True,
    )
    if not labeled:
        return ft.Text("No source data", color=ft.Colors.ON_SURFACE_VARIANT)

    labels = [s for s, _ in labeled]
    values = [v for _, v in labeled]
    total = sum(values)
    labels_with_pct = [
        f"{lbl} ({v / total * 100:.0f}%)" if total > 0 else lbl
        for lbl, v in zip(labels, values)
    ]

    chart_groups = []
    x_labels = []
    for idx, val in enumerate(values):
        rod = BarChartRod(
            to_y=float(val), width=24, color=ft.Colors.PRIMARY, border_radius=4,
            tooltip=BarChartRodTooltip(
                text_style=ft.TextStyle(
                    color=_tooltip_text,
                    weight=ft.FontWeight.BOLD,
                    size=12,
                )
            ),
        )
        chart_groups.append(BarChartGroup(x=idx, rods=[rod]))
        x_labels.append(
            ChartAxisLabel(value=idx, label=ft.Text(labels_with_pct[idx], size=11))
        )

    max_val = max(values) if values else 1
    return BarChart(
        groups=chart_groups,
        bottom_axis=ChartAxis(labels=x_labels, show_labels=True),
        left_axis=ChartAxis(label_size=32),
        horizontal_grid_lines=ChartGridLines(
            color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)
        ),
        tooltip=BarChartTooltip(bgcolor=_tooltip_bg, border_radius=8, padding=8),
        max_y=max_val * 1.15,
        interactive=True,
        height=220,
        expand=False,
    )
