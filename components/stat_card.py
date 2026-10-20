"""
Componente para mostrar tarjetas de información general (stats cards).
Pequeños contenedores con información resumida que reaccionan a cambios de tema.
"""
import flet as ft
from theme import get_text_color, get_subtitle_color, is_dark_mode


# Mapeo de colores: color base → (color_claro, color_oscuro)
# Estilo similar a ResumenCard: _200 para claro, _700 para oscuro
_COLOR_VARIANTS = {
    ft.Colors.BLUE: (ft.Colors.BLUE_200, ft.Colors.BLUE_900),
    ft.Colors.PURPLE: (ft.Colors.PURPLE_100, ft.Colors.PURPLE_900),
    ft.Colors.ORANGE: (ft.Colors.ORANGE_200, ft.Colors.BROWN_700),
    ft.Colors.TEAL: (ft.Colors.TEAL_200, ft.Colors.TEAL_900),
    ft.Colors.RED: (ft.Colors.RED_100, ft.Colors.RED_900),
    ft.Colors.GREEN: (ft.Colors.GREEN_200, ft.Colors.GREEN_900),
    ft.Colors.INDIGO: (ft.Colors.INDIGO_100, ft.Colors.INDIGO_900),
    ft.Colors.CYAN: (ft.Colors.CYAN_200, ft.Colors.CYAN_900),
    ft.Colors.AMBER: (ft.Colors.AMBER_200, ft.Colors.BROWN_700),
    ft.Colors.PINK: (ft.Colors.PINK_100, ft.Colors.PINK_900),
}


class StatCard(ft.Container):
    """
    Tarjeta de estadística que reacciona a cambios de tema.
    Estilo similar al ResumenCard (ticket medio).
    """
    
    def __init__(self, label, value, icon=None, color_base=ft.Colors.BLUE):
        """
        Inicializa la tarjeta de estadística.
        
        Args:
            label: Texto descriptivo (ej: "Total de ventas")
            value: Valor a mostrar (ej: "€ 276.517,59")
            icon: Ícono opcional (ej: ft.Icons.SHOPPING_CART)
            color_base: Color base para el fondo (ej: ft.Colors.BLUE)
        """
        super().__init__()
        self._mounted = False
        self.label = label
        self.value = value
        self.icon = icon
        self.color_base = color_base
        
        # Propiedades del contenedor
        self.padding = 16
        self.border_radius = 12
        self.height = 100
        
        # Construir controles UNA sola vez y cachear referencias (Patrón B - mutación)
        self._label_text = ft.Text(
            self.label,
            size=14,
            color=ft.Colors.ON_SURFACE_VARIANT,
            weight=ft.FontWeight.NORMAL,
        )
        self._value_text = ft.Text(
            str(self.value),
            size=22,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.ON_SURFACE,
        )
        self._text_col = ft.Column(
            [self._label_text, self._value_text],
            spacing=4,
        )
        content_items = []
        if self.icon:
            self._icon_ctrl = ft.Icon(self.icon, size=36, color=ft.Colors.ON_SURFACE)
            content_items.append(self._icon_ctrl)
        else:
            self._icon_ctrl = None
        content_items.append(self._text_col)
        self.content = ft.Row(
            content_items,
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        # Aplicar bgcolor inicial
        self.bgcolor = self._get_themed_bgcolor(is_dark=False)
    
    def _get_themed_bgcolor(self, is_dark: bool) -> str:
        """Obtiene el color de fondo según el tema, igual que ResumenCard."""
        # Buscar en el mapeo, o usar fallback con opacidad
        if self.color_base in _COLOR_VARIANTS:
            light_color, dark_color = _COLOR_VARIANTS[self.color_base]
            return dark_color if is_dark else light_color
        else:
            # Fallback para colores no mapeados
            return ft.Colors.with_opacity(0.25, self.color_base)
    
    def _update_ui(self, is_dark=False):
        """Muta propiedades de controles existentes. NO reconstruye el árbol de controles."""
        if self._mounted:
            text_color = get_text_color(self.page.theme_mode)
            subtitle_color = get_subtitle_color(self.page.theme_mode)
            is_dark = is_dark_mode(self.page.theme_mode)
        else:
            text_color = ft.Colors.ON_SURFACE
            subtitle_color = ft.Colors.ON_SURFACE_VARIANT

        # Mutar bgcolor del contenedor
        self.bgcolor = self._get_themed_bgcolor(is_dark)

        # Mutar colores de controles cacheados (NO reconstruir)
        self._label_text.color = text_color if is_dark else subtitle_color
        self._value_text.color = text_color
        if self._icon_ctrl:
            self._icon_ctrl.color = text_color
    
    def update_theme(self):
        """
        Actualiza los colores cuando cambia el tema.
        
        CONTRATO OFICIAL:
        - NO recibe parámetros
        - SOLO lee self.page.theme_mode
        - NO modifica self.page.theme_mode
        - Defensivo: sale si self.page es None
        """
        if not self._mounted:
            return
        
        # Actualizar UI con el tema actual
        is_dark = is_dark_mode(self.page.theme_mode)
        self._update_ui(is_dark=is_dark)
        
        # NO llamar self.update() aquí: la vista orquesta un único page.update()
    
    def did_mount(self):
        """
        Llamado cuando el control se monta en la página.
        Actualiza el tema con los valores reales de la página.
        """
        self._mounted = True
        self.update_theme()


def create_stat_card(label, value, icon=None, color=None):
    """
    Factory function para crear una tarjeta de estadística.
    
    Args:
        label: Texto descriptivo (ej: "Total de ventas")
        value: Valor a mostrar (ej: "€ 276.517,59")
        icon: Ícono opcional (ej: ft.Icons.SHOPPING_CART)
        color: Color base opcional (ej: ft.Colors.BLUE)
    
    Returns:
        StatCard con la tarjeta de estadística
    """
    if not color:
        color = ft.Colors.BLUE
    
    return StatCard(label, value, icon, color_base=color)
