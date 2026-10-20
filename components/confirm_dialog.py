"""
Componente de diálogo de confirmación reutilizable.

Cumple Contrato 1.5 (AGENTS.md § 1.5):
- Overlay reactivo de primera clase (R2)
- Expone update_theme() para mutación visual (R2, R6)
- Colores derivados de page.theme_mode (R1, R3)
- NO llama page.update() (R7)
- NO reconstruye UI en update_theme() (R6)
"""
import flet as ft


class ConfirmDialog(ft.BottomSheet):
    """
    BottomSheet de confirmación reaccionario al tema.
    
    Uso:
        dialog = ConfirmDialog(
            page=page,
            title="Confirmar eliminación",
            message="¿Estás seguro?",
            on_confirm=lambda e: ...,
            on_cancel=lambda e: ...,
        )
        page.show_dialog(dialog)

    El View es responsable de:
        1. Crear el diálogo
        2. Abrirlo con page.show_dialog()
        3. Actualizar su tema en update_theme() si está abierto
        4. Llamar page.update() después de update_theme()
    """
    
    def __init__(
        self,
        page,
        title: str,
        message: str,
        on_confirm,
        on_cancel=None,
    ):
        """
        Args:
            page: Página de Flet
            title: Título del diálogo
            message: Mensaje a mostrar
            on_confirm: Callable cuando se confirma
            on_cancel: Callable cuando se cancela (opcional)
        """
        self._page_ref = page  # Guardar referencia (page es propiedad read-only en BottomSheet)
        self.title_text = title
        self.message_text = message
        self.on_confirm_callback = on_confirm
        self.on_cancel_callback = on_cancel
        
        # Referencias a controles para mutarlos en update_theme()
        self._title = None
        self._message = None
        self._message_container = None  # ✅ Guardar referencia (R9)
        self._warning = None
        self._icon = None
        self._cancel_btn = None
        self._confirm_btn = None
        self._container = None
        
        # Handlers cacheados (R8: NO recrear en update_theme)
        self._on_cancel_handler = self._handle_cancel
        self._on_confirm_handler = self._handle_confirm
        
        # Construir contenido ANTES de super().__init__()
        content = self._build_content()
        
        # Inicializar BottomSheet con contenido
        super().__init__(content=content, open=False)
    
    def _build_content(self):
        """Construye el contenido del BottomSheet y lo devuelve."""
        
        # Obtener tema inicial
        is_dark = self._page_ref.theme_mode == ft.ThemeMode.DARK
        
        # Calcular colores iniciales
        text_color = ft.Colors.ON_SURFACE_VARIANT if is_dark else ft.Colors.ON_SURFACE
        bg_color = ft.Colors.SURFACE if is_dark else ft.Colors.SURFACE
        card_bg_color = ft.Colors.with_opacity(0.15, ft.Colors.ORANGE)
        warning_color = ft.Colors.ERROR
        
        # Header con ícono
        self._icon = ft.Icon(
            ft.Icons.WARNING_AMBER,
            size=28,
            color=ft.Colors.ORANGE,
        )
        
        self._title = ft.Text(
            self.title_text,
            size=20,
            weight=ft.FontWeight.BOLD,
            color=text_color,
        )
        
        header = ft.Row([
            self._icon,
            self._title,
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        
        # Mensaje
        self._message = ft.Text(
            self.message_text,
            size=15,
            color=text_color,
        )
        
        self._message_container = ft.Container(
            content=self._message,
            padding=12,
            bgcolor=card_bg_color,
            border_radius=8,
        )
        
        # Aviso
        self._warning = ft.Text(
            "This action cannot be undone",
            size=11,
            italic=True,
            color=warning_color,
        )
        
        # Botones
        self._cancel_btn = ft.TextButton(
            "Cancel",
            on_click=self._on_cancel_handler,
            expand=True,
            style=ft.ButtonStyle(padding=12),
        )
        
        self._confirm_btn = ft.Button(
            "Confirm",
            icon=ft.Icons.DELETE,
            color=ft.Colors.WHITE,
            bgcolor=ft.Colors.RED_700,
            on_click=self._on_confirm_handler,
            expand=True,
            style=ft.ButtonStyle(padding=12),
        )
        
        buttons_row = ft.Row([
            self._cancel_btn,
            self._confirm_btn,
        ], spacing=10)
        
        # Contenedor principal
        self._container = ft.Container(
            content=ft.Column([
                header,
                self._message_container,
                self._warning,
                buttons_row,
            ], spacing=12, tight=True),
            padding=16,
            bgcolor=bg_color,
        )
        
        return self._container
    
    def _handle_cancel(self, e):
        """Maneja click en 'Cancelar'."""
        self.open = False
        if self.on_cancel_callback:
            self.on_cancel_callback(e)

    def _handle_confirm(self, e):
        """Maneja click en 'Confirmar'."""
        self.open = False
        self.on_confirm_callback(e)
    
    def update_theme(self):
        """
        Actualiza los colores del diálogo cuando cambia el tema.
        
        Cumple R2, R3, R5, R6, R9:
        - Muta propiedades visuales (colores) de TODOS los controles visibles
        - NO reconstruye la UI
        - NO llama page.update() (responsabilidad del View)
        - R9: Incluye message_container (NO es "decorativo", es VISIBLE)
        """
        is_dark = self._page_ref.theme_mode == ft.ThemeMode.DARK
        
        # Calcular nuevos colores
        text_color = ft.Colors.ON_SURFACE_VARIANT if is_dark else ft.Colors.ON_SURFACE
        bg_color = ft.Colors.SURFACE if is_dark else ft.Colors.SURFACE
        card_bg_color = ft.Colors.with_opacity(0.15, ft.Colors.ORANGE)
        
        # Mutar propiedades de TODOS los controles visibles (R9: sin clasificar como "decorativo")
        self._title.color = text_color
        self._message.color = text_color
        self._message_container.bgcolor = card_bg_color  # ✅ R9: INCLUIDO
        self._container.bgcolor = bg_color
        
        # El warning mantiene su color (ERROR) sin cambios, es independiente del tema


# Factory helper para compatibilidad con código existente
def create_confirm_dialog(page, title, message, on_confirm, on_cancel=None, text_color=None):
    """
    Helper factory para crear ConfirmDialog.
    
    Nota: El parámetro text_color es IGNORADO (deprecated).
    Los colores se derivan automáticamente de page.theme_mode.
    
    Uso:
        dialog = create_confirm_dialog(page, "Título", "Mensaje", on_confirm_fn)
        page.show_dialog(dialog)
    """
    return ConfirmDialog(
        page=page,
        title=title,
        message=message,
        on_confirm=on_confirm,
        on_cancel=on_cancel,
    )
