"""
Componente: Sección Marketing Performance para LeadsView.

Exporta:
  build_marketing_kpi_row(summary)                         → ft.Row
  build_revenue_vs_spend_chart(marketing_metrics, theme)   → ft.Control
  build_marketing_source_table(marketing_metrics)          → ft.Control

No realiza queries. Recibe datos de analysis.marketing_analysis.
Visual coherente con leads_kpi_card.py (hover, colores, tipografía).

Patrones Flet 0.82.2:
  - on_hover usa e.data directo como bool
  - expand=True y scale en containers separados (inner/outer)
  - No llama page.update() — responabilidad del caller
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

from utils.formatting import format_eur

_SOURCE_LABELS: dict[str, str] = {
    "meta_ads":      "Meta",
    "google_ads":    "Google",
    "linkedin_ads":  "LinkedIn",
    "tiktok_ads":    "TikTok",
    "referral":      "Referral",
    "organic":       "Organic",
    "manual_import": "Manual",
}


# ---------------------------------------------------------------------------
# KPI cards globales
# ---------------------------------------------------------------------------

def build_marketing_kpi_row(summary: dict) -> ft.Control:
    """
    Fila inline de 5 métricas: Inversión, Revenue, CPL, CAC, ROI.
    Patrón "inline" — label pequeño arriba, valor grande abajo, sin card container.

    Args:
        summary: dict de get_marketing_efficiency_summary().
            Claves: total_spend, total_revenue, avg_cpl, avg_cac, overall_roi.

    Returns:
        ft.Container con ft.Row de columnas label+valor separadas por divisores.
    """
    overall_roi = summary.get("overall_roi", 0.0)
    roi_color = ft.Colors.GREEN_500 if overall_roi >= 0 else ft.Colors.RED_400
    roi_str = f"{overall_roi * 100:.1f}%"

    metrics = [
        ("TOTAL SPEND", format_eur(summary.get("total_spend", 0)),   ft.Colors.ORANGE_400),
        ("REVENUE",         format_eur(summary.get("total_revenue", 0)), ft.Colors.GREEN_500),
        ("CPL",             format_eur(summary.get("avg_cpl", 0)),       ft.Colors.BLUE_400),
        ("CAC",             format_eur(summary.get("avg_cac", 0)),       ft.Colors.INDIGO_400),
        ("OVERALL ROI",      roi_str,                                     roi_color),
    ]

    items = []
    for i, (label, value, color) in enumerate(metrics):
        if i > 0:
            items.append(
                ft.Container(
                    width=1,
                    height=36,
                    bgcolor=ft.Colors.OUTLINE_VARIANT,
                    margin=ft.Margin.symmetric(horizontal=4),
                )
            )
        items.append(
            ft.Column(
                [
                    ft.Text(label, size=9, weight=ft.FontWeight.W_700, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(value, size=18, weight=ft.FontWeight.BOLD, color=color),
                ],
                spacing=2,
                horizontal_alignment=ft.CrossAxisAlignment.START,
            )
        )

    return ft.Container(
        content=ft.Row(items, spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding.symmetric(horizontal=4, vertical=8),
    )


# ---------------------------------------------------------------------------
# Gráfico Revenue vs Spend
# ---------------------------------------------------------------------------

def build_revenue_vs_spend_chart(marketing_metrics: list, theme_mode=None) -> ft.Control:
    """
    BarChart agrupado: Revenue (verde) vs Spend (naranja) por fuente.

    Args:
        marketing_metrics: lista de get_marketing_metrics().
            Cada elemento: {"source", "leads", "customers", "revenue", "spend", ...}
        theme_mode: ft.ThemeMode para colores adaptativos de tooltip.

    Returns:
        BarChart o ft.Text placeholder si no hay datos.
    """
    metrics = [m for m in marketing_metrics if m.get("revenue", 0) > 0 or m.get("spend", 0) > 0]
    if not metrics:
        return ft.Text(
            "No spend or revenue data by source",
            color=ft.Colors.ON_SURFACE_VARIANT,
            size=13,
        )

    _is_dark = theme_mode == ft.ThemeMode.DARK
    _tooltip_text = ft.Colors.WHITE if _is_dark else ft.Colors.BLACK
    _tooltip_bg   = ft.Colors.BLACK if _is_dark else ft.Colors.WHITE

    chart_groups = []
    x_labels = []

    for idx, m in enumerate(metrics):
        label = _SOURCE_LABELS.get(m["source"], m["source"])
        rod_rev = BarChartRod(
            to_y=float(m.get("revenue", 0)),
            width=14,
            color=ft.Colors.GREEN_400,
            border_radius=3,
            tooltip=BarChartRodTooltip(
                text_style=ft.TextStyle(
                    color=_tooltip_text, size=11, weight=ft.FontWeight.BOLD
                )
            ),
        )
        rod_spend = BarChartRod(
            to_y=float(m.get("spend", 0)),
            width=14,
            color=ft.Colors.ORANGE_400,
            border_radius=3,
            tooltip=BarChartRodTooltip(
                text_style=ft.TextStyle(
                    color=_tooltip_text, size=11, weight=ft.FontWeight.BOLD
                )
            ),
        )
        chart_groups.append(BarChartGroup(x=idx, rods=[rod_rev, rod_spend]))
        x_labels.append(
            ChartAxisLabel(value=idx, label=ft.Text(label, size=10))
        )

    max_val = max(
        (max(m.get("revenue", 0), m.get("spend", 0)) for m in metrics), default=1
    )

    legend = ft.Row(
        [
            ft.Row(
                [ft.Container(width=12, height=12, border_radius=2, bgcolor=ft.Colors.GREEN_400),
                 ft.Text("Revenue", size=11, color=ft.Colors.ON_SURFACE_VARIANT)],
                spacing=4,
            ),
            ft.Row(
                [ft.Container(width=12, height=12, border_radius=2, bgcolor=ft.Colors.ORANGE_400),
                 ft.Text("Spend", size=11, color=ft.Colors.ON_SURFACE_VARIANT)],
                spacing=4,
            ),
        ],
        spacing=20,
    )

    chart = BarChart(
        groups=chart_groups,
        bottom_axis=ChartAxis(labels=x_labels, show_labels=True),
        left_axis=ChartAxis(label_size=32),
        horizontal_grid_lines=ChartGridLines(
            color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE)
        ),
        tooltip=BarChartTooltip(bgcolor=_tooltip_bg, border_radius=8, padding=8),
        max_y=max_val * 1.2,
        expand=False,
        height=190,
    )

    return ft.Column(
        [
            ft.Container(content=chart),
            ft.Container(content=legend, padding=ft.Padding.only(left=40, top=4)),
        ],
        spacing=4,
        tight=True,
    )


# ---------------------------------------------------------------------------
# Tabla por fuente con CPL / CAC / ROI
# ---------------------------------------------------------------------------

def build_marketing_source_table(marketing_metrics: list) -> ft.Control:
    """
    DataTable: Fuente | Leads | Clientes | Revenue | Spend | CPL | CAC | ROI

    Args:
        marketing_metrics: lista de get_marketing_metrics().

    Returns:
        ft.DataTable o ft.Text placeholder si no hay datos.
    """
    metrics = [m for m in marketing_metrics if m.get("leads", 0) > 0]
    if not metrics:
        return ft.Text(
            "No marketing data by source",
            color=ft.Colors.ON_SURFACE_VARIANT,
            size=13,
        )

    def _roi_badge(roi: float) -> ft.Container:
        roi_pct = roi * 100
        color = ft.Colors.GREEN_600 if roi >= 0 else ft.Colors.RED_600
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=8, vertical=2),
            border_radius=6,
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            content=ft.Text(
                f"{roi_pct:.1f}%",
                size=11,
                weight=ft.FontWeight.W_500,
                color=color,
            ),
        )

    rows = []
    for idx, m in enumerate(metrics):
        label = _SOURCE_LABELS.get(m["source"], m["source"])
        zebra = ft.Colors.SURFACE_CONTAINER if idx % 2 == 0 else None
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(
                        ft.Container(
                            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                            border_radius=6,
                            bgcolor=ft.Colors.SURFACE_CONTAINER,
                            content=ft.Text(label, size=11),
                        )
                    ),
                    ft.DataCell(ft.Text(str(m.get("leads", 0)), size=11, color=ft.Colors.BLUE_400)),
                    ft.DataCell(ft.Text(str(m.get("customers", 0)), size=11, color=ft.Colors.GREEN_500)),
                    ft.DataCell(ft.Text(
                        format_eur(m.get("revenue", 0)), size=11,
                        color=ft.Colors.ON_SURFACE, weight=ft.FontWeight.W_500,
                    )),
                    ft.DataCell(ft.Text(
                        format_eur(m.get("spend", 0)), size=11, color=ft.Colors.ON_SURFACE,
                    )),
                    ft.DataCell(ft.Text(
                        format_eur(m.get("cpl", 0)), size=11, color=ft.Colors.BLUE_300,
                    )),
                    ft.DataCell(ft.Text(
                        format_eur(m.get("cac", 0)), size=11, color=ft.Colors.INDIGO_400,
                    )),
                    ft.DataCell(_roi_badge(m.get("roi", 0.0))),
                ],
                color=zebra,
            )
        )

    return ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text("Source",    size=12, weight=ft.FontWeight.W_600)),
            ft.DataColumn(ft.Text("Leads",     size=12, weight=ft.FontWeight.W_600), numeric=True),
            ft.DataColumn(ft.Text("Clients",  size=12, weight=ft.FontWeight.W_600), numeric=True),
            ft.DataColumn(ft.Text("Revenue",   size=12, weight=ft.FontWeight.W_600), numeric=True),
            ft.DataColumn(ft.Text("Spend", size=12, weight=ft.FontWeight.W_600), numeric=True),
            ft.DataColumn(ft.Text("CPL",       size=12, weight=ft.FontWeight.W_600), numeric=True),
            ft.DataColumn(ft.Text("CAC",       size=12, weight=ft.FontWeight.W_600), numeric=True),
            ft.DataColumn(ft.Text("ROI",       size=12, weight=ft.FontWeight.W_600)),
        ],
        rows=rows,
        column_spacing=24,
        heading_row_height=38,
        data_row_min_height=38,
    )
