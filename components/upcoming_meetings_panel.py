"""
Componente: Panel lateral de próximas reuniones.

Exporta:
  build_upcoming_meetings_panel(all_leads, theme_mode) → ft.Container

Extraído de views/leads_view.py._build_analytics_panel().
No realiza queries. Recibe lista de leads del controlador.
"""

import flet as ft
from datetime import date, timedelta

from components.tabla_leads import _SOURCE_LABELS
from theme import get_text_color


def build_upcoming_meetings_panel(all_leads: list, theme_mode) -> ft.Container:
    """
    Right-side panel: upcoming meetings (max 3).

    Args:
        all_leads: Full list of enriched lead dicts.
        theme_mode: ft.ThemeMode for color derivation.

    Returns:
        ft.Container with meeting items or "no meetings" placeholder.
        Also stores _analytics_title_texts on the returned container for theme updates.
    """
    _card_shadow = ft.BoxShadow(
        color=ft.Colors.with_opacity(0.08, ft.Colors.BLACK),
        blur_radius=12,
        offset=ft.Offset(0, 3),
    )
    _title_col = get_text_color(theme_mode)

    # ── Upcoming meetings ─────────────────────────────────────────
    today = date.today().isoformat()
    upcoming = sorted(
        [
            ld for ld in all_leads
            if ld.get("meeting_date") and str(ld["meeting_date"]) >= today
        ],
        key=lambda x: x["meeting_date"],
    )[:3]

    if upcoming:
        today_str = today
        tomorrow_str = (date.today() + timedelta(days=1)).isoformat()

        def _meeting_colors(meeting_date_str: str):
            if str(meeting_date_str) == today_str:
                return ft.Colors.ERROR, ft.Colors.ERROR_CONTAINER, "TODAY", ft.Colors.ERROR
            if str(meeting_date_str) == tomorrow_str:
                return ft.Colors.AMBER_700, ft.Colors.with_opacity(0.12, ft.Colors.AMBER_400), "TOMORROW", ft.Colors.ON_SURFACE
            try:
                meeting_day = date.fromisoformat(str(meeting_date_str)[:10])
                label = f"{meeting_day:%b} {meeting_day.day}"
            except ValueError:
                label = str(meeting_date_str)[:10]
            return ft.Colors.PRIMARY, ft.Colors.SURFACE_CONTAINER, label, ft.Colors.PRIMARY

        meeting_items = []
        for ld in upcoming:
            m_date = str(ld["meeting_date"])
            border_color, badge_bg, date_label, badge_text_color = _meeting_colors(m_date)
            client_name = ld.get("client_name")
            name = client_name if client_name and client_name != "—" else f"Lead #{ld.get('id') or '—'}"
            source_label = _SOURCE_LABELS.get(ld.get("source", ""), ld.get("source", "—"))

            meeting_items.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Container(
                                        content=ft.Text(
                                            date_label,
                                            size=9,
                                            weight=ft.FontWeight.W_700,
                                            color=badge_text_color,
                                        ),
                                        bgcolor=badge_bg,
                                        border_radius=999,
                                        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                                    ),
                                ],
                            ),
                            ft.Text(
                                name,
                                size=12,
                                weight=ft.FontWeight.W_600,
                                no_wrap=True,
                            ),
                            ft.Text(
                                source_label,
                                size=10,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                        spacing=3,
                    ),
                    padding=ft.Padding.only(left=14, right=12, top=10, bottom=10),
                    border_radius=12,
                    bgcolor=ft.Colors.SURFACE_CONTAINER,
                    border=ft.Border.only(left=ft.BorderSide(3, border_color)),
                )
            )
    else:
        meeting_items = [
            ft.Text(
                "No upcoming meetings",
                color=ft.Colors.ON_SURFACE_VARIANT,
                size=12,
            )
        ]

    t_meetings = ft.Text("Upcoming meetings", size=14, weight=ft.FontWeight.W_700, color=_title_col)
    _label = ft.Text(
        "UPCOMING",
        size=9,
        weight=ft.FontWeight.W_700,
        color=ft.Colors.ON_SURFACE_VARIANT,
    )
    _header_row = ft.Row(
        [t_meetings, _label],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    container = ft.Container(
        content=ft.Column(
            [
                _header_row,
                ft.Column(meeting_items, spacing=8),
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        ),
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
        border_radius=20,
        padding=20,
        shadow=_card_shadow,
        expand=1,
    )

    # Expose title texts for theme update access
    container._analytics_title_texts = [t_meetings]

    return container
