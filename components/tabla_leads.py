"""
Componente: Tabla de leads recientes.

Exporta:
  build_leads_table(leads) → ft.DataTable | ft.Text

No realiza queries. Recibe una lista de leads enriched del controlador.
"""
import flet as ft
from datetime import date, datetime
from domain.source_labels import SOURCE_LABELS


# ---------------------------------------------------------------------------
# Helpers — computed / display fields (pure functions, no side-effects)
# ---------------------------------------------------------------------------

_SOURCE_LABELS = SOURCE_LABELS

_MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _source_label(raw: str | None) -> str:
    if not raw:
        return "—"
    return _SOURCE_LABELS.get(raw.lower(), raw)


def _lead_age_days(created_at_str: str | None) -> int | None:
    """Return days since lead was created, or None if unparseable."""
    if not created_at_str:
        return None
    try:
        created = datetime.fromisoformat(created_at_str[:10]).date()
        return (date.today() - created).days
    except (ValueError, TypeError):
        return None


def _age_color(days: int, is_dark: bool = False) -> str:
    """Return a text color token based on lead age urgency."""
    if days > 30:
        return ft.Colors.RED_300 if is_dark else ft.Colors.RED_800
    if days >= 7:
        return ft.Colors.ORANGE_300 if is_dark else ft.Colors.DEEP_ORANGE_900
    return ft.Colors.ON_SURFACE_VARIANT


def _lead_initials(lead_id: str | None) -> str:
    """Derive 2-char uppercase initials from lead_id."""
    if lead_id and len(lead_id) >= 2:
        return lead_id[:2].upper()
    return "??"


def _lead_cell(created_at_str: str | None, lead_id: str | None) -> ft.Row:
    """
    Avatar circle + two-line date/id cell.
    Example:
        [A3]  Mar 14
              #a3f2
    """
    date_label = "—"
    if created_at_str and len(created_at_str) >= 10:
        try:
            d = datetime.fromisoformat(created_at_str[:10]).date()
            date_label = f"{_MONTH_ABBR[d.month]} {d.day}"
        except (ValueError, TypeError):
            pass

    id_suffix = f"#{lead_id[:4]}" if lead_id else ""
    initials = _lead_initials(lead_id)

    avatar = ft.Container(
        content=ft.Text(
            initials,
            size=10,
            weight=ft.FontWeight.W_700,
            color=ft.Colors.PRIMARY,
        ),
        width=32,
        height=32,
        border_radius=999,
        bgcolor=ft.Colors.PRIMARY_CONTAINER,
        alignment=ft.Alignment(0, 0),
    )

    return ft.Row(
        [
            avatar,
            ft.Column(
                [
                    ft.Text(date_label, size=12, weight=ft.FontWeight.W_500),
                    ft.Text(id_suffix, size=10, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                spacing=1,
                tight=True,
            ),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


_STATUS_BADGE_MAP: dict[str, tuple] = {
    "new":       ("Lead",       ft.Colors.BLUE_100,   ft.Colors.BLUE_900),
    "contacted": ("Contacted", ft.Colors.PURPLE_100, ft.Colors.PURPLE_800),
    "meeting":   ("Meeting",   ft.Colors.ORANGE_50,  ft.Colors.DEEP_ORANGE_900),
    "converted": ("Client",   ft.Colors.GREEN_100,  ft.Colors.GREEN_900),
    "lost":      ("Lost",   ft.Colors.RED_100,    ft.Colors.RED_900),
}


def _stage_badge(status: str | None) -> ft.Container:
    """Return a colored pill badge derived exclusively from the lead's status field."""
    label, bgcolor, text_color = _STATUS_BADGE_MAP.get(
        (status or "").lower().strip(),
        ("Lead", ft.Colors.BLUE_100, ft.Colors.BLUE_900),  # fallback for unknown/empty values
    )
    return ft.Container(
        content=ft.Text(label, size=10, weight=ft.FontWeight.W_600, color=text_color),
        bgcolor=bgcolor,
        border_radius=999,
        padding=ft.Padding.symmetric(horizontal=12, vertical=4),
    )


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_leads_table(leads: list, theme_mode=None) -> ft.Control:
    """
    Construye una DataTable con los leads más recientes.

    Columnas: Lead | Edad | Fuente | Stage | Reunión | Cliente

    Args:
        leads: Lista de dicts enriched — claves: id, created_at, source,
               meeting_date, client_id, client_name.
        theme_mode: ft.ThemeMode — para colores adaptativos.

    Returns:
        ft.DataTable, o ft.Text si la lista está vacía.
    """
    _is_dark = theme_mode == ft.ThemeMode.DARK
    if not leads:
        return ft.Text(
            "No leads yet.",
            size=14,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )

    rows = []
    for ld in leads:
        created_at = (ld.get("created_at") or "")[:10]
        meeting_date = ld.get("meeting_date")
        meeting_str = meeting_date[:10] if meeting_date else "—"
        client_name = ld.get("client_name") or "—"
        lead_id = ld.get("id") or ""

        age_days = _lead_age_days(created_at)
        age_str = f"{age_days}d" if age_days is not None else "—"
        age_color = _age_color(age_days, _is_dark) if age_days is not None else ft.Colors.ON_SURFACE_VARIANT

        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(_lead_cell(created_at, lead_id)),
                    ft.DataCell(ft.Text(age_str, size=12, color=age_color)),
                    ft.DataCell(ft.Row([ft.Text(_source_label(ld.get("source")), size=12)], expand=True)),
                    ft.DataCell(_stage_badge(ld.get("status"))),

                    ft.DataCell(ft.Text(meeting_str, size=12)),
                    ft.DataCell(ft.Row([ft.Text(client_name, size=12)], expand=True)),
                ],
                color={
                    ft.ControlState.HOVERED: (
                        ft.Colors.SURFACE_CONTAINER_HIGH if _is_dark
                        else ft.Colors.BLUE_50
                    ),
                },
            )
        )

    return ft.Container(
        content=ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Lead", weight=ft.FontWeight.W_600)),
                ft.DataColumn(ft.Text("Age", weight=ft.FontWeight.W_600), numeric=True),
                ft.DataColumn(ft.Text("Source", weight=ft.FontWeight.W_600)),
                ft.DataColumn(ft.Text("Stage", weight=ft.FontWeight.W_600)),
                ft.DataColumn(ft.Text("Meeting", weight=ft.FontWeight.W_600)),
                ft.DataColumn(ft.Text("Client", weight=ft.FontWeight.W_600)),
            ],
            rows=rows,
            column_spacing=60,
            horizontal_margin=20,
            heading_row_height=40,
            data_row_min_height=44,
            show_checkbox_column=False,
            heading_row_color=ft.Colors.PRIMARY_CONTAINER if _is_dark else ft.Colors.BLUE_50,
            expand=True,
        ),
        expand=True,
    )
