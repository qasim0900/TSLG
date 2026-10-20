"""
Componente: Ranking de conversión por fuente de leads.

Exporta:
  build_conversion_ranking(sources_data) → ft.Control

Extraído de views/leads_view.py._build_conversion_ranking().
No realiza queries. Recibe datos agregados del controlador.
"""

import flet as ft

# Per-source palette: (bgcolor, text_color)
_SOURCE_CHIP_COLORS: dict[str, tuple] = {
    "meta_ads":      (ft.Colors.with_opacity(0.18, ft.Colors.BLUE_400),       ft.Colors.BLUE_700),
    "google_ads":    (ft.Colors.with_opacity(0.18, ft.Colors.RED_400),        ft.Colors.RED_700),
    "linkedin_ads":  (ft.Colors.with_opacity(0.18, ft.Colors.INDIGO_400),     ft.Colors.INDIGO_700),
    "tiktok_ads":    (ft.Colors.with_opacity(0.18, ft.Colors.PINK_400),       ft.Colors.PINK_800),
    "referral":      (ft.Colors.with_opacity(0.18, ft.Colors.GREEN_400),      ft.Colors.GREEN_800),
    "organic":       (ft.Colors.with_opacity(0.18, ft.Colors.TEAL_400),       ft.Colors.TEAL_800),
    "manual_import": (ft.Colors.with_opacity(0.18, ft.Colors.GREY_400),       ft.Colors.GREY_800),
}
_DEFAULT_CHIP = (ft.Colors.SURFACE_CONTAINER_HIGHEST, ft.Colors.ON_SURFACE)


def build_conversion_ranking(sources_data: dict) -> ft.Control:
    """
    Vertical ranking list: source chip | lead count | conversion badge.

    Args:
        sources_data: Dict keyed by source name, each value has:
            total, clients, meeting_to_client_pct, avg_time_to_meeting

    Returns:
        ft.Column with ranking rows, or placeholder text if no data.
    """
    if not sources_data:
        return ft.Text("No source data", color=ft.Colors.ON_SURFACE_VARIANT)

    total_leads_global = sum(d["total"] for d in sources_data.values()) or 1

    rows = [ft.Text("Conversion by source", size=14, weight=ft.FontWeight.W_600)]
    for src, data in sorted(
        sources_data.items(), key=lambda x: x[1]["total"], reverse=True
    ):
        total = data["total"]
        clients = data["clients"]
        conversion_rate = (clients / total * 100) if total > 0 else 0
        share = total / total_leads_global

        meeting_to_client_pct = data.get("meeting_to_client_pct", 0.0)

        chip_bg, chip_text = _SOURCE_CHIP_COLORS.get(src, _DEFAULT_CHIP)
        source_chip = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            border_radius=999,
            bgcolor=chip_bg,
            content=ft.Text(src, size=10, weight=ft.FontWeight.W_600, color=chip_text),
        )
        conversion_badge = ft.Container(
            padding=ft.Padding.symmetric(horizontal=8, vertical=2),
            border_radius=999,
            bgcolor=ft.Colors.TERTIARY_CONTAINER,
            content=ft.Text(
                f"{conversion_rate:.0f}%",
                size=10,
                weight=ft.FontWeight.W_600,
                color=ft.Colors.ON_TERTIARY_CONTAINER,
            ),
        )
        rows.append(
            ft.Column(
                [
                    ft.Row(
                        [
                            source_chip,
                            ft.Text(
                                f"{total} leads",
                                size=11,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                expand=True,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            conversion_badge,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    ft.ProgressBar(
                        value=share,
                        bgcolor=ft.Colors.SURFACE_CONTAINER,
                        color=chip_text,
                        height=4,
                        border_radius=2,
                    ),
                    ft.Text(
                        f"{meeting_to_client_pct:.0f}% closed  ·  {data.get('avg_time_to_meeting', 0.0):.1f}d to meeting",
                        size=9,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                        italic=True,
                    ),
                ],
                spacing=4,
            )
        )

    return ft.Column(rows, spacing=12)
