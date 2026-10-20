"""Tabla de clientes con detalle de ventas y leads asociados."""
import flet as ft
from theme import get_text_color, is_dark_mode, delete_button_style
from components.tabla_leads import _source_label, _stage_badge
from utils.formatting import format_eur, mask_sensitive
from utils.ui_dispatch import mounted_page


class TablaClientes(ft.DataTable):
    """
    Tabla de clientes con Patrón B (Mutación iterativa).
    
    - __init__: Construye tabla completa
    - _rebuild_table(): Recalcula estructura (SOLO cuando hay datos nuevos)
    - update_theme(): SOLO muta Text.color y row.color (NO reconstruye)
    
    Nota: IconButtons en acciones se reconstruyen (no mutable en Flet 0.28.3)
    """
    
    def __init__(self, clients, view, theme_mode=ft.ThemeMode.LIGHT, lead_map=None):
        self._clients = clients
        self._view = view
        self._theme_mode = theme_mode
        self._lead_map = lead_map or {}
        
        # 🔐 REFERENCIAS A ELEMENTOS UI (para mutación en update_theme())
        self._header_texts = []     # ft.Text de encabezados
        self._data_rows_refs = []   # referencias a ft.DataRow para mutar color
        self._all_cell_texts = []   # todos los ft.Text de celdas de datos
        self._icon_buttons = []     # IconButtons en columna de acciones (para potencial mutación futura)
        
        # Inicializar con columnas y filas vacías (Flet lo requiere)
        super().__init__(columns=[], rows=[])
        
        # Construir tabla
        self._rebuild_table()
    
    def _get_row_color(self, index: int, is_dark: bool) -> str:
        """Devuelve el color de fondo para filas alternas (zebra striping)."""
        if index % 2 == 0:
            # Usar color semántico que se adapta automáticamente al theme
            return ft.Colors.with_opacity(0.03, ft.Colors.ON_SURFACE)
        else:
            return ft.Colors.TRANSPARENT

    def _make_masked_cell(self, value: str, color: str, size: int):
        """Crea una celda que muestra datos enmascarados y los revela en hover.

        Returns:
            (cell_widget, text_ref) — cell_widget va al DataCell;
            text_ref se añade a _all_cell_texts para color updates en update_theme().
        """
        masked = mask_sensitive(value)
        text_ref = ft.Text(masked, color=color, size=size)

        if masked == value:
            # Valor vacío/placeholder — sin hover necesario
            return ft.Container(content=text_ref), text_ref

        def on_hover(e):
            text_ref.value = value if e.data else masked
            text_ref.update()

        cell_widget = ft.Container(
            content=text_ref,
            on_hover=on_hover,
            tooltip="Hover to reveal",
        )
        return cell_widget, text_ref
    
    def _rebuild_table(self):
        """Reconstruye la tabla con los colores actuales."""
        text_color = get_text_color(self._theme_mode)
        header_color = get_text_color(self._theme_mode)
        is_dark = is_dark_mode(self._theme_mode)
        
        # Limpiar referencias anteriores
        self._header_texts.clear()
        self._data_rows_refs.clear()
        self._all_cell_texts.clear()
        self._icon_buttons.clear()
        
        # Detectar si es lista de dicts (nuevo formato) o tuplas (formato antiguo)
        is_dict_format = self._clients and isinstance(self._clients[0], dict)
        
        # Estilo de encabezados: más prominentes
        header_weight = ft.FontWeight.BOLD
        header_size = 13
        cell_size = 12
        
        if is_dict_format:
            # ============================================================
            # NUEVO FORMATO: clientes con datos de ventas
            # ============================================================
            
            # Crear y cachear textos de encabezados
            header_id = ft.Text("ID", color=header_color, weight=header_weight, size=header_size)
            header_nombre = ft.Text("Name", color=header_color, weight=header_weight, size=header_size)
            header_cif = ft.Text("Tax ID", color=header_color, weight=header_weight, size=header_size)
            header_email = ft.Text("Email", color=header_color, weight=header_weight, size=header_size)
            header_ventas = ft.Text("# Sales", color=header_color, weight=header_weight, size=header_size)
            header_total = ft.Text("Total (€)", color=header_color, weight=header_weight, size=header_size)
            header_lead_source = ft.Text("Lead source", color=header_color, weight=header_weight, size=header_size)
            header_lead_status = ft.Text("Lead stage", color=header_color, weight=header_weight, size=header_size)
            header_lead_date = ft.Text("Lead date", color=header_color, weight=header_weight, size=header_size)
            header_acciones = ft.Text("Actions", color=header_color, weight=header_weight, size=header_size)
            
            self._header_texts.extend([header_id, header_nombre, header_cif, header_email, header_ventas, header_total, header_lead_source, header_lead_status, header_lead_date, header_acciones])
            
            self.columns = [
                ft.DataColumn(header_id),
                ft.DataColumn(header_nombre),
                ft.DataColumn(header_cif),
                ft.DataColumn(header_email),
                ft.DataColumn(header_ventas),
                ft.DataColumn(header_total),
                ft.DataColumn(header_lead_source),
                ft.DataColumn(header_lead_status),
                ft.DataColumn(header_lead_date),
                ft.DataColumn(header_acciones),
            ]
            
            rows_list = []
            for idx, client in enumerate(self._clients):
                # Crear textos de celdas y cachearios
                cell_id = ft.Text(str(client['client_id']), color=text_color, size=cell_size)
                cell_name = ft.Text(client['name'], color=text_color, size=cell_size, weight=ft.FontWeight.W_500)
                cif_widget, cell_cif = self._make_masked_cell(client['cif'] or "—", text_color, cell_size)
                email_widget, cell_email = self._make_masked_cell(client['email'] or "—", text_color, cell_size)
                cell_sales = ft.Text(str(client['total_sales']), color=text_color, size=cell_size)
                cell_amount = ft.Text(format_eur(client['total_amount']), color=text_color, size=cell_size, weight=ft.FontWeight.W_500)
                
                # Lead columns — lookup from lead_map
                lead = self._lead_map.get(client['client_id'])
                cell_lead_source = ft.Text(
                    _source_label(lead["source"]) if lead else "—",
                    color=text_color, size=cell_size,
                )
                lead_date_str = (lead["created_at"] or "")[:10] if lead else "—"
                cell_lead_date = ft.Text(lead_date_str, color=text_color, size=cell_size)
                
                self._all_cell_texts.extend([cell_id, cell_name, cell_cif, cell_email, cell_sales, cell_amount, cell_lead_source, cell_lead_date])  # noqa: cell_cif/cell_email son text_refs
                
                # Crear IconButtons y cachearlos
                btn_visibility = ft.IconButton(
                    ft.Icons.VISIBILITY,
                    on_click=lambda e, cid=client['client_id']: self._view.show_client_profile(cid),
                    tooltip="View profile",
                    icon_size=18,
                    icon_color=ft.Colors.BLUE_400 if is_dark else ft.Colors.BLUE_600,
                )
                btn_edit = ft.IconButton(
                    ft.Icons.EDIT,
                    on_click=lambda e, cid=client['client_id']: self._view.show_edit_form(cid),
                    tooltip="Edit client",
                    icon_size=18,
                    icon_color=ft.Colors.ORANGE_400 if is_dark else ft.Colors.ORANGE_700,
                )
                btn_delete = ft.IconButton(
                    ft.Icons.DELETE,
                    icon_color=ft.Colors.RED_400 if is_dark else ft.Colors.RED_600,
                    tooltip="Delete client",
                    style=delete_button_style(),
                    on_click=lambda e, cid=client['client_id']: self._view.delete_client(cid),
                    icon_size=18,
                )
                self._icon_buttons.extend([btn_visibility, btn_edit, btn_delete])
                
                # Stage badge (not a Text, so not in _all_cell_texts)
                stage_badge = _stage_badge(
                    lead["status"] if lead else None,
                ) if lead else ft.Text("—", color=text_color, size=cell_size)
                
                row = ft.DataRow(
                    cells=[
                        ft.DataCell(cell_id),
                        ft.DataCell(cell_name),
                        ft.DataCell(cif_widget),
                        ft.DataCell(email_widget),
                        ft.DataCell(cell_sales),
                        ft.DataCell(cell_amount),
                        ft.DataCell(cell_lead_source),
                        ft.DataCell(stage_badge),
                        ft.DataCell(cell_lead_date),
                        ft.DataCell(
                            ft.Row(
                                [btn_visibility, btn_edit, btn_delete],
                                spacing=0,
                            )
                        ),
                    ],
                    color=self._get_row_color(idx, is_dark),
                )
                rows_list.append(row)
                self._data_rows_refs.append(row)
            
            self.rows = rows_list
        else:
            # ============================================================
            # FORMATO ANTIGUO: tuplas simples
            # ============================================================
            
            header_id = ft.Text("ID", color=header_color, weight=header_weight, size=header_size)
            header_nombre = ft.Text("Name", color=header_color, weight=header_weight, size=header_size)
            header_cif = ft.Text("Tax ID", color=header_color, weight=header_weight, size=header_size)
            header_email = ft.Text("Email", color=header_color, weight=header_weight, size=header_size)
            header_acciones = ft.Text("Actions", color=header_color, weight=header_weight, size=header_size)
            
            self._header_texts.extend([header_id, header_nombre, header_cif, header_email, header_acciones])
            
            self.columns = [
                ft.DataColumn(header_id),
                ft.DataColumn(header_nombre),
                ft.DataColumn(header_cif),
                ft.DataColumn(header_email),
                ft.DataColumn(header_acciones),
            ]
            
            rows_list = []
            for idx, (id, name, cif, address, contact, email) in enumerate(self._clients):
                cell_id = ft.Text(str(id), color=text_color, size=cell_size)
                cell_name = ft.Text(name, color=text_color, size=cell_size, weight=ft.FontWeight.W_500)
                cif_widget, cell_cif = self._make_masked_cell(cif or "—", text_color, cell_size)
                email_widget, cell_email = self._make_masked_cell(email or "—", text_color, cell_size)

                self._all_cell_texts.extend([cell_id, cell_name, cell_cif, cell_email])
                
                # Crear IconButtons y cachearlos
                btn_visibility = ft.IconButton(
                    ft.Icons.VISIBILITY,
                    on_click=lambda e, cid=id: self._view.show_client_profile(cid),
                    tooltip="View profile",
                    icon_size=18,
                    icon_color=ft.Colors.BLUE_400 if is_dark else ft.Colors.BLUE_600,
                )
                btn_edit = ft.IconButton(
                    ft.Icons.EDIT,
                    on_click=lambda e, cid=id: self._view.show_edit_form(cid),
                    tooltip="Edit client",
                    icon_size=18,
                    icon_color=ft.Colors.ORANGE_400 if is_dark else ft.Colors.ORANGE_700,
                )
                btn_delete = ft.IconButton(
                    ft.Icons.DELETE,
                    icon_color=ft.Colors.RED_400 if is_dark else ft.Colors.RED_600,
                    tooltip="Delete client",
                    style=delete_button_style(),
                    on_click=lambda e, cid=id: self._view.delete_client(cid),
                    icon_size=18,
                )
                self._icon_buttons.extend([btn_visibility, btn_edit, btn_delete])
                
                row = ft.DataRow(
                    cells=[
                        ft.DataCell(cell_id),
                        ft.DataCell(cell_name),
                        ft.DataCell(cif_widget),
                        ft.DataCell(email_widget),
                        ft.DataCell(
                            ft.Row(
                                [btn_visibility, btn_edit, btn_delete],
                                spacing=0,
                            )
                        ),
                    ],
                    color=self._get_row_color(idx, is_dark),
                )
                rows_list.append(row)
                self._data_rows_refs.append(row)
            
            self.rows = rows_list
    
    def update_theme(self, theme_mode):
        """
        Actualiza tema con Patrón B (SOLO MUTACIÓN, NO RECALCULAR).
        
        ✅ PERMITIDO:
        - Mutar Text.color en encabezados y celdas
        - Mutar row.color en filas
        - Mutar IconButton.icon_color (Patrón A simple)
        
        ❌ PROHIBIDO:
        - Recalcular datos de clientes
        - Reconstruir tabla completa
        - Recrear estructuras DataRow/DataCell
        """
        if mounted_page(self) is None:
            return
        self._theme_mode = theme_mode
        text_color = get_text_color(self._theme_mode)
        is_dark = is_dark_mode(self._theme_mode)
        
        # Mutar colores de encabezados
        for header_text in self._header_texts:
            header_text.color = text_color
        
        # Mutar colores de textos en celdas
        for cell_text in self._all_cell_texts:
            cell_text.color = text_color
        
        # Mutar colores de filas (fondo alternado)
        for idx, row in enumerate(self._data_rows_refs):
            row.color = self._get_row_color(idx, is_dark)
        
        # Mutar colores de IconButtons (indices: 0=VISIBILITY, 1=EDIT, 2=DELETE)
        color_map = {
            0: ft.Colors.BLUE_400 if is_dark else ft.Colors.BLUE_600,
            1: ft.Colors.ORANGE_400 if is_dark else ft.Colors.ORANGE_700,
            2: ft.Colors.RED_400 if is_dark else ft.Colors.RED_600,
        }

        for idx, btn in enumerate(self._icon_buttons):
            btn.icon_color = color_map[idx % 3]
        
        # ✅ NO llamar self.update() aquí: la vista orquesta un único page.update()

