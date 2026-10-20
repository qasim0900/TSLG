"""Contenedor de gráficos y métricas del modo comparación."""
import flet as ft
import logging
from theme import (get_text_color,
                   get_compare_delta_color,
                   get_compare_state_color,
                   get_compare_value_color,
                   get_compare_kpi_card_style,
                   get_subtitle_color,)
from components.compare_charts import CompareBarChart
from components.compare_line_chart import CompareLineChart
from domain.analysis_snapshot import AnalysisSnapshot, TimeGrouping
from utils.formatting import format_eur
from utils.ui_dispatch import mounted_page


logger = logging.getLogger(__name__)


class CompareChartsContainer(ft.Container):
    """
    Contenedor de gráficos del modo comparación (A vs B).
    - No calcula datos
    - No conoce filtros
    - Solo renderiza resultados ya calculados
    """

    def __init__(self, on_grouping_change=None):
        # 🔐 PRIMERO: super().__init__() antes que nada
        super().__init__(
            visible=False,
            padding=12,
            bgcolor=None,
            border_radius=8,
            expand=True,
        )

        self.title = ft.Text(
            "📊 A vs. B comparison",
            size=16,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.ON_SURFACE,
        )
        self.subtitle = ft.Text(
            "",
            size=11,
            color=ft.Colors.GREY,
        )
        self.cards_row = ft.Row(spacing=15, expand=True)
        self.cards_row.controls.clear()
        self.bar_chart = CompareBarChart()
        self.line_chart = CompareLineChart(on_grouping_change=self._handle_grouping_change)

        self.bar_chart.visible = False
        self.line_chart.visible = False
        self._snapshot = None          # Cached snapshot for local regrouping
        self._visual_grouping = None   # Current visual grouping (may differ from snapshot.metadata.grouping)
        
        content = ft.Column(
            [
                self.title,
                self.subtitle,
                self.cards_row,
                self._soft_divider(),
                self.bar_chart,
                self._soft_divider(),
                self.line_chart,
            ],
            spacing=20,
            expand=True,
        )

        self.content = content
        self.on_grouping_change = on_grouping_change

    def did_mount(self):
        """Inicializa tema cuando el control esté montado."""
        self.update_theme()
        if hasattr(self.bar_chart, "update_theme"):
            self.bar_chart.update_theme()
        if hasattr(self.line_chart, "update_theme"):
            self.line_chart.update_theme()


    # ======================================================
    #   API PÚBLICA
    # ======================================================

    def update_from_snapshot(self, snapshot: AnalysisSnapshot):
        """
        --- FASE 4D: Actualización 100% snapshot-only ---
        Actualiza los gráficos comparativos desde un AnalysisSnapshot.
        NO depende de ningún método legacy.
        
        Comportamiento:
        - Si snapshot NO está en modo compare → no hacer nada
        - Si snapshot está en modo compare → extraer datos y pintar UI
        
        Args:
            snapshot: AnalysisSnapshot validado
        """
        if not snapshot:
            self.visible = False
            self._snapshot = None
            self._visual_grouping = None
            return

        # Solo funciona en modo compare
        if not snapshot.is_compare_mode():
            self.visible = False
            self._snapshot = None
            self._visual_grouping = None
            return
        
        # Validar que exista comparison
        if not snapshot.comparison:
            self.visible = False
            self._snapshot = None
            self._visual_grouping = None
            return

        # Cache snapshot for local regrouping solo cuando ya es válido
        self._snapshot = snapshot
        self._visual_grouping = snapshot.metadata.grouping
        self.subtitle.value = (
            f"A: {snapshot.period_a.filters.date_start} → {snapshot.period_a.filters.date_end}   "
            f"B: {snapshot.period_b.filters.date_start} → {snapshot.period_b.filters.date_end}"
        )
        
        try:
            # Extraer datos del snapshot
            abs_changes = snapshot.comparison.metrics.absolute_changes
            
            # Período A y B metrics
            period_a_metrics = snapshot.period_a.metrics
            period_b_metrics = snapshot.period_b.metrics
            
            results = {
                "total_sales": {
                    "A": period_a_metrics.total_sales,
                    "B": period_b_metrics.total_sales,
                    "delta": abs_changes.get("total_sales", 0),
                },
                "transactions": {
                    "A": period_a_metrics.transactions,
                    "B": period_b_metrics.transactions,
                    "delta": abs_changes.get("transactions", 0),
                },
                "avg_ticket": {
                    "A": period_a_metrics.avg_ticket,
                    "B": period_b_metrics.avg_ticket,
                    "delta": abs_changes.get("avg_ticket", 0),
                },
            }
            
            # Tarjetas de métricas (con contexto de fechas y casos especiales)
            # Mutar el ControlList en lugar de reemplazarlo (Flet diff tracking)
            self.cards_row.controls.clear()
            self.cards_row.controls.extend([
                self._build_card(
                    "Total sales", results["total_sales"], " €",
                    period_b=snapshot.period_b
                ),
                self._build_card(
                    "Transactions", results["transactions"], "",
                    period_b=snapshot.period_b
                ),
                self._build_card(
                    "Average sale", results["avg_ticket"], " €",
                    period_b=snapshot.period_b
                ),
            ])

            # Bar chart
            self.bar_chart.update_data(results)
            self.bar_chart.visible = True

            # Line chart desde EvolutionComparisonV2.points
            evolution_points = snapshot.comparison.evolution.points
            if evolution_points:
                self.line_chart.update_from_evolution_points(evolution_points)
                
                # Actualizar información de períodos en la leyenda
                self.line_chart.set_period_info(
                    "a",
                    start=snapshot.period_a.filters.date_start,
                    end=snapshot.period_a.filters.date_end,
                    client=snapshot.period_a.filters.client_name or None,
                    product=snapshot.period_a.filters.product_type or None,
                )
                self.line_chart.set_period_info(
                    "b",
                    start=snapshot.period_b.filters.date_start,
                    end=snapshot.period_b.filters.date_end,
                    client=snapshot.period_b.filters.client_name or None,
                    product=snapshot.period_b.filters.product_type or None,
                )
                
                self.line_chart.visible = True
            else:
                # 🔐 Explícitamente ocultar si no hay evolution_points (previene residualidad)
                self.line_chart.visible = False

            self.visible = True
            # El caller ejecuta page.update() global — no se necesitan
            # .update() locales aquí (evita dirty marks prematuros en el subtree)
        
        except Exception:
            logger.exception("CompareChartsContainer: update_from_snapshot failed")
            self.visible = False

    def update_theme(self):
        """
        Actualiza colores del contenedor según el tema actual (light/dark).

        CONTRATO OFFICIAL:
        - NO recibe parámetros
        - SOLO lee self.page.theme_mode
        - NO modifica self.page.theme_mode
        - Defensivo: sale si self.page es None
        """
        # Defensiva: comprobar que self.page existe
        if not mounted_page(self):
            return

        # Leer el modo de tema actual (NO escribir)
        theme_mode = self.page.theme_mode

        # Textos principales
        self.title.color = get_text_color(theme_mode)
        self.subtitle.color = get_subtitle_color(theme_mode)

        # 🔁 KPI CARDS — REAPLICAR ESTILO (R9: mutar TODOS los controles visibles)
        for card in self.cards_row.controls:
            style = get_compare_kpi_card_style(self.page)

            # Contenedor
            card.bgcolor = style["bgcolor"]
            card.padding = style["padding"]
            card.border_radius = style["radius"]
            card.border = ft.Border.all(1, style["border_color"])
            card.shadow = style["shadow"]

            # 🔐 Recursar para actualizar TODOS los Text dentro de la tarjeta (R9)
            self._update_text_colors_recursive(
                card.content,
                theme_mode,
                style["title_color"],
                style["meta_color"],
            )

            # ✅ NO llamar card.update() aquí (evita tormenta de updates)

        # Gráficos
        if hasattr(self.bar_chart, "update_theme"):
            self.bar_chart.update_theme()

        if hasattr(self.line_chart, "update_theme"):
            self.line_chart.update_theme()

        # ✅ NO llamar self.update() aquí: la vista orquesta un único page.update()

    def _update_text_colors_recursive(self, control, theme_mode, title_color, meta_color):
        """
        Recursivamente busca y actualiza colores de Text dentro de un control (R9).
        
        ✅ ESTRATEGIA ROBUSTA (Flet 0.80.5+):
        - Cada Text tiene un atributo .compare_role asignado en _build_card()
        - Usa el rol (no solo tamaño) para determinar color correcto
        - Recupera datos en caché: .compare_value, .compare_delta, .compare_state
        
        Roles soportados:
        - "title": títulos de métrica (size 12) → title_color
        - "meta": metadatos (size 9) → meta_color
        - "value_a": valor A (size 19) → get_compare_value_color(page, "A")
        - "value_b": valor B (size 19) → get_compare_value_color(page, "B")
        - "delta": delta (size 15) → get_compare_delta_color(page, delta_real)
        - "state": estado (size 11) → get_compare_state_color(page, state_real)
        - "arrow": flecha (value "→") → get_subtitle_color()
        - "state_icon": ícono estado (size 11) → sin cambio (ícono invariable)
        """
        if not control:
            return

        # CASO BASE: si es Text, busca rol y aplica color correcto
        if isinstance(control, ft.Text):
            compare_role = getattr(control, "compare_role", None)
            
            if compare_role == "title":
                control.color = title_color
            elif compare_role == "meta":
                control.color = meta_color
            elif compare_role == "value_a":
                control.color = get_compare_value_color(self.page, "A")
            elif compare_role == "value_b":
                control.color = get_compare_value_color(self.page, "B")
            elif compare_role == "delta":
                # Recuperar delta real del atributo cacheado
                delta = getattr(control, "compare_delta", 0)
                control.color = get_compare_delta_color(self.page, delta)
            elif compare_role == "state":
                # Recuperar estado real del atributo cacheado
                state = getattr(control, "compare_state", "none")
                control.color = get_compare_state_color(self.page, state)
            elif compare_role == "arrow":
                control.color = get_subtitle_color(self.page)
            elif compare_role == "state_icon":
                # No cambiar: ícono es invariable
                pass
            # Si no tiene rol pero heurística lo detecta, fallback por tamaño
            elif control.size == 12:
                control.color = title_color
            elif control.size == 9:
                control.color = meta_color
            elif control.value == "→":
                control.color = get_subtitle_color(self.page)
            return

        # RECURSIÓN: si tiene controles hijos, procesa cada uno
        if hasattr(control, "controls") and control.controls:
            for child in control.controls:
                self._update_text_colors_recursive(child, theme_mode, title_color, meta_color)

    def _handle_grouping_change(self, grouping):
        if self.on_grouping_change:
            self.on_grouping_change(grouping)

    def reagroup_local(self, grouping: str) -> bool:
        """
        Regroup evolution chart locally from cached daily raw data.
        
        Does NOT execute SQL queries.
        Does NOT modify the cached snapshot.
        Does NOT call page.update() (caller must do it).
        
        Returns True if successful, False if preconditions not met
        (caller should fall back to full _on_compare_requested).
        """
        from analysis.time_grouping import regroup_evolution_comparison, is_valid_regroup
        
        # Precondition checks
        if not self._snapshot:
            return False
        if not self._snapshot.is_compare_mode():
            return False
        if self._snapshot.period_a.evolution_raw is None:
            return False
        if self._snapshot.period_b is None or self._snapshot.period_b.evolution_raw is None:
            return False
        
        # Validate granularity hierarchy (raw is always daily)
        if not is_valid_regroup("day", grouping):
            return False
        
        try:
            # Regroup using pure function (no SQL, no side effects on snapshot)
            new_evolution = regroup_evolution_comparison(
                self._snapshot,
                grouping,
            )
            
            # Update ONLY the line chart with new points
            self.line_chart.update_from_evolution_points(new_evolution.points)
            
            # Track visual grouping (snapshot.metadata.grouping stays unchanged)
            self._visual_grouping = TimeGrouping(grouping)
            
            return True
        except Exception:
            logger.exception("CompareChartsContainer: reagroup_local failed")
            return False

    def _build_card(
        self,
        title: str,
        data: dict,
        suffix: str = "",
        period_b=None,
    ) -> ft.Container:
        """Construye tarjeta de métrica KPI (R7: defensiva)."""
        # Defensiva: si no hay page, retornar contenedor vacío
        if not mounted_page(self):
            return ft.Container()

        TITLE_SIZE = 12
        VALUE_SIZE = 19
        DELTA_SIZE = 15
        META_SIZE = 9
        arrow, delta_color = self._delta_visual(data["delta"])
        style = get_compare_kpi_card_style(self.page)
        a = data["A"]
        b = data["B"]
        is_partial = getattr(period_b, "is_partial", False)

        state_icon, state_text, state_color = self._determine_card_state(
            a, b, is_partial
        )

        # 🔐 CREAR TEXTOS CON ROLES ASIGNADOS (R9: cachear para update_theme)
        title_text = ft.Text(
            title,
            size=TITLE_SIZE,
            weight=ft.FontWeight.W_600,
            color=style["title_color"],
        )
        title_text.compare_role = "title"  # Rol para update_theme()

        is_monetary = "€" in suffix
        delta = data["delta"]
        sign = "+" if delta > 0 else "-" if delta < 0 else ""
        if is_monetary:
            value_a_str = format_eur(a)
            value_b_str = format_eur(b)
            delta_str = f"{arrow} {sign}{format_eur(abs(delta))}"
        else:
            value_a_str = f"{a:,.0f}"
            value_b_str = f"{b:,.0f}"
            delta_str = f"{arrow} {sign}{abs(delta):,.0f}"

        value_a_text = ft.Text(
            value_a_str,
            size=VALUE_SIZE,
            weight=ft.FontWeight.BOLD,
            color=get_compare_value_color(self.page, "A"),
        )
        value_a_text.compare_role = "value_a"  # Rol para update_theme()
        value_a_text.compare_value = a  # Cachear valor para delta

        arrow_text = ft.Text("→", size=14, color=get_subtitle_color(self.page))
        arrow_text.compare_role = "arrow"

        value_b_text = ft.Text(
            value_b_str,
            size=VALUE_SIZE,
            weight=ft.FontWeight.BOLD,
            color=get_compare_value_color(self.page, "B"),
        )
        value_b_text.compare_role = "value_b"
        value_b_text.compare_value = b

        delta_text = ft.Text(
            delta_str,
            size=DELTA_SIZE,
            weight=ft.FontWeight.BOLD,
            color=delta_color,
        )
        delta_text.compare_role = "delta"  # Rol para update_theme()
        delta_text.compare_delta = data["delta"]  # Cachear delta real

        content_items = [
            title_text,
            ft.Row(
                [value_a_text, arrow_text, value_b_text],
                spacing=10,
            ),
            delta_text,
        ]

        # Meta (periodo B)
        if period_b and period_b.filters:
            meta_text = ft.Text(
                f"B: {period_b.filters.date_start} → {period_b.filters.date_end}",
                size=META_SIZE,
                color=style["meta_color"],
            )
            meta_text.compare_role = "meta"  # Rol para update_theme()
            content_items.append(meta_text)

        # Estado semántico
        if state_text:
            state_icon_text = ft.Text(state_icon, size=11)
            state_icon_text.compare_role = "state_icon"
            
            state_label_text = ft.Text(
                state_text,
                size=11,
                italic=True,
                color=state_color,
            )
            state_label_text.compare_role = "state"  # Rol para update_theme()
            state_label_text.compare_state = state_text  # Cachear estado
            
            content_items.append(
                ft.Row(
                    [state_icon_text, state_label_text],
                    spacing=6,
                )
            )

        return ft.Container(
            content=ft.Column(content_items, spacing=10),
            padding=style["padding"],
            bgcolor=style["bgcolor"],
            border_radius=style["radius"],
            border=ft.Border.all(1, style["border_color"]),
            shadow=style["shadow"],
            expand=True,
        )

    def _determine_card_state(self, a: float, b: float, is_partial_b: bool):
        """
        Determina estado semántico de una tarjeta comparativa.
        Retorna: (icono, texto, color) o (None, None, None) si no aplica.
        """
        if is_partial_b:
            state = "partial"
            return "⚠", "Period B incomplete", get_compare_state_color(self.page, state)

        if a == 0 and b > 0:
            state = "new"
            return "🆕", "New activity", get_compare_state_color(self.page, state)

        if a > 0 and b == 0:
            state = "inactive"
            return "🛑", "No activity", get_compare_state_color(self.page, state)

        if a == 0 and b == 0:
            state = "none"
            return "—", "No change", get_compare_state_color(self.page, state)

        return None, None, None
    
    def _delta_visual(self, delta: float):
        """Determina flecha y color del delta (R7: defensiva)."""
        if not mounted_page(self):
            return "—", ft.Colors.GREY

        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "—"
        color = get_compare_delta_color(self.page, delta)
        return arrow, color

    def _soft_divider(self):
        return ft.Divider(
            height=1,
            thickness=0.6,
            color=ft.Colors.TRANSPARENT
        )
