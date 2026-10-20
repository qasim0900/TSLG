"""
Componente: Embudo de conversión de leads (funnel visual nativo).

Exporta:
  build_funnel_chart(stats)   → ft.Column  (tapering bars)
  build_funnel_insight(stats) → ft.Text    (texto de resumen)

No realiza queries. Recibe stats calculadas por analysis.leads_analysis.get_funnel_stats().
"""
import flet as ft
from utils.formatting import pluralize


def build_funnel_chart(stats: dict) -> ft.Control:
    """
    Construye el funnel visual con tarjetas estilo Material Design 3.

    Cada etapa es una card con tonal container (PRIMARY/SECONDARY/TERTIARY),
    icono representativo, etiqueta, descripción y valor numérico dominante.
    Conectores entre etapas muestran la tasa de conversión inter-etapa.

    Args:
        stats: dict de get_funnel_stats() — claves: total, meetings, converted,
               lead_to_meeting_pct, meeting_to_client_pct.

    Returns:
        ft.Column centrada con cards y conectores, o ft.Text vacío si no hay datos.
    """
    total = stats["total"]
    meetings = stats["meetings"]
    converted = stats["converted"]

    if total == 0:
        return ft.Text("No lead data", color=ft.Colors.ON_SURFACE_VARIANT)

    stages = [
        {
            "label":       "Leads",
            "description": "Registered contacts",
            "value":       total,
            "icon":        ft.Icons.PERSON_ADD,
            "bgcolor":     ft.Colors.PRIMARY_CONTAINER,
            "text_color":  ft.Colors.ON_PRIMARY_CONTAINER,
        },
        {
            "label":       "Meetings",
            "description": "Leads with a scheduled meeting",
            "value":       meetings,
            "icon":        ft.Icons.EVENT,
            "bgcolor":     ft.Colors.SECONDARY_CONTAINER,
            "text_color":  ft.Colors.ON_SECONDARY_CONTAINER,
        },
        {
            "label":       "Clients",
            "description": "Leads converted to clients",
            "value":       converted,
            "icon":        ft.Icons.HANDSHAKE,
            "bgcolor":     ft.Colors.TERTIARY_CONTAINER,
            "text_color":  ft.Colors.ON_TERTIARY_CONTAINER,
        },
    ]

    # Conversion rates come directly from the pre-calculated stats dict
    connector_rates = [
        None,
        stats["lead_to_meeting_pct"],
        stats["meeting_to_client_pct"],
    ]

    _card_shadow = ft.BoxShadow(
        color=ft.Colors.with_opacity(0.1, ft.Colors.BLACK),
        blur_radius=12,
        offset=ft.Offset(0, 3),
    )

    items = []
    for i, stage in enumerate(stages):
        # Minimal connector between stages
        if i > 0:
            rate = connector_rates[i]
            items.append(
                ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.ARROW_DOWNWARD,
                            size=16,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        ft.Text(
                            f"{rate:.0f}% conversion",
                            size=11,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    ],
                    spacing=4,
                    alignment=ft.MainAxisAlignment.CENTER,
                )
            )

        items.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            stage["icon"],
                            size=28,
                            color=stage["text_color"],
                        ),
                        ft.Column(
                            [
                                ft.Text(
                                    stage["label"],
                                    size=14,
                                    weight=ft.FontWeight.W_600,
                                    color=stage["text_color"],
                                ),
                                ft.Text(
                                    stage["description"],
                                    size=11,
                                    color=stage["text_color"],
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        ft.Text(
                            str(stage["value"]),
                            size=28,
                            weight=ft.FontWeight.BOLD,
                            color=stage["text_color"],
                        ),
                    ],
                    spacing=16,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=20,
                border_radius=16,
                bgcolor=stage["bgcolor"],
                shadow=_card_shadow,
            )
        )

    return ft.Column(
        items,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=8,
    )


def build_funnel_insight(stats: dict) -> ft.Control:
    """
    Genera una frase de resumen sobre el rendimiento del funnel.

    Args:
        stats: dict de get_funnel_stats().

    Returns:
        ft.Column con texto principal e indicadores explícitos.
    """
    lead_to_meeting_pct = stats["lead_to_meeting_pct"]
    meetings = stats["meetings"]
    converted = stats["converted"]
    converted_from_meeting = stats.get("converted_from_meeting", stats["meetings"] - stats["meeting_dropoff"])

    if meetings == 0:
        main_text = "No meetings scheduled yet."
        sub_text = ""
    elif converted == 0:
        main_text = f"{lead_to_meeting_pct:.0f}% of leads scheduled a meeting, but none has converted yet."
        sub_text = f"0 of {pluralize(meetings, 'meeting')} converted  ·  Total clients: 0"
    else:
        conversion_rate = stats["meeting_to_client_pct"]
        main_text = (
            f"{lead_to_meeting_pct:.0f}% of leads convert to a meeting; "
            f"{conversion_rate:.0f}% of meetings converted to a client."
        )
        sub_text = f"{converted_from_meeting} of {pluralize(meetings, 'meeting')} converted  ·  Total clients: {converted}"

    inner = ft.Column(
        [
            ft.Row(
                [
                    ft.Icon(ft.Icons.LIGHTBULB_OUTLINE, size=16, color=ft.Colors.PRIMARY),
                    ft.Text(
                        main_text,
                        size=11,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        italic=True,
                        expand=True,
                    ),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        ],
        spacing=4,
    )
    if sub_text:
        inner.controls.append(
            ft.Text(sub_text, size=10, color=ft.Colors.ON_SURFACE_VARIANT)
        )

    return ft.Container(
        content=inner,
        padding=ft.Padding.only(left=14, right=12, top=10, bottom=10),
        border_radius=12,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.Border.only(left=ft.BorderSide(3, ft.Colors.PRIMARY)),
    )
