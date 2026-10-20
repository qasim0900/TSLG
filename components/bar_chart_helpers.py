"""Helpers para construir gráficos de barras horizontales con ranking."""
import flet as ft


def build_ranked_bar(
    *,
    name: str,
    value: str,
    pct: float,
    idx: int,
    palette: list,
    unit_label: str,
    tooltip: str,
    min_height: int = 30,
    max_height: int = 360,
):
    """
    Construye una barra con jerarquía visual consistente:
    - Barra
    - Valor destacado
    - Unidad semántica
    - Nombre

    Usa colores semánticos (THEME_AGENTS.md §2.1) que se actualizan automáticamente.

    Devuelve:
        column, bar_container, value_text, unit_text, name_text
    """
    BAR_WIDTH = 72
    COLUMN_WIDTH = 82
    is_top_1 = idx == 0
    is_top_3 = idx < 3

    bar_height = max(min_height, int(max_height * pct / 100))
    bar_opacity = 1.0 if is_top_3 else 0.75

    def _on_hover(e):
      if e.data:
          bar_container.scale = 1.06
          bar_container.opacity = 1.0
      else:
          bar_container.scale = 1.0
          bar_container.opacity = bar_opacity
      bar_container.update()

    bar_container = ft.Container(
        height=bar_height,
        width=BAR_WIDTH,
        bgcolor=palette[idx % len(palette)],
        opacity=bar_opacity,
        scale=1.0,
        animate_scale=ft.Animation(140, ft.AnimationCurve.EASE_OUT),
        animate_opacity=ft.Animation(120, ft.AnimationCurve.EASE_OUT),
        border_radius=8,
        tooltip=tooltip,
        alignment=ft.alignment.Alignment(0,1),
    )
    bar_container.on_hover = _on_hover

    value_text = ft.Text(
        value,
        size=15 if is_top_1 else 12,
        weight=ft.FontWeight.BOLD,
        color=ft.Colors.ON_SURFACE,  # Color semántico (THEME_AGENTS.md §2.1)
        text_align=ft.TextAlign.CENTER,
    )

    value_container = ft.Container(
      content=value_text,
      margin=ft.Margin.only(bottom=2),
  )
    unit_text = ft.Text(
        unit_label,
        size=9,
        color=ft.Colors.ON_SURFACE_VARIANT,  # Color semántico (THEME_AGENTS.md §2.1)
        text_align=ft.TextAlign.CENTER,
    )

    name_text = ft.Text(
        name[:16],
        size=12,
        weight=ft.FontWeight.W_600,
        color=ft.Colors.ON_SURFACE,  # Color semántico (THEME_AGENTS.md §2.1)
        max_lines=2,
        overflow=ft.TextOverflow.ELLIPSIS,
        text_align=ft.TextAlign.CENTER,
    )

    column = ft.Column(
        [ 
            value_container,
            unit_text,
            bar_container,
            name_text,
        ],
        width=COLUMN_WIDTH,
        spacing=4,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.END,
    )
    return column, bar_container, value_text, unit_text, name_text
