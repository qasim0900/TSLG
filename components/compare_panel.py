"""Panel de configuración del modo comparación A vs B."""
import flet as ft

from analysis import get_unique_clients, get_unique_products
from core import shift_year_iso, normalize_iso
from theme import get_compare_panel_bgcolor, get_text_color, date_picker_chip, clear_filter_button_style, styled_dropdown, update_styled_dropdown
from theme.colors import get_compare_colors
from theme.theme_utils import is_dark_mode
from utils.notifications import NotificationManager
from domain.compare_preset import PRESET_REGISTRY
from utils.ui_dispatch import mounted_page
from domain.filter_options import ALL_FILTER_KEY, ALL_FILTER_LABEL
import logging

logger = logging.getLogger(__name__)
class ComparePanel(ft.Container):
    def __init__(self, compare_controller, on_clear_comparison=None, on_compare_requested=None,):
        self.compare = compare_controller
        self.on_clear_comparison = on_clear_comparison
        self.on_compare_requested = on_compare_requested
        self._internal_sync = False
        self._compare_running = False
        # ---------- Controles ----------
        self.title = ft.Text(
            "📊 Period comparison",
            size=18,
            weight=ft.FontWeight.BOLD,
            expand=True,
        )

        #Cachear hover handler ANTES de crear botones (igual que FilterPanel)
        self._hover_handler = self._create_hover_handler()

        self.btn_compare = None
        self._create_compare_button()

        _prev_colors = get_compare_colors(False)  # Default light; se actualiza en update_theme()
        self.btn_prev_year = ft.Button(
            "Period B = A − 1 year",
            icon=ft.Icons.HISTORY,
            on_click=self._set_b_from_a_prev_year,
            visible=False,
            bgcolor=_prev_colors['bgcolor'],
            color=_prev_colors['color'],
            elevation=_prev_colors['elevation'],
            on_hover=self._hover_handler,
        )

        self.btn_clear_compare = ft.TextButton(
            "Clear comparison",
            icon=ft.Icons.CLEAR,
            on_click=self._clear_compare,
            style=clear_filter_button_style(),
        )

        # ---------- DatePickers B ----------
        self.dp_b_start = ft.DatePicker(
            on_change=lambda e: self._on_date_change("start", e.control.value),
            on_dismiss=lambda e: logger.debug("ComparePanel dp_b_start dismissed")
        )
        self.dp_b_end = ft.DatePicker(
            on_change=lambda e: self._on_date_change("end", e.control.value),
            on_dismiss=lambda e: logger.debug("ComparePanel dp_b_end dismissed")
        )

        self._pickers_attached = False

        self.chip_b_start = date_picker_chip(
            label="Start B",
            value=self.compare.b_start,
            is_start=True,
            page=None,
            on_click=lambda _: self._open_picker("start"),
        )

        self.chip_b_end = date_picker_chip(
            label="End B",
            value=self.compare.b_end,
            is_start=False,
            page=None,
            on_click=lambda _: self._open_picker("end"),
        )

        # 🔥 Cachear referencias internas de chips (igual que FilterPanel)
        self._chip_b_start_icon = self.chip_b_start.content.controls[0]
        self._chip_b_start_text = self.chip_b_start.content.controls[1]
        self._chip_b_end_icon = self.chip_b_end.content.controls[0]
        self._chip_b_end_text = self.chip_b_end.content.controls[1]

        self.chip_b_start.visible = True
        self.chip_b_end.visible = True

        # ---------- Dropdowns Compare ----------
        clients = get_unique_clients()
        client_items = (
            [ft.dropdown.Option(key=ALL_FILTER_KEY, text=ALL_FILTER_LABEL)]
            + [ft.dropdown.Option(key=name, text=name.upper()) for name in clients]
        )

        self.client_dropdown = styled_dropdown(
            label="👤 Client",
            options=client_items,
            on_change=self._on_client_change,
            page_or_theme_mode=None,
        )

        products = get_unique_products()
        product_items = (
            [ft.dropdown.Option(key=ALL_FILTER_KEY, text=ALL_FILTER_LABEL)]
            + [ft.dropdown.Option(key=p, text=p.upper()) for p in products]
        )

        self.product_dropdown = styled_dropdown(
            label="📦 Product",
            options=product_items,
            on_change=self._on_product_change,
            page_or_theme_mode=None,
        )


        self.header_row = ft.Row(
            [
            self.title,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )

        self.start_col = ft.Column(
            [
                ft.Text("Start B", size=12),
                self.chip_b_start,
            ],
            spacing=5,
            expand=1,
        )

        self.end_col = ft.Column(
            [
                ft.Text("End B", size=12),
                self.chip_b_end,
            ],
            spacing=5,
            expand=1,
        )

        self.date_row = ft.Row(
            [self.start_col, self.end_col],
            spacing=10,
        )

        self.actions_row = ft.Row(
            [
                self.btn_compare,
                self.btn_clear_compare,
            ],
            spacing=10,
        )

        self.filters_row = ft.Row(
            [
                self.client_dropdown,
                self.product_dropdown,
            ],
            spacing=10,
        )
        self.txt_presets = ft.Text(
            "Comparison presets",
            size=14,
            weight=ft.FontWeight.BOLD,
        )

        self.presets_row = ft.Row(
            spacing=10,
            wrap=True,
        )

        self._build_preset_buttons()

        self.compare_content = ft.Column(
            [
                self.date_row,
                self.filters_row,
                self.txt_presets,
                self.presets_row,
                self.actions_row,
                
            ],
            spacing=15,
            visible=True,
        )

    # ---------- Layout ----------
        self.column = ft.Column(
            [
                self.header_row,
                self.compare_content,
            ],
            spacing=15,
        )
        self.compare_content.visible = True

        # Forzar visibles los controles que antes dependían del toggle
        self.chip_b_start.visible = True
        self.chip_b_end.visible = True
        self.btn_compare.visible = True
        self.btn_prev_year.visible = True
        self.btn_clear_compare.visible = True
       

        # Usar bgcolor inicial (fallback a LIGHT si no hay page)
        initial_bgcolor = get_compare_panel_bgcolor(ft.ThemeMode.LIGHT)

        super().__init__(
            content=self.column,
            padding=16,
            border_radius=10,
            bgcolor=initial_bgcolor,  # Se corrige en did_mount() via update_theme()
            expand=True,
        )

    # ---------------- UI logic ----------------
    def _on_user_compare_click(self, e):
        self._run_compare_safely()

    def _compare(self, e=None):
        self._run_compare_safely()

    def _can_execute_compare(self):
        return (
            not self._compare_running
            and not self._internal_sync
            and not getattr(self, "_is_rebuilding", False)
            and not getattr(self, "_initial_render_pending", False)
            and self.page is not None
        )

    def _run_compare_safely(self):
        if self._compare_running:
            return
        if not self._can_execute_compare():
            return
        self._compare_running = True
        try:
            self._execute_compare()
        finally:
            self._compare_running = False

    def _execute_compare(self):
        if not self.compare.b_start or not self.compare.b_end:
            if mounted_page(self):
                nm = NotificationManager(self.page)
                nm.show_snackbar(
                    "Fill in period B to compare.",
                    severity="warning",
                )
            return
        if self.on_compare_requested:
            self.on_compare_requested()

    def _build_preset_buttons(self):
        self.presets_row.controls.clear()
        self._preset_buttons = {}

        # Usar colores LIGHT como default. update_theme() corregirá después según theme actual.
        # NO acceder self.page aquí — aún no está inicializado
        colors = get_compare_colors(False)

        for preset in PRESET_REGISTRY.list_all():
            btn = ft.Button(
                preset.label,
                tooltip=preset.description,
                on_click=lambda e, pid=preset.id: self._apply_preset(pid),
                bgcolor=colors["bgcolor"],
                color=colors["color"],
                elevation=colors["elevation"],
            )

            self.presets_row.controls.append(btn)
            self._preset_buttons[preset.id] = btn
    def _update_preset_buttons_state(self):
        has_a = (
            self.compare.a_start is not None
            and self.compare.a_end is not None
        )

        for preset in PRESET_REGISTRY.list_all():
            btn = self._preset_buttons.get(preset.id)
            if not btn:
                continue

            if preset.requires_period_a and not has_a:
                btn.disabled = True
            else:
                btn.disabled = False
       
    def _on_grouping_changed(self, grouping: str):
        """
        Se llama cuando el usuario cambia la agrupación temporal
        desde el gráfico comparativo.
        """
        # 1️⃣ Guardar estado en el controller
        self.compare.set_grouping(grouping)

        # 2️⃣ Solo recalcular si la comparación es válida
        if not self.compare.is_compare_active():
            return

        # 🔑 Recalcular comparación y gráficos
        self._compare(None)

    def _apply_preset(self, preset_id: str):
        preset = PRESET_REGISTRY.get(preset_id)
        if not preset:
            return

        applied = self.compare.apply_preset(preset)

        if not applied:
            NotificationManager(self.page).show_snackbar(
                "Could not apply the preset. Check period A.",
                severity="warning",
            )
            return

        # Sincronizar UI desde controller
        self._sync_from_controller()

        # Sincronizar agrupación temporal si el preset la define
        if preset.grouping_hint:
            self.compare.set_grouping(preset.grouping_hint)
        
        self._update_preset_buttons_state()
        self.refresh()

        if self.compare.is_compare_active() and self.on_compare_requested:
            self.on_compare_requested()


    def _open_picker(self, which: str):
        """Abre DatePicker usando page.overlay + open=True (Flet 0.80.5)."""
        if not mounted_page(self):
            return
        
        picker = self.dp_b_start if which == "start" else self.dp_b_end
        # ✅ Forzar ciclo close→open para que Flet detecte el cambio de estado
        if picker.open:
            picker.open = False
            self.page.update()
        picker.open = True
        self.page.update()

    def _on_date_change(self, which: str, value):
        iso = normalize_iso(value)
        if not iso:
            return

        # ✅ Cerrar picker explícitamente
        picker = self.dp_b_start if which == "start" else self.dp_b_end
        picker.open = False

        if which == "start":
            self.compare.set_period_b(iso, self.compare.b_end)
            self._chip_b_start_text.value = f"Start B: {iso}"
        else:
            self.compare.set_period_b(self.compare.b_start, iso)
            self._chip_b_end_text.value = f"End B: {iso}"

        self.refresh()
        # ✅ Flet 0.80.5: Cerrar DatePicker y actualizar chips requiere page.update()
        # (igual que FilterPanel._on_date_change)
        if mounted_page(self):
            self.page.update()
   
    def _clear_compare(self, e):
        if self.on_clear_comparison:
            self.on_clear_comparison()
        # ✅ Flet 0.80.5: El callback on_clear_comparison maneja el rendering
        # NO llamar self.update() (patrón oficial)

    def _on_client_change(self, e):
        if self._internal_sync:
            return
        value = e.control.value
        client = None if value == ALL_FILTER_KEY else value
        # Echo suppression: async on_change from refresh() echo — same value, skip
        if client == self.compare.client_b:
            return
        self.compare.set_client_b(client)
        self.refresh()

    def _on_product_change(self, e):
        if self._internal_sync:
            return
        value = e.control.value
        product = None if value == ALL_FILTER_KEY else value
        # Echo suppression: async on_change from refresh() echo — same value, skip
        if product == self.compare.product_b:
            return
        self.compare.set_product_b(product)
        self.refresh()
    

    def _set_b_from_a_prev_year(self, e):
        if not self.compare.a_start or not self.compare.a_end:
            return

        b_start = shift_year_iso(self.compare.a_start, -1)
        b_end = shift_year_iso(self.compare.a_end, -1)

        self.compare.set_period_b(b_start, b_end)

        self._chip_b_start_text.value = f"Start B: {b_start}"
        self._chip_b_end_text.value = f"End B: {b_end}"

        self.refresh()

    def refresh(self):
        self._update_preset_buttons_state()
        self._internal_sync = True
        try:
            if not self.compare.client_b_overridden:
                self.client_dropdown.value = (
                    self.compare.client_b if self.compare.client_b else ALL_FILTER_KEY
                )

            if not self.compare.product_b_overridden:
                self.product_dropdown.value = (
                    self.compare.product_b if self.compare.product_b else ALL_FILTER_KEY
                )
        finally:
            self._internal_sync = False

    def update_from_snapshot(self, snapshot):
        """
        Marca el panel como usando snapshot, sin pintar UI ni métricas.
        """
        if not snapshot or not snapshot.is_compare_mode():
            return

    def reset_visual_state(self):
        """
        Resetea SOLO el estado visual del panel de comparación.
        No toca el controller.
        """
        # Chips
        self._chip_b_start_text.value = "Start B: –"
        self._chip_b_end_text.value = "End B: –"

        # DatePickers
        self.dp_b_start.value = None
        self.dp_b_end.value = None

        # Dropdowns
        self.client_dropdown.value = ALL_FILTER_KEY
        self.product_dropdown.value = ALL_FILTER_KEY

        self.update()

    def update_theme(self):
        """
        Actualiza todos los colores del panel y botones al cambiar el tema.
        
        CUMPLE R9 (Cláusula Anti-Heurística):
        - Muta TODOS los controles visibles (sin clasificar como "decorativos")
        - NO recibe parámetros
        - SOLO lee self.page.theme_mode
        - NO modifica self.page.theme_mode
        - Defensivo: sale si self.page es None
        """
        if not mounted_page(self):
            return
        
        # Leer el modo de tema actual (NO escribir)
        theme_mode = self.page.theme_mode
        is_dark = theme_mode == ft.ThemeMode.DARK
        
        # ============================================================
        # 1. PANEL: Fondo, bordes, dropdowns, chips
        # ============================================================
        self.title.color = get_text_color(self.page.theme_mode)
        self.bgcolor = get_compare_panel_bgcolor(theme_mode)

        update_styled_dropdown(self.client_dropdown, theme_mode)
        update_styled_dropdown(self.product_dropdown, theme_mode)
        
        # Actualizar chips (contenedores visuales de los date pickers)
        # NOTA: se llama ANTES de cualquier recorrido recursivo para evitar
        # que los colores WHITE/BLACK sean sobreescritos (bug previo con update_container_theme)
        self._update_chip_colors(theme_mode)

        # ============================================================
        # 2. BOTONES: Colores de todos los botones de acción
        # ============================================================
        compare_colors = get_compare_colors(is_dark)

        # Botón "Comparar"
        self.btn_compare.bgcolor = compare_colors['bgcolor']
        self.btn_compare.color = compare_colors['color']
        self.btn_compare.elevation = compare_colors['elevation']
        if self.btn_compare.on_hover != self._hover_handler:
            self.btn_compare.on_hover = self._hover_handler

        # Botón "Limpiar comparación" (R9: INCLUIDO - es visible)
        self.btn_clear_compare.color = get_text_color(theme_mode)

        # Botón "Periodo B = A − 1 año" (R9: INCLUIDO - es visible cuando expanded)
        self.btn_prev_year.bgcolor = compare_colors['bgcolor']
        self.btn_prev_year.color = compare_colors['color']
        self.btn_prev_year.elevation = compare_colors['elevation']
        if self.btn_prev_year.on_hover != self._hover_handler:
            self.btn_prev_year.on_hover = self._hover_handler
        
        # ============================================================
        # 3. TEXTOS: Etiquetas del panel (R9: INCLUIDO - son visibles)
        # ============================================================
        self.txt_presets.color = get_text_color(theme_mode)
        
        # Etiquetas "Inicio B" y "Fin B" dentro de las columnas
        if self.start_col.controls and len(self.start_col.controls) > 0:
            self.start_col.controls[0].color = get_text_color(theme_mode)
        if self.end_col.controls and len(self.end_col.controls) > 0:
            self.end_col.controls[0].color = get_text_color(theme_mode)
        
        # ============================================================
        # 4. PRESET BUTTONS: Botones de presets dinámicos (R9: INCLUIDO)
        # ============================================================
        if self._preset_buttons:
            for preset_id, btn in self._preset_buttons.items():
                if btn:
                    btn.bgcolor = compare_colors['bgcolor']
                    btn.color = compare_colors['color']
                    btn.elevation = compare_colors['elevation']
        
        # NO llamar self.update() aquí: la vista orquesta un único page.update()

    def _update_chip_colors(self, theme_mode):
        """Actualiza colores de chips usando referencias cacheadas (igual que FilterPanel)."""
        is_dark = theme_mode == ft.ThemeMode.DARK

        start_bg = ft.Colors.GREEN_800 if is_dark else ft.Colors.GREEN_200
        end_bg = ft.Colors.RED_700 if is_dark else ft.Colors.RED_200
        text_color = ft.Colors.WHITE if is_dark else ft.Colors.BLACK
        icon_color = ft.Colors.WHITE if is_dark else ft.Colors.BLACK

        # Actualizar usando referencias cacheadas (NO por iteración)
        self.chip_b_start.bgcolor = start_bg
        self._chip_b_start_icon.color = icon_color
        self._chip_b_start_text.color = text_color

        self.chip_b_end.bgcolor = end_bg
        self._chip_b_end_icon.color = icon_color
        self._chip_b_end_text.color = text_color

        # Los chips tienen on_click → son controles aislados en Flet.
        # page.update() no los incluye en el diff global: requieren update() explícito.
        
        self.chip_b_start.update()
        self.chip_b_end.update()

    def _sync_from_controller(self):
        """
        Sincroniza el estado visual del panel con el CompareController.
        Se llama SOLO al expandir.
        """
        logger.debug("sync_from_controller")
        self._internal_sync = True

        try:
            # Dropdowns (herencia A → B)
            if not self.compare.client_b_overridden:
                self.client_dropdown.value = (
                    self.compare.client_b if self.compare.client_b else ALL_FILTER_KEY
                )
            if not self.compare.product_b_overridden:
                self.product_dropdown.value = (
                    self.compare.product_b if self.compare.product_b else ALL_FILTER_KEY
                )

            # Chips de fechas B
            self._chip_b_start_text.value = f"Start B: {self.compare.b_start}" if self.compare.b_start else "Start B: –"
            self._chip_b_end_text.value = f"End B: {self.compare.b_end}" if self.compare.b_end else "End B: –"

        finally:
            self._internal_sync = False

        # Solo flush si ya está montado (puede llamarse desde __init__ antes del mount)
        if mounted_page(self):
            self.update()


    def _create_hover_handler(self):
        def on_hover_event(e):
            if not mounted_page(self):
                return

            is_dark = is_dark_mode(self.page)
            colors = get_compare_colors(is_dark)

            if e.data:
                e.control.scale = 1.03
                e.control.animate_scale = ft.Animation(100, ft.AnimationCurve.EASE_OUT)
                e.control.bgcolor = colors['hover_bgcolor']
                e.control.elevation = colors['hover_elevation']
            else:
                e.control.scale = 1.0
                e.control.animate_scale = ft.Animation(100, ft.AnimationCurve.EASE_OUT)
                e.control.bgcolor = colors['bgcolor']
                e.control.elevation = colors['elevation']
            # ✅ Fuente oficial: examples/controls/container/handling_hovers.py
            # e.control.update() es obligatorio en on_hover handlers
            e.control.update()

        return on_hover_event

    def _create_compare_button(self):
        """Crea el botón 'Comparar' con colores por defecto (se actualiza en update_theme)."""
        colors = get_compare_colors(False)  # Default light; se actualiza en update_theme()
        self.btn_compare = ft.Button(
            "Compare",
            icon=ft.Icons.COMPARE_ARROWS,
            on_click=self._on_user_compare_click,
            bgcolor=colors['bgcolor'],
            color=colors['color'],
            elevation=colors['elevation'],
            on_hover=self._btn_compare_on_hover,
            on_focus=self._btn_compare_on_focus,
            on_blur=self._btn_compare_on_blur,
        )

    # ----------------- Diagnostic wrappers for button events -----------------
    def _btn_compare_on_hover(self, e):
        logger.debug("btn_compare.on_hover data=%s", getattr(e, 'data', None))
        # call original hover handler if present
        try:
            if hasattr(self, '_hover_handler') and callable(self._hover_handler):
                self._hover_handler(e)
        except Exception:
            pass

    def _btn_compare_on_focus(self, e):
        logger.debug("btn_compare.on_focus data=%s", getattr(e, 'data', None))

    def _btn_compare_on_blur(self, e):
        logger.debug("btn_compare.on_blur data=%s", getattr(e, 'data', None))

    def did_mount(self):
        """
        Hook manual del proyecto.
        Se llama explícitamente cuando el control ya está montado en la Page.
        """
        if not mounted_page(self):
            return

        # ✅ DatePickers van en page.overlay para que on_change/on_dismiss funcionen
        if self.dp_b_start not in self.page.overlay:
            self.page.overlay.append(self.dp_b_start)
        if self.dp_b_end not in self.page.overlay:
            self.page.overlay.append(self.dp_b_end)
        self.update_theme()
        self.update()
        # ✅ page.update() para registrar los DatePickers en el overlay
        self.page.update()
