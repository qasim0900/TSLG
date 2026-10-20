"""
Componente: Fila de KPI cards para la vista de Leads.

Exporta:
  build_kpi_row(stats) → ft.Row  (5 cards con hover animation)

No realiza queries. Recibe stats calculadas por analysis.leads_analysis.get_funnel_stats().

Patrón hover (Flet 0.81.0):
  - Wrapper externo con expand=True (layout)
  - Inner card con scale + animate + animate_scale + on_hover (animación)
"""
import flet as ft


def build_kpi_row(stats: dict, inactive_count: int = 0) -> ft.Row:
    """
    Construye una fila de KPI cards con hover animation.

    Args:
        stats: dict de get_funnel_stats() — claves: total, meetings, converted,
               lead_to_meeting_pct, meeting_to_client_pct, lead_dropoff, meeting_dropoff.
        inactive_count: leads sin meeting_date ni client_id, computado en _build_ui.

    Returns:
        ft.Row con cards que se expanden horizontalmente.
    """
    total = stats["total"]
    meetings = stats["meetings"]
    converted = stats["converted"]
    lead_to_meeting_pct = stats["lead_to_meeting_pct"]
    meeting_to_client_pct = stats["meeting_to_client_pct"]
    lead_dropoff = stats["lead_dropoff"]
    meeting_dropoff = stats["meeting_dropoff"]
    avg_days = stats["avg_time_to_meeting"]
    avg_days_str = f"{avg_days:.1f} days" if avg_days > 0 else "— days"
    converted_from_meeting = stats.get("converted_from_meeting", 0)
    direct_clients = converted - converted_from_meeting
    if converted > 0:
        clientes_sub = f"{converted_from_meeting} from meetings · {direct_clients} direct"
    else:
        clientes_sub = "—"

    cards_data = [
        ("Leads",                str(total),                       ft.Colors.BLUE_400,        ft.Icons.PERSON_ADD_ROUNDED,       None),
        ("Meetings",             str(meetings),                    ft.Colors.AMBER_600,        ft.Icons.EVENT_ROUNDED,            None),
        ("Clients",              str(converted),                   ft.Colors.GREEN_500,        ft.Icons.VERIFIED_ROUNDED,         clientes_sub),
        ("Lead→Meeting",         f"{lead_to_meeting_pct:.0f}%",   ft.Colors.BLUE_ACCENT_400,  ft.Icons.TRENDING_UP_ROUNDED,      None),
        ("Meeting→Client",       f"{meeting_to_client_pct:.0f}%", ft.Colors.GREEN_400,        ft.Icons.CHECK_CIRCLE_ROUNDED,     None),
        ("No meeting",           str(lead_dropoff),               ft.Colors.ORANGE_400,       ft.Icons.PERSON_OFF_ROUNDED,       None),
        ("Open meetings",        str(meeting_dropoff),            ft.Colors.RED_400,          ft.Icons.EVENT_BUSY_ROUNDED,       None),
        ("No action",            str(inactive_count),             ft.Colors.GREY_500,         ft.Icons.PENDING_ROUNDED,          None),
        ("Time to meeting",      avg_days_str,                    ft.Colors.PURPLE_300,       ft.Icons.SCHEDULE_ROUNDED,         None),
    ]

    return ft.Row(
        [_build_kpi_card(title, value, color, icon, sub) for title, value, color, icon, sub in cards_data],
        spacing=12,
    )


def _build_kpi_card(title: str, value_str: str, accent_color, icon_name, subtitle: str | None = None) -> ft.Container:
    """
    Card individual con hover animation.

    Patrón: Wrapper externo (expand=True, layout) + inner card (escala + color + on_hover).
    Separar expand del control animado evita que Flet bloquee la transformación scale.
    """

    def on_hover(e):
        is_hovered = e.data
        e.control.scale = 1.05 if is_hovered else 1.0
        e.control.bgcolor = (
            ft.Colors.SURFACE_CONTAINER_HIGHEST if is_hovered
            else ft.Colors.SURFACE_CONTAINER
        )
        e.control.update()

    column_controls = [
        ft.Row(
            [
                ft.Icon(icon_name, size=16, color=accent_color),
                ft.Text(title, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        ft.Text(
            value_str,
            size=28,
            weight=ft.FontWeight.BOLD,
            color=accent_color,
        ),
    ]
    if subtitle:
        column_controls.append(
            ft.Text(subtitle, size=10, color=ft.Colors.ON_SURFACE_VARIANT)
        )

    inner_card = ft.Container(
        content=ft.Column(column_controls, spacing=4),
        padding=ft.Padding.symmetric(horizontal=20, vertical=20),
        border_radius=16,
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        scale=1.0,
        # Animar tanto la escala como el color de fondo simultáneamente
        animate=ft.Animation(200, ft.AnimationCurve.DECELERATE),
        animate_scale=ft.Animation(200, ft.AnimationCurve.DECELERATE),
        on_hover=on_hover,
    )

    # Wrapper: solo gestiona layout (expand)
    return ft.Container(content=inner_card, expand=True)
