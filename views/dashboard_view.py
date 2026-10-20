"""
Vista del Dashboard principal — Diseño premium v2 (rediseño jerárquico).
"""
import flet as ft
import logging
from datetime import datetime
from theme import is_dark_mode
from components.dashboard_kpi_hero_card import KPIHeroCard
from components.danger_button import create_danger_button
from components.confirm_dialog import create_confirm_dialog
from controllers.dashboard_controller import DashboardController
from controllers.file_import_controller import FileImportController
from utils.ui_dispatch import ui_callback
from utils.notifications import show_notification, NotificationManager
from components.import_flow import run_import_flow
from components.import_demo_modal import download_and_open_template
from views.scrollable_view import ScrollableView
from utils.formatting import format_datetime_us, pluralize

logger = logging.getLogger(__name__)


class DashboardView(ScrollableView):
    """Pantalla Home con KPIs hero, accesos rápidos, importación y limpieza de datos."""

    def __init__(self, page, open_file_picker, go_to_ventas, go_to_leads, go_to_clientes):
        super().__init__(expand=True)
        self._page = page
        self.open_file_picker = open_file_picker
        self.go_to_ventas = go_to_ventas
        self.go_to_leads = go_to_leads
        self.go_to_clientes = go_to_clientes

        # Notifications manager
        self.notifications = NotificationManager(page)

        # File import controller
        self.file_import_controller = FileImportController(
            on_success=ui_callback(page, self._on_import_success),
            on_error=ui_callback(page, self._on_import_error),
            on_start=ui_callback(page, self._on_import_start),
        )

        # --- Referencias para update_theme() ---
        self._header = None
        self._subtitle = None
        self._info_icon = None
        self._status_title = None
        self._status_message = None
        self._info_box = None
        self._hero_cards = []           # 3 grandes tarjetas KPI
        self._danger_buttons = []
        self._action_tile_data = []     # dicts con inner + colores por tile
        self._activity_panel_container = None

        # Referencia a diálogo reactivo
        self._confirm_dialog = None
        self._detected_prefix = None

        # Construir UI inicial
        self._build_ui()

    def _format_import_date(self, raw: str | None) -> str:
        """Formatea la fecha de importación para mostrar en chips."""
        if not raw:
            return "—"
        try:
            dt = datetime.fromisoformat(raw)
            return format_datetime_us(dt)
        except Exception:
            return raw[:16] if len(raw) > 16 else raw

    def _build_ui(self):
        snapshot = DashboardController.get_dashboard_kpi_snapshot()
        last_import_text = self._format_import_date(snapshot.last_import)

        # =====================
        # Header
        # =====================
        self._header = ft.Text(
            "Dashboard",
            size=32,
            weight=ft.FontWeight.W_700,
            color=ft.Colors.ON_SURFACE,
        )
        self._subtitle = ft.Text(
            "Overview and quick access to the main features.",
            size=16,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )

        # =====================
        # Sección 1 — 3 Hero KPI Cards
        # =====================
        hero_card_1 = KPIHeroCard(
            icon=ft.Icons.RECEIPT_LONG,
            accent_color=ft.Colors.BLUE,
            main_value=str(snapshot.sales_rows),
            main_label="Sales records",
            chips=[
                {
                    "icon": ft.Icons.GROUP,
                    "text": pluralize(snapshot.clients_rows, "client"),
                    "color": ft.Colors.AMBER,
                },
            ],
            theme_mode=self._page.theme_mode,
        )

        hero_card_2 = KPIHeroCard(
            icon=ft.Icons.PERSON_ADD,
            accent_color=ft.Colors.TEAL,
            main_value=str(snapshot.total_leads),
            main_label="Total leads",
            chips=[
                {
                    "icon": ft.Icons.TRENDING_UP,
                    "text": f"{snapshot.leads_conversion_rate}% conv.",
                    "color": ft.Colors.GREEN,
                },
                {
                    "icon": ft.Icons.CALENDAR_TODAY,
                    "text": pluralize(snapshot.leads_with_meeting, "meeting"),
                    "color": ft.Colors.INDIGO,
                },
            ],
            theme_mode=self._page.theme_mode,
        )

        status_icon = ft.Icons.CHECK_CIRCLE if snapshot.has_data else ft.Icons.INFO
        status_accent = ft.Colors.GREEN if snapshot.has_data else ft.Colors.GREY
        hero_card_3 = KPIHeroCard(
            icon=status_icon,
            accent_color=status_accent,
            main_value="Active" if snapshot.has_data else "No data",
            main_label="System status",
            chips=[
                {
                    "icon": ft.Icons.UPLOAD,
                    "text": f"Imported: {last_import_text}",
                    "color": ft.Colors.PURPLE,
                },
                {
                    "icon": ft.Icons.SCHEDULE,
                    "text": f"{pluralize(snapshot.leads_this_month, 'lead')} this month",
                    "color": ft.Colors.ORANGE,
                },
            ],
            theme_mode=self._page.theme_mode,
            trend_icon=ft.Icons.VERIFIED if snapshot.has_data else ft.Icons.CLOUD_UPLOAD,
        )

        self._hero_cards = [hero_card_1, hero_card_2, hero_card_3]
        hero_row = ft.Row(self._hero_cards, spacing=16)

        # =====================
        # Sección 2 — Mosaicos de acción premium
        # =====================
        self._action_tile_data = []
        tile_import_outer = self._build_action_tile(
            ft.Icons.FILE_UPLOAD,
            "Import data",
            "Upload a CSV or Excel file",
            lambda _: self._handle_import_click(),
        )
        tile_ventas_outer = self._build_action_tile(
            ft.Icons.ANALYTICS,
            "Sales analytics",
            "View reports and trends",
            lambda _: self.go_to_ventas(),
        )
        tile_leads_outer = self._build_action_tile(
            ft.Icons.PERSON_ADD,
            "Leads",
            "Marketing and conversion funnel",
            lambda _: self.go_to_leads(),
        )
        tile_clientes_outer = self._build_action_tile(
            ft.Icons.GROUP,
            "Clients",
            "Manage profiles and history",
            lambda _: self.go_to_clientes(),
        )
        tiles_row = ft.Row(
            [tile_import_outer, tile_ventas_outer, tile_leads_outer, tile_clientes_outer],
            spacing=12,
        )

        # =====================
        # Sección 3 — Fila inferior (info sistema + actividad)
        # =====================
        if snapshot.has_data:
            status_title_val = "System active"
            status_msg_val = (
                f"{pluralize(snapshot.sales_rows, 'sale')} · {pluralize(snapshot.clients_rows, 'client')}\n"
                f"Last import: {last_import_text}"
            )
            info_bg = ft.Colors.with_opacity(0.06, ft.Colors.GREEN)
        else:
            status_title_val = "No data yet"
            status_msg_val = (
                "No data has been loaded.\n"
                "Import a CSV or Excel file to get started."
            )
            info_bg = ft.Colors.with_opacity(0.04, ft.Colors.GREY)

        self._info_icon = ft.Icon(
            ft.Icons.INFO_OUTLINE, size=28, color=ft.Colors.ON_SURFACE_VARIANT
        )
        self._status_title = ft.Text(
            status_title_val,
            size=16,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.ON_SURFACE,
        )
        self._status_message = ft.Text(
            status_msg_val,
            size=14,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        self._info_box = ft.Container(
            padding=ft.Padding.symmetric(horizontal=20, vertical=14),
            border_radius=14,
            bgcolor=info_bg,
            content=ft.Row(
                [
                    self._info_icon,
                    ft.Column(
                        [self._status_title, self._status_message],
                        spacing=4,
                    ),
                ],
                spacing=16,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        )

        clear_sales_btn = create_danger_button(
            text="Clear sales",
            on_click=lambda _: self._show_confirmation("sales"),
            page_or_theme_mode=self._page,
        )
        clear_clients_btn = create_danger_button(
            text="Clear clients",
            on_click=lambda _: self._show_confirmation("clients"),
            page_or_theme_mode=self._page,
        )
        clear_leads_btn = create_danger_button(
            text="Clear leads",
            on_click=lambda _: self._show_confirmation("leads"),
            page_or_theme_mode=self._page,
        )
        self._danger_buttons = [clear_sales_btn, clear_clients_btn, clear_leads_btn]

        activity_panel = self._build_activity_panel(snapshot)

        import_guide = self._build_import_guide()

        left_col = ft.Column(
            [
                self._info_box,
                ft.Container(height=12),
                import_guide,
                ft.Container(height=16),
                ft.Row([clear_sales_btn, clear_clients_btn, clear_leads_btn], spacing=12),
            ],
            spacing=0,
            expand=2,
        )
        right_col = ft.Column(
            [activity_panel],
            spacing=0,
            expand=3,
        )
        bottom_row = ft.Row(
            [left_col, right_col],
            spacing=20,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        # =====================
        # Layout final
        # =====================
        self.set_controls([
            self._header,
            self._subtitle,
            ft.Container(height=24),
            hero_row,
            ft.Container(height=24),
            tiles_row,
            ft.Container(height=24),
            bottom_row,
            ft.Container(height=32),
        ])

    def _build_action_tile(self, icon, title, desc, on_click):
        """Construye un mosaico de acción premium con hover animado."""
        td = {
            "base_light": ft.Colors.BLUE_900,
            "base_dark": ft.Colors.BLUE_900,
            "hover_light": ft.Colors.BLUE_800,
            "hover_dark": ft.Colors.BLUE_800,
        }

        def on_hover(e, _td=td):
            _is_dark = is_dark_mode(self._page)
            base = _td["base_dark"] if _is_dark else _td["base_light"]
            hover = _td["hover_dark"] if _is_dark else _td["hover_light"]
            e.control.scale = 1.03 if e.data else 1.0
            e.control.bgcolor = hover if e.data else base

        initial_bg = (
            td["base_dark"] if is_dark_mode(self._page) else td["base_light"]
        )
        inner = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(
                            icon, size=44, color=ft.Colors.AMBER_300
                        ),
                        bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.AMBER_300),
                        width=72,
                        height=72,
                        border_radius=36,
                        alignment=ft.Alignment.CENTER,
                    ),
                    ft.Text(
                        title,
                        size=17,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.WHITE,
                    ),
                    ft.Text(
                        desc,
                        size=13,
                        color=ft.Colors.with_opacity(0.9, ft.Colors.WHITE),
                        text_align=ft.TextAlign.CENTER,
                        max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                ],
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
                expand=True,
            ),
            bgcolor=initial_bg,
            border_radius=16,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=24,
                offset=ft.Offset(0, 8),
                color=ft.Colors.with_opacity(0.30, ft.Colors.BLACK),
            ),
            on_click=on_click,
            ink=True,
            scale=1.0,
            animate=ft.Animation(200, ft.AnimationCurve.DECELERATE),
            animate_scale=ft.Animation(200, ft.AnimationCurve.DECELERATE),
            on_hover=on_hover,
        )
        td["inner"] = inner
        self._action_tile_data.append(td)
        return ft.Container(content=inner, expand=True, height=160)

    def _build_activity_panel(self, snapshot) -> ft.Container:
        """Construye el panel de actividad reciente."""
        activities = []
        if snapshot.has_data:
            activities.append({
                "icon": ft.Icons.RECEIPT_LONG, "color": ft.Colors.BLUE,
                "text": pluralize(snapshot.sales_rows, "sales record"),
                "sub": "Sales imported into the system",
            })
        if snapshot.clients_rows > 0:
            activities.append({
                "icon": ft.Icons.GROUP, "color": ft.Colors.AMBER,
                "text": pluralize(snapshot.clients_rows, "registered client"),
                "sub": "Active client base",
            })
        if snapshot.total_leads > 0:
            activities.append({
                "icon": ft.Icons.PERSON_ADD, "color": ft.Colors.TEAL,
                "text": f"{pluralize(snapshot.total_leads, 'lead')} in the system",
                "sub": f"Conversion: {snapshot.leads_conversion_rate}%",
            })
        if snapshot.last_import:
            activities.append({
                "icon": ft.Icons.UPLOAD_FILE, "color": ft.Colors.PURPLE,
                "text": "Last import",
                "sub": self._format_import_date(snapshot.last_import),
            })
        if not activities:
            activities.append({
                "icon": ft.Icons.INFO_OUTLINE, "color": ft.Colors.GREY,
                "text": "No recent activity.",
                "sub": "Import data to get started",
            })

        item_controls = []
        for i, act in enumerate(activities):
            item_controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(act["icon"], size=18, color=act["color"]),
                                bgcolor=ft.Colors.with_opacity(0.10, act["color"]),
                                width=36,
                                height=36,
                                border_radius=18,
                                alignment=ft.Alignment.CENTER,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        act["text"],
                                        size=12,
                                        color=ft.Colors.ON_SURFACE,
                                        weight=ft.FontWeight.W_500,
                                    ),
                                    ft.Text(
                                        act["sub"],
                                        size=11,
                                        color=ft.Colors.ON_SURFACE_VARIANT,
                                    ),
                                ],
                                spacing=1,
                                expand=True,
                            ),
                        ],
                        spacing=12,
                    ),
                    padding=ft.Padding.symmetric(vertical=8, horizontal=4),
                )
            )
            if i < len(activities) - 1:
                item_controls.append(
                    ft.Divider(
                        height=1,
                        color=ft.Colors.with_opacity(0.08, ft.Colors.OUTLINE),
                    )
                )

        is_dark = is_dark_mode(self._page)
        panel_bg = ft.Colors.with_opacity(
            0.08 if is_dark else 0.04, ft.Colors.ON_SURFACE
        )
        self._activity_panel_container = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Recent activity",
                        size=15,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE,
                    ),
                    ft.Container(height=8),
                    ft.Column(item_controls, spacing=0),
                ],
                spacing=0,
            ),
            padding=ft.Padding.all(16),
            border_radius=14,
            bgcolor=panel_bg,
            expand=True,
        )
        return self._activity_panel_container

    def refresh(self):
        """Reconstruye la UI con datos actualizados."""
        self._build_ui()
        if self._page:
            self.update_theme()
            self.update()

    def update_theme(self):
        """Actualiza el tema de la vista. Caller es responsable de page.update()."""
        if not self._page:
            return

        from theme import get_text_color, get_subtitle_color
        _theme = self._page.theme_mode

        # Header y subtitle (R9: incluir aunque usen colores semánticos)
        if self._header:
            self._header.color = get_text_color(_theme)
        if self._subtitle:
            self._subtitle.color = get_subtitle_color(_theme)

        # Textos del info box (R9)
        if self._status_title:
            self._status_title.color = get_text_color(_theme)
        if self._status_message:
            self._status_message.color = get_subtitle_color(_theme)
        if self._info_icon:
            self._info_icon.color = get_subtitle_color(_theme)

        # Hero KPI cards
        for card in getattr(self, "_hero_cards", []):
            if hasattr(card, "update_theme"):
                try:
                    card.update_theme()
                except RuntimeError:
                    pass

        # Action tiles — actualizar bgcolor según tema actual
        _is_dark = is_dark_mode(self._page)
        for td in getattr(self, "_action_tile_data", []):
            if "inner" in td:
                td["inner"].bgcolor = (
                    td["base_dark"] if _is_dark else td["base_light"]
                )

        # Info box bgcolor (refleja estado del sistema)
        if self._info_box and self._status_title:
            if "activo" in (self._status_title.value or "").lower():
                self._info_box.bgcolor = ft.Colors.with_opacity(0.06, ft.Colors.GREEN)
            else:
                self._info_box.bgcolor = ft.Colors.with_opacity(0.04, ft.Colors.GREY)

        # Activity panel bgcolor
        if self._activity_panel_container:
            self._activity_panel_container.bgcolor = ft.Colors.with_opacity(
                0.08 if _is_dark else 0.04, ft.Colors.ON_SURFACE
            )

        # Danger buttons
        for btn in getattr(self, "_danger_buttons", []):
            if hasattr(btn, "update_theme"):
                btn.update_theme(self._page)

        # Confirm dialog (si está abierto)
        if (
            self._confirm_dialog
            and getattr(self._confirm_dialog, "open", False)
            and hasattr(self._confirm_dialog, "update_theme")
        ):
            self._confirm_dialog.update_theme()

        # ✅ NO llamar page.update() aquí — el caller es responsable

    def _build_import_guide(self):
        """Construye la guía de importación inline con ExpansionTiles."""

        def _field_chip(text, required=False):
            return ft.Container(
                content=ft.Text(
                    text, size=12,
                    weight=ft.FontWeight.W_600 if required else ft.FontWeight.W_400,
                    color=ft.Colors.ON_PRIMARY_CONTAINER if required
                    else ft.Colors.ON_SURFACE_VARIANT,
                ),
                bgcolor=ft.Colors.PRIMARY_CONTAINER if required else None,
                border=None if required
                else ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=16,
                padding=ft.Padding.symmetric(horizontal=10, vertical=3),
            )

        # --- Leads tile ---
        leads_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text(h, size=11, weight=ft.FontWeight.W_600))
                for h in ["external_id", "created_at", "source", "status",
                           "meeting_date", "client_id"]
            ],
            rows=[
                ft.DataRow(cells=[ft.DataCell(ft.Text(c, size=11)) for c in row])
                for row in [
                    ["L001", "2026-03-01", "Facebook", "new", "2026-03-05", "C001"],
                    ["L002", "2026-03-03", "Google", "contacted", "—", "C002"],
                    ["L003", "2026-03-07", "LinkedIn", "meeting", "2026-03-12", "—"],
                ]
            ],
            column_spacing=14,
        )

        leads_content = ft.Column([
            ft.Row(scroll=ft.ScrollMode.AUTO, controls=[leads_table]),
            ft.Container(height=8),
            ft.Row([
                ft.Text("Required:", size=11, weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE),
                _field_chip("created_at", True),
                _field_chip("source", True),
                ft.Text("  Optional:", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                _field_chip("status"),
                _field_chip("external_id"),
                _field_chip("meeting_date"),
                _field_chip("client_id"),
            ], spacing=6, wrap=True),
            ft.Container(height=8),
            ft.OutlinedButton(
                "Download leads template (.csv)",
                icon=ft.Icons.DOWNLOAD,
                on_click=lambda _: download_and_open_template("leads"),
            ),
        ], spacing=0)

        # --- Ventas tile ---
        sales_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text(h, size=11, weight=ft.FontWeight.W_600))
                for h in ["client_name", "client_id", "product_type", "price", "date"]
            ],
            rows=[
                ft.DataRow(cells=[ft.DataCell(ft.Text(c, size=11)) for c in row])
                for row in [
                    ["Alpha Inc.", "C001", "Product A", "1200", "2026-03-05"],
                    ["Alpha Inc.", "C001", "Product B", "850", "2026-03-12"],
                    ["Beta Corp", "C002", "Product A", "2400", "2026-03-08"],
                ]
            ],
            column_spacing=14,
        )

        sales_content = ft.Column([
            ft.Row(scroll=ft.ScrollMode.AUTO, controls=[sales_table]),
            ft.Container(height=8),
            ft.Row([
                ft.Text("Required:", size=11, weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE),
                _field_chip("client_name", True),
                _field_chip("client_id", True),
                _field_chip("product_type", True),
                _field_chip("price", True),
                ft.Text("  Optional:", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                _field_chip("date"),
            ], spacing=6, wrap=True),
            ft.Container(height=8),
            ft.OutlinedButton(
                "Download sales template (.csv)",
                icon=ft.Icons.DOWNLOAD,
                on_click=lambda _: download_and_open_template("sales"),
            ),
        ], spacing=0)

        # --- Inversión Marketing tile ---
        spend_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text(h, size=11, weight=ft.FontWeight.W_600))
                for h in ["source", "amount", "date"]
            ],
            rows=[
                ft.DataRow(cells=[ft.DataCell(ft.Text(c, size=11)) for c in row])
                for row in [
                    ["Facebook", "1200.00", "2026-03-01"],
                    ["Google", "2500.00", "2026-03-01"],
                    ["LinkedIn", "800.00", "2026-03-15"],
                ]
            ],
            column_spacing=14,
        )

        spend_content = ft.Column([
            ft.Row(scroll=ft.ScrollMode.AUTO, controls=[spend_table]),
            ft.Container(height=8),
            ft.Row([
                ft.Text("Required:", size=11, weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE),
                _field_chip("source", True),
                _field_chip("amount", True),
                ft.Text("  Optional:", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                _field_chip("date"),
            ], spacing=6, wrap=True),
            ft.Container(height=8),
            ft.OutlinedButton(
                "Download marketing spend template (.csv)",
                icon=ft.Icons.DOWNLOAD,
                on_click=lambda _: download_and_open_template("marketing_spend"),
            ),
        ], spacing=0)

        # --- ExpansionTiles ---
        self._leads_tile = ft.ExpansionTile(
            title="Leads format",
            subtitle="created_at, source, status...",
            leading=ft.Icon(ft.Icons.PERSON_ADD, color=ft.Colors.TEAL),
            controls=[ft.Container(content=leads_content, padding=ft.Padding.only(
                left=16, right=16, bottom=12))],
            collapsed_bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            shape=ft.RoundedRectangleBorder(radius=12),
            collapsed_shape=ft.RoundedRectangleBorder(radius=12),
            maintain_state=True,
        )

        self._sales_tile = ft.ExpansionTile(
            title="Sales format",
            subtitle="client_name, client_id, price...",
            leading=ft.Icon(ft.Icons.RECEIPT_LONG, color=ft.Colors.BLUE),
            controls=[ft.Container(content=sales_content, padding=ft.Padding.only(
                left=16, right=16, bottom=12))],
            collapsed_bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            shape=ft.RoundedRectangleBorder(radius=12),
            collapsed_shape=ft.RoundedRectangleBorder(radius=12),
            maintain_state=True,
        )

        self._spend_tile = ft.ExpansionTile(
            title="Marketing spend format",
            subtitle="source, amount, date...",
            leading=ft.Icon(ft.Icons.ATTACH_MONEY, color=ft.Colors.ORANGE),
            controls=[ft.Container(content=spend_content, padding=ft.Padding.only(
                left=16, right=16, bottom=12))],
            collapsed_bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            shape=ft.RoundedRectangleBorder(radius=12),
            collapsed_shape=ft.RoundedRectangleBorder(radius=12),
            maintain_state=True,
        )

        return ft.Column([
            ft.Text("Import guide", size=14, weight=ft.FontWeight.W_600,
                    color=ft.Colors.ON_SURFACE),
            ft.Text("CSV (.csv) and Excel (.xlsx) — first row = column headers",
                    size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Container(height=8),
            self._leads_tile,
            ft.Container(height=6),
            self._sales_tile,
            ft.Container(height=6),
            self._spend_tile,
        ], spacing=0)

    def _handle_import_click(self):
        # Llamar al callback de importación (que abre FilePicker async)
        logger.info("[DashboardView] Import button clicked")
        self._page.run_task(self._pick_and_import_file)

    async def _pick_and_import_file(self):
        """Abre FilePicker e importa el archivo detectando el tipo automáticamente."""
        await run_import_flow(
            page=self._page,
            controller=self.file_import_controller,
            notifications=self.notifications,
            set_detected_prefix=lambda prefix: setattr(self, "_detected_prefix", prefix),
        )

    def _show_confirmation(self, table_type: str):
        """Muestra diálogo de confirmación para vaciar tabla."""
        if table_type == "sales":
            title = "Clear sales"
            message = "Are you sure you want to delete\nall sales data?"
            on_confirm = self._clear_sales
        elif table_type == "clients":
            title = "Clear clients"
            message = (
                "Are you sure you want to delete all client data?\n\n"
                "⚠ This also deletes all sales for those clients."
            )
            on_confirm = self._clear_clients
        else:
            title = "Clear leads"
            message = "Are you sure you want to delete\nall lead data?"
            on_confirm = self._clear_leads
        
        # Crear y guardar referencia al diálogo (Contrato 1.5 R2)
        self._confirm_dialog = create_confirm_dialog(
            self._page,
            title=title,
            message=message,
            on_confirm=on_confirm,
        )
        
        self._page.show_dialog(self._confirm_dialog)
        
    def _clear_sales(self, e=None):
        """Ejecuta la limpieza de ventas."""
        success, message = DashboardController.clear_sales()
        notification_type = "success" if success else "error"
        show_notification(self._page, message, notification_type)
        if success:
            self.refresh()
    
    def _clear_clients(self, e=None):
        """Ejecuta la limpieza de clientes."""
        success, message = DashboardController.clear_clients()
        notification_type = "success" if success else "error"
        show_notification(self._page, message, notification_type)
        if success:
            self.refresh()

    def _clear_leads(self, e=None):
        """Ejecuta la limpieza de leads."""
        success, message = DashboardController.clear_leads()
        notification_type = "success" if success else "error"
        show_notification(self._page, message, notification_type)
        if success:
            self.refresh()
    
    # ============================================================
    # Import handlers
    # ============================================================
    
    def handle_import_file(self, file_path: str):
        """Recibe un archivo seleccionado y ejecuta la importación."""
        logger.info(f"[DashboardView] handle_import_file called with: {file_path}")
        
        if not file_path:
            logger.warning("[DashboardView] No file path provided")
            self.notifications.show_file_selected_error()
            return
        
        self.file_import_controller.import_file(file_path)
    
    def _on_import_start(self):
        """Callback cuando inicia la importación."""
        self.notifications.show_importing_file()
    
    def _on_import_success(self, message: str):
        """Callback cuando la importación es exitosa."""
        if self._detected_prefix:
            message = f"{self._detected_prefix} detected \u2192 {message}"
            self._detected_prefix = None
        self.refresh()
        self.notifications.show_import_success(message)
    
    def _on_import_error(self, message: str):
        """Callback cuando hay error en la importación."""
        self.notifications.show_import_error(message)
