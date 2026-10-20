"""
Módulo de tema centralizado.

Re-exporta funciones y constantes para mantener compatibilidad.
Ver /theme/THEME_AGENTS.md para el contrato técnico.
"""
from theme.kpi_styles import get_kpi_card_style

# Colores (solo seeds de theme)
from .colors import (
    PRIMARY_COLOR,
    PRIMARY_DARK,
    get_apply_filter_colors,
    get_compare_colors,
    get_export_colors,
    get_visualization_colors,
    get_import_colors,
)

# Utilidades de tema
from .theme_utils import (
    is_dark_mode,
    get_text_color,
    get_subtitle_color,
    get_container_translucent_bgcolor,
    get_card_color,
    get_icon_color,
    get_chart_palette,
    get_tops_chart_color,
    get_tops_chart_palette,
    get_filter_panel_bgcolor,
    get_dashboard_card_colors,
    get_action_tile_colors,
    get_compare_panel_bgcolor,
    get_compare_delta_color,
    get_compare_card_bgcolor,
    get_compare_value_color,
    get_compare_state_color,
    get_compare_bar_colors,
    update_container_theme,
    update_component_theme_recursive,
    get_compare_kpi_card_style,
    get_label_text_style,
    get_input_text_style,
)

# Componentes estilizados
from .components import (
    date_picker_chip,
    date_filter_chip,
    styled_button,
    clear_filter_button_style,
    delete_button_style,
    card_container,
    styled_dropdown,
    update_styled_dropdown,
)

# Constructores de tema
from .builders import (
    build_light_theme,
    build_dark_theme,
)


__all__ = [
    # Colores
    "PRIMARY_COLOR",
    "PRIMARY_DARK",
    "get_apply_filter_colors",
    "get_compare_colors",
    "get_export_colors",
    "get_visualization_colors",
    "get_import_colors",
    # Utilidades
    "is_dark_mode",
    "get_text_color",
    "get_subtitle_color",
    "get_container_translucent_bgcolor",
    "get_card_color",
    "get_compare_card_bgcolor",
    "get_compare_kpi_card_style",
    "get_icon_color",
    "get_chart_palette",
    "get_tops_chart_color",
    "get_compare_value_color",
    "get_tops_chart_palette",
    "get_compare_panel_bgcolor",
    "get_filter_panel_bgcolor",
    "get_compare_delta_color",
    "get_compare_state_color",
    "get_dashboard_card_colors",
    "get_action_tile_colors",
    "update_container_theme",
    "update_component_theme_recursive",
    # Componentes
    "date_picker_chip",
    "date_filter_chip",
    "styled_button",
    "clear_filter_button_style",
    "delete_button_style",
    "card_container",
    "styled_dropdown",
    "update_styled_dropdown",
    # Builders
    "build_light_theme",
    "build_dark_theme",
    # KPI
    "get_kpi_card_style",
]
