"""Botones de acción del dashboard: importar, visualizar, exportar, limpiar."""
import flet as ft
from theme.colors import (
    get_import_colors,
    get_visualization_colors,
    get_export_colors,
)
from utils.ui_dispatch import mounted_page


def _create_button_hover_handler(get_colors_func):
    """Hover handler compatible con Flet 0.80.5.

    Lee el theme actual desde e.control.page.theme_mode para evitar recrear
    handlers en cambios de theme (patrón oficial: no hacer work extra en theme).
    
    ✅ R7 CONFORME: NO llama e.control.update() internamente.
    Flet 0.80.5+ sincroniza automáticamente mutaciones de propiedades visuales.
    """
    def on_hover(e):
        page = getattr(e.control, "page", None)
        is_dark = bool(page and page.theme_mode == ft.ThemeMode.DARK)
        colors = get_colors_func(is_dark)

        if e.data:
            e.control.scale = 1.03
            e.control.animate_scale = ft.Animation(100, ft.AnimationCurve.EASE_OUT)
            e.control.bgcolor = colors["hover_bgcolor"]
            e.control.elevation = colors["hover_elevation"]
        else:
            e.control.scale = 1.0
            e.control.animate_scale = ft.Animation(100, ft.AnimationCurve.EASE_OUT)
            e.control.bgcolor = colors["bgcolor"]
            e.control.elevation = colors["elevation"]

        # ✅ R7: NO llamar e.control.update() → Flet sincroniza automáticamente
        # Evita cascada de updates que degrada rendimiento

    return on_hover


def _build_button_content(label: str, icon: ft.Icons):
    """Contenido estándar icono + texto"""
    return ft.Row(
        [
            ft.Icon(icon, size=18),
            ft.Text(label, size=13, weight=ft.FontWeight.W_500),
        ],
        spacing=8,
        alignment=ft.MainAxisAlignment.CENTER,
    )


class ActionButtons(ft.Row):
    """Botones de acción principales (Flet 0.80.5 compatible)."""

    def __init__(self, on_import, on_show_summary, on_show_charts, on_export=None):
        self.on_import = on_import
        self.on_show_summary = on_show_summary
        self.on_show_charts = on_show_charts
        self.on_export = on_export
        self.btn_import = None
        self.btn_summary = None
        self.btn_charts = None
        self.btn_export = None
        
        # R8: Cachear handlers (NO recrear en cada update_theme)
        self._hover_handlers = {}

        self._create_buttons()

        controls = [self.btn_import, self.btn_summary, self.btn_charts]
        if self.btn_export:
            controls.append(self.btn_export)

        super().__init__(
            controls=controls,
            spacing=10,
            wrap=True,
        )


    def did_mount(self):
        if not mounted_page(self):
            return
        self.update_theme()

    # -------------------------------------------------
    # CREACIÓN
    # -------------------------------------------------

    def _create_buttons(self):
        # Crear con theme por defecto (se actualizará en did_mount → update_theme)
        is_dark = False

        import_colors = get_import_colors(is_dark)
        vis_colors = get_visualization_colors(is_dark)
        export_colors = get_export_colors(is_dark)

        # Crear y cachear handlers (NO recrear en update_theme)
        self._hover_handlers["import"] = _create_button_hover_handler(get_import_colors)
        self._hover_handlers["summary"] = _create_button_hover_handler(get_visualization_colors)
        self._hover_handlers["charts"] = _create_button_hover_handler(get_visualization_colors)
        if self.on_export:
            self._hover_handlers["export"] = _create_button_hover_handler(get_export_colors)
        
        self.btn_import = ft.Button(
            content=_build_button_content("Import file", ft.Icons.FILE_UPLOAD),
            on_click=self.on_import,
            bgcolor=import_colors["bgcolor"],
            color=import_colors["color"],
            elevation=import_colors["elevation"],
            on_hover=self._hover_handlers["import"],
        )

        self.btn_summary = ft.Button(
            content=_build_button_content("Show summary", ft.Icons.SHOW_CHART),
            on_click=self.on_show_summary,
            bgcolor=vis_colors["bgcolor"],
            color=vis_colors["color"],
            elevation=vis_colors["elevation"],
            on_hover=self._hover_handlers["summary"],
        )

        self.btn_charts = ft.Button(
            content=_build_button_content("Show charts", ft.Icons.INSERT_CHART),
            on_click=self.on_show_charts,
            bgcolor=vis_colors["bgcolor"],
            color=vis_colors["color"],
            elevation=vis_colors["elevation"],
            on_hover=self._hover_handlers["charts"],
        )

        if self.on_export:
            self.btn_export = ft.Button(
                content=_build_button_content("Export HTML", ft.Icons.DOWNLOAD),
                on_click=self.on_export,
                bgcolor=export_colors["bgcolor"],
                color=export_colors["color"],
                elevation=export_colors["elevation"],
                on_hover=self._hover_handlers["export"],
            )

    # -------------------------------------------------
    # THEME UPDATE
    # -------------------------------------------------

    def update_theme(self):
        """Actualiza colores de botones al cambiar theme (R9: TODOS los controles visibles)."""
        if not mounted_page(self):
            return
        
        is_dark = self.page.theme_mode == ft.ThemeMode.DARK

        import_colors = get_import_colors(is_dark)
        vis_colors = get_visualization_colors(is_dark)
        export_colors = get_export_colors(is_dark)
        
        # Mutar propiedades visuales (R9: controles visibles DEBEN reaccionar)
        self._apply_button_theme(self.btn_import, import_colors, "import")
        self._apply_button_theme(self.btn_summary, vis_colors, "summary")
        self._apply_button_theme(self.btn_charts, vis_colors, "charts")

        if self.btn_export:
            self._apply_button_theme(self.btn_export, export_colors, "export")

        # NO llamar self.update() aquí.
        # La vista orquesta un único page.update() tras aplicar el theme.

    def _apply_button_theme(self, btn, colors, handler_key):
        """Muta propiedades visuales usando handler cacheado (R8: NO recrear)."""
        btn.bgcolor = colors["bgcolor"]
        btn.color = colors["color"]
        btn.elevation = colors["elevation"]
        # Usar handler cacheado (NO recrear)
        if btn.on_hover != self._hover_handlers[handler_key]:
            btn.on_hover = self._hover_handlers[handler_key]
