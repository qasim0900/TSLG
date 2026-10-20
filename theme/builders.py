"""
Constructores de temas para Flet (Material 3).

PATRÓN OFICIAL FLET 0.80.5+:
1. Configurar page.theme y page.dark_theme UNA vez al inicio (main.py)
2. Toggle solo page.theme_mode (ui/user_ui.py)
3. Llamar page.update() UNA vez
4. Flet actualiza automáticamente todos los controles con colores semánticos

NO usar update_theme() wrapper. Fue removido en favor del patrón oficial.
"""
import flet as ft
from .colors import PRIMARY_COLOR, PRIMARY_DARK


def build_light_theme() -> ft.Theme:
    """
    Construye el tema claro de la aplicación.
    
    Se configura UNA vez en main.py como page.theme.
    """
    return ft.Theme(
        color_scheme_seed=PRIMARY_COLOR,
        use_material3=True,
    )


def build_dark_theme() -> ft.Theme:
    """
    Construye el tema oscuro de la aplicación.
    
    Se configura UNA vez en main.py como page.dark_theme.
    """
    return ft.Theme(
        color_scheme_seed=PRIMARY_DARK,
        use_material3=True,
    )
