"""Tarjeta de resumen con indicador de variación (delta)."""
import flet as ft
from utils.formatting import format_eur
from theme import get_text_color, is_dark_mode

# Constantes para mantener consistencia con StatCard
_GREEN_LIGHT = ft.Colors.GREEN_200
_GREEN_DARK = ft.Colors.GREEN_700


class ResumenCard(ft.Container):
    def __init__(self, promedio, theme_mode=ft.ThemeMode.LIGHT):
        self.promedio = promedio
        self._theme_mode = theme_mode
        is_dark = is_dark_mode(theme_mode)
        
        self._text_content = ft.Text(
            f"Average sale: {format_eur(promedio)}",
            size=18,
            weight="bold",
            color=get_text_color(theme_mode),
        )
        
        super().__init__(
            content=self._text_content,
            bgcolor=_GREEN_DARK if is_dark else _GREEN_LIGHT,
            padding=15,
            border_radius=12,
            expand=True,
        )
    
    def update_theme(self, theme_mode):
        """Actualiza los colores según el nuevo tema."""
        self._theme_mode = theme_mode
        is_dark = is_dark_mode(theme_mode)
        
        # Actualizar color del texto
        self._text_content.color = get_text_color(theme_mode)
        
        # Actualizar color de fondo
        self.bgcolor = _GREEN_DARK if is_dark else _GREEN_LIGHT
        
        # Actualizar el componente
        

