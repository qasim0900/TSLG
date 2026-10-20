"""
Vista de Leads (Tipo A - vista simple).

Carga datos reales desde la BD. Basada en Leads_view_demo.py.
Construye toda la UI en __init__ (sin did_mount).
Auto-update de Flet maneja el render.

Componentes externos:
  components/grafico_funnel_leads.py   — embudo de conversión
  components/leads_kpi_card.py         — fila de KPI cards con hover
  components/grafico_leads_source.py   — gráfico de barras por fuente
  components/tabla_leads.py            — tabla de leads recientes

Analytics:
  analysis/leads_analysis.get_funnel_stats()      — métricas del funnel
  analysis/leads_analysis.group_leads_by_source() — agrupación por fuente
"""
import os
import flet as ft
import logging

from views.scrollable_view import ScrollableView
from controllers.leads_controller import LeadsController
from controllers.leads_filter_controller import (
    ALL_LEADS_DESCRIPTION,
    ALL_SOURCES,
    ALL_STAGES,
    ALL_TIME,
    _DATE_RANGE_OPTIONS,
    _STAGE_STATUS_MAP,
    filter_leads,
)
from theme import get_text_color, get_subtitle_color, date_picker_chip, clear_filter_button_style

from components.grafico_funnel_leads import build_funnel_chart, build_funnel_insight
from components.leads_kpi_card import build_kpi_row
from components.grafico_leads_source import build_source_chart
from components.tabla_leads import build_leads_table, _SOURCE_LABELS
from components.conversion_ranking import build_conversion_ranking
from components.upcoming_meetings_panel import build_upcoming_meetings_panel
from components.marketing_summary_section import (
    build_marketing_kpi_row,
    build_revenue_vs_spend_chart,
    build_marketing_source_table,
)
from components.marketing_spend_editor import MarketingSpendEditor
from utils.notifications import show_notification
from utils.file_dialogs import save_html_file
from utils.file_opener import open_file_cross_platform
from reports.report_leads_html import generate_leads_html_report

logger = logging.getLogger(__name__)

_STAGE_OPTIONS = [ALL_STAGES, *_STAGE_STATUS_MAP]


class LeadsView(ScrollableView):
    """Vista de Leads — Tipo A (simple). Sin did_mount()."""

    def __init__(self, page):
        super().__init__(expand=True)
        self._page = page
        self._header = None
        self._subtitle = None
        self._load_data()

    def _attach_date_pickers(self):
        if not self._page:
            return
        if self._specific_start_picker not in self._page.overlay:
            self._page.overlay.append(self._specific_start_picker)
        if self._specific_end_picker not in self._page.overlay:
            self._page.overlay.append(self._specific_end_picker)

    @staticmethod
    def _format_picker_date(value) -> str | None:
        if not value:
            return None
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]

    def _build_specific_date_filter_section(self) -> ft.Column:
        self._specific_start_date = None
        self._specific_end_date = None

        self._specific_start_picker = ft.DatePicker(
            on_change=lambda e: self._on_specific_date_change("start", e.control.value),
            on_dismiss=lambda e: self._on_specific_picker_dismiss("start"),
        )
        self._specific_end_picker = ft.DatePicker(
            on_change=lambda e: self._on_specific_date_change("end", e.control.value),
            on_dismiss=lambda e: self._on_specific_picker_dismiss("end"),
        )
        self._attach_date_pickers()

        self._specific_start_chip = date_picker_chip(
            label="From",
            value=None,
            is_start=True,
            page=self._page,
            on_click=lambda _: self._open_specific_picker("start"),
        )
        self._specific_end_chip = date_picker_chip(
            label="To",
            value=None,
            is_start=False,
            page=self._page,
            on_click=lambda _: self._open_specific_picker("end"),
        )

        self._specific_start_icon = self._specific_start_chip.content.controls[0]
        self._specific_start_text = self._specific_start_chip.content.controls[1]
        self._specific_end_icon = self._specific_end_chip.content.controls[0]
        self._specific_end_text = self._specific_end_chip.content.controls[1]

        self._clear_specific_dates_btn = ft.TextButton(
            "Clear dates",
            icon=ft.Icons.CLEAR,
            on_click=self._clear_specific_dates,
            style=clear_filter_button_style(),
        )
        self._apply_specific_dates_btn = ft.Button(
            "Apply period",
            icon=ft.Icons.FILTER_ALT,
            on_click=self._apply_specific_dates,
            height=36,
        )

        return ft.Column(
            controls=[
                ft.Text(
                    "Custom range",
                    size=12,
                    weight=ft.FontWeight.W_600,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Row(
                    controls=[
                        self._specific_start_chip,
                        self._specific_end_chip,
                        self._apply_specific_dates_btn,
                        self._clear_specific_dates_btn,
                    ],
                    spacing=10,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=8,
        )

    def _open_specific_picker(self, which: str):
        if not self._page:
            return
        picker = self._specific_start_picker if which == "start" else self._specific_end_picker
        if picker.open:
            picker.open = False
            self._page.update()
        picker.open = True
        self._page.update()

    def _on_specific_picker_dismiss(self, which: str):
        picker = self._specific_start_picker if which == "start" else self._specific_end_picker
        picker.open = False

    def _on_specific_date_change(self, which: str, value):
        picker = self._specific_start_picker if which == "start" else self._specific_end_picker
        picker.open = False

        iso_value = self._format_picker_date(value)
        if which == "start":
            self._specific_start_date = iso_value
            self._specific_start_text.value = f"From: {iso_value or '–'}"
        else:
            self._specific_end_date = iso_value
            self._specific_end_text.value = f"To: {iso_value or '–'}"

        if self._page:
            self._page.update()

    def _apply_specific_dates(self, e=None):
        # Validar coherencia del rango antes de aplicar.
        if self._specific_start_date and self._specific_end_date:
            if self._specific_start_date > self._specific_end_date:
                show_notification(
                    self._page,
                    "The 'From' date cannot be after the 'To' date.",
                    "error",
                )
                return
        # Rango específico desactiva preset rápido para evitar estados ambiguos.
        self._date_dropdown.value = ALL_TIME
        self._on_filter_changed(None)
        desc = self._get_filters_description()
        show_notification(self._page, f"Period applied: {desc}", "success")

    def _clear_specific_dates(self, e=None):
        self._specific_start_date = None
        self._specific_end_date = None
        self._specific_start_picker.value = None
        self._specific_end_picker.value = None
        self._specific_start_text.value = "From: –"
        self._specific_end_text.value = "To: –"
        self._on_filter_changed(None)

    def _update_specific_date_chip_colors(self):
        is_dark = self._page.theme_mode == ft.ThemeMode.DARK
        start_bg = ft.Colors.GREEN_800 if is_dark else ft.Colors.GREEN_200
        end_bg = ft.Colors.RED_700 if is_dark else ft.Colors.RED_200
        text_color = ft.Colors.WHITE if is_dark else ft.Colors.BLACK

        self._specific_start_chip.bgcolor = start_bg
        self._specific_end_chip.bgcolor = end_bg
        self._specific_start_icon.color = text_color
        self._specific_start_text.color = text_color
        self._specific_end_icon.color = text_color
        self._specific_end_text.color = text_color

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self):
        try:
            leads = LeadsController.get_leads_enriched()
            # Precarga UNA sola vez desde BD — usada en todos los filtros in-memory
            self._spend_by_source = LeadsController.get_spend_by_source()
            self._revenue_by_client = LeadsController.get_revenue_by_client()
            self._build_ui(leads)
        except Exception as e:
            logger.exception("Could not load lead data: %s", e)
            self._build_error_ui()

    def _get_active_leads(self) -> list:
        return self._filtered_leads if hasattr(self, "_filtered_leads") else []

    # ------------------------------------------------------------------
    # Main layout
    # ------------------------------------------------------------------

    @staticmethod
    def _kpi_grid(kpi_row) -> ft.Column:
        """Split the single KPI row into 3 grouped rows — layout only."""
        c = kpi_row.controls  # 9 wrapper containers, order as in cards_data
        # Current order: 0=Leads, 1=Reuniones, 2=Clientes,
        #                3=Lead→Meeting, 4=Meeting→Client, 5=Sin reunión,
        #                6=Reuniones sin cerrar, 7=Sin acción, 8=Tiempo a reunión
        return ft.Column(
            [
                ft.Row([c[0], c[1], c[2]], spacing=12),  # Core funnel
                ft.Row([c[3], c[4], c[8]], spacing=12),  # Performance (% rates + time)
                ft.Row([c[5], c[6], c[7]], spacing=12),  # Drop-off
            ],
            spacing=12,
        )

    def _build_ui(self, leads):
        stats = LeadsController.get_funnel_stats(leads)
        sources_data = LeadsController.group_leads_by_source(leads)

        # Marketing metrics — reactivo a leads (usa datos precargados desde BD)
        marketing_data = LeadsController.get_marketing_data(
            leads=leads,
            spend_by_source=self._spend_by_source,
            revenue_by_client=self._revenue_by_client,
        )
        marketing_summary = marketing_data["summary"]
        marketing_metrics = marketing_data["metrics"]

        self._marketing_summary = marketing_summary
        self._marketing_metrics = marketing_metrics

        # Leads with NO action: status has not advanced beyond "new"
        inactive_count = len([
            ld for ld in leads
            if ld.get("status") == "new"
        ])

        # Keep full leads list for client-side filtering
        self._all_leads = leads
        self._filtered_leads = leads
        self._funnel_stats = stats
        self._sources_data = sources_data

        _title_color = get_text_color(self._page.theme_mode)

        self._header = ft.Text(
            "Leads",
            size=32,
            weight=ft.FontWeight.W_700,
            color=get_text_color(self._page.theme_mode),
        )
        self._subtitle = ft.Text(
            "Track and analyze marketing leads",
            size=16,
            color=get_subtitle_color(self._page.theme_mode),
        )

        _card_shadow = ft.BoxShadow(
            color=ft.Colors.with_opacity(0.06, ft.Colors.BLACK),
            blur_radius=16,
            offset=ft.Offset(0, 4),
        )

        # --- Marketing Performance section (refs para actualización reactiva) ---
        self._marketing_chart_container = ft.Container(
            content=build_revenue_vs_spend_chart(marketing_metrics, self._page.theme_mode),
        )
        _marketing_empty_kpi = ft.Container(
            content=ft.Text(
                "No marketing data yet (import your ad spend)",
                color=ft.Colors.ON_SURFACE_VARIANT,
                size=13,
                italic=True,
            ),
            padding=16,
        )
        self._marketing_kpi_container = ft.Container(
            content=(
                build_marketing_kpi_row(marketing_summary)
                if marketing_summary
                else _marketing_empty_kpi
            )
        )
        self._marketing_insight_container = ft.Container(
            content=self._build_marketing_best_channel(marketing_metrics)
        )
        self._marketing_table_container = ft.Container(
            content=(
                ft.Row(
                    controls=[build_marketing_source_table(marketing_metrics)],
                    scroll=ft.ScrollMode.AUTO,
                )
                if marketing_metrics
                else ft.Container()
            )
        )
        self._marketing_context_label = ft.Text(
            "ALL LEADS",
            size=9,
            weight=ft.FontWeight.W_700,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )

        self._source_chart_inner = ft.Container(
            content=build_source_chart(sources_data, self._page.theme_mode),
            expand=2,
            alignment=ft.Alignment(0, 1),
            padding=ft.Padding.only(top=16),
        )
        self._conversion_ranking_inner = ft.Container(
            content=build_conversion_ranking(sources_data),
            expand=1,
        )

        marketing_card = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(
                                "Marketing performance",
                                size=18,
                                weight=ft.FontWeight.W_600,
                            ),
                            self._marketing_context_label,
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self._marketing_kpi_container,
                    self._marketing_insight_container,
                    ft.Row(
                        [
                            self._source_chart_inner,
                            self._conversion_ranking_inner,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        spacing=20,
                    ),
                    ft.Text("Revenue vs. spend by source", size=14, weight=ft.FontWeight.W_600),
                    self._marketing_chart_container,
                    ft.Text("Details by source", size=14, weight=ft.FontWeight.W_600),
                    self._marketing_table_container,
                ],
                spacing=20,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            border_radius=20,
            padding=24,
            shadow=_card_shadow,
        )

        # --- Filter bar controls ---
        unique_sources = sorted({ld.get("source", "") for ld in leads if ld.get("source")})
        source_options = [ft.dropdown.Option(ALL_SOURCES, ALL_SOURCES)] + [
            ft.dropdown.Option(s, _SOURCE_LABELS.get(s, s)) for s in unique_sources
        ]

        self._search_field = ft.TextField(
            label="Search leads",
            prefix_icon=ft.Icons.SEARCH,
            height=44,
            text_size=13,
            expand=True,
            on_change=self._on_filter_changed,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border=ft.InputBorder.UNDERLINE,
            focused_border_color=ft.Colors.PRIMARY,
        )
        self._source_dropdown = ft.Dropdown(
            label="Source",
            options=source_options,
            value=ALL_SOURCES,
            height=44,
            text_size=13,
            width=160,
            on_select=self._on_filter_changed,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border=ft.InputBorder.UNDERLINE,
            focused_border_color=ft.Colors.PRIMARY,
        )
        self._stage_dropdown = ft.Dropdown(
            label="Stage",
            options=[ft.dropdown.Option(s) for s in _STAGE_OPTIONS],
            value=ALL_STAGES,
            height=44,
            text_size=13,
            width=140,
            on_select=self._on_filter_changed,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border=ft.InputBorder.UNDERLINE,
            focused_border_color=ft.Colors.PRIMARY,
        )
        self._date_dropdown = ft.Dropdown(
            label="Quick range",
            options=[ft.dropdown.Option(label) for label, _ in _DATE_RANGE_OPTIONS],
            value=ALL_TIME,
            height=44,
            text_size=13,
            width=130,
            on_select=self._on_filter_changed,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border=ft.InputBorder.UNDERLINE,
            focused_border_color=ft.Colors.PRIMARY,
        )

        filter_bar = ft.Row(
            [
                self._search_field,
                self._source_dropdown,
                self._stage_dropdown,
                self._date_dropdown,
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        specific_date_filters = self._build_specific_date_filter_section()

        self._global_filters_title = ft.Text(
            "Filters",
            size=18,
            weight=ft.FontWeight.W_600,
            color=_title_color,
        )
        self._global_filters_card = ft.Container(
            content=ft.Column(
                [
                    self._global_filters_title,
                    filter_bar,
                    specific_date_filters,
                ],
                spacing=14,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border_radius=20,
            padding=24,
            shadow=_card_shadow,
        )

        # --- Table inside scrollable container ---
        self._table_container = ft.Column(
            [build_leads_table(self._all_leads, self._page.theme_mode)],
            scroll=ft.ScrollMode.AUTO,
        )

        self._leads_section_title = ft.Text(
            "Recent leads",
            size=18,
            weight=ft.FontWeight.W_600,
            color=_title_color,
        )
        self._leads_card = ft.Container(
            content=ft.Column(
                [
                    self._leads_section_title,
                    self._table_container,
                ],
                spacing=16,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border_radius=20,
            padding=24,
            shadow=_card_shadow,
        )

        _export_btn = ft.Button(
            "Export HTML",
            icon=ft.Icons.FILE_DOWNLOAD_OUTLINED,
            on_click=lambda _: self._page.run_task(self._export_leads_html),
        )

        self._funnel_chart_container = ft.Container(content=build_funnel_chart(stats))
        self._kpi_container = ft.Container(
            content=self._kpi_grid(build_kpi_row(stats, inactive_count))
        )
        self._insight_container = ft.Container(content=build_funnel_insight(stats))

        # --- Funnel Performance card ---
        funnel_card = ft.Container(
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            border_radius=20,
            padding=24,
            shadow=_card_shadow,
            content=ft.Column(
                spacing=20,
                controls=[
                    ft.Text("Funnel performance", size=18, weight=ft.FontWeight.W_600),
                    ft.Row(
                        [
                            ft.Container(
                                content=self._funnel_chart_container,
                                expand=5,
                            ),
                            ft.Column(
                                [
                                    self._kpi_container,
                                    self._insight_container,
                                ],
                                spacing=16,
                                expand=7,
                            ),
                        ],
                        spacing=32,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ],
            ),
        )

        # --- Leads Management section ---
        leads_section = ft.Column(
            spacing=16,
            controls=[
                ft.Text("Leads management", size=18, weight=ft.FontWeight.W_600),
                ft.Row(
                    spacing=20,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Container(
                            content=self._leads_card,
                            expand=3,
                        ),
                        ft.Container(
                            content=self._build_analytics_panel_wrapper(self._all_leads),
                            width=300,
                        ),
                    ],
                ),
            ],
        )

        # --- Marketing Spend Editor (CRUD manual de inversión) ---
        self._spend_editor = MarketingSpendEditor(
            page=self._page,
            on_data_changed=self._on_marketing_spend_changed,
        )

        _spend_editor_card = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Manage marketing spend",
                        size=18,
                        weight=ft.FontWeight.W_600,
                    ),
                    self._spend_editor,
                ],
                spacing=12,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER,
            border_radius=20,
            padding=24,
            shadow=_card_shadow,
        )

        self.set_controls([
            ft.Row(
                [
                    ft.Column([self._header, self._subtitle], spacing=4, expand=True),
                    _export_btn,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Divider(),
            self._global_filters_card,
            funnel_card,
            marketing_card,
            _spend_editor_card,
            leads_section,
        ])

    # ------------------------------------------------------------------
    # Marketing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_marketing_best_channel(metrics: list) -> ft.Control:
        """Muestra el canal con mayor ROI positivo, si existe."""
        candidates = [m for m in metrics if m.get("roi", 0) > 0]
        if not candidates:
            return ft.Container()
        best = max(candidates, key=lambda x: x["roi"])
        from components.marketing_summary_section import _SOURCE_LABELS as _MKT_LABELS
        label = _MKT_LABELS.get(best["source"], best["source"])
        roi_pct = best["roi"] * 100
        return ft.Row(
            [
                ft.Icon(ft.Icons.STAR_ROUNDED, size=14, color=ft.Colors.AMBER_400),
                ft.Text(
                    f"Best channel: {label} \u00b7 ROI {roi_pct:.1f}%",
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ],
            spacing=6,
        )

    def _get_marketing_context(self) -> str:
        """Etiqueta de contexto para la tarjeta de marketing."""
        desc = self._get_filters_description()
        if desc == ALL_LEADS_DESCRIPTION:
            return "ALL LEADS"
        return f"FILTERED: {desc.upper()}"

    # ------------------------------------------------------------------
    # Analytics side panel — delegado a componente extraído
    # ------------------------------------------------------------------

    def _build_analytics_panel_wrapper(self, all_leads: list) -> ft.Container:
        """Wrapper que delega a build_upcoming_meetings_panel y guarda refs."""
        self._analytics_container = build_upcoming_meetings_panel(
            all_leads, self._page.theme_mode
        )
        self._analytics_title_texts = getattr(
            self._analytics_container, '_analytics_title_texts', []
        )
        return self._analytics_container

    # ------------------------------------------------------------------
    # Filter logic — delegado a controllers/leads_filter_controller.py
    # ------------------------------------------------------------------

    def _on_filter_changed(self, e):
        """Refilter leads list and rebuild the table in-place."""
        if e and getattr(e, "control", None) is self._date_dropdown and self._date_dropdown.value != ALL_TIME:
            self._specific_start_date = None
            self._specific_end_date = None
            self._specific_start_picker.value = None
            self._specific_end_picker.value = None
            self._specific_start_text.value = "From: –"
            self._specific_end_text.value = "To: –"

        filtered = filter_leads(
            all_leads=self._all_leads,
            source=self._source_dropdown.value,
            stage=self._stage_dropdown.value,
            date_label=self._date_dropdown.value,
            start_date=self._specific_start_date,
            end_date=self._specific_end_date,
            search_term=self._search_field.value,
        )

        self._filtered_leads = filtered
        self._funnel_stats = LeadsController.get_funnel_stats(filtered)
        self._sources_data = LeadsController.group_leads_by_source(filtered)
        inactive_count = len([ld for ld in filtered if ld.get("status") == "new"])

        # Marketing reactivo
        marketing_data = LeadsController.get_marketing_data(
            leads=filtered,
            spend_by_source=self._spend_by_source,
            revenue_by_client=self._revenue_by_client,
        )
        self._marketing_summary = marketing_data["summary"]
        self._marketing_metrics = marketing_data["metrics"]

        self._table_container.controls = [build_leads_table(filtered, self._page.theme_mode)]
        self._funnel_chart_container.content = build_funnel_chart(self._funnel_stats)
        self._kpi_container.content = self._kpi_grid(build_kpi_row(self._funnel_stats, inactive_count))
        self._insight_container.content = build_funnel_insight(self._funnel_stats)
        self._source_chart_inner.content = build_source_chart(self._sources_data, self._page.theme_mode)
        self._conversion_ranking_inner.content = build_conversion_ranking(self._sources_data)
        # Marketing UI
        self._marketing_context_label.value = self._get_marketing_context()
        self._marketing_kpi_container.content = (
            build_marketing_kpi_row(self._marketing_summary)
            if self._marketing_summary
            else ft.Text("No marketing data", color=ft.Colors.ON_SURFACE_VARIANT, size=13)
        )
        self._marketing_insight_container.content = self._build_marketing_best_channel(self._marketing_metrics)
        self._marketing_chart_container.content = build_revenue_vs_spend_chart(
            self._marketing_metrics, self._page.theme_mode
        )
        self._marketing_table_container.content = (
            ft.Row(
                controls=[build_marketing_source_table(self._marketing_metrics)],
                scroll=ft.ScrollMode.AUTO,
            )
            if self._marketing_metrics
            else ft.Container()
        )

    # ------------------------------------------------------------------
    # Marketing spend changed — refresh KPIs after CRUD
    # ------------------------------------------------------------------

    def _on_marketing_spend_changed(self):
        """Recarga spend desde BD y recalcula métricas de marketing."""
        self._spend_by_source = LeadsController.get_spend_by_source()

        filtered = self._filtered_leads if hasattr(self, "_filtered_leads") else self._all_leads
        marketing_data = LeadsController.get_marketing_data(
            leads=filtered,
            spend_by_source=self._spend_by_source,
            revenue_by_client=self._revenue_by_client,
        )
        self._marketing_summary = marketing_data["summary"]
        self._marketing_metrics = marketing_data["metrics"]

        # Mutar UI de marketing
        self._marketing_context_label.value = self._get_marketing_context()
        self._marketing_kpi_container.content = (
            build_marketing_kpi_row(self._marketing_summary)
            if self._marketing_summary
            else ft.Text("No marketing data", color=ft.Colors.ON_SURFACE_VARIANT, size=13)
        )
        self._marketing_insight_container.content = self._build_marketing_best_channel(self._marketing_metrics)
        self._marketing_chart_container.content = build_revenue_vs_spend_chart(
            self._marketing_metrics, self._page.theme_mode
        )
        self._marketing_table_container.content = (
            ft.Row(
                controls=[build_marketing_source_table(self._marketing_metrics)],
                scroll=ft.ScrollMode.AUTO,
            )
            if self._marketing_metrics
            else ft.Container()
        )

    # ------------------------------------------------------------------
    # Error state
    # ------------------------------------------------------------------

    def _build_error_ui(self):
        self.set_controls([
            ft.Text(
                "Leads",
                size=32,
                weight=ft.FontWeight.W_700,
                color=get_text_color(self._page.theme_mode),
            ),
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.ERROR_OUTLINE, size=48, color=ft.Colors.ERROR),
                        ft.Text(
                            "Could not load data",
                            size=16,
                            weight=ft.FontWeight.W_500,
                            color=ft.Colors.ON_SURFACE,
                        ),
                        ft.Text(
                            "Try importing a leads CSV file",
                            size=12,
                            color=get_subtitle_color(self._page.theme_mode),
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
                padding=40,
            ),
        ])

    # ------------------------------------------------------------------
    # Export — genera HTML desde datos ya cargados en memoria
    # ------------------------------------------------------------------

    def _get_filters_description(self) -> str:
        """Construye descripción textual de los filtros activos."""
        parts = []
        source_val = getattr(self, '_source_dropdown', None)
        if source_val and source_val.value and source_val.value != ALL_SOURCES:
            parts.append(f"Source: {_SOURCE_LABELS.get(source_val.value, source_val.value)}")
        stage_val = getattr(self, '_stage_dropdown', None)
        if stage_val and stage_val.value and stage_val.value != ALL_STAGES:
            parts.append(f"Stage: {stage_val.value}")
        if getattr(self, '_specific_start_date', None) or getattr(self, '_specific_end_date', None):
            if self._specific_start_date and self._specific_end_date:
                parts.append(f"Period: {self._specific_start_date} → {self._specific_end_date}")
            elif self._specific_start_date:
                parts.append(f"From: {self._specific_start_date}")
            elif self._specific_end_date:
                parts.append(f"To: {self._specific_end_date}")
        else:
            date_val = getattr(self, '_date_dropdown', None)
            if date_val and date_val.value and date_val.value != ALL_TIME:
                parts.append(f"Period: {date_val.value}")
        return " · ".join(parts) if parts else ALL_LEADS_DESCRIPTION

    async def _export_leads_html(self):
        """Exporta informe de leads usando datos ya cargados."""
        try:
            leads = self._get_active_leads()
            funnel_stats = self._funnel_stats
            sources_data = self._sources_data
            filters_desc = self._get_filters_description()

            default_name = "Leads_Report.html"
            filepath = await save_html_file(self._page, default_name)
            if not filepath:
                return

            success, message, _ = generate_leads_html_report(
                leads=leads,
                funnel_stats=funnel_stats,
                sources_data=sources_data,
                filters_desc=filters_desc,
                filename=filepath,
                marketing_summary=getattr(self, '_marketing_summary', {}),
                marketing_metrics=getattr(self, '_marketing_metrics', []),
            )

            if success:
                show_notification(self._page, f"Report exported: {os.path.basename(filepath)}", "success")
                open_file_cross_platform(filepath)
            else:
                show_notification(self._page, message, "error")
        except Exception as e:
            logger.exception("LeadsView: leads report export failed")
            show_notification(self._page, f"Export failed: {e}", "error")

    # ------------------------------------------------------------------
    # Theme update — muta colores sin reconstruir la UI
    # ------------------------------------------------------------------

    def update_theme(self):
        if not self._page:
            return
        if self._header:
            self._header.color = get_text_color(self._page.theme_mode)
        if self._subtitle:
            self._subtitle.color = get_subtitle_color(self._page.theme_mode)
        # Update section title colors
        _title_color = get_text_color(self._page.theme_mode)
        if hasattr(self, '_leads_section_title') and self._leads_section_title:
            self._leads_section_title.color = _title_color
        if hasattr(self, '_global_filters_title') and self._global_filters_title:
            self._global_filters_title.color = _title_color
        if hasattr(self, '_analytics_title_texts'):
            for t in self._analytics_title_texts:
                t.color = _title_color
        # Update input field styling
        for dd in [
            getattr(self, '_source_dropdown', None),
            getattr(self, '_stage_dropdown', None),
            getattr(self, '_date_dropdown', None),
        ]:
            if dd:
                dd.bgcolor = ft.Colors.SURFACE_CONTAINER_LOWEST
                dd.focused_border_color = ft.Colors.PRIMARY
        if getattr(self, '_search_field', None):
            self._search_field.bgcolor = ft.Colors.SURFACE_CONTAINER_LOWEST
            self._search_field.focused_border_color = ft.Colors.PRIMARY
        if hasattr(self, '_update_specific_date_chip_colors'):
            self._update_specific_date_chip_colors()
        # Rebuild table with updated theme colors
        if hasattr(self, '_table_container') and hasattr(self, '_filtered_leads'):
            self._table_container.controls = [
                build_leads_table(self._filtered_leads, self._page.theme_mode)
            ]
        # Rebuild revenue vs spend chart (uses theme-dependent tooltip colors)
        if hasattr(self, '_marketing_chart_container') and hasattr(self, '_marketing_metrics'):
            self._marketing_chart_container.content = build_revenue_vs_spend_chart(
                self._marketing_metrics, self._page.theme_mode
            )
        # Marketing spend editor theme
        if hasattr(self, '_spend_editor'):
            self._spend_editor.update_theme()
        # Caller (router) es responsable del page.update()

