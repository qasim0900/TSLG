"""
Componente reutilizable de estado vacío.

Usado cuando no hay datos para mostrar.
Compatible con cambio de tema (Patrón A - colores semánticos via helpers).
"""
import flet as ft
from theme import get_text_color, get_subtitle_color, get_container_translucent_bgcolor


class EmptyState(ft.Container):
    """
    Estado vacío genérico con mensaje y acción opcional.
    
    Usa colores semánticos (THEME_AGENTS.md §2.1) que se actualizan automáticamente.
    Obtiene self.page por herencia (no requiere parámetro explícito).
    """
    
    def __init__(
        self,
        title: str,
        subtitle: str,
        action_label: str = None,
        on_action=None,
        icon=ft.Icons.INBOX,
    ):
        super().__init__()
        self.on_action = on_action

        self.padding = 30
        self.border_radius = 12
        self.expand = True
        self.alignment = ft.Alignment.CENTER

        self._build_ui(title, subtitle, action_label, icon)

    def _build_ui(self, title, subtitle, action_label, icon):
        # Obtener theme_mode con fallback seguro — en Flet 0.82, self.page lanza RuntimeError
        # si el control aún no está montado en la página
        try:
            theme_mode = self.page.theme_mode
        except (RuntimeError, AttributeError):
            theme_mode = ft.ThemeMode.LIGHT
        
        icon_widget = ft.Icon(
            icon,
            size=48,
            color=get_subtitle_color(theme_mode),
        )

        title_text = ft.Text(
            title,
            size=20,
            weight=ft.FontWeight.BOLD,
            color=get_text_color(theme_mode),
            text_align=ft.TextAlign.CENTER,
        )

        subtitle_text = ft.Text(
            subtitle,
            size=14,
            color=get_subtitle_color(theme_mode),
            text_align=ft.TextAlign.CENTER,
        )

        controls = [
            icon_widget,
            title_text,
            subtitle_text,
        ]

        if action_label and self.on_action:
            action_button = ft.Button(
                action_label,
                icon=ft.Icons.ADD,
                on_click=lambda _: self.on_action(),
            )
            controls.append(ft.Container(height=10))
            controls.append(action_button)

        self.content = ft.Column(
            controls,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        )

        self.bgcolor = get_container_translucent_bgcolor(theme_mode)
