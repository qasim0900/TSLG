"""
Vista de gestión de clientes.
Refactorizada para usar componentes reutilizables.
"""
import os
import logging
import flet as ft
from components.tabla_clientes import TablaClientes
from components.client_form import create_client_form
from components.client_profile import create_client_profile
from components.confirm_dialog import create_confirm_dialog
from components.client_empty_state import EmptyState

from theme import (
    get_text_color,
    get_subtitle_color,
    update_container_theme,
)
from views.scrollable_view import ScrollableView
from controllers.clients_controller import ClientsController
from controllers.leads_controller import LeadsController
from analysis.leads_analysis import get_leads
from models.lead_manager import get_latest_lead_per_client
from utils.notifications import show_notification
from utils.file_dialogs import save_html_file
from utils.file_opener import open_file_cross_platform
from reports.report_client_html import generate_client_html_report

logger = logging.getLogger(__name__)


class ClientesView(ScrollableView):
    def __init__(self, page):
        super().__init__(expand=True, spacing=20)
        self._page = page  # Use _page instead of page (page is read-only property in Flet 0.82.0)
        
        # Referencias a elementos de UI para actualizar tema sin perder datos
        self.header = None
        self.subtitle = None
        self.search_field = None
        self.btn_add = None
        self.btn_merge = None
        self.current_tabla = None
        self._cached_list_content = None  # Fix 6: guardar contenido previo al mostrar form

        # Contenedor para contenido dinámico (tabla o formularios)
        self.content_container = ft.Container(expand=True)
        
        # Referencias a diálogos reactivos (Contrato 1.5 R2, R5)
        self._confirm_merge_dialog = None
        self._confirm_delete_dialog = None
        
        # Construir UI
        self._build_ui()
        
        # Cargar clientes inicial (sin update, aún no montado)
        self._load_initial_content()

    def _on_search_change(self, e):
        """Ejecuta búsqueda cuando cambia el texto del campo de búsqueda."""
        if not self.search_field:
            return
            
        search_term = self.search_field.value
        filtered_clients = ClientsController.search_clients_by_name(search_term)
        
        if not filtered_clients:
            self.current_tabla = None
            self.content_container.content = EmptyState(
                title="No results",
                subtitle=f"No clients match '{search_term}'.",
                icon=ft.Icons.SEARCH_OFF,
            )
        else:
            lead_map = get_latest_lead_per_client()
            self.current_tabla = TablaClientes(
                filtered_clients,
                self,
                theme_mode=self._page.theme_mode,
                lead_map=lead_map,
            )
            self.content_container.content = self.current_tabla

    def _load_initial_content(self):
        """Carga contenido inicial sin llamar a update (control aún no montado)."""
        all_clients_data = ClientsController.get_all_clients_with_sales()
        if not all_clients_data:
            self.current_tabla = None
            self.content_container.content = EmptyState(
                title="No clients yet",
                subtitle="You have not added any clients yet.",
                action_label="Add client",
                on_action=self.show_add_form,
            )
        else:
            lead_map = get_latest_lead_per_client()
            self.current_tabla = TablaClientes(
                all_clients_data,
                self,
                theme_mode=self._page.theme_mode,
                lead_map=lead_map,
            )
            self.content_container.content = self.current_tabla
        # NO llamar update() aquí - control aún no montado

    def refresh(self):
        """Recarga la lista de clientes."""
        if self.search_field:
            self.search_field.value = ""
        
        all_clients_data = ClientsController.get_all_clients_with_sales()
        if not all_clients_data:
            self.current_tabla = None
            self.content_container.content = EmptyState(
                title="No clients yet",
                subtitle="You have not added any clients yet.",
                action_label="Add client",
                on_action=self.show_add_form,
            )
        else:
            lead_map = get_latest_lead_per_client()
            self.current_tabla = TablaClientes(
                all_clients_data,
                self,
                theme_mode=self._page.theme_mode,
                lead_map=lead_map,
            )
            self.content_container.content = self.current_tabla

        self._page.update()
        
    def show_merge_confirmation(self):
        """Muestra confirmación antes de fusionar clientes duplicados."""
        # Obtener info de duplicados
        count, summary = ClientsController.get_duplicates_info()
        
        if count == 0:
            show_notification(self._page, "No clients share the same name.", "info")
            return
        
        def on_confirm(e):
            success, message = ClientsController.merge_duplicate_clients()
            notification_type = "success" if success else "error"
            show_notification(self._page, message, notification_type)
            if success:
                self.refresh()
        
        # Crear y guardar referencia al diálogo (Contrato 1.5 R2)
        self._confirm_merge_dialog = create_confirm_dialog(
            page=self._page,
            title="Merge duplicates",
            message=f"{summary}\n\nThis merges client IDs that share the same name into one client.",
            on_confirm=on_confirm,
        )
        
        self._page.show_dialog(self._confirm_merge_dialog)

    def _cancel_form(self):
        """Restaura la vista de lista previa sin recargar la base de datos (Fix 6)."""
        if self._cached_list_content is not None:
            self.content_container.content = self._cached_list_content
            if isinstance(self._cached_list_content, TablaClientes):
                self.current_tabla = self._cached_list_content
            self._cached_list_content = None
        else:
            self.refresh()  # Fallback
        self._page.update()

    def show_add_form(self):
        """Muestra el formulario para añadir cliente."""
        def on_save(name, cif, address, contact, email):
            success, message = ClientsController.create_client(name, cif, address, contact, email)
            notification_type = "success" if success else "error"
            show_notification(self._page, message, notification_type)
            if success:
                self.refresh()

        self._cached_list_content = self.content_container.content  # Fix 6
        form = create_client_form(
            title="➕ Add client",
            subtitle_text="Enter the new client's details",
            on_save=on_save,
            on_cancel=lambda e=None: self._cancel_form(),
            theme_mode=self._page.theme_mode,
        )

        self.current_tabla = None
        self.content_container.content = form
        self._page.update()

    def show_edit_form(self, client_id):
        """Muestra el formulario para editar cliente."""
        client = ClientsController.find_client(client_id)

        if not client:
            show_notification(self._page, "Client not found.", "error")
            return

        _, name_val, cif_val, address_val, contact_val, email_val = client

        # Fetch most recent lead for this client
        lead_values = None
        try:
            leads = get_leads(client_id=client_id)
            if leads:
                ld = leads[0]  # already sorted by created_at DESC
                lead_values = {
                    "id": ld.get("id"),
                    "source": ld.get("source"),
                    "status": ld.get("status"),
                    "meeting_date": ld.get("meeting_date"),
                    "created_at": ld.get("created_at"),
                }
        except Exception:
            lead_values = None

        def on_save(name, cif, address, contact, email):
            success, message = ClientsController.update_client_info(
                client_id, name, cif, address, contact, email
            )
            notification_type = "success" if success else "error"
            show_notification(self._page, message, notification_type)
            if success:
                self._cached_list_content = None  # Invalidar cache para forzar refresh
                self.show_client_profile(client_id)  # Fix 7: ir al perfil tras guardar

        def on_save_lead(lead_id, status, meeting_date):
            success, message = LeadsController.update_lead_info(
                lead_id, status, meeting_date
            )
            notification_type = "success" if success else "error"
            show_notification(self._page, message, notification_type)
            if success:
                self._cached_list_content = None
                self.show_edit_form(client_id)  # Refresh form with updated lead data

        self._cached_list_content = self.content_container.content  # Fix 6
        form = create_client_form(
            title="✏ Edit client",
            subtitle_text="Update the client's details",
            on_save=on_save,
            on_cancel=lambda e=None: self._cancel_form(),
            initial_values={
                'name': name_val,
                'cif': cif_val,
                'address': address_val,
                'contact': contact_val,
                'email': email_val,
            },
            lead_values=lead_values,
            on_save_lead=on_save_lead,
            theme_mode=self._page.theme_mode,
        )

        self.current_tabla = None
        self.content_container.content = form
        self._page.update()

    def delete_client(self, client_id):
        """Muestra diálogo de confirmación antes de eliminar cliente."""
        client_info = ClientsController.find_client(client_id)
        
        if not client_info:
            show_notification(self._page, "Client not found.", "error")
            return
        
        client_name = client_info[1]
        
        def on_confirm(e):
            success, message = ClientsController.remove_client(client_id)
            notification_type = "success" if success else "error"
            show_notification(self._page, message, notification_type)
            if success:
                self.refresh()
        
        # Crear y guardar referencia al diálogo (Contrato 1.5 R2)
        self._confirm_delete_dialog = create_confirm_dialog(
            self._page,
            title=f"Delete {client_name}",
            message=f"Are you sure you want to delete {client_name}?\n\n⚠ All of this client's sales will also be deleted.",
            on_confirm=on_confirm
        )
        
        self._page.show_dialog(self._confirm_delete_dialog)

    def show_client_profile(self, client_id):
        """Muestra el perfil detallado del cliente."""
        client_info = ClientsController.find_client(client_id)
        if not client_info:
            show_notification(self._page, "Client not found.", "error")
            return

        client_id_val, name, cif, address, contact_person, email = client_info
        stats = ClientsController.get_client_sales_stats(client_id)

        client_dict = {
            'client_id': client_id_val,
            'name': name,
            'cif': cif,
            'address': address,
            'contact_person': contact_person,
            'email': email,
        }

        def _on_export_client():
            self._page.run_task(
                self._export_client_html, client_dict, stats
            )

        profile = create_client_profile(
            client_info=client_dict,
            stats=stats,
            on_back=self.refresh,
            on_export=_on_export_client,
        )

        self.current_tabla = None
        self.content_container.content = profile
        self._page.update()

    async def _export_client_html(self, client_info: dict, stats: dict):
        """Exporta ficha de cliente individual a HTML."""
        try:
            name = client_info.get('name', 'Cliente')
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
            default_name = f"Client_Profile_{safe_name}.html"

            filepath = await save_html_file(self._page, default_name)
            if not filepath:
                return

            success, message, _ = generate_client_html_report(
                client_info=client_info,
                stats=stats,
                filename=filepath,
            )

            if success:
                show_notification(self._page, f"Profile exported: {os.path.basename(filepath)}", "success")
                open_file_cross_platform(filepath)
            else:
                show_notification(self._page, message, "error")

        except Exception as e:
            logger.exception("ClientesView: client profile export failed")
            show_notification(self._page, f"Export failed: {e}", "error")

    def update_theme(self):
        """Actualiza el tema de la vista sin recrearla completamente."""
        title_color = get_text_color(self._page.theme_mode)
        subtitle_color = get_subtitle_color(self._page.theme_mode)
        
        if self.header:
            self.header.color = title_color
        
        if self.subtitle:
            self.subtitle.color = subtitle_color
        
        if self.search_field:
            self.search_field.border_color = subtitle_color
            self.search_field.label_style = ft.TextStyle(color=subtitle_color)
            self.search_field.text_style = ft.TextStyle(color=title_color)
        
        if self.current_tabla and hasattr(self.current_tabla, 'update_theme'):
            self.current_tabla.update_theme(self._page.theme_mode)
        
        if self.content_container.content and not self.current_tabla:
            if hasattr(self.content_container.content, "update_theme"):
                self.content_container.content.update_theme(self._page.theme_mode)
            else:
                update_container_theme(self.content_container.content, self._page.theme_mode)
        
        # Diálogos reactivos (Contrato 1.5 R2, R5)
        if hasattr(self, '_confirm_merge_dialog') and self._confirm_merge_dialog and hasattr(self._confirm_merge_dialog, 'open') and self._confirm_merge_dialog.open:
            if hasattr(self._confirm_merge_dialog, 'update_theme'):
                self._confirm_merge_dialog.update_theme()
        
        if hasattr(self, '_confirm_delete_dialog') and self._confirm_delete_dialog and hasattr(self._confirm_delete_dialog, 'open') and self._confirm_delete_dialog.open:
            if hasattr(self._confirm_delete_dialog, 'update_theme'):
                self._confirm_delete_dialog.update_theme()
        
        # ✅ R7: NO llamar update() aquí — el caller es responsable
    
    def _build_ui(self):
        """Construye la interfaz según el tema actual."""
        self.clear_controls()
        
        title_color = get_text_color(self._page.theme_mode)
        subtitle_color = get_subtitle_color(self._page.theme_mode)
        
        self.search_field = ft.TextField(
            label="Search clients by name",
            on_change=self._on_search_change,
            border_radius=12,
            width=360,
            border_color=subtitle_color,
            label_style=ft.TextStyle(color=subtitle_color),
            text_style=ft.TextStyle(color=title_color),
        )
        
        self.header = ft.Text(
            "Client management",
            size=28,
            weight=ft.FontWeight.BOLD,
            color=title_color,
        )
        
        self.subtitle = ft.Text(
            "Manage your client database.",
            size=16,
            color=subtitle_color,
        )
        
        self.btn_add = ft.Button(
            "➕ Add client",
            on_click=lambda _: self.show_add_form()
        )
        
        self.btn_merge = ft.Button(
            "🔗 Merge duplicates",
            on_click=lambda _: self.show_merge_confirmation(),
            bgcolor=ft.Colors.ORANGE,
            color=ft.Colors.BLACK,
            # ⚠️ INTENCIONAL:
            # Color semántico fijo (acción crítica).
            # NO depende del theme → NO se muta en update_theme().
        )
        
        
        self.add_control(self.header)
        self.add_control(self.subtitle)
        self.add_control(ft.Container(height=10))
        self.add_control(
            ft.Row(
                [
                    self.btn_add,
                    self.btn_merge,
                    ft.Container(expand=True),  # 👈 ESTE es el spacer en Flet 0.28
                    self.search_field,
                ],
                spacing=10,
                expand=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        


        self.add_control(
            ft.Row(
                [
                    ft.Container(
                        content=self.content_container,
                        expand=True,
                    )
                ],
                expand=True,
            )
        )
