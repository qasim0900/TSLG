"""Gráfico de barras de evolución temporal de ventas."""
import flet as ft
from flet_charts import BarChart, BarChartGroup, BarChartRod, ChartAxis, ChartAxisLabel, ChartGridLines, BarChartTooltip, BarChartRodTooltip
from theme import get_text_color, get_tops_chart_color, is_dark_mode
from theme.chart_helpers import get_chart_palette, get_grouping_button_style
from analysis.time_grouping import group_time_series
from analysis.chart_dimensions import get_rod_width, get_label_interval, round_to_nice_number
from components.chart_builder_helpers import build_rod_list, build_x_labels, build_base_chart_config
from utils.ui_dispatch import mounted_page
import logging

logger = logging.getLogger(__name__)



class GraficoEvolucion(ft.Container):
    """
    Gráfico de barras (BarChart) que muestra la evolución de ventas por fecha.
    
    Implementación con Flet 0.80.5 — BarChart API real (legacy).
    
    Patrón C (Mutación sin reconstrucción):
    - NO recalcula datos en update_theme()
    - Mantiene _rows y _grouped_data siempre
    - update_theme() SOLO muta rod.color en los grupos
    - Reconstrucción del chart SOLO al cambiar grouping
    
    Ciclo de vida:
    1. __init__: Guarda datos crudos, calcula agrupación inicial
    2. _set_grouping(): Recalcula agrupación, reconstruye gráfico
    3. update_theme(): SOLO muta rod.color (sin reconstruir)
    
    APIs utilizadas (Flet 0.80.5):
    - BarChart(groups=[...])
    - BarChartGroup(x=..., rods=[...])
    - BarChartRod(to_y=..., color=...)
    """

    def __init__(self, rows, on_grouping_change=None, theme_mode: ft.ThemeMode | str = ft.ThemeMode.LIGHT):
        """
        Args:
            rows: lista de tuplas (date, total_vendido)
            on_grouping_change: callback cuando cambia la agrupación
            theme_mode: ft.ThemeMode.LIGHT / DARK o "light"/"dark"
        """
        self._rows = rows if rows else []
        self._grouping = "day"  # day | week | month | quarter | year
        self._on_grouping_change = on_grouping_change
        self._theme_mode = theme_mode
        
        # 🔐 ESTADO CRÍTICO (Patrón C):
        # Estos datos NO se recalculan en update_theme()
        self._grouped_data = None
        self._chart = None  # Instancia actual de BarChart
        self._rods_by_group = {}  # Mapa de index → [rods] para update_theme()

        # ===============================
        # Botones de agrupación
        # ===============================
        self.btn_day = ft.FilledButton("Day", on_click=lambda _: self._set_grouping("day"))
        self.btn_week = ft.FilledButton("Week", on_click=lambda _: self._set_grouping("week"))
        self.btn_month = ft.FilledButton("Month", on_click=lambda _: self._set_grouping("month"))
        self.btn_quarter = ft.FilledButton("Quarter", on_click=lambda _: self._set_grouping("quarter"))
        self.btn_year = ft.FilledButton("Year", on_click=lambda _: self._set_grouping("year"))

        self._buttons = {
            "day": self.btn_day,
            "week": self.btn_week,
            "month": self.btn_month,
            "quarter": self.btn_quarter,
            "year": self.btn_year,
        }

        # Calcular datos iniciales UNA SOLA VEZ
        self._grouped_data = group_time_series(self._rows, self._grouping)
        self._sync_button_styles()

        # Construir gráfico inicial
        self._chart = self._build_chart()

        # ⚠️ IMPORTANTE: Container con altura fija para que scroll funcione
        # Sin altura fija, el Row con scroll se expande infinitamente
        self._chart_container = ft.Container(
            content=self._chart if self._chart else ft.Text(
                "⚠ No data available.",
                size=14,
                color=get_text_color(self._theme_mode),
            ),
            height=400,  # ← ALTURA FIJA necesaria para scroll (Patrón oficial)
            expand=True,  # Expandir horizontalmente
        )

        # Construir controles: botones + warning (si dataset grande) + chart
        chart_controls = [
            ft.Row(list(self._buttons.values()), spacing=10, wrap=True),
        ]
        
        # ⚠️ WARNING: Dataset masivo (> 100 puntos)
        # Índice donde irá el warning (si aplica)
        self._warning_index = None
        if self._grouped_data and len(self._grouped_data) > 100:
            self._warning_index = len(chart_controls)
            chart_controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.ORANGE_400, size=16),
                        ft.Text(
                            f"⚠️ {len(self._grouped_data)} points. Use a coarser grouping for better readability.",
                            size=12,
                            color=ft.Colors.DEEP_ORANGE_900,
                            italic=True,
                        )
                    ], spacing=8),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    bgcolor=ft.Colors.ORANGE_50,
                    border_radius=4,
                )
            )
        
        # Guardar índice donde estará el chart (CRÍTICO para _set_grouping)
        self._chart_index = len(chart_controls)
        chart_controls.append(self._chart_container)

        # Guardar referencia al Column principal (CRÍTICO para _set_grouping)
        self._main_column = ft.Column(
            chart_controls,
            spacing=15,
            expand=True,
        )

        super().__init__(
            content=self._main_column,
            padding=12,
            bgcolor=ft.Colors.SURFACE,
            border_radius=8,
            expand=True,
        )

    # ======================================================
    # CAMBIO DE DATOS (PERMITIDO: reconstruir)
    # ======================================================

    def _set_grouping(self, grouping: str):
        """
        Cambia el tipo de agrupación.
        
        ✅ PERMITIDO:
        - Recalcular _grouped_data
        - Reconstruir gráfico completo
        - Cambiar botones
        
        ❌ NO TOCAR:
        - Theme (pasar a update_theme())
        """
        self._grouping = grouping
        self._grouped_data = group_time_series(self._rows, self._grouping)
        self._sync_button_styles()
        
        # Reconstruir gráfico completamente
        self._chart = self._build_chart()

        # Mutar .content del container existente (NO reemplazar el nodo montado)
        # Patrón seguro: el nodo _chart_container permanece en el árbol,
        # solo su contenido cambia. Evita referencias huérfanas y renders inconsistentes.
        self._chart_container.content = (
            self._chart if self._chart else ft.Text(
                "⚠ No data available.",
                size=14,
                color=get_text_color(self._theme_mode),
            )
        )

        if self._on_grouping_change:
            self._on_grouping_change(grouping)

        # VentasView orquesta page.update() al final — NO llamar update() parcial aquí

    def _sync_button_styles(self):
        """Sincroniza estilos de botones: activo vs inactivo."""
        for key, btn in self._buttons.items():
            is_active = (key == self._grouping)
            btn.style = get_grouping_button_style(is_active, self._theme_mode)

    # ======================================================
    # CONSTRUCCIÓN DEL GRÁFICO (usa BarChart real)
    # ======================================================

    def _build_chart(self):
        """
        Construye BarChart usando APIs reales de Flet 0.80.5 (legacy).
        
        Almacena referencias a rods en _rods_by_group para update_theme().
        
        [REFACTORIZADO - PHASE 3]
        Usa helpers: chart_builder_helpers.build_rod_list(), build_x_labels(), build_base_chart_config()
        """
        logger.debug("RAW evolution rows: %s", self._rows[:3])


        if not self._grouped_data:
            return None

        theme_mode = self._theme_mode
        
        labels = [r["label"] for r in self._grouped_data]
        values = [float(r["total"]) if r.get("total") is not None else 0.0 for r in self._grouped_data]
        
        # Calcular max_y con mínimo seguro (previene eje Y = 0)
        max_value = max(values) if values else 0.0
        max_y_raw = max(max_value * 1.2, 100.0)  # ✅ Mínimo 100 SIEMPRE
        max_y = round_to_nice_number(max_y_raw)  # ✅ Redondeo inteligente

        # Generar paleta de colores
        palette = get_chart_palette(theme_mode, len(labels))
        
        # Calcular dimensiones adaptativas según densidad
        rod_width = get_rod_width(len(labels))  # ✅ Dinámico
        label_interval = get_label_interval(len(labels))  # ✅ Selectivo

        # ✅ HELPERS (Phase 3 refactoring): Construir rods y labels
        chart_groups, self._rods_by_group = build_rod_list(
            labels, values, palette, rod_width, theme_mode
        )
        x_labels = build_x_labels(labels, label_interval, theme_mode)

        # ✅ SCROLL HORIZONTAL: Solo si hay más de 20 barras
        if len(labels) > 20:
            # Calcular ancho total necesario
            spacing_per_bar = 8
            total_width = (rod_width + spacing_per_bar) * len(labels) + 150
            
            chart_config = build_base_chart_config(
                chart_groups, x_labels, max_y, theme_mode,
                expand=False, width=total_width, height=350
            )
            chart = BarChart(**chart_config)
            
            return ft.Row(
                [chart],
                scroll=ft.ScrollMode.AUTO,
            )
        else:
            chart_config = build_base_chart_config(
                chart_groups, x_labels, max_y, theme_mode,
                expand=True, height=350
            )
            chart = BarChart(**chart_config)
            return chart

    # ======================================================
    # PATRÓN C: ACTUALIZACIÓN DE THEME (SOLO MUTA rod.color)
    # ======================================================

    def update_theme(self, theme_mode: ft.ThemeMode | str = None):
        """
        Actualiza SOLO los colores de las barras al cambiar de tema.
        
        CUMPLE PATRÓN C:
        - NO recalcula datos (_grouped_data permanece)
        - NO reconstruye BarChart
        - SOLO muta rod.color en cada grupo
        
        Args:
            theme_mode: Theme a aplicar. Si es None, lee de self.page.theme_mode
        """
        if theme_mode is None:
            if mounted_page(self) is None:
                return
            theme_mode = self.page.theme_mode
        
        self._theme_mode = theme_mode
        
        # 1️⃣ Mutar contenedor principal
        self.bgcolor = ft.Colors.SURFACE
        
        # 2️⃣ Actualizar colores de botones
        self._sync_button_styles()
        
        # 3️⃣ Mutar SOLO rod.color en los grupos existentes
        if not self._chart:
            import logging
            logging.warning("GraficoEvolucion.update_theme(): No chart instance")
            return
        
        if not self._rods_by_group:
            import logging
            logging.warning(
                f"GraficoEvolucion.update_theme(): Empty _rods_by_group "
                f"(grouped_data len={len(self._grouped_data or [])})"
            )
            return
        
        text_color = get_text_color(theme_mode)
        palette = get_chart_palette(theme_mode, len(self._rods_by_group))

        # Iterar sobre referencias guardadas y mutar color de cada rod
        for idx, rods in self._rods_by_group.items():
            for rod in rods:
                rod.color = palette[idx % len(palette)]
        
        # Actualizar etiquetas del eje X con nuevo color
        if hasattr(self._chart, "bottom_axis") and self._chart.bottom_axis:
            axis = self._chart.bottom_axis
            if hasattr(axis, "labels"):
                for label_obj in (axis.labels or []):
                    if hasattr(label_obj, "label") and isinstance(label_obj.label, ft.Text):
                        label_obj.label.color = text_color
        
        # Actualizar títulos
        if hasattr(self._chart, "left_axis") and self._chart.left_axis:
            axis = self._chart.left_axis
            if hasattr(axis, "title") and isinstance(axis.title, ft.Text):
                axis.title.color = text_color
        
        # ✅ NO llamar self.update() aquí
        # La Vista orquesta un único page.update() después de todas las mutaciones
