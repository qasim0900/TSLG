"""Orquestador principal de la UI de Techset LeadGen.

Gestiona la navegación por pestañas (Dashboard, Ventas, Leads, Clientes),
el cambio de tema claro/oscuro y la propagación de update_theme() a todas
las vistas cacheadas.
"""

import flet as ft
import logging
from branding import LOGO_ASSET, PRODUCT_NAME, PRODUCT_TAGLINE
from views.dashboard_view import DashboardView
from views.ventas_view import VentasView
from views.leads_view import LeadsView
from views.clientes_view import ClientesView
from utils.notifications import NotificationManager
from theme import (
    BRAND_PRIMARY,
    BRAND_PRIMARY_ACCESSIBLE,
    BRAND_RADIUS_MD,
    get_icon_color,
    is_dark_mode,
)

logger = logging.getLogger(__name__)

class FDTApp(ft.Column):
    """Application shell with brand header, navigation, content, and theme toggle."""

    def __init__(self, page: ft.Page):
        super().__init__(expand=True, spacing=0)
        self._page = page  # Usar _page en lugar de page (page es property de solo lectura en Flet 0.80.5)
        # Cache de vistas (patrón correcto Flet 0.80.x)
        self._dashboard_view = None
        self._ventas_view = None
        self._leads_view = None
        self._clientes_view = None

        # ==============================
        # Export state (FilePicker ya no es global - se crea cuando se necesita)
        # ==============================
        self._pending_export_snapshot = None
        
        # Inicializar gestor de notificaciones
        self.notifications = NotificationManager(page)
        page.notifications = self.notifications
        self.logo_image = ft.Image(
            src=LOGO_ASSET,
            width=46,
            height=46,
            fit=ft.BoxFit.CONTAIN,
            filter_quality=ft.FilterQuality.HIGH,
            semantics_label="Techset Solutions logo",
        )

        # Preserve the official artwork and render the product wordmark beside it.
        self.logo = ft.Container(
            width=54,
            height=54,
            padding=4,
            border_radius=BRAND_RADIUS_MD,
            bgcolor=ft.Colors.with_opacity(0.06, BRAND_PRIMARY),
            content=self.logo_image,
        )
        self._techset_span = ft.TextSpan(
            "Techset",
            style=ft.TextStyle(
                color=BRAND_PRIMARY_ACCESSIBLE,
                weight=ft.FontWeight.W_700,
            ),
        )
        self._leadgen_span = ft.TextSpan(
            " LeadGen",
            style=ft.TextStyle(
                color=ft.Colors.ON_SURFACE,
                weight=ft.FontWeight.W_700,
            ),
        )
        self.product_name = ft.Text(
            spans=[self._techset_span, self._leadgen_span],
            size=22,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
            semantics_label=PRODUCT_NAME,
        )
        self.product_tagline = ft.Text(
            PRODUCT_TAGLINE,
            size=11,
            weight=ft.FontWeight.W_500,
            color=ft.Colors.ON_SURFACE_VARIANT,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self.brand_lockup = ft.Row(
            [
                self.logo,
                ft.Column(
                    [self.product_name, self.product_tagline],
                    spacing=0,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ],
            spacing=10,
            tight=True,
        )

        def _tab_content(label: str, icon: str) -> ft.Control:
            icon_control = ft.Icon(icon, size=20)
            text_control = ft.Text(label, size=14, weight=ft.FontWeight.W_500)

            def _on_hover(e):
                ft.context.disable_auto_update()
                # Resaltar icono y título al hacer hover
                if str(e.data).lower() == "true":
                    hover_color = get_icon_color(self._page.theme_mode)
                    icon_control.color = hover_color
                    text_control.color = hover_color
                else:
                    # Volver a colores por defecto del tema
                    icon_control.color = None
                    text_control.color = None
                e.control.update()

            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                content=ft.Row(
                    [
                        icon_control,
                        text_control,
                    ],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                on_hover=_on_hover,
            )

        # Navegación (Flet 0.80.5 — Tabs con TabBar)
        self.tab_bar = ft.TabBar(
            tabs=[
                ft.Tab(label=_tab_content("Dashboard", ft.Icons.DASHBOARD)),
                ft.Tab(label=_tab_content("Sales", ft.Icons.TRENDING_UP)),
                ft.Tab(label=_tab_content("Leads", ft.Icons.PERSON_ADD)),
                ft.Tab(label=_tab_content("Clients", ft.Icons.GROUP)),
            ],
            scrollable=True,
            divider_color=ft.Colors.TRANSPARENT,
            indicator_color=BRAND_PRIMARY,
            indicator_thickness=3,
            label_color=ft.Colors.ON_SURFACE,
            unselected_label_color=ft.Colors.ON_SURFACE_VARIANT,
            splash_border_radius=24,
        )
        
        self.tabs = ft.Tabs(
            content=self.tab_bar,
            length=4,
            selected_index=0,
            on_change=self._on_tab_change,
            height=48,
        )

        # Botón de tema
        self.theme_button = ft.IconButton(
            icon=ft.Icons.DARK_MODE,
            tooltip="Toggle light/dark theme",
            icon_color=BRAND_PRIMARY_ACCESSIBLE,
            on_click=self._toggle_theme,
        )

        # Contenedor de contenido
        self.body = ft.Container(
            expand=True,
            padding=ft.Padding.only(left=16, right=16, top=20, bottom=0),
        )

        # A two-tier shell remains usable at narrow widths: the product name
        # never competes with the tab labels, and the TabBar can scroll.
        self.header = ft.Container(
            bgcolor=ft.Colors.SURFACE,
            border=ft.Border.only(
                bottom=ft.BorderSide(
                    1,
                    ft.Colors.with_opacity(0.35, ft.Colors.OUTLINE_VARIANT),
                )
            ),
            shadow=ft.BoxShadow(
                blur_radius=18,
                offset=ft.Offset(0, 4),
                color=ft.Colors.with_opacity(0.06, ft.Colors.SHADOW),
            ),
            padding=ft.Padding.only(left=16, right=12, top=10, bottom=4),
            content=ft.Column(
                [
                    ft.Row(
                        [self.brand_lockup, self.theme_button],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    self.tabs,
                ],
                spacing=2,
            ),
        )

        # Layout principal
        self.controls = [
            self.header,
            self.body,
        ]

        # Cargar vista inicial
        self._load_view(0)
        
        # 🚀 FIX: Flag para debounce de cambios de tema
        self._theme_toggling = False

    def _on_tab_change(self, e):
        """Cambia de vista según la pestaña seleccionada."""
        idx = e.control.selected_index
        old_view_type = type(self.body.content).__name__ if self.body.content else "None"
        self._load_view(idx)
        new_view_type = type(self.body.content).__name__ if self.body.content else "None"
        logger.debug("Tab %s: %s -> %s", idx, old_view_type, new_view_type)

    def _load_view(self, index):
        """Carga (o reutiliza) la vista correspondiente al índice de pestaña."""
        if index == 0:
            if self._dashboard_view is None:
                self._dashboard_view = DashboardView(
                    self._page,
                    open_file_picker=self.request_import,
                    go_to_ventas=lambda: self._go_to_tab(1),
                    go_to_leads=lambda: self._go_to_tab(2),
                    go_to_clientes=lambda: self._go_to_tab(3),
                )
            self.body.content = self._dashboard_view
    
        elif index == 1:
            if self._ventas_view is None:
                self._ventas_view = VentasView(self._page)
            self.body.content = self._ventas_view
    
        elif index == 2:
            if self._leads_view is None:
                self._leads_view = LeadsView(self._page)
            self.body.content = self._leads_view

        elif index == 3:
            if self._clientes_view is None:
                self._clientes_view = ClientesView(self._page)
            self.body.content = self._clientes_view

        #self._page.update()


    def _go_to_tab(self, index):
        """Cambia a la pestaña especificada."""
        self.tabs.selected_index = index
        self._load_view(index)

    # =========================================================
    # API PÚBLICA — INTENCIONES DE IMPORT / EXPORT
    # =========================================================

    def request_import(self):
        """
        NO USADO - Dashboard maneja import directamente.
        Mantenido para compatibilidad con VentasView si es necesario.
        """
        pass

    def request_export(self, snapshot):
        """
        Intención: exportar datos desde Ventas.
        """
        self._pending_export_snapshot = snapshot
        self._page.run_task(lambda: self._export_file_async(snapshot))
    
    async def _export_file_async(self, snapshot):
        """Exporta el snapshot a HTML."""
        file_picker = ft.FilePicker()
        file_path = await file_picker.save_file(allowed_extensions=["html"])
        
        if not file_path:
            return
        
        # Delegar en VentasView
        vista = self.body.content
        if isinstance(vista, VentasView) and getattr(vista, "_mounted", False):
            vista.handle_export_file(file_path, snapshot)

    def _toggle_theme(self, e):
        """Alterna entre modo claro y oscuro (patrón oficial de Flet)."""
        if self._theme_toggling:
            return
        
        self._theme_toggling = True
        try:
            # Cambiar theme_mode directamente (patrón oficial)
            self._page.theme_mode = (
                ft.ThemeMode.DARK
                if self._page.theme_mode == ft.ThemeMode.LIGHT
                else ft.ThemeMode.LIGHT
            )
            
            # Actualizar icono del botón según el nuevo theme
            self.theme_button.icon = (
                ft.Icons.LIGHT_MODE
                if self._page.theme_mode == ft.ThemeMode.DARK
                else ft.Icons.DARK_MODE
            )
            
            # The official site uses the same unmodified logo in both modes.
            self.logo.bgcolor = ft.Colors.with_opacity(
                0.12 if self._page.theme_mode == ft.ThemeMode.DARK else 0.06,
                BRAND_PRIMARY,
            )
            self._techset_span.style.color = (
                BRAND_PRIMARY
                if is_dark_mode(self._page)
                else BRAND_PRIMARY_ACCESSIBLE
            )
            self.theme_button.icon_color = (
                BRAND_PRIMARY
                if is_dark_mode(self._page)
                else BRAND_PRIMARY_ACCESSIBLE
            )

            # Propagar theme a la vista activa (actualiza colores hardcoded)
            # Los colores semánticos (ON_SURFACE, SURFACE, etc.) se adaptan solos,
            # pero colores condicionales (GREEN_200/700, BLUE_200/700, etc.) requieren
            # update_theme() explícito en la vista.
            active_view = self.body.content
            views = [active_view] + [
                view
                for view in (self._dashboard_view, self._ventas_view, self._leads_view, self._clientes_view)
                if view is not active_view
            ]
            for view in views:
                if view is not None and hasattr(view, "update_theme"):
                    view.update_theme()

            # page.update() final: envía todas las mutaciones al frontend
            self._page.update()
        finally:
            self._theme_toggling = False
