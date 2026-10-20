"""Componente de perfil de cliente — Customer 360 layout.

Regla importante: debe reaccionar a cambios de tema sin reconstruir TODO.
"""

import flet as ft

from analysis.db_utils import get_db_connection
from analysis.leads_analysis import get_leads
from components.tabla_leads import _STATUS_BADGE_MAP, _source_label
from theme import get_container_translucent_bgcolor, get_subtitle_color, get_text_color
from utils.formatting import format_eur, mask_sensitive
from utils.ui_dispatch import mounted_page


class ClientProfile(ft.Container):
    """
    Perfil de cliente — Customer 360 Layout.

    Layout:
        Header
        Row([Client Info Card, Marketing Card])
        Sales Stats Card
        Sales History Card

    Patrón A: Mutación simple en update_theme() — no reconstruye UI.
    """

    def __init__(
        self,
        client_info: dict,
        stats: dict,
        on_back,
        on_export=None,
    ):
        super().__init__()
        self.client_info = client_info or {}
        self.stats = stats or {}
        self.on_back = on_back
        self.on_export = on_export

        self.padding = 20
        self.border_radius = 12
        self.expand = True

        # 🔐 REFERENCIAS para mutar colores en update_theme() (Contrato R2/R9)
        self._title = None
        self._section_title_texts = []  # títulos de sección (bold, title_color)
        self._label_texts = []          # etiquetas de fila (bold, title_color)
        self._value_texts = []          # valores de fila y subtítulos (subtitle_color)
        self._dividers = []
        self._sales_table_texts = []    # encabezados + celdas de la tabla
        self._sales_empty_text = None
        self._stat_label_texts = []     # etiquetas de estadísticas (subtitle_color)
        self._stat_value_texts = []     # valores de estadísticas (title_color)
        # Each entry: (container, light_bg, dark_bg, icon_ref, txt_ref, light_fg, dark_fg)
        self._badge_info = []           # badges de source y status

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def did_mount(self):
        """Inicializa UI cuando el control esté montado (Flet 0.80+)."""
        self._build_ui()
        self.update_theme(self.page.theme_mode)
        self.page.update()

    # ─────────────────────────────────────────────────────────────────────────
    # Data helpers (read-only, no side effects)
    # ─────────────────────────────────────────────────────────────────────────

    def _get_lead_info(self):
        """Returns the most recent lead linked to this client, or None."""
        client_id = self.client_info.get("client_id")
        if not client_id:
            return None
        leads = get_leads(client_id=client_id)
        return leads[0] if leads else None

    def _get_funnel_events(self):
        """Returns the last 5 funnel events for this client (read-only)."""
        client_id = self.client_info.get("client_id")
        if not client_id:
            return []
        try:
            conn = get_db_connection()
            rows = conn.execute(
                "SELECT event_type, event_date FROM funnel_events "
                "WHERE client_id = ? ORDER BY event_date DESC LIMIT 5",
                (client_id,),
            ).fetchall()
            conn.close()
            return [{"event_type": r[0], "event_date": r[1]} for r in rows]
        except Exception:
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # UI builder
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        """Construye la UI completa (Customer 360 layout)."""
        if not mounted_page(self):
            return

        title_color = get_text_color(self.page.theme_mode)
        subtitle_color = get_subtitle_color(self.page.theme_mode)

        # Limpiar referencias previas
        self._section_title_texts.clear()
        self._label_texts.clear()
        self._value_texts.clear()
        self._dividers.clear()
        self._sales_table_texts.clear()
        self._stat_label_texts.clear()
        self._stat_value_texts.clear()
        self._badge_info.clear()

        # ── Data extraction ──────────────────────────────────────────────────
        name = self.client_info.get("name", "")
        cif = self.client_info.get("cif") or "—"
        address = self.client_info.get("address") or "—"
        contact_person = self.client_info.get("contact_person") or "—"
        email = self.client_info.get("email") or "—"

        lead_info = self._get_lead_info()
        funnel_events = self._get_funnel_events()

        # ── Shared helpers ───────────────────────────────────────────────────

        def _section_title(text):
            t = ft.Text(text, size=16, weight=ft.FontWeight.BOLD, color=title_color)
            self._section_title_texts.append(t)
            return t

        def _info_row(label, value):
            lbl = ft.Text(
                f"{label}:",
                weight=ft.FontWeight.BOLD,
                width=175,
                color=title_color,
            )
            val = ft.Text(str(value), color=subtitle_color)
            self._label_texts.append(lbl)
            self._value_texts.append(val)
            return ft.Row([lbl, val])

        def _masked_info_row(label, value):
            """Como _info_row pero con enmascarado hover-reveal para datos sensibles."""
            lbl = ft.Text(
                f"{label}:",
                weight=ft.FontWeight.BOLD,
                width=175,
                color=title_color,
            )
            value_str = str(value)
            masked = mask_sensitive(value_str)
            val = ft.Text(masked, color=subtitle_color)
            self._label_texts.append(lbl)
            self._value_texts.append(val)

            if masked == value_str:
                # Valor vacío/placeholder — no es necesario hacer hover
                return ft.Row([lbl, val])

            def on_hover(e):
                val.value = value_str if e.data else masked
                val.update()

            val_container = ft.Container(
                content=val,
                on_hover=on_hover,
                tooltip="Hover to reveal",
            )
            return ft.Row([lbl, val_container])

        def _divider():
            d = ft.Divider(color=subtitle_color)
            self._dividers.append(d)
            return d

        # ── HEADER ───────────────────────────────────────────────────────────
        btn_back = ft.IconButton(
            icon=ft.Icons.ARROW_BACK,
            icon_color=title_color,
            on_click=lambda _: self.on_back(),
            tooltip="Back to the client list",
        )
        self._title = ft.Text(
            f"👤 {name}", size=24, weight=ft.FontWeight.BOLD, color=title_color
        )
        header_controls = [btn_back, self._title]
        if self.on_export:
            btn_export = ft.IconButton(
                icon=ft.Icons.FILE_DOWNLOAD_OUTLINED,
                icon_color=title_color,
                on_click=lambda _: self.on_export(),
                tooltip="Export client profile to HTML",
            )
            header_controls.append(ft.Container(expand=True))
            header_controls.append(btn_export)
        header_row = ft.Row(
            header_controls,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # ── CLIENT INFO CARD ─────────────────────────────────────────────────
        client_info_card = ft.Container(
            content=ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        [
                            _section_title("Client information"),
                            _divider(),
                            _masked_info_row("Tax ID", cif),
                            _masked_info_row("Email", email),
                            _info_row("Contact person", contact_person),
                            _info_row("Address", address),
                        ],
                        spacing=8,
                    ),
                    padding=20,
                ),
                elevation=2,
            ),
            expand=1,
        )

        # ── MARKETING CARD ───────────────────────────────────────────────────

        # Status → (light_bgcolor, dark_bgcolor, light_fg, dark_fg, icon)
        _STATUS_MAP = {
            "converted": (ft.Colors.GREEN_100,  ft.Colors.GREEN_900,  ft.Colors.GREEN_900,  ft.Colors.GREEN_100,  ft.Icons.CHECK_CIRCLE),
            "contacted":  (ft.Colors.BLUE_100,   ft.Colors.BLUE_900,   ft.Colors.BLUE_900,   ft.Colors.BLUE_100,   ft.Icons.PHONE),
            "new":        (ft.Colors.GREY_200,   ft.Colors.GREY_700,   ft.Colors.GREY_800,   ft.Colors.GREY_200,   ft.Icons.FIBER_NEW),
            "lost":       (ft.Colors.RED_100,    ft.Colors.RED_900,    ft.Colors.RED_900,    ft.Colors.RED_100,    ft.Icons.CANCEL),
        }

        def _make_badge(label, light_bg, dark_bg, light_fg, dark_fg, icon_name):
            icon_ref = ft.Icon(icon_name, size=16, color=light_fg)
            txt_ref  = ft.Text(label, size=12, color=light_fg, weight=ft.FontWeight.W_500)
            container = ft.Container(
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                border_radius=8,
                bgcolor=light_bg,
                content=ft.Row([icon_ref, txt_ref], spacing=6, tight=True),
            )
            self._badge_info.append((container, light_bg, dark_bg, icon_ref, txt_ref, light_fg, dark_fg))
            return container

        marketing_body = []

        if lead_info:
            status_val = lead_info.get("status") or "—"
            status_key = status_val.lower()
            s_light_bg, s_dark_bg, s_light_fg, s_dark_fg, s_icon = _STATUS_MAP.get(
                status_key,
                (ft.Colors.GREY_200, ft.Colors.GREY_700, ft.Colors.GREY_800, ft.Colors.GREY_200, ft.Icons.CIRCLE),
            )
            source_badge = _make_badge(
                _source_label(lead_info.get("source")),
                ft.Colors.BLUE_100, ft.Colors.BLUE_900,
                ft.Colors.BLUE_900, ft.Colors.BLUE_100,
                ft.Icons.CAMPAIGN,
            )
            status_label = _STATUS_BADGE_MAP[status_key][0] if status_key in _STATUS_BADGE_MAP else status_val
            status_badge = _make_badge(status_label, s_light_bg, s_dark_bg, s_light_fg, s_dark_fg, s_icon)
            marketing_body.append(
                ft.Row([source_badge, status_badge], spacing=10)
            )
            for field, raw_value in [
                ("Lead created", (lead_info.get("created_at") or "—")[:10]),
                ("Meeting",
                 lead_info.get("meeting_date")[:10]
                 if lead_info.get("meeting_date") else "—"),
            ]:
                marketing_body.append(_info_row(field, raw_value))
        else:
            no_lead_txt = ft.Text("No linked lead", color=subtitle_color, italic=True)
            self._value_texts.append(no_lead_txt)
            marketing_body.append(no_lead_txt)

        if funnel_events:
            events_header = ft.Text(
                "Latest events",
                weight=ft.FontWeight.BOLD,
                size=13,
                color=title_color,
            )
            self._label_texts.append(events_header)
            marketing_body.append(ft.Container(height=6))
            marketing_body.append(events_header)
            for ev in funnel_events:
                ev_txt = ft.Text(
                    f"• {ev['event_type']}  {(ev['event_date'] or '')[:10]}",
                    size=12,
                    color=subtitle_color,
                )
                self._value_texts.append(ev_txt)
                marketing_body.append(ev_txt)

        marketing_card = ft.Container(
            content=ft.Card(
                content=ft.Container(
                    content=ft.Column(
                        [
                            _section_title("Marketing / Lead"),
                            _divider(),
                            *marketing_body,
                        ],
                        spacing=8,
                    ),
                    padding=20,
                ),
                elevation=2,
            ),
            expand=1,
        )

        # ── SALES STATS CARD ─────────────────────────────────────────────────
        def _stat_item(label, value):
            val_txt = ft.Text(
                value, size=22, weight=ft.FontWeight.BOLD, color=title_color
            )
            lbl_txt = ft.Text(label, size=13, color=subtitle_color)
            self._stat_value_texts.append(val_txt)
            self._stat_label_texts.append(lbl_txt)
            return ft.Column(
                [val_txt, lbl_txt],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
            )

        stats_card = ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        _section_title("Sales statistics"),
                        _divider(),
                        ft.Row(
                            [
                                _stat_item(
                                    "Total sales",
                                    str(self.stats.get("total_sales", 0)),
                                ),
                                _stat_item(
                                    "Total amount",
                                    format_eur(self.stats.get('total_amount', 0)),
                                ),
                                _stat_item(
                                    "Average per sale",
                                    format_eur(self.stats.get('avg_amount', 0)),
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ],
                    spacing=12,
                ),
                padding=20,
            ),
            elevation=2,
        )

        # ── SALES HISTORY CARD ───────────────────────────────────────────────
        sales_rows = []
        for s in self.stats.get("sales", []):
            date_txt  = ft.Text(s["date"],                    size=12, color=title_color)
            prod_txt  = ft.Text(s["product_type"],            size=12, color=title_color)
            price_txt = ft.Text(format_eur(s['price']),  size=12, color=title_color)
            self._sales_table_texts.extend([date_txt, prod_txt, price_txt])
            sales_rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(date_txt),
                        ft.DataCell(prod_txt),
                        ft.DataCell(price_txt),
                    ]
                )
            )

        if sales_rows:
            fecha_hdr   = ft.Text("Date",    weight="bold", color=title_color)
            product_hdr = ft.Text("Product", weight="bold", color=title_color)
            precio_hdr  = ft.Text("Price",   weight="bold", color=title_color)
            self._sales_table_texts.extend([fecha_hdr, product_hdr, precio_hdr])
            table_content = ft.DataTable(
                columns=[
                    ft.DataColumn(fecha_hdr),
                    ft.DataColumn(product_hdr),
                    ft.DataColumn(precio_hdr),
                ],
                rows=sales_rows,
            )
        else:
            self._sales_empty_text = ft.Text(
                "No sales yet", color=subtitle_color, italic=True
            )
            table_content = self._sales_empty_text

        history_card = ft.Card(
            content=ft.Container(
                content=ft.Column(
                    [
                        _section_title("Sales history"),
                        _divider(),
                        table_content,
                    ],
                    spacing=12,
                ),
                padding=20,
            ),
            elevation=2,
        )

        # ── MAIN LAYOUT ──────────────────────────────────────────────────────
        self.content = ft.Column(
            [
                header_row,
                ft.Row(
                    [client_info_card, marketing_card],
                    spacing=20,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                stats_card,
                history_card,
            ],
            spacing=20,
            scroll=ft.ScrollMode.AUTO,
        )

        self.bgcolor = get_container_translucent_bgcolor(self.page.theme_mode)

    # ─────────────────────────────────────────────────────────────────────────
    # Theme
    # ─────────────────────────────────────────────────────────────────────────

    def update_theme(self, theme_mode=None):
        """
        Actualiza tema con Patrón A (SOLO MUTACIÓN simple).

        ✅ PERMITIDO: mutar .color de textos y divisores, .bgcolor del container.
        ❌ PROHIBIDO: reconstruir UI completa.
        """
        if theme_mode is None:
            theme_mode = self.page.theme_mode

        title_color = get_text_color(theme_mode)
        subtitle_color = get_subtitle_color(theme_mode)

        if self._title:
            self._title.color = title_color

        for t in self._section_title_texts:
            t.color = title_color

        for t in self._label_texts:
            t.color = title_color

        for t in self._value_texts:
            t.color = subtitle_color

        for d in self._dividers:
            d.color = subtitle_color

        for t in self._sales_table_texts:
            t.color = title_color

        if self._sales_empty_text:
            self._sales_empty_text.color = subtitle_color

        for t in self._stat_value_texts:
            t.color = title_color

        for t in self._stat_label_texts:
            t.color = subtitle_color

        # Mutar badges de source y status
        is_dark = theme_mode == ft.ThemeMode.DARK
        for container, light_bg, dark_bg, icon_ref, txt_ref, light_fg, dark_fg in self._badge_info:
            container.bgcolor = dark_bg if is_dark else light_bg
            icon_ref.color    = dark_fg if is_dark else light_fg
            txt_ref.color     = dark_fg if is_dark else light_fg

        self.bgcolor = get_container_translucent_bgcolor(theme_mode)

        # ✅ NO llamar self.update() aquí — la vista orquesta un único page.update()


def create_client_profile(
    client_info: dict,
    stats: dict,
    on_back,
    on_export=None,
):
    """Factory para mantener compatibilidad con imports existentes."""
    return ClientProfile(client_info=client_info, stats=stats, on_back=on_back, on_export=on_export)
