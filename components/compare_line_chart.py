"""Gráfico de líneas comparativo para evolución temporal A vs B."""
import flet as ft
import flet_charts as ftc
from theme import get_text_color, get_tops_chart_color, is_dark_mode
from utils.ui_dispatch import mounted_page
from utils.formatting import format_date_range_us, format_eur
from domain.filter_options import ALL_FILTER_LABEL


class CompareLineChart(ft.Container):
    """
    CompareLineChart

    Gráfico de líneas comparativo A vs B con control manual de agrupación temporal.

    Características:
    - Escala Y dinámica con jerarquía visual (máximo / medio / secundarios)
    - Agrupación temporal manual: day / week / month / quarter / year
    - Gridlines adaptativas con baseline semántica
    - Tooltips unificados (A, B, Δ, período)
    - Leyenda externa con metadatos de período
    - Soporte completo light / dark mode

    Arquitectura:
    - NO recalcula datos
    - Renderiza exclusivamente datos ya agregados
    - La View orquesta los page.update()

    ⚠️ Componente sensible:
    No modificar layout ni lógica del eje Y sin validar impacto visual.
    """

    _y_axis_title = "Amount (€)"

    # Layout constants (Flet ChartAxis.label_size/title_size are *reserved pixels*, not font sizes).
    # These values are tuned to prevent axis text clipping across day/week/month/quarter/year.
    _LEFT_AXIS_LABEL_SIZE = 36  # Reducido de 44 para dar más espacio horizontal
    _LEFT_AXIS_TITLE_SIZE = 20   # Reducido de 24 para dar más espacio horizontal
    _BOTTOM_AXIS_LABEL_SIZE = 50

    # Tooltip tuning (UI-only): blanco sobre el bgcolor oscuro fijo (#607D8B) del LineChartTooltip
    # Sigue el estándar AGENTS.md § 4.4: texto WHITE sobre fondo dark
    _TOOLTIP_TEXT_STYLE = ft.TextStyle(size=12, weight=ft.FontWeight.W_500, color=ft.Colors.WHITE)

    def __init__(self, on_grouping_change=None, title="Comparative trend"):
        self._grouping = "day"
        self._on_grouping_change = on_grouping_change
        
        # ⭐ Guardar valores Y para update_theme (reconstrucción de colores)
        self._last_y_values = []
        # ⭐ Guardar labels para reconstrucción del eje X
        self._last_labels = []
        
        # ⭐ Información de períodos (para leyenda mejorada)
        self.period_a_info = {"start": None, "end": None, "client": ALL_FILTER_LABEL, "product": ALL_FILTER_LABEL}
        self.period_b_info = {"start": None, "end": None, "client": ALL_FILTER_LABEL, "product": ALL_FILTER_LABEL}

        # ===============================
        # Título
        # ===============================
        self.title = ft.Text(
            title,
            size=14,
            weight=ft.FontWeight.BOLD,
            color=None,
        )

        # ===============================
        # Botones
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

        # ===============================
        # LineChart
        # ===============================
        self.line_chart = ftc.LineChart(
            data_series=[],
            min_y=0,
            left_axis=ftc.ChartAxis(
                # Reserve enough horizontal space so Y labels (incl. max tick) never get clipped.
                label_size=self._LEFT_AXIS_LABEL_SIZE,
                title=ft.Text(self._y_axis_title, size=12, weight=ft.FontWeight.W_600),
                # Reserve space for the (rotated) Y-axis title.
                title_size=self._LEFT_AXIS_TITLE_SIZE,
            ),
            bottom_axis=ftc.ChartAxis(
                labels=[],
                # Reserve enough vertical space so X labels are fully visible.
                label_size=self._BOTTOM_AXIS_LABEL_SIZE,
                show_labels=True,  # Forzar mostrar labels siempre
            ),
            # Gridlines horizontales: muy sutiles, solo en puntos estratégicos
            horizontal_grid_lines=ftc.ChartGridLines(
                interval=None,  # Se configurará dinámicamente en _build_y_axis
                color=ft.Colors.with_opacity(0.1, ft.Colors.GREY_400),
                width=0.5,
            ),
            # Tooltip con max_width ampliado: el contenido tiene múltiples líneas
            # ("A: €", "B: €", "Δ: €", rango de fecha) que superan el default de 120px
            tooltip=ftc.LineChartTooltip(
                max_width=260,
                fit_inside_horizontally=True,
                fit_inside_vertically=True,
            ),
            expand=True,
        )

        # Construir leyenda (será asignada en el contenedor)
        self.legend = ft.Container()
        
        # ⭐ CONTENEDOR DE LEYENDA (para actualización dinámica en update_theme)
        self.legend_container = ft.Container(
            content=self.legend,
            padding=ft.Padding(0, 8, 0, 4),  # Espacio arriba y abajo
        )

        # ===============================
        # Axis Line del Eje Y (anclaje visual)
        # ===============================
        # Color adaptativo para axis line del eje Y
        self._y_axis_line_color = ft.Colors.GREY_600

        # Store the chart without scroll wrapper (LineChart doesn't play well with Row(scroll) in Flet 0.28.x)
        self._chart_scroll_container = self.line_chart

        super().__init__(
            height=650,  # Altura aumentada para acomodar labels del eje X
            # Padding moderado
            padding=ft.Padding(24, 12, 24, 32),
            border_radius=8,
            bgcolor=ft.Colors.SURFACE,
            # Borde izquierdo sutil = axis line del eje Y
            border=ft.Border.only(left=ft.BorderSide(1.4, self._y_axis_line_color)),
            content=ft.Column(
                [
                    # ============================================================
                    # SECCIÓN 1: METADATOS DEL GRÁFICO
                    # ============================================================
                    self.title,
                    ft.Row(list(self._buttons.values()), spacing=10, wrap=True),
                    
                    # ============================================================
                    # SECCIÓN 2: LEYENDA (fuera del área del gráfico)
                    # ============================================================
                    self.legend_container,
                    
                    # ============================================================
                    # SEPARADOR ESTRUCTURAL: divide metadatos de gráfico
                    # ============================================================
                    ft.Divider(height=2, thickness=1.2),
                    
                    # ============================================================
                    # SECCIÓN 3: GRÁFICO (con scroll horizontal si hay muchos puntos)
                    # ============================================================
                    self._chart_scroll_container,
                ],
                spacing=10,  # Espacio consistente entre secciones
                expand=True,
            ),
        )

    # ======================================================
    # API PÚBLICA
    # ======================================================
    def did_mount(self):
        self._y_axis_line_color = self._get_y_axis_line_color()
        self.border = ft.Border.only(left=ft.BorderSide(1.4, self._y_axis_line_color))
        self.update_theme()

    def _format_value(self, label: str, value: float) -> str:
        """Formatea valor para tooltip, indicando "Sin movimiento" cuando es 0."""
        if value == 0:
            return f"{label}: No activity"
        return f"{label}: {format_eur(value)}"

    def update_data(self, points):
        """
        Actualiza el chart desde EvolutionPointV2 points.
        
        Genera tooltips UNIFICADOS que muestran ambas series (A y B) en orden consistente,
        previniendo reorden cuando uno de los valores es 0.
        
        Args:
            points: List[EvolutionPointV2] - puntos ya validados del snapshot
        """
        
        COLOR_A = ft.Colors.BLUE
        COLOR_B = ft.Colors.ORANGE

        if not points:
            self.line_chart.data_series = []
            return

        # Extraer valores Y de los puntos
        y_values = []
        labels = []
        
        points_a = []
        points_b = []
        
        for idx, point in enumerate(points):
            # Eje X: usar label del punto (ya formateado en el builder)
            labels.append(point.label)
            
            # Eje Y: valores A y B
            y_values.append(point.value_a)
            y_values.append(point.value_b)
            
            # ================================================================
            # TOOLTIP UNIFICADO Y ROBUSTO
            # ================================================================
            # Ambas series comparten el MISMO tooltip para garantizar:
            # 1. Orden consistente: A → B → Δ (sin importar valores)
            # 2. Información completa: ambas líneas visibles
            # 3. Sin duplicación: no se repite metadata
            # 4. Defensivo: show_tooltip=True fuerza consistencia en Flet 0.28+
            
            label_a = self._format_value("A", point.value_a)
            label_b = self._format_value("B", point.value_b)
            
            period_range = format_date_range_us(point.start, point.end)
            partial_flag = "⚠ Incomplete period" if point.is_partial else ""

            # Construir tooltip único con orden garantizado
            tooltip = "\n".join(
                line
                for line in (
                    label_a,
                    label_b,
                    f"Δ: {'+' if point.difference > 0 else ''}{format_eur(point.difference)}",
                    period_range,
                    partial_flag,
                )
                if line
            )

            # Tooltip unificado en AMBAS series.
            # Razón: si la serie A tiene valor ~0 queda oculta visualmente y el usuario
            # no puede hacer hover sobre ella → tooltip invisible. Al poner el mismo
            # contenido en B garantizamos que siempre hay un punto interactivo visible.
            # Flet superpone los dos tooltips en el mismo pixel cuando ambas series
            # están activas, pero el texto es idéntico así que no hay información duplicada.
            _tooltip_obj = ftc.LineChartDataPointTooltip(
                text=tooltip,
                text_style=self._TOOLTIP_TEXT_STYLE,
            )
            point_a = ftc.LineChartDataPoint(
                idx,
                point.value_a,
                tooltip=_tooltip_obj,
                show_tooltip=True,
            )
            
            point_b = ftc.LineChartDataPoint(
                idx,
                point.value_b,
                tooltip=_tooltip_obj,
                show_tooltip=True,
            )

            points_a.append(point_a)
            points_b.append(point_b)
        
        # Guardar valores Y para update_theme
        self._last_y_values = y_values
        # Guardar labels para reconstrucción del eje X
        self._last_labels = labels
        
        self._build_y_axis(y_values)
        
        # Series con jerarquía visual
        # Serie A (Azul): Principal
        # Serie B (Naranja): Secundaria
        self.line_chart.data_series = [
            ftc.LineChartData(points_a, color=COLOR_A, stroke_width=3.5, curved=True),
            ftc.LineChartData(points_b, color=COLOR_B, stroke_width=2.5, curved=True),
        ]

        # Construir eje X inicial
        self._rebuild_bottom_axis()
        # El contenedor orquestador hace page.update() después

    def update_from_evolution_points(self, points):
        """
        Actualiza el chart directamente desde EvolutionComparisonV2.points.
        
        Args:
            points: List[EvolutionPointV2]
        """
        self.update_data(points)
    
    def set_period_info(self, period: str, start: str = None, end: str = None, client: str = None, product: str = None):
        """
        Actualiza la información del período A o B para mostrar en la leyenda.
        
        Args:
            period: "a" o "b"
            start: Fecha inicio (formato YYYY-MM-DD o similar)
            end: Fecha fin (formato YYYY-MM-DD o similar)
            client: Nombre del cliente (None o vacío → "TODOS")
            product: Tipo de producto (None o vacío → "TODOS")
        """
        info = {
            "start": start,
            "end": end,
            "client": client or ALL_FILTER_LABEL,
            "product": product or ALL_FILTER_LABEL,
        }
        
        if period.lower() == "a":
            self.period_a_info = info
        elif period.lower() == "b":
            self.period_b_info = info
        
        # Reconstruir leyenda con nueva información
        self._rebuild_legend()

    def update_theme(self):
        """
        Actualiza TODOS los elementos visuales al cambiar el theme (light/dark).
        
        CONTRATO OFFICIAL:
        - NO recibe parámetros
        - SOLO lee self.page.theme_mode
        - NO modifica self.page.theme_mode
        """
        if not mounted_page(self):
            return
        
        # Leer el modo de tema actual (NO escribir)
        theme_mode = self.page.theme_mode
        
        # 1️⃣ Actualizar título
        self.title.color = get_text_color(theme_mode)
        
        # 2️⃣ Actualizar estados visuales de botones
        self._update_button_states()
        
        # 3️⃣ LEYENDA: Reconstruir con nuevo tema
        self._rebuild_legend()
        
        # 4️⃣ EJE Y: Reemplazar ChartAxis COMPLETO
        # (Flet 0.28.x NO repinta si solo cambiamos .labels)
        if self._last_y_values:
            self._rebuild_y_axis_for_theme()
        
        # 5️⃣ Actualizar axis line del eje Y
        self._y_axis_line_color = self._get_y_axis_line_color()
        self.border = ft.Border.only(left=ft.BorderSide(1.4, self._y_axis_line_color))
        
        # NO llamar self.update() aquí: la vista orquesta un único page.update()

    def _rebuild_y_axis_for_theme(self):
        """
        Reconstruye el eje Y COMPLETO para forzar repaint de Flet.
        Usa los mismos valores guardados, solo cambia colores.
        """
        if not self._last_y_values:
            return
        
        # Recalcular labels y límites usando valores existentes
        self._build_y_axis(self._last_y_values)


    # ======================================================
    # LEYENDA Y AXIS LINE
    # ======================================================

    def _get_y_axis_line_color(self):
        """
        Retorna color para la axis line del eje Y.
        
        Estrategia:
        - Más visible que gridlines (opacidad ~0.30-0.35)
        - Menos visible que texto y líneas de datos
        - GREY neutro adaptado al tema
        """
        if is_dark_mode(self.page.theme_mode):
            # Dark mode: opacidad 0.32
            return ft.Colors.with_opacity(0.32, ft.Colors.GREY_500)
        else:
            # Light mode: opacidad 0.28
            return ft.Colors.with_opacity(0.28, ft.Colors.GREY_600)

    def _build_legend(self) -> ft.Container:
        """
        Construye leyenda con información de períodos.
        
        Formato compacto:
        ■ Period A | Jan 1 – Jan 31, 2024 | Client: All | Product: All
        ■ Period B | Feb 1 – Feb 29, 2024 | Client: X | Product: Y
        
        Compatible con dark/light mode.
        """
        # Color del texto según tema
        text_color = get_text_color(self.page.theme_mode)
        
        def format_date_range(start: str, end: str) -> str:
            if not start or not end:
                return "—"
            try:
                from datetime import datetime
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                return format_date_range_us(start_dt, end_dt)
            except (ValueError, TypeError):
                return "—"
        
        # Construir línea de Periodo A
        range_a = format_date_range(self.period_a_info["start"], self.period_a_info["end"])
        client_a = self.period_a_info.get("client", ALL_FILTER_LABEL)
        product_a = self.period_a_info.get("product", ALL_FILTER_LABEL)
        label_a_text = f"Period A | {range_a} | Client: {client_a} | Product: {product_a}"
        
        # Construir línea de Periodo B
        range_b = format_date_range(self.period_b_info["start"], self.period_b_info["end"])
        client_b = self.period_b_info.get("client", ALL_FILTER_LABEL)
        product_b = self.period_b_info.get("product", ALL_FILTER_LABEL)
        label_b_text = f"Period B | {range_b} | Client: {client_b} | Product: {product_b}"
        
        # Indicador A (Azul)
        indicator_a = ft.Container(
            width=12,
            height=12,
            bgcolor=ft.Colors.BLUE,
            border_radius=2,
        )
        label_a = ft.Text(
            label_a_text,
            size=11,
            weight=ft.FontWeight.W_400,
            color=text_color,
        )
        item_a = ft.Row(
            [indicator_a, label_a],
            spacing=8,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        
        # Indicador B (Naranja)
        indicator_b = ft.Container(
            width=12,
            height=12,
            bgcolor=ft.Colors.ORANGE,
            border_radius=2,
        )
        label_b = ft.Text(
            label_b_text,
            size=11,
            weight=ft.FontWeight.W_400,
            color=text_color,
        )
        item_b = ft.Row(
            [indicator_b, label_b],
            spacing=8,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        
        # Contenedor con leyenda (columna vertical para mejor legibilidad)
        legend_column = ft.Column(
            [item_a, item_b],
            spacing=6,
            tight=True,
        )
        
        return ft.Container(
            content=legend_column,
            padding=ft.Padding(0, 6, 0, 0),
        )
    
    def _rebuild_legend(self):
        """
        Reconstruye la leyenda en el contenedor (para actualizaciones dinámicas).
        
        Flet 0.28.x requiere reemplazo completo del Container para forzar repaint.
        """
        if not hasattr(self, 'content') or not hasattr(self.content, 'controls'):
            return
        
        new_legend_container = ft.Container(
            content=self._build_legend(),
            padding=ft.Padding(0, 8, 0, 4),
        )
        
        # Buscar y reemplazar el container de leyenda
        for i, ctrl in enumerate(self.content.controls):
            if ctrl is self.legend_container:
                self.content.controls[i] = new_legend_container
                self.legend_container = new_legend_container
                break
        
    def _get_height_for_grouping(self) -> int:
        """
        Retorna la altura óptima del gráfico según densidad temporal.
        
        Criterios (UI/layout):
        - day / week: más alto (muchos puntos + labels densos)
        - month: alto (densidad moderada)
        - quarter/year: suficiente para ejes sin clipping (evitar "compacto" excesivo)
        """
        if self._grouping in ("day", "week"):
            return 720  # Más altura para evitar clipping de ejes y dar aire visual
        elif self._grouping == "month":
            return 680
        elif self._grouping == "quarter":
            return 640
        else:  # year
            return 600

    def _set_grouping(self, grouping):
        self._grouping = grouping
        self._update_button_states()
        
        # Ajustar altura dinámicamente
        new_height = self._get_height_for_grouping()
        self.height = new_height
        # Auto-update de Flet 0.80.5 maneja cambios de propiedades simples

        if self._on_grouping_change:
            self._on_grouping_change(grouping)

    def _update_button_states(self):
        if not mounted_page(self):
            return
        for key, btn in self._buttons.items():
            btn.style = ft.ButtonStyle(
                bgcolor=get_tops_chart_color(self.page.theme_mode) if key == self._grouping
                else (ft.Colors.GREY_300 if not is_dark_mode(self.page.theme_mode) else ft.Colors.GREY_700),
                color=ft.Colors.ON_PRIMARY if key == self._grouping  # Color semántico
                else ft.Colors.ON_SURFACE,  # Color semántico
                padding=10,
            )
        
    # ======================================================
    # EJE Y (LEGIBLE Y AGNÓSTICO)
    # ======================================================

    def _format_y_value(self, v: float) -> str:
        a = abs(v)
        if a >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if a >= 1_000:
            return f"{v / 1_000:.0f}k"
        return f"{int(v)}"

    def _add_manual_bottom_labels(self, tick_indices: list, labels: list, label_color):
        """
        Agrega labels manuales debajo del gráfico cuando Flet no los renderiza.
        Usado como fallback para casos con muy pocos puntos (≤3).
        """
        # Esta es una llamada registrada para posible future implementation
        # Actualmente Flet 0.28 no permite agregar controles dinámicamente debajo
        # del LineChart, así que esta es solo referencia para futuro
        pass

    def _build_y_axis(self, values: list[float]):
        """
        Construye y reasigna completamente el eje Y del LineChart.

        Motivo:
        - Flet 0.80.x NO repinta correctamente cuando se mutan labels existentes
        - Es obligatorio reemplazar el ChartAxis completo

        Estrategia:
        - Padding dinámico según agrupación temporal
        - Headroom superior para evitar clipping
        - Gridlines jerárquicas (baseline / midpoint)
        - Etiquetas con jerarquía visual (max / mid / others)

        Nota:
        Este método es el único responsable del eje Y.
        """
        if not values:
            return

        min_val = min(values)
        max_val = max(values)

        # Si todos los valores son iguales, crear rango artificial
        if min_val == max_val:
            min_val = 0
            max_val *= 1.2 if max_val > 0 else 1

        range_val = max_val - min_val

        # ============================================================
        # ESCALA DINÁMICA POR AGRUPACIÓN
        # ============================================================
        if self._grouping == "year":
            # Años: muy pocas muestras, máximo espacio visual
            padding_ratio = 0.45
            steps = 3
            allow_negative = False
        elif self._grouping == "quarter":
            # Trimestres: pocas muestras, contexto amplio
            padding_ratio = 0.40
            steps = 3
            allow_negative = False
        elif self._grouping == "month":
            # Meses: densidad baja-moderada, buen contexto
            padding_ratio = 0.30
            steps = 3
            allow_negative = False
        elif self._grouping == "week":
            # Semanas: densidad moderada, balance
            padding_ratio = 0.20
            steps = 4
            allow_negative = False
        else:  # day
            # Días: máxima densidad, precisión visual
            padding_ratio = 0.12
            steps = 4
            allow_negative = False

        # Calcular padding dinámico
        padding = range_val * padding_ratio

        # Construir rango Y
        min_y = min_val - padding if allow_negative else max(0, min_val - padding)
        max_y = max_val + padding
        
        # Calcular step_value PRIMERO (necesario antes de usarlo para label_headroom)
        step_value = (max_y - min_y) / steps

        # ============================================================
        # HEADROOM PARA LABEL SUPERIOR (evita clipping del label max)
        # ============================================================

        if self._grouping in ("day", "week"):
            label_headroom = step_value * 0.35
        else:
            label_headroom = step_value * 0.25

        max_y += label_headroom
        
        # Recalcular step_value con el nuevo max_y
        step_value = (max_y - min_y) / steps

        # Asignar límites al gráfico
        self.line_chart.min_y = min_y
        self.line_chart.max_y = max_y

        # ============================================================
        # GRIDLINES HORIZONTALES CON JERARQUÍA VISUAL + BASELINE
        # ============================================================
        # Objetivo: MÁXIMO 2-3 gridlines con jerarquía clara
        # - Baseline (y=0): si está visible, es el "suelo" del gráfico
        # - Midpoint (principal): "eje mental", referencia primaria
        # - Upper quartile (secundaria): solo contexto adicional
        
        total_range = max_y - min_y
        
        # Verificar si baseline (y=0) está dentro del rango visible
        baseline_visible = min_y <= 0 <= max_y
        
        # ============================================================
        # ESTRATEGIA DE INTERVAL SEGÚN BASELINE
        # ============================================================
        if baseline_visible:
            # Si baseline visible: interval desde 0
            # Esto asegura que una gridline caiga exactamente en y=0
            if steps >= 4:
                # Con 4+ steps: generar gridlines cada 2 steps desde baseline
                # Resultado: baseline + ~1-2 gridlines superiores
                grid_interval = step_value * 2
            else:
                # Con 3 steps: generar gridline cada 1-2 steps
                grid_interval = step_value * 1.5
            
            # Color y grosor optimizados para baseline + midpoint
            if is_dark_mode(self.page.theme_mode):
                gridline_opacity = 0.28  # Más visible con baseline
                gridline_base_color = ft.Colors.GREY_500
            else:
                gridline_opacity = 0.22  # Más visible con baseline
                gridline_base_color = ft.Colors.GREY_600
            
            gridline_width = 1.3  # Ligeramente más grueso para baseline
            
        else:
            # Sin baseline: estrategia original optimizada para midpoint
            if steps >= 4:
                grid_interval = step_value * 2
            else:
                grid_interval = total_range
            
            if is_dark_mode(self.page.theme_mode):
                gridline_opacity = 0.24
                gridline_base_color = ft.Colors.GREY_500
            else:
                gridline_opacity = 0.17
                gridline_base_color = ft.Colors.GREY_600
            
            gridline_width = 1.2
        
        gridline_color = ft.Colors.with_opacity(gridline_opacity, gridline_base_color)
        
        # Actualizar gridlines del LineChart
        self.line_chart.horizontal_grid_lines = ftc.ChartGridLines(
            interval=grid_interval,
            color=gridline_color,
            width=gridline_width,
        )

        # ============================================================
        # JERARQUÍA VISUAL DEL EJE Y
        # ============================================================
        # Estrategia:
        # - Máximo (top): size=13, BOLD, color más oscuro
        # - Medio (midpoint): size=12, W_600, color medio
        # - Otros: size=11, W_500, color más claro
        
        # Colores adaptativos según theme
        color_max = get_text_color(self.page.theme_mode)  # Máximo contraste
        color_mid = (
            ft.Colors.GREY_500 if is_dark_mode(self.page.theme_mode)
            else ft.Colors.GREY_600
        )
        color_other = (
            ft.Colors.GREY_600 if is_dark_mode(self.page.theme_mode)
            else ft.Colors.GREY_500
        )

        # Generar etiquetas con jerarquía visual
        labels = []
        mid_index = steps // 2  # Índice del punto medio
        
        for i in range(steps + 1):
            value = min_y + i * step_value
            formatted_value = self._format_y_value(value)
            
            # Detectar tipo de label
            if i == steps:
                # MÁXIMO: mayor jerarquía, más compacto
                label = ftc.ChartAxisLabel(
                    value,
                    ft.Text(
                        formatted_value,
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=color_max,
                        no_wrap=True,
                        max_lines=1,
                    ),
                )
            elif i == mid_index:
                # MEDIO: jerarquía intermedia, más compacto
                label = ftc.ChartAxisLabel(
                    value,
                    ft.Text(
                        formatted_value,
                        size=11,
                        weight=ft.FontWeight.W_600,
                        color=color_mid,
                        no_wrap=True,
                        max_lines=1,
                    ),
                )
            else:
                # OTROS: jerarquía baja, más compacto
                label = ftc.ChartAxisLabel(
                    value,
                    ft.Text(
                        formatted_value,
                        size=10,
                        weight=ft.FontWeight.W_500,
                        color=color_other,
                        no_wrap=True,
                        max_lines=1,
                    ),
                )
            
            labels.append(label)
        
        self.line_chart.left_axis = ftc.ChartAxis(
            labels=labels,
            label_size=self._LEFT_AXIS_LABEL_SIZE,
            title=ft.Text(self._y_axis_title, size=12, weight=ft.FontWeight.W_600),
            title_size=self._LEFT_AXIS_TITLE_SIZE
        )

    def _rebuild_bottom_axis(self):
        """
        Reconstruye el eje X COMPLETO desde labels guardados.
        
        ⚠️ LIMITACIÓN CONOCIDA DE FLET 0.80:
        Cuando hay muy pocos puntos (2-5, típicamente modo trimestre/año),
        los labels de los EXTREMOS (primer y último) NO se renderizan visiblemente.
        
        Aunque los labels existen en la estructura y los tooltips muestran el
        período correcto, Flet decide no pintarlos en pantalla.
        
        Ver: FLET_LIMITATION_CHART_LABELS.md para detalles completos.
        
        CRÍTICO (Flet 0.28.x):
        - Flet NO repinta si solo modificamos propiedades internas
        - Debemos REEMPLAZAR la lista completa de labels
        
        Llamado cuando:
        - update_data() actualiza las series
        - El número de puntos cambia
        
        Garantiza:
        - Sincronización entre índices X y puntos Y
        - Subsampling adaptativo según densidad
        - Inclusión de primer/último label siempre
        - TODOS los labels visibles cuando hay ≤ 12 puntos
        """
        if not self._last_labels:
            # Sin datos, limpiar eje X
            self.line_chart.bottom_axis.labels = []
            return
        
        labels = self._last_labels
        total = len(labels)
        
        # Color adaptativo según tema (aumentado contraste)
        label_color = (
            ft.Colors.GREY_300 if is_dark_mode(self.page.theme_mode)
            else ft.Colors.GREY_700
        )
        
        # Estrategia adaptativa según cantidad de puntos
        if total <= 5:
            # MUY pocos puntos (año, trimestre): mostrar solo extremos + medio
            # Esto evita superposición visual en Flet cuando hay 2-5 puntos
            tick_indices = {0, total - 1}  # Primero y último siempre
            if total >= 3:
                tick_indices.add(total // 2)  # Agregar el del medio si hay al menos 3
        elif total <= 12:
            # Pocos puntos: MOSTRAR TODOS (crítico para mes)
            tick_indices = set(range(total))
        else:
            # Muchos puntos: subsampling inteligente (objetivo: ~12 labels)
            target_labels = 12
            step = max(1, (total - 1) // (target_labels - 1))
            
            # Siempre incluir primero/último + intermedios espaciados
            tick_indices = {0, total - 1}
            tick_indices.update(i for i in range(0, total, step))
        
        # REEMPLAZAR completamente la lista de labels (Flet 0.28.x)
        # Usar propiedades mínimas para mejor compatibilidad con Flet
        self.line_chart.bottom_axis.labels = [
            ftc.ChartAxisLabel(
                i,
                ft.Text(
                    labels[i],
                    size=11,
                    color=label_color,
                ),
            )
            for i in sorted(tick_indices)
        ]
