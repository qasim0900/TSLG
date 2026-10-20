"""Tarjeta KPI compacta para el dashboard principal."""
import flet as ft
from theme import get_kpi_card_style
from utils.ui_dispatch import mounted_page

_CARD_HEIGHT = 88  # Altura fija compartida por todas las KPICard


class KPICard(ft.Container):
    """
    Tipo A puro: todo construido en __init__, sin did_mount.
    theme_mode se pasa como parámetro porque self.page no existe aún en __init__.

    Patrón hover (Flet 0.81.0):
    - KPICard (outer wrapper): solo expand=True para layout en Row.
    - _inner (Container): toda la estética + scale + animate + on_hover.
    Separar expand del control animado evita que Flet bloquee la transformación scale.
    """

    def __init__(
        self,
        *,
        title: str,
        value: str,
        icon: ft.Icons,
        theme_mode: ft.ThemeMode,
        subtitle: str | None = None,
        accent_color: ft.Colors | None = None,
        expand: bool = True,
    ):
        self._title = title
        self._value = value
        self._subtitle = subtitle
        self._icon = icon
        self._accent_color = accent_color or ft.Colors.BLUE

        # Referencias mutables para update_theme()
        self._value_text = None
        self._title_text = None
        self._subtitle_text = None
        self._icon_circle = None
        self._icon_obj = None
        self._inner = None

        style = get_kpi_card_style(theme_mode, self._accent_color)
        # Base bgcolor para restaurar correctamente on_hover=False tras cambio de tema
        self._base_bgcolor = style["bgcolor"]

        self._inner = self._build_inner(style)

        # Outer wrapper: layout (expand + height fija).
        # expand=True + height aquí; scale va en _inner — no mezclar scale con expand.
        super().__init__(
            expand=expand,
            height=_CARD_HEIGHT,
            content=self._inner,
        )

    def _build_inner(self, style: dict) -> ft.Container:
        """Construye el contenedor visual interno con hover y animaciones."""
        self._icon_obj = ft.Icon(
            self._icon,
            size=22,
            color=style["icon_color"],
        )

        self._icon_circle = ft.Container(
            width=42,
            height=42,
            border_radius=21,
            bgcolor=style["icon_bg"],
            alignment=ft.Alignment.CENTER,
            content=self._icon_obj,
        )

        self._value_text = ft.Text(
            self._value,
            size=26,
            weight=ft.FontWeight.BOLD,
            color=style["value_color"],
        )

        self._title_text = ft.Text(
            self._title,
            size=13,
            color=style["title_color"],
        )

        texts = [self._value_text, self._title_text]

        if self._subtitle:
            self._subtitle_text = ft.Text(
                self._subtitle,
                size=12,
                color=style["subtitle_color"],
            )
            texts.append(self._subtitle_text)

        content = ft.Row(
            [
                self._icon_circle,
                ft.Column(
                    texts,
                    spacing=2,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ],
            spacing=14,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Container(
            content=content,
            padding=8,
            border_radius=14,
            bgcolor=style["bgcolor"],
            shadow=style["shadow"],
            border=style.get("border"),
            scale=1.0,
            animate=ft.Animation(200, ft.AnimationCurve.DECELERATE),
            animate_scale=ft.Animation(200, ft.AnimationCurve.DECELERATE),
            on_hover=self._on_hover,
        )

    def _on_hover(self, e):
        is_hovered = e.data
        e.control.scale = 1.05 if is_hovered else 1.0
        e.control.bgcolor = (
            ft.Colors.SURFACE_CONTAINER_HIGHEST if is_hovered
            else self._base_bgcolor
        )
        e.control.update()

    def update_theme(self, theme_mode=None):
        """Muta colores sin reconstruir."""
        if theme_mode is None:
            if mounted_page(self):
                theme_mode = self.page.theme_mode
            else:
                return

        style = get_kpi_card_style(theme_mode, self._accent_color)

        # Actualizar base_bgcolor para que _on_hover restaure al color correcto del nuevo tema
        self._base_bgcolor = style["bgcolor"]

        # Mutaciones en _inner (contenedor visual)
        self._inner.bgcolor = style["bgcolor"]
        self._inner.shadow = style["shadow"]

        if self._icon_circle:
            self._icon_circle.bgcolor = style["icon_bg"]

        if self._icon_obj:
            self._icon_obj.color = style["icon_color"]

        if self._value_text:
            self._value_text.color = style["value_color"]

        if self._title_text:
            self._title_text.color = style["title_color"]

        if self._subtitle_text:
            self._subtitle_text.color = style["subtitle_color"]

        # ✅ NO llamar self.update() aquí (la vista orquesta un único page.update())
