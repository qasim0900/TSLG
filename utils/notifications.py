"""Gestor de notificaciones de la aplicación (snackbar y diálogos)."""

import flet as ft
from typing import Optional, TypedDict

from domain.filter_options import ALL_FILTER_LABEL


class NotificationManager:
    """Gestor centralizado de notificaciones para la app."""
    
    def __init__(self, page: ft.Page):
        self._page = page
    
    def show_snackbar(self, message: str, severity: str = "info", auto_update: bool = True):
        """
        Muestra un SnackBar con el mensaje (Flet 0.80.5).
        
        Args:
            message: Texto a mostrar
            severity: 'success', 'error', 'warning', 'info' (determina color e icono)
            auto_update: Ignorado (existe por compatibilidad hacia atrás).

        Notas:
        - Duración: 3.5 segundos por defecto
        - Incluye icono de severidad + mensaje en Row con espacio
        
        Ejemplo:
            nm = NotificationManager(page)
            nm.show_snackbar("Filtro aplicado correctamente", severity="success")
        """
        # Colores según severidad
        colors = {
            'success': ft.Colors.GREEN_800,
            'error': ft.Colors.RED_700,
            'warning': ft.Colors.DEEP_ORANGE_900,
            'info': ft.Colors.BLUE_700,
        }
        
        icons = {
            'success': ft.Icons.CHECK_CIRCLE,
            'error': ft.Icons.ERROR,
            'warning': ft.Icons.WARNING,
            'info': ft.Icons.INFO,
        }
        
        snack = ft.SnackBar(
            content=ft.Row(
                [
                    ft.Icon(icons.get(severity, ft.Icons.INFO), color=ft.Colors.WHITE),
                    ft.Text(message, color=ft.Colors.WHITE, size=14),
                ],
                spacing=10,
            ),
            bgcolor=colors.get(severity, ft.Colors.BLUE_700),
            duration=3500,  # 3,5 segundos
        )
        
        self._page.show_dialog(snack)
    
    
    def show_dialog(self, title: str, message: str, severity: str = "info", on_ok=None):
        """
        Muestra un diálogo modal (AlertDialog en Flet 0.80.5).
        
        Args:
            title: Título del diálogo con icono
            message: Mensaje detallado
            severity: 'success', 'error', 'warning', 'info' (determina icono y color)
            on_ok: Callback opcional cuando se presiona OK
        
        Ejemplo:
            nm = NotificationManager(page)
            nm.show_dialog("Error", "No se encontraron datos", severity="error")
        """
        icons = {
            'success': (ft.Icons.CHECK_CIRCLE, ft.Colors.GREEN_700),
            'error': (ft.Icons.ERROR, ft.Colors.RED_700),
            'warning': (ft.Icons.WARNING, ft.Colors.ORANGE_700),
            'info': (ft.Icons.INFO, ft.Colors.BLUE_700),
        }
        
        icon, color = icons.get(severity, (ft.Icons.INFO, ft.Colors.BLUE_700))
        
        def close_dialog(e):
            dialog.open = False
            if on_ok:
                try:
                    on_ok()
                except Exception as ex:
                    self.show_snackbar(f"Unexpected error: {str(ex)}", severity="error")
        
        dialog = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(icon, color=color, size=30),
                    ft.Text(title, weight=ft.FontWeight.BOLD),
                ],
                spacing=10,
            ),
            content=ft.Text(message, size=14),
            actions=[
                ft.TextButton("OK", on_click=close_dialog),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self._page.show_dialog(dialog)

    def show_confirm_dialog(self, title: str, message: str, on_confirm, on_cancel=None):
        """
        Muestra un diálogo de confirmación con botones "Cancelar" y "Confirmar".
        
        Args:
            title: Título del diálogo
            message: Mensaje de confirmación
            on_confirm: Callback cuando usuario presiona "Confirmar" (REQUERIDO)
            on_cancel: Callback opcional cuando usuario presiona "Cancelar"
        
        Ejemplo:
            nm = NotificationManager(page)
            nm.show_confirm_dialog(
                "Confirmar eliminación",
                "Esta acción no se puede deshacer",
                on_confirm=lambda: delete_item(),
                on_cancel=lambda: print("Cancelado")
            )
        """
        def handle_confirm(e):
            dialog.open = False
            if on_confirm:
                try:
                    on_confirm()
                except Exception as ex:
                    self.show_snackbar(f"Unexpected error: {str(ex)}", severity="error")

        def handle_cancel(e):
            dialog.open = False
            if on_cancel:
                try:
                    on_cancel()
                except Exception as ex:
                    self.show_snackbar(f"Unexpected error: {str(ex)}", severity="error")
        
        dialog = ft.AlertDialog(
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.HELP_OUTLINE, color=ft.Colors.ORANGE_700, size=30),
                    ft.Text(title, weight=ft.FontWeight.BOLD),
                ],
                spacing=10,
            ),
            content=ft.Text(message, size=14),
            actions=[
                ft.TextButton("Cancel", on_click=handle_cancel),
                ft.Button("Confirm", on_click=handle_confirm),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self._page.show_dialog(dialog)

    # ============================================================
    #   NOTIFICACIONES ESPECÍFICAS DE VENTAS
    # ============================================================
    
    def show_filter_applied(self, start_date: str | None = None, end_date: str | None = None, 
                           client_name: str | None = None, product_type: str | None = None):
        """
        Muestra notificación cuando se aplica un filtro.
        
        ============================================================
        FIX: Evitar doble page.update()
        ============================================================
        Esta función es llamada desde _populate_view_containers() que
        TAMBIÉN hace page.update() al final. Para evitar dobles updates,
        este método NO hace update automático.
        El caller (_populate_view_containers) es responsable del update.
        """
        filter_parts = []
        
        # Fecha
        fecha_str = f"{start_date or 'start'} to {end_date or 'end'}"
        filter_parts.append(f"Dates: {fecha_str}")
        
        # Cliente
        if client_name:
            filter_parts.append(f"Client: {client_name}")
        
        # Producto
        if product_type:
            filter_parts.append(f"Product: {product_type}")
        
        mensaje = "Filter applied: " + " | ".join(filter_parts)
        # ✅ FIX: auto_update=False para evitar doble update
        self.show_snackbar(mensaje, severity='success', auto_update=False)

    def show_compare_applied(
        self,
        start_a: str,
        end_a: str,
        client_a: Optional[str],
        product_a: Optional[str],
        start_b: str,
        end_b: str,
        client_b: Optional[str],
        product_b: Optional[str],
        auto_update: bool = True,
    ):
        """Muestra notificación cuando se aplica una comparación A vs B."""

        def _fmt_side(label: str, start: str, end: str,
                      client: Optional[str], product: Optional[str]) -> str:
            return (
                f"{label} → {start} to {end} | "
                f"Client: {client if client else ALL_FILTER_LABEL} | "
                f"Product: {product if product else ALL_FILTER_LABEL}"
            )

        line_a = _fmt_side("A", start_a, end_a, client_a, product_a)
        line_b = _fmt_side("B", start_b, end_b, client_b, product_b)

        message = "Comparison applied:\n" + line_a + "\n" + line_b
        self.show_snackbar(message, severity="success", auto_update=auto_update)



    def show_filter_cleared(self):
        """Muestra notificación cuando se limpian los filtros."""
        self.show_snackbar("Filters cleared", severity='info')
    
    def show_no_data(self):
        """Muestra notificación cuando no hay datos."""
        self.show_snackbar("No data in that date range", severity='warning')
    
    def show_no_data_loaded(self):
        """Muestra notificación cuando no hay datos cargados."""
        self.show_snackbar("No data loaded", severity='warning')
    
    def show_file_selected_error(self):
        """Muestra notificación de error al seleccionar archivo."""
        self.show_snackbar("No file selected", severity='warning')
    
    def show_file_not_found(self):
        """Muestra notificación cuando el archivo no existe."""
        self.show_snackbar("Could not read the file", severity='error')
    
    def show_importing_file(self):
        """Muestra notificación de importación en progreso."""
        self.show_snackbar("Importing data, please wait...", severity='info')
    
    def show_import_success(self, message: str):
        """Muestra notificación de importación exitosa."""
        self.show_snackbar(message, severity='success')
    
    def show_import_error(self, message: str):
        """Muestra notificación de error en importación."""
        self.show_snackbar(message, severity='error')

# ============================================================
#   FUNCIÓN GLOBAL DE NOTIFICACIÓN (para uso fácil)
# ============================================================

# Cache de NotificationManager por page (evita crear instancias en cada call)
_notification_managers_cache: dict[int, NotificationManager] = {}

def show_notification(page: ft.Page, message: str, type: str = "info"):
    """
    Función global para mostrar notificaciones.
    
    Args:
        page: Página de Flet
        message: Mensaje a mostrar
        type: Tipo de notificación ('success', 'error', 'warning', 'info')
    
    Nota: Usa singleton cache para evitar crear NotificationManager en cada call.
    """
    page_id = id(page)
    if page_id not in _notification_managers_cache:
        _notification_managers_cache[page_id] = NotificationManager(page)
    _notification_managers_cache[page_id].show_snackbar(message, severity=type)