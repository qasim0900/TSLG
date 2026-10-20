"""
Componente de formulario de cliente reutilizable.
Usado para añadir y editar clientes.

Soporta cambio de tema mediante update_theme() (Patrón A).
"""

import flet as ft
from theme import (
    get_text_color,
    get_subtitle_color,
    get_label_text_style,
    get_input_text_style,
)
from models.client_validators import (
    validate_name,
    validate_cif,
    validate_email,
    validate_contact,
)
from models.lead_manager import VALID_LEAD_STATUSES
from utils import normalize_text
from utils.notifications import show_notification
from utils.ui_dispatch import mounted_page


class ClientForm(ft.Container):
    """
    Formulario de cliente con soporte de cambio de tema.

    - __init__: construye UI
    - update_theme(): muta colores sin reconstruir
    """

    def __init__(
        self,
        *,
        title: str,
        subtitle_text: str,
        on_save,
        on_cancel,
        initial_values: dict = None,
        lead_values: dict = None,
        on_save_lead=None,
        theme_mode=ft.ThemeMode.LIGHT,
    ):
        super().__init__()
        self.on_save = on_save
        self.on_cancel = on_cancel
        self.values = initial_values or {}
        self._lead_values = lead_values
        self._on_save_lead = on_save_lead

        self.padding = 20
        self.border_radius = 0

        # 🔐 Referencias mutables (Patrón A)
        self._title_text = None
        self._subtitle_text = None
        self._labels = []  # TextField labels
        self._btn_back = None

        self._title = title
        self._subtitle = subtitle_text

        # Lead section references
        self._lead_section_title = None
        self._lead_no_lead_text = None
        self._lead_source_field = None
        self._lead_created_field = None
        self._lead_status_dropdown = None
        self._lead_meeting_field = None
        self._lead_meeting_picker = None  # ft.DatePicker for meeting date
        self._lead_labels = []  # lead TextFields for theme update

        # 🔐 Cachea helpers de TextStyle (R8: evitar recreación)
        self._label_style_cache = None
        self._input_style_cache = None

        # Build UI in __init__ (Tipo A — auto-update es suficiente, no did_mount doble)
        self._build_ui(theme_mode)

    # ------------------------------------------------------------------
    def did_mount(self):
        """Actualiza tema al montarse y registra DatePicker en overlay."""
        self.update_theme(self.page.theme_mode)
        # Register meeting DatePicker on the page overlay
        if self._lead_meeting_picker and self.page:
            if self._lead_meeting_picker not in self.page.overlay:
                self.page.overlay.append(self._lead_meeting_picker)
                self.page.update()

    def will_unmount(self):
        """Remove the meeting DatePicker from the page overlay."""
        if self._lead_meeting_picker and self.page:
            try:
                self.page.overlay.remove(self._lead_meeting_picker)
            except ValueError:
                pass

    def _build_ui(self, theme_mode=None):
        if theme_mode is None:
            theme_mode = getattr(mounted_page(self), "theme_mode", None) or ft.ThemeMode.LIGHT

        title_color = get_text_color(theme_mode)
        subtitle_color = get_subtitle_color(theme_mode)

        self._labels.clear()

        # 🔐 Cachea TextStyle helpers (R8)
        self._label_style_cache = get_label_text_style(theme_mode)
        self._input_style_cache = get_input_text_style(theme_mode)

        # Campos del formulario
        self.name = ft.TextField(
            label="Name",
            value=normalize_text(self.values.get("name")),
            label_style=self._label_style_cache,
            text_style=self._input_style_cache,
            border_radius=8,
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.PRIMARY,
        )
        self.cif = ft.TextField(
            label="Tax ID (CIF/NIF)",
            value=normalize_text(self.values.get("cif")),
            label_style=self._label_style_cache,
            text_style=self._input_style_cache,
            border_radius=8,
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.PRIMARY,
        )
        self.address = ft.TextField(
            label="Address",
            value=normalize_text(self.values.get("address")),
            label_style=self._label_style_cache,
            text_style=self._input_style_cache,
            border_radius=8,
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.PRIMARY,
        )
        self.contact = ft.TextField(
            label="Contact person",
            value=normalize_text(self.values.get("contact")),
            label_style=self._label_style_cache,
            text_style=self._input_style_cache,
            border_radius=8,
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.PRIMARY,
        )
        self.email = ft.TextField(
            label="Email",
            value=normalize_text(self.values.get("email")),
            label_style=self._label_style_cache,
            text_style=self._input_style_cache,
            border_radius=8,
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.PRIMARY,
        )

        self._labels.extend(
            [self.name, self.cif, self.address, self.contact, self.email]
        )

        # Textos
        self._title_text = ft.Text(
            self._title,
            size=22,
            weight=ft.FontWeight.BOLD,
            color=title_color,
        )

        self._subtitle_text = ft.Text(
            self._subtitle,
            size=14,
            color=subtitle_color,
        )

        # Botón volver
        self._btn_back = ft.IconButton(
            icon=ft.Icons.ARROW_BACK,
            icon_color=title_color,
            on_click=lambda _: self.on_cancel(),
            tooltip="Back to the client list",
        )

        def handle_save(e):
            # Skip si ningún campo cambió (None-safe via normalize_text)
            if (
                normalize_text(self.name.value) == normalize_text(self.values.get("name"))
                and normalize_text(self.cif.value) == normalize_text(self.values.get("cif"))
                and normalize_text(self.address.value) == normalize_text(self.values.get("address"))
                and normalize_text(self.contact.value) == normalize_text(self.values.get("contact"))
                and normalize_text(self.email.value) == normalize_text(self.values.get("email"))
            ):
                show_notification(self.page, "No changes to save.", "info")
                return

            # Fix 4: Limpiar errores previos
            for field in self._labels:
                field.error = None

            # Fix 4: Validación inline
            has_error = False
            if not validate_name(self.name.value):
                self.name.error = "The name must have at least 2 characters."
                has_error = True
            if not validate_cif(self.cif.value):
                self.cif.error = "The tax ID (CIF/NIF) must have 7 to 12 letters or digits."
                has_error = True
            if not validate_email(self.email.value):
                self.email.error = "Enter a valid email address."
                has_error = True
            if not validate_contact(self.contact.value):
                self.contact.error = "The contact name must have at least 2 characters."
                has_error = True
            if has_error:
                show_notification(self.page, "Fix the fields marked in red.", "warning")
                return  # Auto-update muestra error

            self.on_save(
                self.name.value,
                self.cif.value,
                self.address.value,
                self.contact.value,
                self.email.value,
            )

        header_row = ft.Row(
            [self._btn_back, self._title_text],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # --- Lead Information panel (right column) ---
        lead_panel = self._build_lead_panel(theme_mode)

        # --- Client sub-card (left column) ---
        client_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "Client details",
                        size=16,
                        weight=ft.FontWeight.W_600,
                        color=ft.Colors.ON_SURFACE,
                    ),
                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    self.name,
                    self.cif,
                    self.address,
                    self.contact,
                    self.email,
                    ft.Container(height=4),
                    ft.Row(
                        [
                            ft.Button(
                                "Save client",
                                icon=ft.Icons.SAVE,
                                on_click=handle_save,
                                style=ft.ButtonStyle(
                                    shape=ft.RoundedRectangleBorder(radius=8)
                                ),
                            ),
                            ft.TextButton(
                                "Cancel",
                                on_click=lambda _: self.on_cancel(),
                            ),
                        ]
                    ),
                ],
                spacing=16,
            ),
            padding=20,
            border_radius=12,
            bgcolor=ft.Colors.SURFACE,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            expand=2,
        )

        # --- Main centered card ---
        main_card = ft.Container(
            alignment=ft.Alignment(0, 0),
            content=ft.Container(
                width=1100,
                padding=24,
                border_radius=16,
                bgcolor=ft.Colors.SURFACE,
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                shadow=ft.BoxShadow(
                    blur_radius=20,
                    spread_radius=1,
                    color=ft.Colors.with_opacity(0.08, ft.Colors.BLACK),
                    offset=ft.Offset(0, 6),
                ),
                content=ft.Row(
                    [client_panel, lead_panel],
                    spacing=40,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
            ),
        )

        self.content = ft.Column(
            [
                header_row,
                self._subtitle_text,
                ft.Container(height=16),
                main_card,
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

        self.bgcolor = ft.Colors.SURFACE_CONTAINER

    # ------------------------------------------------------------------

    def _build_lead_panel(self, theme_mode):
        """Builds the lead information panel as a Container for side-by-side layout."""
        self._lead_labels.clear()

        # No lead data — show informational text
        if self._lead_values is None:
            self._lead_section_title = None
            self._lead_no_lead_text = ft.Text(
                "This client has no linked lead.",
                italic=True,
                color=ft.Colors.ON_SURFACE_VARIANT,
            )
            return ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "Lead information",
                            size=16,
                            weight=ft.FontWeight.W_600,
                            color=ft.Colors.ON_SURFACE,
                        ),
                        ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                        self._lead_no_lead_text,
                    ],
                    spacing=16,
                ),
                padding=20,
                border_radius=12,
                bgcolor=ft.Colors.SURFACE,
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                expand=1,
            )

        self._lead_no_lead_text = None

        self._lead_section_title = ft.Text(
            "Lead information",
            size=16,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.ON_SURFACE,
        )

        # Read-only fields
        self._lead_source_field = ft.TextField(
            label="Source",
            value=normalize_text(self._lead_values.get("source")),
            read_only=True,
            label_style=self._label_style_cache,
            text_style=self._input_style_cache,
            border_radius=8,
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.PRIMARY,
        )
        self._lead_created_field = ft.TextField(
            label="Lead created",
            value=normalize_text(self._lead_values.get("created_at")),
            read_only=True,
            label_style=self._label_style_cache,
            text_style=self._input_style_cache,
            border_radius=8,
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.PRIMARY,
        )

        # Editable fields
        current_status = normalize_text(self._lead_values.get("status")) or ""
        status_options = [
            ft.dropdown.Option(key=s, text=s.capitalize())
            for s in sorted(VALID_LEAD_STATUSES)
        ]
        self._lead_status_dropdown = ft.Dropdown(
            label="Lead status",
            value=current_status.lower() if current_status else None,
            options=status_options,
            label_style=self._label_style_cache,
            text_style=self._input_style_cache,
            border_radius=8,
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.PRIMARY,
        )

        meeting_val = self._lead_values.get("meeting_date") or ""
        meeting_normalized = normalize_text(meeting_val)
        self._lead_meeting_field = ft.TextField(
            label="Meeting date",
            value=meeting_normalized,
            read_only=True,
            label_style=self._label_style_cache,
            text_style=self._input_style_cache,
            border_radius=8,
            border_color=ft.Colors.OUTLINE_VARIANT,
            focused_border_color=ft.Colors.PRIMARY,
            expand=True,
        )

        # Parse initial date for picker value
        import datetime as _dt
        picker_initial = None
        if meeting_normalized and len(meeting_normalized) >= 10:
            try:
                picker_initial = _dt.datetime.fromisoformat(meeting_normalized[:10])
            except ValueError:
                pass

        self._lead_meeting_picker = ft.DatePicker(
            value=picker_initial,
            on_change=self._on_meeting_date_change,
            on_dismiss=self._on_meeting_picker_dismiss,
        )
        self._lead_meeting_pick_btn = ft.IconButton(
            icon=ft.Icons.CALENDAR_MONTH,
            tooltip="Pick a date",
            on_click=lambda _: self._open_meeting_picker(),
        )
        self._lead_meeting_clear_btn = ft.IconButton(
            icon=ft.Icons.CLEAR,
            tooltip="Clear date",
            icon_size=18,
            on_click=self._clear_meeting_date,
        )

        self._lead_labels = [
            self._lead_source_field,
            self._lead_created_field,
            self._lead_meeting_field,
        ]

        return ft.Container(
            content=ft.Column(
                [
                    self._lead_section_title,
                    ft.Divider(height=1, color=ft.Colors.OUTLINE_VARIANT),
                    self._lead_source_field,
                    self._lead_created_field,
                    self._lead_status_dropdown,
                    ft.Row(
                        [
                            self._lead_meeting_field,
                            self._lead_meeting_pick_btn,
                            self._lead_meeting_clear_btn,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(height=4),
                    ft.Row(
                        [
                            ft.OutlinedButton(
                                "Save lead",
                                icon=ft.Icons.SAVE,
                                on_click=self._handle_save_lead,
                                style=ft.ButtonStyle(
                                    shape=ft.RoundedRectangleBorder(radius=8)
                                ),
                            ),
                        ]
                    ),
                ],
                spacing=16,
            ),
            padding=20,
            border_radius=12,
            bgcolor=ft.Colors.SURFACE,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            expand=1,
        )

    # ------------------------------------------------------------------
    # Meeting DatePicker helpers
    # ------------------------------------------------------------------

    def _open_meeting_picker(self):
        if not mounted_page(self) or not self._lead_meeting_picker:
            return
        if self._lead_meeting_picker.open:
            self._lead_meeting_picker.open = False
            self.page.update()
        self._lead_meeting_picker.open = True
        self.page.update()

    def _on_meeting_date_change(self, e):
        selected = e.control.value
        if selected:
            self._lead_meeting_field.value = selected.strftime("%Y-%m-%d")
        e.control.open = False
        if mounted_page(self):
            self.page.update()

    def _on_meeting_picker_dismiss(self, e):
        e.control.open = False

    def _clear_meeting_date(self, _):
        self._lead_meeting_field.value = ""
        if self._lead_meeting_picker:
            self._lead_meeting_picker.value = None

    def _handle_save_lead(self, e):
        """Saves lead status and meeting_date via on_save_lead callback."""
        if self._lead_values is None or not self._on_save_lead:
            show_notification(self.page, "This client has no linked lead.", "warning")
            return

        lead_id = self._lead_values.get("id")
        if not lead_id:
            show_notification(self.page, "Lead ID is not available.", "error")
            return

        new_status = normalize_text(self._lead_status_dropdown.value) if self._lead_status_dropdown.value else ""
        new_meeting = normalize_text(self._lead_meeting_field.value)

        old_status = normalize_text(self._lead_values.get("status")) or ""
        old_meeting = normalize_text(self._lead_values.get("meeting_date")) or ""

        if new_status == old_status and new_meeting == old_meeting:
            show_notification(self.page, "No lead changes to save.", "info")
            return

        self._on_save_lead(lead_id, new_status, new_meeting)

    # ------------------------------------------------------------------

    def update_theme(self, theme_mode=None):
        """
        Actualiza colores sin reconstruir UI.
        Cachea TextStyle para evitar recreación innecesaria (R8).
        """
        if not mounted_page(self):
            return

        theme_mode = theme_mode or self.page.theme_mode

        title_color = get_text_color(theme_mode)
        subtitle_color = get_subtitle_color(theme_mode)

        if self._title_text:
            self._title_text.color = title_color

        if self._subtitle_text:
            self._subtitle_text.color = subtitle_color

        if self._btn_back:
            self._btn_back.icon_color = title_color

        # 🔐 Cachea TextStyle helpers (R8: evitar recreación)
        self._label_style_cache = get_label_text_style(theme_mode)
        self._input_style_cache = get_input_text_style(theme_mode)

        for field in self._labels:
            field.label_style = self._label_style_cache
            field.text_style = self._input_style_cache

        # Lead section theme update
        if self._lead_section_title:
            self._lead_section_title.color = ft.Colors.ON_SURFACE
        if self._lead_no_lead_text:
            self._lead_no_lead_text.color = ft.Colors.ON_SURFACE_VARIANT
        for field in self._lead_labels:
            field.label_style = self._label_style_cache
            field.text_style = self._input_style_cache
        if self._lead_status_dropdown:
            self._lead_status_dropdown.label_style = self._label_style_cache
            self._lead_status_dropdown.text_style = self._input_style_cache

        self.bgcolor = ft.Colors.SURFACE_CONTAINER

        # ✅ NO llamar self.update() aquí (la vista orquesta un único page.update())


# ----------------------------------------------------------------------
# FACTORY (API PÚBLICA – NO SE ROMPE)
# ----------------------------------------------------------------------


def create_client_form(
    title: str,
    subtitle_text: str,
    on_save,
    on_cancel,
    initial_values: dict = None,
    lead_values: dict = None,
    on_save_lead=None,
    theme_mode=ft.ThemeMode.LIGHT,
):
    """
    Factory para mantener compatibilidad con imports existentes.
    lead_values and on_save_lead are optional — omitting them preserves
    the original behavior (no lead section shown).
    """
    return ClientForm(
        title=title,
        subtitle_text=subtitle_text,
        on_save=on_save,
        on_cancel=on_cancel,
        initial_values=initial_values,
        lead_values=lead_values,
        on_save_lead=on_save_lead,
        theme_mode=theme_mode,
    )
