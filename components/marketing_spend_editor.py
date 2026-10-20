"""
Componente: Editor manual de inversión de marketing.

Permite al usuario:
  - Agregar registros de inversión (source, amount, date)
  - Editar registros existentes
  - Eliminar registros
  - Ver tabla de registros existentes

Patrón Flet 0.82.2:
  - Hereda de ft.Container (patrón actual del proyecto)
  - update_theme() muta propiedades, no reconstruye UI
  - Nunca llama page.update() — responsabilidad del caller
  - Event handlers cacheados en __init__ (R8)
"""

import flet as ft
from datetime import date as _date

from theme import get_text_color, get_card_color, delete_button_style
from models.marketing_spend_manager import (
    insert_spend,
    update_spend,
    delete_spend,
    get_all_spend,
)
from components.confirm_dialog import create_confirm_dialog
from utils.formatting import format_eur, parse_amount
from utils.notifications import show_notification

# Fuentes conocidas — consistente con marketing_summary_section._SOURCE_LABELS
_SOURCE_OPTIONS: list[tuple[str, str]] = [
    ("meta_ads", "Meta (Facebook/Instagram)"),
    ("google_ads", "Google Ads"),
    ("linkedin_ads", "LinkedIn Ads"),
    ("tiktok_ads", "TikTok Ads"),
    ("referral", "Referral"),
    ("organic", "Organic"),
    ("manual_import", "Manual / Other"),
]


class MarketingSpendEditor(ft.Container):
    """Editor CRUD de inversión de marketing con formulario y tabla."""

    def __init__(self, page: ft.Page, on_data_changed=None):
        super().__init__()
        self._page = page
        self._on_data_changed = on_data_changed
        self._editing_id = None  # None = nuevo, int = editando

        # R8: cachear handlers en __init__
        self._on_save_handler = self._handle_save
        self._on_cancel_handler = self._handle_cancel
        self._on_date_pick_handler = self._handle_date_pick
        self._confirm_delete_dialog = None

        is_dark = self._page.theme_mode == ft.ThemeMode.DARK

        # --- Form fields ---
        self._source_dropdown = ft.Dropdown(
            label="Source",
            options=[ft.dropdown.Option(key=k, text=v) for k, v in _SOURCE_OPTIONS],
            value="meta_ads",
            height=48,
            text_size=13,
            expand=True,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border=ft.InputBorder.UNDERLINE,
            focused_border_color=ft.Colors.PRIMARY,
        )

        self._amount_field = ft.TextField(
            label="Amount (EUR)",
            prefix_icon=ft.Icons.EURO,
            height=48,
            text_size=13,
            expand=True,
            input_filter=ft.InputFilter(
                regex_string=r"[0-9.]",
                allow=True,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border=ft.InputBorder.UNDERLINE,
            focused_border_color=ft.Colors.PRIMARY,
        )

        self._date_field = ft.TextField(
            label="Date (YYYY-MM-DD)",
            value=_date.today().isoformat(),
            height=48,
            text_size=13,
            expand=True,
            read_only=True,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border=ft.InputBorder.UNDERLINE,
            focused_border_color=ft.Colors.PRIMARY,
        )

        self._date_pick_btn = ft.IconButton(
            icon=ft.Icons.CALENDAR_MONTH,
            tooltip="Pick a date",
            on_click=self._on_date_pick_handler,
        )

        self._save_btn = ft.Button(
            "Save",
            icon=ft.Icons.SAVE_OUTLINED,
            on_click=self._on_save_handler,
            bgcolor=ft.Colors.PRIMARY,
            color=ft.Colors.ON_PRIMARY,
        )

        self._cancel_btn = ft.TextButton(
            "Cancel",
            on_click=self._on_cancel_handler,
            visible=False,
        )

        self._form_status = ft.Text("", size=12, color=ft.Colors.ERROR)

        self._form_title = ft.Text(
            "Add spend",
            size=14,
            weight=ft.FontWeight.W_600,
            color=get_text_color(is_dark),
        )

        # --- Form layout ---
        form_section = ft.Column(
            [
                self._form_title,
                ft.Row(
                    [self._source_dropdown, self._amount_field],
                    spacing=12,
                ),
                ft.Row(
                    [
                        self._date_field,
                        self._date_pick_btn,
                        self._save_btn,
                        self._cancel_btn,
                    ],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._form_status,
            ],
            spacing=10,
        )

        # --- Entries table ---
        self._table_container = ft.Column(
            controls=[self._build_entries_table()],
            scroll=ft.ScrollMode.AUTO,
            height=150,
        )

        self._section_title = ft.Text(
            "Spend records",
            size=14,
            weight=ft.FontWeight.W_600,
            color=get_text_color(is_dark),
        )

        # Asignar contenido al Container padre
        self.bgcolor = get_card_color(is_dark)
        self.border_radius = 16
        self.padding = 16
        self.content = ft.Column(
            [
                form_section,
                ft.Divider(height=1),
                self._section_title,
                self._table_container,
            ],
            spacing=10,
        )

    # ------------------------------------------------------------------
    # Table builder
    # ------------------------------------------------------------------

    def _build_entries_table(self) -> ft.Control:
        """Construye DataTable con los registros actuales de marketing_spend."""
        entries = get_all_spend()

        if not entries:
            return ft.Container(
                content=ft.Text(
                    "No spend records yet",
                    color=ft.Colors.ON_SURFACE_VARIANT,
                    size=13,
                    italic=True,
                ),
                padding=16,
            )

        # Source label lookup
        source_labels = {k: v for k, v in _SOURCE_OPTIONS}

        rows = []
        for idx, entry in enumerate(entries):
            label = source_labels.get(entry["source"], entry["source"])
            zebra = ft.Colors.SURFACE_CONTAINER if idx % 2 == 0 else None
            spend_id = entry["id"]

            rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(label, size=11)),
                        ft.DataCell(ft.Text(
                            format_eur(entry["amount"]),
                            size=11,
                            color=ft.Colors.ON_SURFACE,
                            weight=ft.FontWeight.W_500,
                        )),
                        ft.DataCell(ft.Text(entry["date"], size=11)),
                        ft.DataCell(
                            ft.Row(
                                [
                                    ft.IconButton(
                                        icon=ft.Icons.EDIT,
                                        icon_size=16,
                                        tooltip="Edit",
                                        icon_color=ft.Colors.ORANGE_400 if self._page.theme_mode == ft.ThemeMode.DARK else ft.Colors.ORANGE_700,
                                        data=spend_id,
                                        on_click=self._handle_edit,
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.DELETE,
                                        icon_size=16,
                                        icon_color=ft.Colors.RED_400 if self._page.theme_mode == ft.ThemeMode.DARK else ft.Colors.RED_600,
                                        tooltip="Delete",
                                        style=delete_button_style(),
                                        data=spend_id,
                                        on_click=self._handle_delete,
                                    ),
                                ],
                                spacing=0,
                            )
                        ),
                    ],
                    color=zebra,
                )
            )

        return ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Source", size=12, weight=ft.FontWeight.W_600)),
                ft.DataColumn(ft.Text("Amount", size=12, weight=ft.FontWeight.W_600), numeric=True),
                ft.DataColumn(ft.Text("Date", size=12, weight=ft.FontWeight.W_600)),
                ft.DataColumn(ft.Text("", size=12)),
            ],
            rows=rows,
            column_spacing=12,
            heading_row_height=36,
            data_row_min_height=32,
        )

    # ------------------------------------------------------------------
    # Date picker — Flet 0.82 pattern
    # ------------------------------------------------------------------

    def _handle_date_pick(self, e):
        """Abre DatePicker nativo de Flet 0.82."""
        picker = ft.DatePicker(
            first_date=_date(2020, 1, 1),
            last_date=_date(2030, 12, 31),
            value=_date.today(),
            on_change=self._on_date_selected,
        )
        self._page.show_dialog(picker)

    def _on_date_selected(self, e):
        """Callback del DatePicker — muta el campo de fecha."""
        if e.control.value:
            selected = e.control.value
            if isinstance(selected, _date):
                self._date_field.value = selected.isoformat()
            else:
                self._date_field.value = str(selected)[:10]

    # ------------------------------------------------------------------
    # Form handlers
    # ------------------------------------------------------------------

    def _handle_save(self, e):
        """Guarda (insert o update) un registro de inversión."""
        source = self._source_dropdown.value
        amount_str = self._amount_field.value
        date_str = self._date_field.value

        # Validación básica en UI
        if not amount_str or not amount_str.strip():
            self._form_status.value = "Enter an amount."
            self._form_status.color = ft.Colors.ERROR
            return

        try:
            amount = parse_amount(amount_str)
            if amount <= 0:
                self._form_status.value = "The amount must be greater than 0."
                self._form_status.color = ft.Colors.ERROR
                return
        except ValueError:
            self._form_status.value = "Invalid amount."
            self._form_status.color = ft.Colors.ERROR
            return

        try:
            if self._editing_id is not None:
                update_spend(self._editing_id, source, amount, date_str)
                self._form_status.value = "Record updated."
                show_notification(self._page, "Spend record updated.", "success")
            else:
                insert_spend(source, amount, date_str)
                self._form_status.value = "Record saved."
                show_notification(self._page, "Spend record saved.", "success")

            self._form_status.color = ft.Colors.GREEN_500
            self._reset_form()
            self._refresh_table()
            self._notify_data_changed()

        except ValueError as ve:
            self._form_status.value = str(ve)
            self._form_status.color = ft.Colors.ERROR

    def _handle_cancel(self, e):
        """Cancela la edición y vuelve a modo nuevo."""
        self._reset_form()
        self._form_status.value = ""

    def _handle_edit(self, e):
        """Carga un registro en el formulario para editar."""
        spend_id = e.control.data
        from models.marketing_spend_manager import get_spend_by_id
        entry = get_spend_by_id(spend_id)
        if not entry:
            return

        self._editing_id = spend_id
        self._source_dropdown.value = entry["source"]
        self._amount_field.value = str(entry["amount"])
        self._date_field.value = entry["date"]
        self._form_title.value = "Edit spend"
        self._cancel_btn.visible = True
        self._save_btn.text = "Update"

    def _handle_delete(self, e):
        """Pide confirmación antes de eliminar un registro de inversión."""
        spend_id = e.control.data
        entries = {entry["id"]: entry for entry in get_all_spend()}
        entry = entries.get(spend_id)

        if not entry:
            self._form_status.value = "Record not found."
            self._form_status.color = ft.Colors.ERROR
            show_notification(self._page, "Record not found.", "error")
            return

        source_labels = {k: v for k, v in _SOURCE_OPTIONS}
        label = source_labels.get(entry["source"], entry["source"])

        def on_confirm(e):
            try:
                deleted = delete_spend(spend_id)
                if deleted:
                    self._form_status.value = "Record deleted."
                    self._form_status.color = ft.Colors.GREEN_500
                    show_notification(self._page, "Spend record deleted.", "success")
                    self._refresh_table()
                    self._notify_data_changed()
                else:
                    self._form_status.value = "Record not found."
                    self._form_status.color = ft.Colors.ERROR
                    show_notification(self._page, "Record not found.", "error")
            except Exception as ex:
                self._form_status.value = f"Error: {ex}"
                self._form_status.color = ft.Colors.ERROR
                show_notification(self._page, f"Could not delete: {ex}", "error")

        self._confirm_delete_dialog = create_confirm_dialog(
            self._page,
            title=f"Delete {label} spend",
            message=f"Are you sure you want to delete the {format_eur(entry['amount'])} record from {entry['date']}?",
            on_confirm=on_confirm,
        )
        self._page.show_dialog(self._confirm_delete_dialog)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _reset_form(self):
        """Resetea el formulario a modo 'nuevo'."""
        self._editing_id = None
        self._amount_field.value = ""
        self._date_field.value = _date.today().isoformat()
        self._source_dropdown.value = "meta_ads"
        self._form_title.value = "Add spend"
        self._cancel_btn.visible = False
        self._save_btn.text = "Save"

    def _refresh_table(self):
        """Reconstruye la tabla de registros."""
        self._table_container.controls = [self._build_entries_table()]

    def _notify_data_changed(self):
        """Notifica al padre que los datos de inversión cambiaron."""
        if self._on_data_changed:
            self._on_data_changed()

    # ------------------------------------------------------------------
    # Theme — R6: solo mutar, R7: nunca page.update(), R9: todo visible
    # ------------------------------------------------------------------

    def update_theme(self):
        if not self._page:
            return
        is_dark = self._page.theme_mode == ft.ThemeMode.DARK
        self._form_title.color = get_text_color(is_dark)
        self._section_title.color = get_text_color(is_dark)
        self.bgcolor = get_card_color(is_dark)

        for field in [self._source_dropdown, self._amount_field, self._date_field]:
            field.bgcolor = ft.Colors.SURFACE_CONTAINER_LOWEST
            field.focused_border_color = ft.Colors.PRIMARY

        if self._confirm_delete_dialog and getattr(self._confirm_delete_dialog, "open", False):
            if hasattr(self._confirm_delete_dialog, "update_theme"):
                self._confirm_delete_dialog.update_theme()

        # Rebuild table to apply theme colors to cells
        self._refresh_table()
