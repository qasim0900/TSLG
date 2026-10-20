"""Gráficos de barras para modo comparación A vs B."""
import flet as ft
from utils.formatting import format_eur
import flet_charts as ftc
from theme import get_text_color, get_compare_bar_colors
from utils.ui_dispatch import mounted_page


class CompareBarChart(ft.Container):
    """
    Gráfico de barras comparativo A vs B.
    Renderiza resultados ya calculados.
    """

    def __init__(self, results: dict | None = None):
        # Chart base (vacío)
        self.chart = ftc.BarChart(
            left_axis=ftc.ChartAxis(
                label_size=40,
                label_spacing=25,
                title=ft.Text("% of the higher period"),
            ),
            bottom_axis=ftc.ChartAxis(labels=[]),
            min_y=0,
            max_y=100,
            expand=True,
        )

        super().__init__(
            content=self.chart,
            padding=10,
            visible=False,  # 🔑 apagado por defecto
        )

        # Datos actuales (para reaplicar tema)
        self._current_results: dict | None = None

        if results:
            self.update_data(results)

    # ======================================================
    #   CICLO DE VIDA
    # ======================================================

    def did_mount(self):
        # Aplicar tema inicial cuando page ya existe
        self.update_theme()

    # ======================================================
    #   API PÚBLICA
    # ======================================================

    def update_data(self, results: dict):
        """Actualiza el gráfico con nuevos resultados."""
        self._current_results = results
        theme_mode = getattr(mounted_page(self), "theme_mode", None) or ft.ThemeMode.LIGHT

        labels = ["Total sales", "Transactions", "Average sale"]

        a_values = [
            results["total_sales"]["A"],
            results["transactions"]["A"],
            results["avg_ticket"]["A"],
        ]
        b_values = [
            results["total_sales"]["B"],
            results["transactions"]["B"],
            results["avg_ticket"]["B"],
        ]
        if self.content is None:
            self.content = self.chart
            
        colors = get_compare_bar_colors(theme_mode)
        color_a = colors["color_a"]
        color_b = colors["color_b"]
        text_color = get_text_color(theme_mode)


        def format_tooltip(label, value):
            if label == "Transactions":
                return f"{int(value):,}"
            return format_eur(value)

        def share_of_top(value, other):
            top = max(abs(value), abs(other))
            return max(value, 0) / top * 100 if top else 0.0

        self.chart.groups = [
            ftc.BarChartGroup(
                x=i,
                rods=[
                    ftc.BarChartRod(
                        to_y=share_of_top(a_values[i], b_values[i]),
                        width=18,
                        color=color_a,
                        tooltip=format_tooltip(labels[i], a_values[i]),
                    ),
                    ftc.BarChartRod(
                        to_y=share_of_top(b_values[i], a_values[i]),
                        width=18,
                        color=color_b,
                        tooltip=format_tooltip(labels[i], b_values[i]),
                    ),
                ],
            )
            for i in range(len(labels))
        ]

        self.chart.bottom_axis.labels = [
            ftc.ChartAxisLabel(
                value=i,
                label=ft.Text(
                    labels[i],
                    size=11,
                    color=text_color,
                ),
            )
            for i in range(len(labels))
        ]

        self.chart.left_axis.title.color = text_color

        self.visible = True
        # NO llamar self.update() aquí: la vista/página orquesta el render.

    def clear(self):
        """Limpia el gráfico visualmente."""
        self.chart.groups = []
        self.chart.bottom_axis.labels = []
        self.content = None
        self.visible = True    
        # NO llamar self.update() aquí: la vista/página orquesta el render.

    def update_theme(self):
        """
        Actualiza colores cuando cambia el tema.

        CONTRATO:
        - NO recibe parámetros
        - SOLO usa self.page.theme_mode
        """
        if not mounted_page(self) or not self.chart.groups:
            return

        theme_mode = self.page.theme_mode

        colors = get_compare_bar_colors(theme_mode)
        color_a = colors["color_a"]
        color_b = colors["color_b"]
        text_color = get_text_color(theme_mode)

        for group in self.chart.groups:
            if len(group.rods) >= 2:
                group.rods[0].color = color_a
                group.rods[1].color = color_b

        for label in self.chart.bottom_axis.labels:
            if isinstance(label.label, ft.Text):
                label.label.color = text_color

        self.chart.left_axis.title.color = text_color
        # NO llamar self.update() aquí: la vista/página orquesta el render.
