"""Panel de filtros de fecha, cliente y producto para la vista de ventas."""
import flet as ft
from flet import Colors
from theme.theme_utils import is_dark_mode
from theme.colors import get_apply_filter_colors
from controllers.date_filter_controller import DateFilterController

# Sentinel para distinguir "draft no tocado" de "draft explícitamente puesto a None (TODOS)"
_DRAFT_UNSET = object()
from theme import (
    clear_filter_button_style,
    get_filter_panel_bgcolor,
    get_text_color,
    styled_dropdown,
    update_styled_dropdown,
)
from analysis import get_unique_clients, get_unique_products, get_date_range
from datetime import datetime
from utils.ui_dispatch import mounted_page
from domain.filter_options import ALL_FILTER_KEY, ALL_FILTER_LABEL
import logging

logger = logging.getLogger(__name__)


class FilterPanel(ft.Container):
    """Panel de filtros de fecha con rangos rápidos."""

    def __init__(self, on_filter_applied, on_filter_cleared, filter_controller=None):
        self.on_filter_applied = on_filter_applied
        self.on_filter_cleared = on_filter_cleared
        self.filter_controller = filter_controller # 🆕 FASE 0 - Referencia al FilterController externo
 
        self._internal_sync = False
        self.date_filter = DateFilterController()

        # 🆕 DRAFT STATE: buffers de filtros no confirmados (no sincronizados a FilterController)
        # ✅ FIX: usar _DRAFT_UNSET como centinela para distinguir:
        #   - _DRAFT_UNSET  → el usuario NO tocó el dropdown (no hay cambio pendiente)
        #   - None          → el usuario explícitamente seleccionó "TODOS"
        #   - "NombreX"     → el usuario seleccionó un valor concreto
        self._draft_client = _DRAFT_UNSET
        self._draft_product = _DRAFT_UNSET
        self._filters_dirty = False

        # ---------------------------
        # Obtener rango de fechas de la BD
        # ---------------------------
        min_date_str, max_date_str = get_date_range()
        
        # Convertir strings ISO a datetime si existen
        self.initial_min_date = None
        self.initial_max_date = None
        if min_date_str:
            try:
                self.initial_min_date = datetime.fromisoformat(min_date_str).date()
            except:
                pass
        if max_date_str:
            try:
                self.initial_max_date = datetime.fromisoformat(max_date_str).date()
            except:
                pass
        
        # INICIALIZAR date_filter con las fechas por defecto
        if min_date_str:
            self.date_filter.set_date("start", min_date_str)
        if max_date_str:
            self.date_filter.set_date("end", max_date_str)

        # ---------------------------
        # DatePickers (UNA SOLA VEZ)
        # ---------------------------
        self.dp_start = ft.DatePicker(
            value=self.initial_min_date,
            on_change=lambda e: self._on_date_change("start", e.control.value),
            on_dismiss=lambda e: self._on_picker_dismiss("start")
        )
        self.dp_end = ft.DatePicker(
            value=self.initial_max_date,
            on_change=lambda e: self._on_date_change("end", e.control.value),
            on_dismiss=lambda e: self._on_picker_dismiss("end")
        )
        self._hover_handler = self._create_hover_handler()  # 🔥 Cachear el handler ANTES de usarlo en _build_static_ui()

        # ---------------------------
        # Dropdowns (UNA SOLA VEZ)
        # ---------------------------   
        clients = get_unique_clients()
        client_items = (
            [ft.dropdown.Option(key=ALL_FILTER_KEY, text=ALL_FILTER_LABEL)]
            + [ft.dropdown.Option(key=name, text=name.upper()) for name in clients]
        )
        self.client_dropdown = styled_dropdown(
            label="👤 Client",
            options=client_items,
            on_change=self._on_client_change,
            page_or_theme_mode=None
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
        self.selected_product = None

        # ---------------------------
        # UI estática (UNA SOLA VEZ)
        # ---------------------------
        self._build_static_ui()

        super().__init__(
            content=self._main_column,
            padding=15,
            border_radius=12,
            bgcolor=None,  # Se establece en did_mount() via update_theme()
            expand=True,
        )

    # ======================================================================
    # BUILD UI (solo una vez)
    # ======================================================================
    def did_mount(self):
        """
        Hook manual del proyecto.
        Se llama cuando el control ya está montado en la Page.
        """
        if not mounted_page(self):
            return

        # ✅ DatePickers van en page.overlay para que on_change/on_dismiss funcionen
        if self.dp_start not in self.page.overlay:
            self.page.overlay.append(self.dp_start)
        if self.dp_end not in self.page.overlay:
            self.page.overlay.append(self.dp_end)

        # Aplicar tema inicial
        self.update_theme()
        self.update()
        # ✅ page.update() para registrar los DatePickers en el overlay
        self.page.update()

    def will_unmount(self):
        """Hook called before unmounting the control from the page."""
        pass

    def _build_static_ui(self):

        # Pills de fecha
        self.lbl_start = self._build_date_chip("Start", is_start=True)
        self.lbl_end = self._build_date_chip("End", is_start=False)
        
        # 🚀 FIX: Cachear referencias a elementos internos de chips para evitar acceso frágil por índice
        self._chip_start_icon = self.lbl_start.content.controls[0]
        self._chip_start_text = self.lbl_start.content.controls[1]
        self._chip_end_icon = self.lbl_end.content.controls[0]
        self._chip_end_text = self.lbl_end.content.controls[1]

        # Textos
        self.txt_inicio = ft.Text("Start", size=12)
        self.txt_fin = ft.Text("End", size=12)
        self.txt_rangos = ft.Text(
            "Quick ranges",
            size=14,
            weight=ft.FontWeight.BOLD,
        )
        self.txt_titulo = ft.Text(
            "🔎 Date filters",
            size=18,
            weight=ft.FontWeight.BOLD,
            expand=True,
        )

        # Columnas fecha
        self.start_col = ft.Column([self.txt_inicio, self.lbl_start], spacing=5, expand=1)
        self.end_col = ft.Column([self.txt_fin, self.lbl_end], spacing=5, expand=1)

        self.header_row = ft.Row(
            [self.txt_titulo],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        )
        self.date_row = ft.Row(
            [self.start_col, self.end_col],
            spacing=10,
        )
        self._apply_label = "Apply filter"
        self._apply_loading_label = "Applying..."
        self.btn_apply = None
        self._create_apply_button()
        
        # Botón "Limpiar filtros" (R9: referencia persistente para mutación en update_theme)
        self.btn_clear = ft.TextButton(
            "Clear filters",
            icon=ft.Icons.CLEAR,
            on_click=self._clear,
            style=clear_filter_button_style(),
        )
        
        self.actions_row = ft.Row(
            [
                self.btn_apply,
                self.btn_clear,
            ],
            spacing=10,
        )
        # 🚀 FIX: Cachear referencias a botones de rangos rápidos para actualizar tema
        self.btn_quick_7 = ft.Button("Last 7 days", on_click=lambda _: self._quick_range(7))
        self.btn_quick_15 = ft.Button("Last 15 days", on_click=lambda _: self._quick_range(15))
        self.btn_quick_3m = ft.Button("Last 3 months", on_click=lambda _: self._quick_last_months(3))
        self.btn_quick_6m = ft.Button("Last 6 months", on_click=lambda _: self._quick_last_months(6))
        self.btn_quick_year = ft.Button("Last year", on_click=lambda _: self._quick_year())
        
        self.quick_ranges_row_1 = ft.Row(
            [self.btn_quick_7, self.btn_quick_15, self.btn_quick_3m, self.btn_quick_6m, self.btn_quick_year],
            spacing=10,
            wrap=True,
        )

        self.btn_week = ft.Button("This week", on_click=lambda _: self._current_week_to_date())
        self.btn_month = ft.Button("This month", on_click=lambda _: self._current_month_to_date())
        self.btn_quarter = ft.Button("This quarter", on_click=lambda _: self._current_quarter_to_date())
        self.btn_semester = ft.Button("This half-year", on_click=lambda _: self._current_semester_to_date())
        self.btn_year = ft.Button("This year", on_click=lambda _: self._current_year_to_date())
        
        self.quick_ranges_row_2 = ft.Row(
            [self.btn_week, self.btn_month, self.btn_quarter, self.btn_semester, self.btn_year],
            spacing=10,
            wrap=True,
        )

        self.filters_row = ft.Row(
            [self.client_dropdown, self.product_dropdown],
            spacing=10,
        )
    
        # Contenido expandible
        self.filter_content = ft.Column(
            [
                self.date_row,
                self.filters_row,
                self.txt_rangos,
                self.quick_ranges_row_1,
                self.quick_ranges_row_2,
                self.actions_row,
            ],
            spacing=15,
            visible=True ,
        )

        self._main_column = ft.Column(
            [
                self.header_row,
                self.filter_content,
            ],
            spacing=15,
        )   

    def _build_date_chip(self, label: str, is_start: bool) -> ft.Container:
        is_dark = False

        base_color = (
            Colors.GREEN_800 if is_start else Colors.RED_700
        ) if is_dark else (
            Colors.GREEN_200 if is_start else Colors.RED_200
        )

        text_color = Colors.WHITE if is_dark else Colors.BLACK

        # Usar fechas iniciales si existen, sino "-"
        if is_start:
            date_value = self.initial_min_date.strftime("%Y-%m-%d") if self.initial_min_date else "–"
        else:
            date_value = self.initial_max_date.strftime("%Y-%m-%d") if self.initial_max_date else "–"

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CALENDAR_MONTH, color=text_color),
                    ft.Text(f"{label}: {date_value}", color=text_color, size=12),
                ],
                spacing=5,
            ),
            bgcolor=base_color,
            border_radius=20,
            padding=ft.Padding(8, 4, 8, 4),
            on_click=lambda _: self._open_picker("start" if is_start else "end"),
            on_hover=lambda e: self._hover_chip(e, is_start),
        )

    # ======================================================================
    # SINCRONIZACIÓN DESDE EXTERNAL (compare_controller, etc)
    # ======================================================================

    def update_dates_from_compare_controller(self, start_iso: str, end_iso: str):
        """
        Sincroniza el panel de filtros con fechas externas (ej. compare_controller).
        Usado tras aplicar presets o confirmar comparación.
        
        Args:
            start_iso: Fecha de inicio ISO (ej: "2025-01-01")
            end_iso: Fecha de fin ISO (ej: "2025-12-31")
        """
        # Guardas defensivas: evitar cambios y renders si los valores no difieren
        current_start = getattr(self.date_filter, 'start_date', None)
        current_end = getattr(self.date_filter, 'end_date', None)
        if start_iso == current_start and end_iso == current_end:
            return  # nada que actualizar

        # 1. Actualizar el DateFilterController (source of truth)
        self.date_filter.start_date = start_iso
        self.date_filter.end_date = end_iso

        # 2. Actualizar labels visuales SOLO si cambian
        try:
            self.lbl_start.content.controls[1].value = (
                f"Start: {start_iso[:10]}" if start_iso else "Start: –"
            )
            self.lbl_end.content.controls[1].value = (
                f"End: {end_iso[:10]}" if end_iso else "End: –"
            )
        except Exception:
            # defensivo: si la estructura del control cambia, no romper
            pass

        # 3. Sincronizar DatePickers (si existen) SOLO si cambian
        try:
            new_dp_start = datetime.fromisoformat(start_iso).date() if start_iso else None
            new_dp_end = datetime.fromisoformat(end_iso).date() if end_iso else None

            if getattr(self.dp_start, 'value', None) != new_dp_start:
                self.dp_start.value = new_dp_start
            if getattr(self.dp_end, 'value', None) != new_dp_end:
                self.dp_end.value = new_dp_end
        except Exception:
            pass  # defensivo: nunca romper UI

        # ✅ Flet 0.80.5: Auto-update habilitado
        # Mutación de chip values se refleja automáticamente al finalizar el evento

    # ======================================================================
    # THEME UPDATE (SOLO MUTAR, NUNCA RECREAR)
    # ======================================================================

    def update_theme(self):
        """Actualiza todos los colores del panel según el tema actual (Patrón B - mutación)."""
        if not mounted_page(self):
            return
        
        # Fondo del panel
        self.bgcolor = get_filter_panel_bgcolor(self.page.theme_mode)

        # Textos generales
        text_color = get_text_color(self.page.theme_mode)
        self.txt_titulo.color = text_color
        self.txt_inicio.color = text_color
        self.txt_fin.color = text_color
        self.txt_rangos.color = text_color

        # Dropdowns personalizados
        update_styled_dropdown(self.client_dropdown, self.page.theme_mode)
        update_styled_dropdown(self.product_dropdown, self.page.theme_mode)

        # Chips de fecha
        self._update_chip_colors()
        
        # Botón Aplicar filtro
        self._update_apply_button_theme()
        
        # Botón "Limpiar filtros": usa clear_filter_button_style() (no necesita mutación manual)
        
        # NO llamar self.update() aquí: la vista orquesta un único page.update()
    
    def _update_apply_button_theme(self):
        """Actualiza el botón 'Aplicar filtro' cuando cambia el tema."""
        is_dark = is_dark_mode(self.page)
        colors = get_apply_filter_colors(is_dark)
        self.btn_apply.bgcolor = colors['bgcolor']
        self.btn_apply.color = colors['color']
        self.btn_apply.elevation = colors['elevation']
        # ✅ Usar el handler cacheado, NO crear uno nuevo
        if not hasattr(self.btn_apply, 'on_hover') or self.btn_apply.on_hover != self._hover_handler:
            self.btn_apply.on_hover = self._hover_handler
        
    def _update_chip_colors(self):
        """Actualiza colores de chips usando referencias cacheadas (Patrón B - mutación)."""
        is_dark = is_dark_mode(self.page)

        start_bg = Colors.GREEN_800 if is_dark else Colors.GREEN_200
        end_bg = Colors.RED_700 if is_dark else Colors.RED_200
        text_color = Colors.WHITE if is_dark else Colors.BLACK

        # Actualizar fondos
        self.lbl_start.bgcolor = start_bg
        self.lbl_end.bgcolor = end_bg

        # Actualizar usando referencias cacheadas (NO por índice)
        self._chip_start_icon.color = text_color
        self._chip_start_text.color = text_color
        self._chip_end_icon.color = text_color
        self._chip_end_text.color = text_color

        # Los chips tienen on_click/on_hover → son controles aislados en Flet.
        # page.update() no los incluye en el diff global: requieren update() explícito.
        self.lbl_start.update()
        self.lbl_end.update()

    def refresh_from_filter_controller(self):
        """
        Sincroniza valores visuales desde FilterController (FASE 0).
        """

        if not self.filter_controller:
            return

        fc = self.filter_controller

        self._internal_sync = True  # 🚨 bloquear recursión

        try:
            # -----------------------------
            # Fechas
            # -----------------------------
            if self.date_filter.start_date != fc.start_date:
                self.date_filter.start_date = fc.start_date
                self._chip_start_text.value = (
                    f"Start: {fc.start_date[:10]}" if fc.start_date else "Start: –"
                )

            if self.date_filter.end_date != fc.end_date:
                self.date_filter.end_date = fc.end_date
                self._chip_end_text.value = (
                    f"End: {fc.end_date[:10]}" if fc.end_date else "End: –"
                )

            # -----------------------------
            # Cliente
            # -----------------------------
            if not self._filters_dirty:
                target_client = fc.client_name or ALL_FILTER_KEY
                if self.client_dropdown.value != target_client:
                    self.client_dropdown.value = target_client
                # ✅ FIX: resetear a UNSET tras la sync (el FC ya tiene el valor correcto;
                # el draft no necesita "saber" el valor actual, solo detectar cambios futuros)
                self._draft_client = _DRAFT_UNSET

            # -----------------------------
            # Producto
            # -----------------------------
            if not self._filters_dirty:
                target_product = fc.product_type or ALL_FILTER_KEY
                if self.product_dropdown.value != target_product:
                    self.product_dropdown.value = target_product
                # ✅ FIX: resetear a UNSET tras la sync
                self._draft_product = _DRAFT_UNSET

        finally:
            # 🔥 SIEMPRE liberar el bloqueo
            self._internal_sync = False


    # ======================================================================
    # EVENTOS
    # ======================================================================
    def _open_picker(self, which: str):
        """Abre DatePicker usando page.overlay + open=True (Flet 0.80.5)."""
        if not mounted_page(self):
            return
        
        if which == "start":
            picker = self.dp_start
        elif which == "end":
            picker = self.dp_end
        else:
            return

        logger.debug("_open_picker(%s) value=%s open=%s", which, picker.value, picker.open)
        # ✅ Forzar ciclo close→open para que Flet detecte el cambio de estado
        if picker.open:
            picker.open = False
            self.page.update()
        picker.open = True
        self.page.update()

    def _on_picker_dismiss(self, which: str):
        """Handle DatePicker dismiss (cancelled without selecting)."""
        logger.debug("_on_picker_dismiss(%s)", which)
        picker = self.dp_start if which == "start" else self.dp_end
        picker.open = False

    def _on_date_change(self, which, value):
        """Actualiza la etiqueta de fecha cuando cambia la selección (usando referencias cacheadas)."""
        logger.debug("_on_date_change(%s, %s)", which, value)
        picker = self.dp_start if which == "start" else self.dp_end
        picker.open = False
        text = self.date_filter.set_date(which, value)
        if which == "start":
            self._chip_start_text.value = f"Start: {text}"
        else:
            self._chip_end_text.value = f"End: {text}"
        # ✅ Flet 0.80.5: Cerrar DatePicker y actualizar chips requiere page.update()
        if mounted_page(self):
            self.page.update()

    def _apply(self, _):
        # 🆕 DRAFT STATE: sincronizar DRAFT → FilterController antes de validar
        # ✅ FIX: comparar contra _DRAFT_UNSET (no contra None)
        # Así "TODOS" (None) también se sincroniza correctamente al FilterController
        if self.filter_controller:
            if self._draft_client is not _DRAFT_UNSET:
                self.filter_controller.set_client(self._draft_client)
            if self._draft_product is not _DRAFT_UNSET:
                self.filter_controller.set_product(self._draft_product)
        self._draft_client = _DRAFT_UNSET
        self._draft_product = _DRAFT_UNSET
        self._filters_dirty = False

        ok, error_msg = self.date_filter.validate()
        if not ok:
            if hasattr(self.page, "notifications"):
                self.page.notifications.show_snackbar(
                    error_msg, severity="warning"
                )
            return
        if self.filter_controller:
            start_iso, end_iso = self.date_filter.get_filter_params()
            self.filter_controller.set_date_range(start_iso, end_iso)
        self.on_filter_applied(None)
        if mounted_page(self):
            self.page.update()
    
    def _apply_client_product_filter(self):
        """
        🚫 DEAD CODE — Draft State Model (2026-03-03)
        Este método ya no se invoca. El flujo nuevo es:
            on_change → _draft_* → _apply() → on_filter_applied()
        Pendiente de eliminación en próxima refactorización.
        """
        pass


    def _clear(self, _):
        """Limpia todos los filtros aplicados."""
        # 1️⃣ Limpiar fechas
        self.date_filter.clear()
        self._chip_start_text.value = "Start: –"
        self._chip_end_text.value = "End: –"
        self.dp_start.value = None
        self.dp_end.value = None

        # 2️⃣ Limpiar filtros de cliente y producto
        # ✅ FIX: Establecer dropdowns a "TODOS" primero para sincronizar el estado interno
        self._internal_sync = True  # Bloquear on_change handlers
        try:
            self.client_dropdown.value = ALL_FILTER_KEY
            self.product_dropdown.value = ALL_FILTER_KEY
        finally:
            self._internal_sync = False
        
        # Limpiar estado en FilterController
        if self.filter_controller:
            self.filter_controller.set_client(None)
            self.filter_controller.set_product(None)
        
        # Limpiar buffers de draft no confirmados
        self._draft_client = _DRAFT_UNSET
        self._draft_product = _DRAFT_UNSET
        self._filters_dirty = False
        
        # 3️⃣ Callback externo
        if self.on_filter_cleared:
            self.on_filter_cleared()

    def _on_client_change(self, e):
        logger.debug("_on_client_change")
        if self._internal_sync:
            return

        value = e.control.value
        client = None if value == ALL_FILTER_KEY else value

        # 🆕 DRAFT STATE: guardar en buffer, NO mutar FilterController ni disparar análisis
        self._draft_client = client
        self._filters_dirty = True

    def _on_product_change(self, e):
        logger.debug("_on_product_change")
        if self._internal_sync:
            return
         
        value = e.control.value
        product = None if value == ALL_FILTER_KEY else value
        # 🆕 DRAFT STATE: guardar en buffer, NO mutar FilterController ni disparar análisis
        self._draft_product = product
        self._filters_dirty = True

    def _quick_range(self, days):
        start, end = self.date_filter.apply_quick_range(days)
        self._update_labels(start, end)

    def _quick_last_months(self, months: int):
        start, end = self.date_filter.apply_last_n_months(months)
        self._update_labels(start, end)


    def _quick_current_week(self):
        start, end = self.date_filter.apply_current_week()
        self._update_labels(start, end)

    def _current_week_to_date(self):
        """Semana actual (hasta hoy)."""
        start, end = self.date_filter.apply_current_week()
        self._update_labels(start, end)

    def _quick_current_quarter(self):
        start, end = self.date_filter.apply_current_quarter()
        self._update_labels(start, end)

    def _current_quarter_to_date(self):
        """Quarter actual (hasta hoy)."""
        start, end = self.date_filter.apply_current_quarter()
        self._update_labels(start, end)

    def _quick_current_semester(self):
        start, end = self.date_filter.apply_current_semester()
        self._update_labels(start, end)

    def _current_semester_to_date(self):
        """Semestre actual (hasta hoy)."""
        start, end = self.date_filter.apply_current_semester()
        self._update_labels(start, end)

    def _quick_month(self):
        start, end = self.date_filter.apply_month_range()
        self._update_labels(start, end)

    def _current_month_to_date(self):
        """Mes actual (hasta hoy)."""
        start, end = self.date_filter.apply_current_month()
        self._update_labels(start, end)

    def _quick_year(self):
        start, end = self.date_filter.apply_year_range()
        self._update_labels(start, end)

    def _current_year_to_date(self):
        """Año actual (hasta hoy)."""
        start, end = self.date_filter.apply_current_year()
        self._update_labels(start, end)

    def _update_labels(self, start, end):
        """Actualiza las etiquetas de fecha con nuevos valores (usando referencias cacheadas)."""
        self._chip_start_text.value = f"Start: {start[:10]}"
        self._chip_end_text.value = f"End: {end[:10]}"
        # ✅ Flet 0.80.5: Auto-update habilitado
        # El caller es responsable de page.update() si es necesario

    def _hover_chip(self, event, is_start: bool):
        """Maneja el hover sobre chips de fecha con colores consistentes."""
        if event.data == "true":
            # Hover: resaltar el chip
            if is_start:
                self.lbl_start.bgcolor = Colors.GREEN_ACCENT
            else:
                self.lbl_end.bgcolor = Colors.RED_ACCENT
        else:
            # Salir del hover: restaurar colores originales
            self._update_chip_colors()
        # ✅ Flet 0.80.5: Auto-update habilitado por defecto
        # NO llamar self.update() desde hover handlers (patrón oficial)

    def _create_hover_handler(self):
        def on_hover_event(e):
            if not mounted_page(self):
                return
    
            is_dark = is_dark_mode(self.page)
            colors = get_apply_filter_colors(is_dark)
    
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
    
            e.control.update()
    
        return on_hover_event

    
    def _create_apply_button(self):
        """Crea el botón 'Aplicar filtro' con colores según el tema inicial (se actualizará en update_theme)."""
        # 🚀 FIX: Usar tema por defecto. Se actualizará correctamente en update_theme().
        # Nota: En Flet 0.80.5+ page.theme_mode es accesible desde __init__() (AGENTS.md § 1.5 R1)
        is_dark = False  # Default (sin acceso a page aún en componente aislado)
        colors = get_apply_filter_colors(is_dark)
        
        self.btn_apply = ft.Button(
            self._apply_label,
            icon=ft.Icons.FILTER_LIST,
            on_click=self._apply,
            bgcolor=colors['bgcolor'],
            color=colors['color'],
            elevation=colors['elevation'],
            on_hover=self._hover_handler,
        )

    def set_applying(self, applying: bool):
        """Marca estado de aplicación de filtros (sin llamar update)."""
        if not self.btn_apply:
            return
        self.btn_apply.disabled = False
        self.btn_apply.text = self._apply_label

