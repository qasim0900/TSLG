"""Vista de Ventas — pantalla principal de análisis de ventas.

Ofrece filtrado por fecha/cliente/producto, visualización de KPIs, gráficos
de evolución y distribución, tabla de resumen, modo comparación A vs B,
importación de datos y exportación a HTML.
"""

import time
import flet as ft
import logging
from datetime import datetime
from components.filter_panel import FilterPanel
from components import ComparePanel, CompareChartsContainer
from components.action_buttons import ActionButtons
from components.stat_card import create_stat_card
from components.grafico_circular import PieChartInteractive
from components.grafico_evolucion import GraficoEvolucion
from components.tabla_resumen import TablaResumen
from controllers.file_import_controller import FileImportController
from utils.ui_dispatch import ui_callback
from controllers.ventas_controller import VentasController
from controllers import CompareController
from utils.notifications import NotificationManager, show_notification
from utils.file_dialogs import save_html_file
from utils.formatting import format_eur
from utils.file_opener import open_file_cross_platform
from components.import_flow import run_import_flow
from theme import get_text_color, update_container_theme
from components.client_summary_card import build_client_summary_card
from components.top_clients_row import build_top_clients_row
from views.scrollable_view import ScrollableView
from reports.report_html import generate_html_report_from_snapshot
from domain.analysis_snapshot import PieChartSnapshot, PieChartSegmentSnapshot

logger = logging.getLogger(__name__)


def _shimmer_placeholder(height: int | None = None) -> ft.Shimmer:
    """Shimmer placeholder for containers that load content asynchronously."""
    return ft.Shimmer(
        content=ft.Container(
            expand=True,
            height=height,
            border_radius=8,
        ),
        base_color=ft.Colors.with_opacity(0.3, ft.Colors.ON_SURFACE),
        highlight_color=ft.Colors.with_opacity(0.1, ft.Colors.ON_SURFACE),
    )

class VentasView(ScrollableView):
    """Vista de Ventas con filtros, KPIs, gráficos, tabla y modo comparación."""

    def __init__(self, page: ft.Page):
        super().__init__(expand=True, spacing=20)
        self._page = page
        self.ventas_controller = VentasController()
        self.notifications = NotificationManager(page)
        self.compare_controller = CompareController()
        self.compare_charts_container = CompareChartsContainer(on_grouping_change=self._on_compare_grouping_change,)
        self.compare_panel = ComparePanel(self.compare_controller, on_clear_comparison=self._on_compare_cleared, on_compare_requested=self._on_compare_requested,)
        
        # File Import Controller
        self.file_import_controller = FileImportController(
            on_success=ui_callback(page, self._on_import_success),
            on_error=ui_callback(page, self._on_import_error),
            on_start=ui_callback(page, self._on_import_start),
        )
        self._detected_prefix = None  # Prefijo de tipo de archivo para mensaje final
        
        # Output
        self.output = ft.Text(size=14, color=get_text_color(page.theme_mode))

        # Contenedores — shimmer placeholder durante carga inicial
        self.summary_container = ft.Container(
            expand=True,
            content=_shimmer_placeholder(height=60),
        )
        # Flag para activar/desactivar snapshot en modo COMPARE (FASE 3)
        self.use_compare_snapshot = True
        # --- INTEGRACIÓN SNAPSHOT (NORMAL) ---
        self.use_snapshot = True  # Flag temporal para activar snapshot (solo StatCards)
        self.current_snapshot = None  # Último snapshot obtenido (modo NORMAL)
        self._current_snapshot_key = None  # Clave de validación del snapshot en cache
        
        # ============================================================
        # MEJORA B: REFERENCIAS A COMPONENTES DINÁMICOS
        # ============================================================
        self._current_tabla_resumen = None  # Referencia a tabla summary
        self._current_grafico_circular = None  # Referencia a gráfico circular
        self._current_grafico_evolucion = None  # Referencia a gráfico evolución
        self._current_top_clients_row = None  # Referencia a fila de top clientes
        self._current_grafico_top = None  # Referencia a GraficoClientesTop (Patrón B)
        self._current_grafico_monto = None  # Referencia a GraficoClientesMonto (Patrón B)
        
        # ============================================================
        
        # Importante: NO reservar altura grande si aún no hay gráficos.
        # Esto evita la "pantalla vacía" inicial que parece un bug.

        self.chart_container = ft.Container(
            height=None,
            visible=False,
            content=ft.Text(
                'Click "Show charts" to display them.',
                size=12,
                color=get_text_color(page.theme_mode),
            ),
        )
        
        self._evolution_switcher = ft.AnimatedSwitcher(
            content=_shimmer_placeholder(),
            transition=ft.AnimatedSwitcherTransition.FADE,
            duration=ft.Duration(milliseconds=300),
            expand=True,
        )
        self.evolution_container = ft.Container(expand=True, height=450, content=self._evolution_switcher)
        
        # Filter Panel
        self.filter_panel = FilterPanel(
            on_filter_applied=self._on_filter_applied,
            on_filter_cleared=self._on_filter_cleared,
            filter_controller=self.ventas_controller.filter_controller,  # 🆕 FASE 0
        )

        # Action Buttons
        self.action_buttons = ActionButtons(
            on_import=self._on_import_button_click,
            on_show_summary=self.show_summary,
            on_show_charts=self.show_both,
            on_export=self._on_export_button_click,
        )
        
        # Obtener la columna contenedora del scroll
        self._content_column = self.get_content_column()

        # 🔑 Generar snapshot inicial antes de construir la UI
        # Garantiza que _build_ui() ya tiene snapshot disponible
        self._refresh_snapshot()

        # Construir UI
        self._build_ui()

        self._is_rebuilding = False  # Guard: previene renders simultáneos
        self._pending_filter_call = False  # Guard: encola filtro si render en curso
        self._charts_visible = True  # Estado de visibilidad de gráficos

        # Poblar contenedores en __init__ — self._page ya está disponible
        self._populate_view_containers(view_mode="both", show_notification=False)

    def _get_current_snapshot_key(self, grouping: str = "day") -> str:
        """Construye la clave de cache basada en los filtros actuales."""
        params = self.ventas_controller.get_filter_params()
        return self.ventas_controller.build_snapshot_key(
            date_start=params['start_date'],
            date_end=params['end_date'],
            client_name=params['client_name'],
            product_type=params['product_type'],
            grouping=grouping,
        )

    def _get_statcard_values_from_snapshot(self) -> dict | None:
        """
        Intenta obtener valores de StatCards desde AnalysisSnapshot.
        Si self.use_snapshot es False, retorna None (calcula directamente).
        Si snapshot no existe o no es válido, retorna None.
        
        MEJORA A: Valida que el snapshot en cache corresponde a los filtros actuales.
        """
        if not getattr(self, "use_snapshot", False):
            return None
        try:
            # ============================================================
            # MEJORA A: SNAPSHOT CACHE VALIDATION
            # ============================================================
            # Obtener clave actual basada en filtros
            snapshot = self.current_snapshot
            if snapshot is None:
                return None
            current_key = self._get_current_snapshot_key(snapshot.metadata.grouping)
            
            # Usar snapshot almacenado SOLO si la clave coincide
            if snapshot is not None and self._current_snapshot_key == current_key:
                # Cache válido: usar snapshot existente
                if snapshot.validate() and snapshot.is_normal_mode():
                    metrics = snapshot.period_a.metrics
                    product_dist = snapshot.period_a.product_distribution
                    return {
                        'transactions': str(metrics.transactions),
                        'total_sales': format_eur(metrics.total_sales),
                        'avg_ticket': format_eur(metrics.avg_ticket),
                        'clients': str(metrics.unique_clients),
                        'products': str(len(product_dist.labels)) if product_dist and product_dist.labels else "0",
                    }
            
            # Si no hay snapshot válido en cache, no regenerar aquí.
            # La responsabilidad de generar snapshot pertenece a _refresh_snapshot().
            return None
        except Exception:
            logger.exception("VentasView: _get_statcard_values_from_snapshot failed"
                             )
            return None

    # === INTEGRACIÓN SNAPSHOT – FASE 2 ===
    def _get_valid_normal_snapshot(self):
        """
        Devuelve un AnalysisSnapshot NORMAL válido si:
        - self.use_snapshot == True
        - self.current_snapshot existe
        - snapshot_key coincide con filtros actuales (MEJORA A)
        - .validate() == True
        - .is_normal_mode() == True
        Si alguna condición falla, retorna None.
        NUNCA crea ni actualiza snapshots aquí.
        """
        if not getattr(self, "use_snapshot", False):
            return None
        
        snapshot = getattr(self, "current_snapshot", None)
        if snapshot is None:
            return None
        
        try:
            # ============================================================
            # MEJORA A: SNAPSHOT CACHE KEY VALIDATION
            # ============================================================
            current_key = self._get_current_snapshot_key(snapshot.metadata.grouping)

            # Validar que la clave coincide
            if self._current_snapshot_key != current_key:
                return None
            
            if not snapshot.validate():
                return None
            if not snapshot.is_normal_mode():
                return None
            return snapshot
        except Exception:
            logger.exception("VentasView: error validando snapshot NORMAL")
            return None

    def _get_valid_period_a_snapshot(self):
        """
        Devuelve un AnalysisSnapshot válido con period_a, SIN importar el modo.
        
        Funciona tanto en NORMAL como en COMPARE mode.
        En ambos modos, period_a contiene los datos del Periodo A
        que se usan para poblar los containers principales
        (summary, charts, evolution).
        
        Validaciones:
        - use_snapshot == True
        - current_snapshot existe
        - snapshot_key coincide con filtros actuales
        - validate() == True
        - period_a existe
        
        Returns: AnalysisSnapshot o None
        """
        if not getattr(self, "use_snapshot", False):
            return None
        
        snapshot = getattr(self, "current_snapshot", None)
        if snapshot is None:
            return None
        
        try:
            current_key = self._get_current_snapshot_key(snapshot.metadata.grouping)

            if self._current_snapshot_key != current_key:
                return None

            if not snapshot.validate():
                return None
            if snapshot.period_a is None:
                return None
            return snapshot
        except Exception:
            logger.exception("VentasView: period_a snapshot validation failed")
            return None

    def _get_valid_compare_snapshot(self, grouping: str | None = None):
        """
        --- INTEGRACIÓN SNAPSHOT FASE 3 (COMPARE) ---
        Devuelve un AnalysisSnapshot COMPARE válido si:
        - self.use_compare_snapshot == True
        - get_sales_snapshot() devuelve snapshot válido
        - snapshot.validate() == True
        - snapshot.is_compare_mode() == True
        - snapshot.comparison is not None
        Si alguna condición falla, retorna None.
        NUNCA crea ni actualiza snapshots aquí.
        
        Args:
            grouping: Agrupación temporal ("day", "week", "month", "quarter", "year")
        """
        if not getattr(self, "use_compare_snapshot", False):
            return None
        
        try:
            if grouping is None:
                grouping = self.compare_controller.grouping if self.compare_controller.is_compare_active() else "day"

            snapshot = self.ventas_controller.get_sales_snapshot(
                grouping=grouping,
                compare_controller=self.compare_controller,
            )

            if snapshot is None:
                return None
            if not snapshot.validate():
                return None
            if not snapshot.is_compare_mode():
                return None
            if snapshot.comparison is None:
                return None
            return snapshot
        except Exception:
            logger.exception(
                "VentasView: error validando snapshot COMPARE"
            )
            return None

    def _refresh_snapshot(self):
        """
        ✅ INVARIANTE CRÍTICO: Mantiene coherencia snapshot ↔ key
        
        Regenera self.current_snapshot + asigna self._current_snapshot_key.
        Garantiza SIEMPRE: if snapshot ≠ None → key ≠ None
        
        Debe ser llamado cuando:
        - Se aplican nuevos filtros
        - Se importa datos y dataset cambia
        - Se limpian filtros (state limpio)
        - Inicialización en build()
        
        ⚠️ IMPORTANTE:
        - NO renderiza (caller responsable de _populate_view_containers)
        - NO modifica controladores (solo asigna state local)
        - Funciones utilizadas son puras (deterministas)
        """
        # 1️⃣ Regenerar snapshot con filtros ACTUALES
        t0 = time.perf_counter()
        snapshot_grouping = "day"
        if self.compare_controller.is_compare_active():
            snapshot_grouping = self.compare_controller.grouping or "day"

        self.current_snapshot = self.ventas_controller.get_sales_snapshot(
            grouping=snapshot_grouping,
            compare_controller=self.compare_controller,
        )
        logger.debug("[PERF] SNAPSHOT: %.4fs", time.perf_counter() - t0)

        # 2️⃣ Asignar key asociada (CRÍTICO para mantener invariancia)
        if self.current_snapshot:
            self._current_snapshot_key = self._get_current_snapshot_key(
                self.current_snapshot.metadata.grouping
            )

    def _build_ui(self):
        """Construye/reconstruye la UI con los colores del tema actual."""
        self._content_column.controls.clear()
        
        # Snapshot is the single source of truth — no fallback path
        snapshot_values = self._get_statcard_values_from_snapshot()
        if snapshot_values is not None:
            stat_transactions = snapshot_values['transactions']
            stat_sales = snapshot_values['total_sales']
            stat_avg_ticket = snapshot_values['avg_ticket']
            stat_clients = snapshot_values['clients']
            stat_products = snapshot_values['products']
        else:
            stat_transactions = "—"
            stat_sales = "—"
            stat_avg_ticket = "—"
            stat_clients = "—"
            stat_products = "—"
        
        # Crear tarjetas de estadísticas (guardar referencias)
        self.stat_card_transactions = create_stat_card(
            label="Total transactions",
            value=stat_transactions,
            icon=ft.Icons.RECEIPT_LONG,
            color=ft.Colors.PURPLE,
        )
        self.stat_card_sales = create_stat_card(
            label="Total sales",
            value=stat_sales,
            icon=ft.Icons.SHOPPING_CART,
            color=ft.Colors.GREEN,
        )
        self.stat_card_avg_ticket = create_stat_card(
            label="Average sale",
            value=stat_avg_ticket,
            icon=ft.Icons.CONFIRMATION_NUMBER,
            color=ft.Colors.TEAL,
        )
        self.stat_card_clients = create_stat_card(
            label="Registered clients",
            value=stat_clients,
            icon=ft.Icons.PEOPLE,
            color=ft.Colors.BLUE,
        )
        self.stat_card_products = create_stat_card(
            label="Products",
            value=stat_products,
            icon=ft.Icons.INVENTORY_2,
            color=ft.Colors.ORANGE,
        )
        
        stat_cards = [
            self.stat_card_transactions,
            self.stat_card_sales,
            self.stat_card_avg_ticket,
            self.stat_card_clients,
            self.stat_card_products,
        ]
        for card in stat_cards:
            card.col = {"xs": 60, "sm": 30, "md": 20, "xl": 12}
        self._stat_cards = ft.ResponsiveRow(stat_cards, columns=60, spacing=15, run_spacing=15)
        
        # Agregar controles a la columna scrolleable
        
        # ===== FILA 1: SOLO PANELES =====
        self._filters_row = ft.Row(
            [
                self.filter_panel,
                self.compare_panel,
            ],
            spacing=20,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        
        # ===== CONTENIDO PRINCIPAL =====
        self._content_column.controls = [
            self._stat_cards,
            ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
            self._filters_row,
            self.action_buttons,
            self.summary_container,
            self.chart_container,
            ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
            self.evolution_container,
            self.compare_charts_container,
            self.output,
        ]

    def update_theme(self):
        """Actualiza el tema de la vista sin recrearla completamente.
        
        ✅ IMPORTANTE: Este método NO llama page.update().
        El caller es responsable de una sola llamada page.update() global (R7).
        """
        # Actualizar tarjetas de estadísticas
        if hasattr(self, 'stat_card_transactions'):
            self.stat_card_transactions.update_theme()
        if hasattr(self, 'stat_card_sales'):
            self.stat_card_sales.update_theme()
        if hasattr(self, 'stat_card_avg_ticket'):
            self.stat_card_avg_ticket.update_theme()
        if hasattr(self, 'stat_card_clients'):
            self.stat_card_clients.update_theme()
        if hasattr(self, 'stat_card_products'):
            self.stat_card_products.update_theme()
        
        # Actualizar color del output
        if hasattr(self, 'output') and self.output:
            self.output.color = get_text_color(self._page.theme_mode)
        
        # Actualizar FilterPanel
        if hasattr(self, 'filter_panel') and hasattr(self.filter_panel, 'update_theme'):
            self.filter_panel.update_theme()

        # Actualizar ActionButtons (actualizar colores)
        if hasattr(self, 'action_buttons') and hasattr(self.action_buttons, 'update_theme'):
            self.action_buttons.update_theme()
        
        # Actualizar contenedores usando función helper (sin pintar fondo del wrapper)
        if hasattr(self, 'summary_container'):
            update_container_theme(self.summary_container, self._page.theme_mode, set_bg=False)
        if hasattr(self, 'chart_container'):
            update_container_theme(self.chart_container, self._page.theme_mode, set_bg=False)
        if hasattr(self, 'evolution_container'):
            update_container_theme(self.evolution_container, self._page.theme_mode, set_bg=False)
        if hasattr(self, 'compare_panel') and hasattr(self.compare_panel, "update_theme"):
            self.compare_panel.update_theme()
        if hasattr(self, 'compare_charts_container') and hasattr(self.compare_charts_container, "update_theme"):
            self.compare_charts_container.update_theme()
        
        # ============================================================
        # MEJORA B: PROPAGAR THEME A COMPONENTES DINÁMICOS
        # ============================================================
        # Actualizar tabla de resumen si existe
        if hasattr(self, '_current_tabla_resumen') and self._current_tabla_resumen is not None and hasattr(self._current_tabla_resumen, 'update_theme'):
            self._current_tabla_resumen.update_theme(self._page.theme_mode)
        
        # Actualizar gráfico circular si existe
        if hasattr(self, '_current_grafico_circular') and self._current_grafico_circular is not None and hasattr(self._current_grafico_circular, 'update_theme'):
            self._current_grafico_circular.update_theme(self._page.theme_mode)
        
        # Actualizar gráfico evolución si existe
        if hasattr(self, '_current_grafico_evolucion') and self._current_grafico_evolucion is not None and hasattr(self._current_grafico_evolucion, 'update_theme'):
            self._current_grafico_evolucion.update_theme(self._page.theme_mode)
        
        # Actualizar gráficos de clientes (Patrón B - mutación pura)
        if hasattr(self, '_current_grafico_top') and self._current_grafico_top is not None and hasattr(self._current_grafico_top, 'update_theme'):
            self._current_grafico_top.update_theme(self._page.theme_mode)
        
        if hasattr(self, '_current_grafico_monto') and self._current_grafico_monto is not None and hasattr(self._current_grafico_monto, 'update_theme'):
            self._current_grafico_monto.update_theme(self._page.theme_mode)
        
        # ✅ R7: NO llamar page.update() aquí — el caller es responsable
    
    def did_mount(self):
        """Sincroniza ComparePanel cuando la vista se monta (self.page ya disponible)."""
        self.compare_panel._sync_from_controller()
        self.compare_panel._update_preset_buttons_state()

    # ============================================================
    #   HELPERS PARA CONSTRUCCIÓN DESDE SNAPSHOT
    # ============================================================
    
    def _build_tabla_resumen_from_snapshot(self, table_data):
        """Construye una tabla de resumen a partir de table_data del snapshot."""
        rows = [(t.product_type, t.total_sales, t.quantity, t.avg_price, t.min_price, t.max_price) for t in table_data]
        return TablaResumen(rows)
    
    def _build_grafico_circular_from_snapshot(self, product_dist):
        """Construye gráfico circular a partir de ProductDistribution del snapshot."""
        segments = [
            PieChartSegmentSnapshot(
                label=label,
                value=value,
                percentage=pct,
                color_index=idx,
            )
            for idx, (label, value, pct) in enumerate(zip(product_dist.labels, product_dist.values, product_dist.percentages))
        ]
        pie_snapshot = PieChartSnapshot(title="Sales distribution", segments=segments)
        return PieChartInteractive(pie_snapshot, theme_mode=self._page.theme_mode)
    
    def _build_top_clients_row_from_snapshot(self, top_clients):
        """Construye o actualiza la fila de gráficos de top clientes desde snapshot."""
        row, self._current_grafico_top, self._current_grafico_monto = build_top_clients_row(
            top_clients=top_clients,
            theme_mode=self._page.theme_mode,
            grafico_top=self._current_grafico_top,
            grafico_monto=self._current_grafico_monto,
            existing_row=self._current_top_clients_row,
        )
        self._current_top_clients_row = row
        return self._current_top_clients_row
    
    def _build_grafico_evolucion_from_snapshot(self, evolution):
        """Construye gráfico de evolución a partir de EvolutionData del snapshot."""
        rows = list(zip(evolution.labels, evolution.values))
        return GraficoEvolucion(rows, on_grouping_change=None, theme_mode=self._page.theme_mode)
    
    # ============================================================
    #   HELPER PARA POBLACIÓN DE CONTENEDORES
    # ============================================================
    
    def _populate_view_containers(self, view_mode: str = "both", show_notification: bool = True):
        """
        Población genérica de contenedores según el modo de vista.
        
        ============================================================
        FIX v2.3.1: Delegación de notificaciones al caller
        ============================================================
        
        IMPORTANTE: Este método NO llama a show_notification().
        El parámetro show_notification se ignora (mantenido por compatibilidad).
        El CALLER es responsable de:
        1. Llamar _populate_view_containers()
        2. Llamar page.update()
        3. LUEGO llamar show_snackbar() / show_no_data()
        
        Esto evita race condition en Flet 0.80.5:
        - page.show_dialog() es async
        - page.update() inmediatamente después causa deadlock parcial
        
        Usa SNAPSHOT path únicamente - el snapshot se valida con _get_valid_period_a_snapshot().
        Funciona tanto en modo NORMAL como COMPARE (usa period_a en ambos).
        Si el snapshot es inválido o hay error, retorna False.
        
        Args:
            view_mode: "summary" (solo tabla) | "both" (tabla + gráficos)
            show_notification: IGNORADO (mantenido por compatibilidad hacia atrás)
        
        Returns: (success: bool)
        """
        snapshot = self._get_valid_period_a_snapshot()
        
        if snapshot is not None:
            try:
                # Update stat card values from the current snapshot
                sv = self._get_statcard_values_from_snapshot()
                if sv is not None:
                    self.stat_card_transactions._value_text.value = sv['transactions']
                    self.stat_card_sales._value_text.value = sv['total_sales']
                    self.stat_card_avg_ticket._value_text.value = sv['avg_ticket']
                    self.stat_card_clients._value_text.value = sv['clients']
                    self.stat_card_products._value_text.value = sv['products']

                t_build = time.perf_counter()
                # --- INTEGRACIÓN SNAPSHOT – FASE 2.1 (TABLA) ---
                table_data = getattr(snapshot.period_a, "table_data", None)
                if table_data is not None:
                    # ============================================================
                    # MEJORA B: GUARDAR REFERENCIA A TABLA DINÁMICA
                    # ============================================================
                    self._current_tabla_resumen = self._build_tabla_resumen_from_snapshot(table_data)
                    self.summary_container.content = self._current_tabla_resumen
                else:
                    self._current_tabla_resumen = None
                    self.summary_container.content = None

                # --- INTEGRACIÓN SNAPSHOT – FASE 2.2 (PRODUCTOS) + FASE 2.3 (TOP CLIENTES) ---
                product_dist = getattr(snapshot.period_a, "product_distribution", None)
                top_clients = getattr(snapshot.period_a, "top_clients", None)
                
                if view_mode == "both":
                    chart_components = []
                    
                    # Agregar donut si hay datos
                    if product_dist is not None:
                        # ============================================================
                        # MEJORA B: GUARDAR REFERENCIA A GRÁFICO CIRCULAR
                        # ============================================================
                        self._current_grafico_circular = self._build_grafico_circular_from_snapshot(product_dist)
                        chart_components.append(self._current_grafico_circular)
                    else:
                        self._current_grafico_circular = None
                    
                    # ============================================================
                    # LÓGICA ESPECIAL: SI SE FILTRA POR CLIENTE, MOSTRAR RESUMEN
                    # ============================================================
                    # Detectar si hay un cliente específico seleccionado
                    selected_client = snapshot.filters.client_name

                    if selected_client:
                        # Cliente específico: mostrar RESUMEN del cliente en lugar de tops
                        if top_clients is not None and len(top_clients) > 0:
                            client_info = top_clients[0]  # Debería haber solo 1 cuando filtras por cliente
                            avg_ticket = snapshot.period_a.metrics.avg_ticket
                            client_summary = build_client_summary_card(
                                client_info=client_info,
                                product_dist=product_dist,
                                avg_ticket=avg_ticket,
                                theme_mode=self._page.theme_mode,
                            )
                            chart_components.append(client_summary)
                        else:
                            # Sin datos para el cliente
                            no_data_msg = ft.Container(
                                padding=12,
                                bgcolor=ft.Colors.SURFACE,
                                border_radius=8,
                                content=ft.Text(
                                    "⚠ No data for this client in this period.",
                                    size=14,
                                    color=get_text_color(self._page.theme_mode),
                                ),
                            )
                            chart_components.append(no_data_msg)
                    elif top_clients is not None:
                        # Sin filtro de cliente: mostrar rankings (Top 5)
                        self._current_top_clients_row = self._build_top_clients_row_from_snapshot(top_clients)

                        if self._current_top_clients_row is not None:
                            chart_components.append(self._current_top_clients_row)
                    else:
                        self._current_top_clients_row = None
                        self._current_grafico_top = None
                        self._current_grafico_monto = None
                    
                    # Si hay al menos un componente, mostrar chart_container
                    if chart_components:
                        _chart_content = ft.Column(
                            chart_components,
                            spacing=20,
                            expand=True,
                        )
                        # ✅ MUTAR propiedades del container existente (mismo patrón que summary_container)
                        # ✅ FASE 2: Eliminar .update() local - renderizado global en page.update()
                        self.chart_container.visible = True
                        self.chart_container.height = 800
                        self.chart_container.content = _chart_content
                    else:
                        self.chart_container.visible = False
                        self.chart_container.height = None
                        self.chart_container.content = None
                else:
                    self.chart_container.visible = False
                    self.chart_container.height = None
                    self.chart_container.content = None

                # --- INTEGRACIÓN SNAPSHOT – FASE 2.4 (EVOLUCIÓN) ---
                evolution = getattr(snapshot.period_a, "evolution", None)
                if evolution is not None:
                    # ============================================================
                    # MEJORA B: GUARDAR REFERENCIA A GRÁFICO EVOLUCIÓN
                    # ============================================================
                    self._current_grafico_evolucion = self._build_grafico_evolucion_from_snapshot(evolution)
                    self._evolution_switcher.content = self._current_grafico_evolucion
                else:
                    self._current_grafico_evolucion = None
                    self._evolution_switcher.content = ft.Container()  # vacío; AnimatedSwitcher no acepta None

                compare_visible = (
                    view_mode == "both"
                    and self.current_snapshot is not None
                    and self.current_snapshot.is_compare_mode()
                    and self.compare_controller.is_compare_active()
                )
                self.compare_charts_container.visible = compare_visible
                if compare_visible:
                    self.compare_charts_container.update_from_snapshot(self.current_snapshot)
                else:
                    self.compare_charts_container.visible = False

                logger.debug("[PERF] BUILD COMPONENTS: %.4fs", time.perf_counter() - t_build)

                # ============================================================
                # Render delegado al caller via page.update() único
                # ============================================================
                # FIX v2.3.1: Notificaciones delegadas al caller
                # ============================================================
                # El CALLER es responsable de:
                # 1. Llamar _populate_view_containers()
                # 2. Llamar page.update() para completar renders
                # 3. LUEGO llamar show_snackbar() si es necesario
                # 
                # Esto evita race condition entre page.show_dialog() (async)
                # y page.update() en Flet 0.80.5
                
                # 🔄 Responsabilidad de page.update() delegada al caller
                return True
            except Exception:
                logger.exception(
                    "VentasView: error poblando UI desde snapshot"
                )
                return False
        else:
            # Snapshot None = sin datos en el período seleccionado
            # Clear stat cards
            for _card in [
                getattr(self, "stat_card_transactions", None),
                getattr(self, "stat_card_sales", None),
                getattr(self, "stat_card_avg_ticket", None),
                getattr(self, "stat_card_clients", None),
                getattr(self, "stat_card_products", None),
            ]:
                if _card is not None:
                    _card._value_text.value = "—"
            # Limpiar UI
            self.summary_container.content = None
            self.chart_container.visible = False
            self.chart_container.height = None
            self.chart_container.content = None
            self._evolution_switcher.content = ft.Container()  # vacío; AnimatedSwitcher no acepta None

            # ============================================================
            # FIX v2.3.1: Notificaciones delegadas al caller
            # ============================================================
            # El CALLER es responsable de mostrar show_no_data() DESPUÉS
            # de llamar page.update() en _on_filter_applied() u otros
            
            # 🔄 Responsabilidad de page.update() delegada al caller
            return False
    
    # ============================================================
    #   CALLBACKS
    # ============================================================
    def _on_compare_requested(self):
        cmp = self.compare_controller
        fc = self.ventas_controller.filter_controller

        # ============================================================
        # 🔥 RESTAURAR SINGLE SOURCE OF TRUTH (Compare → Filter)
        fc.set_start_date(cmp.a_start)
        fc.set_end_date(cmp.a_end)
        fc.set_client(cmp.client_a)
        fc.set_product(cmp.product_a)

        # 1️⃣ Validar Periodo A
        if not fc.start_date or not fc.end_date:
            self.notifications.show_snackbar(
                "Apply a date filter first (period A).",
                severity="warning",
            )
            return

        # 2️⃣ Validar Periodo B
        if not cmp.b_start or not cmp.b_end:
            self.notifications.show_snackbar(
                "Fill in period B to compare.",
                severity="warning",
            )
            return

        # Activar modo compare
        self.compare_controller.activate_compare()

        # Regenerar snapshot con datos actuales
        self._refresh_snapshot()

        # Validar snapshot compare (ya generado por _refresh_snapshot)
        snapshot = self.current_snapshot
        if (
            snapshot is None
            or not snapshot.validate()
            or not snapshot.is_compare_mode()
            or snapshot.comparison is None
        ):
            self.notifications.show_snackbar(
                "Could not load the comparison data.",
                severity="error",
            )
            return

        # Actualizar containers principales (tabla, gráficos, evolución)
        self._is_rebuilding = True
        try:
            self._charts_visible = True
            self._populate_view_containers(view_mode="both", show_notification=False)

            # Sincronizar paneles primero (no generan dirty marks en gráficos)
            self.compare_panel.update_from_snapshot(snapshot)
            self.filter_panel.refresh_from_filter_controller()
            self.compare_panel.refresh()

            # Actualizar gráficos comparativos al final, cuando el árbol ya está
            # completamente configurado — evita invalidación parcial del subtree
            self.compare_charts_container.update_from_snapshot(snapshot)
        finally:
            self._is_rebuilding = False
            self.page.update()

        self.notifications.show_compare_applied(
            start_a=fc.start_date,
            end_a=fc.end_date,
            client_a=cmp.client_a,
            product_a=cmp.product_a,
            start_b=cmp.b_start,
            end_b=cmp.b_end,
            client_b=cmp.client_b,
            product_b=cmp.product_b,
            auto_update=False,
        )

    


    def _on_filter_applied(self, _):
        if self._is_rebuilding:
            self._pending_filter_call = True
            return

        fc = self.ventas_controller.filter_controller

        # 🔥 Solo sincronizar CompareController
        self.compare_controller.set_period_a(fc.start_date, fc.end_date)
        self.compare_controller.set_client_a(fc.client_name)
        self.compare_controller.set_product_a(fc.product_type)

        # 🔥 NO volver a setear en fc
        # 🔥 NO usar filter_params
        # 🔥 NO tocar dropdowns aquí

        # Regenerar snapshot (mantiene invariancia snapshot ↔ key)
        self._refresh_snapshot()

        self._is_rebuilding = True
        success = False
        try:
            self._charts_visible = True
            success = self._populate_view_containers(view_mode="both", show_notification=False)

            # Sincronizar paneles ANTES del page.update()
            # ✅ FIX: refresh_from_filter_controller() reinicializa dropdowns
            # Esto evita que los dropdowns queden desincronizados después de aplicar filtros
            self.filter_panel.refresh_from_filter_controller()
            self.compare_panel.refresh()
        finally:
            self._is_rebuilding = False
            # ✅ R7: única page.update() — en finally para garantizar ejecución
            self.page.update()

        # Si hubo una llamada encolada durante este render, ejecutarla ahora
        if self._pending_filter_call:
            self._pending_filter_call = False
            self._on_filter_applied(None)
            return

        # ============================================================
        # FIX v2.3.1: Notificaciones DESPUÉS de page.update()
        # ============================================================
        # En Flet 0.82, page.show_dialog() es async.
        # Llamarlo inmediatamente DESPUÉS de page.update() causa race condition.
        # Solución: page.update() primero (render thread completa),
        # LUEGO page.show_dialog() (es seguro ahora).
        
        if success:
            # ✅ Verificar si el snapshot tiene datos reales
            snapshot = self._get_valid_period_a_snapshot()
            if snapshot and snapshot.period_a and snapshot.period_a.metrics:
                has_data = snapshot.period_a.metrics.transactions > 0
            else:
                has_data = False
            
            if has_data:
                # Mostrar notificación de filtro aplicado (hay datos)
                self.notifications.show_filter_applied(
                    snapshot.filters.date_start,
                    snapshot.filters.date_end,
                    snapshot.filters.client_name,
                    snapshot.filters.product_type,
                )
            else:
                # Mostrar notificación de sin datos
                self.notifications.show_no_data()


    def _on_compare_grouping_change(self, grouping: str):
        """
        Handle grouping dropdown change in ComparePanel.

        Uses local regrouping from cached daily raw data.
        """

        self.compare_controller.set_grouping(grouping)

        # Try local regrouping first (no SQL queries)
        success = self.compare_charts_container.reagroup_local(grouping)

        if not success:
            # Fallback a full re-query
            self._on_compare_requested()
            return

        # 🔄 Actualizar solo el subtree afectado (NO toda la página)
        if hasattr(self.compare_charts_container, "update"):
            self._page.update()

                

    def _on_compare_cleared(self):
        # 1️⃣ Limpieza REAL del estado de comparación
        self.compare_controller.clear()

        # 2️⃣ Invalidar cache + regenerar snapshot limpio
        self.ventas_controller.invalidate_snapshot_cache()
        self._refresh_snapshot()  # mantiene invariancia snapshot ↔ key

        # 3️⃣ Reset visual del modo compare
        self.compare_panel.reset_visual_state()
        self.compare_charts_container.visible = False

        # 4️⃣ Sincronizar estado local de la vista
        self._charts_visible = False

        # 5️⃣ Repoblar vista base (misma semántica que filter_cleared)
        self._populate_view_containers(
            view_mode="summary",
            show_notification=False
        )
        # Único page.update() cubre todo el árbol (incluye compare_panel y compare_charts_container)
        self._page.update()

        # 7️⃣ Feedback al usuario
        self.notifications.show_snackbar(
            "Comparison cleared",
            severity="info"
        )

    
    def _on_filter_cleared(self):
        self.compare_controller.clear()

        self.ventas_controller.invalidate_snapshot_cache()
        self._refresh_snapshot()

        # 2️⃣ Limpiar UI del ComparePanel
        self.compare_panel.reset_visual_state()

        self.compare_charts_container.visible = False

        # 3️⃣ Volver a vista de resumen
        self._charts_visible = False
        self._populate_view_containers(view_mode="summary", show_notification=False)

        # 4️⃣ Render global ANTES de la notificación
        self.page.update()

        # 5️⃣ Notificación
        self.notifications.show_filter_cleared()       
    
    def _on_import_button_click(self, e):
        """Handler para el botón de importar (usa run_task para async)."""
        logger.info("[VentasView] Import button clicked")
        self._page.run_task(self._pick_and_import_file)
    
    async def _pick_and_import_file(self):
        """Abre FilePicker e importa el archivo detectando el tipo automáticamente."""
        await run_import_flow(
            page=self._page,
            controller=self.file_import_controller,
            notifications=self.notifications,
            set_detected_prefix=lambda prefix: setattr(self, "_detected_prefix", prefix),
        )
    
    def _on_import_start(self):
        """Callback cuando inicia la importación."""
        self.notifications.show_importing_file()
    
    def _on_import_success(self, message: str):
        """Callback cuando la importación es exitosa."""
        # ============================================================
        # 1️⃣ INVALIDAR CACHE COMPLETO (dataset cambió)
        # ============================================================
        self.ventas_controller.invalidate_snapshot_cache()

        # ============================================================
        # 2️⃣ REGENERAR SNAPSHOT (mantiene invariancia snapshot ↔ key)
        # ============================================================
        self._refresh_snapshot()

        # ============================================================
        # 3️⃣ REPINTAR UI
        # ============================================================
        # show_both() ya llama self._page.update() internamente (R7)
        self.show_both()

        # ============================================================
        # 5️⃣ NOTIFICACIÓN
        # ============================================================
        if self._detected_prefix:
            message = f"{self._detected_prefix} detected \u2192 {message}"
            self._detected_prefix = None
        self.notifications.show_import_success(message)

    
    def _on_import_error(self, message: str):
        """Callback cuando hay error en la importación."""
        self.notifications.show_import_error(message)
    
    def show_summary(self, e=None):
        """Muestra solo el resumen (tabla + evolución, sin gráficos)."""
        self._charts_visible = False
        self._populate_view_containers(view_mode="summary", show_notification=False)

        # ✅ R7: Una sola llamada a page.update() por acción usuario
        if self._page is not None:
            self._page.update()

        
    
    def show_both(self, e=None):
        """Muestra resumen + gráficos + evolución."""
        self._charts_visible = True
        self._populate_view_containers(view_mode="both", show_notification=False)

        # ✅ R7: Una sola llamada a page.update() por acción usuario
        if self._page is not None:
            self._page.update()

    # ============================================================
    #   EXPORT USANDO SNAPSHOT (Integración progresiva - alternativa)
    # ============================================================
    
    def _on_export_button_click(self, e):
        """Handler para el botón de exportar (usa run_task para async)."""
        self._page.run_task(self._export_html_report_using_snapshot)
    
    async def _export_html_report_using_snapshot(self, e=None):
        """
        Exporta usando AnalysisSnapshot.
        Este es el ÚNICO flujo de export activo.

        Usa self.current_snapshot (snapshot cacheado) para garantizar que
        el export sea 100% consistente con lo que se muestra en UI.
        """
        try:
            # Usar snapshot actual en cache (debe estar sincronizado con UI)
            snapshot = self.current_snapshot

            if not snapshot or not snapshot.validate():
                show_notification(self._page, "There is no data to export. Reload the view.", "error")
                return
            
            # Determinar nombre por defecto
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            mode_suffix = "Compare" if snapshot.is_compare_mode() else "Normal"
            default_name = f"Sales_Report_{mode_suffix}_{timestamp}.html"
            
            # Abrir diálogo de guardar
            filepath = await save_html_file(self._page, default_name)
            if not filepath:
                return  # Usuario canceló
            
            # Generar informe usando snapshot
            success, message, _ = generate_html_report_from_snapshot(
                snapshot=snapshot,
                filename=filepath
            )
            
            if success:
                import os
                show_notification(self._page, f"Report saved: {os.path.basename(filepath)}", "success")
                open_file_cross_platform(filepath)
            else:
                show_notification(self._page, message, "error")
        
        except Exception as e:
            logger.exception("VentasView: error exportando HTML desde snapshot")
            show_notification(
                self._page,
                f"Export failed: {str(e)}",
                "error",
            )
