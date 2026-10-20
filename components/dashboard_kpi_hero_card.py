"""
KPI Hero Card — Gran tarjeta de KPI para el Dashboard rediseñado.

Diseño premium con hover, animaciones y soporte completo de tema.
Patrón wrapper/inner (Flet 0.82): outer maneja layout (expand + height),
inner maneja estética y animaciones (scale, bgcolor, hover).
"""
import flet as ft
from utils.ui_dispatch import mounted_page

_CARD_HEIGHT = 170


class KPIHeroCard(ft.Container):
    """
    Tarjeta KPI grande con diseño jerárquico y premium.

    Tipo A: construida íntegramente en __init__, sin did_mount().
    on_hover: e.data es bool Python directo (Flet 0.82).
    """

    def __init__(
        self,
        *,
        icon: ft.Icons,
        accent_color,
        main_value: str,
        main_label: str,
        chips: list,  # [{"icon": ft.Icons.X, "text": str, "color": ft.Colors.X}]
        theme_mode: ft.ThemeMode,
        trend_icon=ft.Icons.SHOW_CHART,
        expand: bool = True,
    ):
        self._icon = icon
        self._accent_color = accent_color
        self._main_value = main_value
        self._main_label = main_label
        self._chips_data = chips
        self._trend_icon = trend_icon

        # Mutable refs for update_theme()
        self._inner = None
        self._icon_circle = None
        self._icon_obj = None
        self._value_text = None
        self._label_text = None
        self._chip_containers = []
        self._trend_icon_obj = None
        self._base_bgcolor = None

        is_dark = theme_mode == ft.ThemeMode.DARK
        self._base_bgcolor = (
            ft.Colors.SURFACE_CONTAINER if is_dark else ft.Colors.SURFACE
        )

        self._inner = self._build_inner(is_dark)

        # Outer: layout only (expand + height). scale vive en _inner, NO aquí.
        super().__init__(
            expand=expand,
            height=_CARD_HEIGHT,
            content=self._inner,
        )

    def _build_inner(self, is_dark: bool) -> ft.Container:
        # Ícono con círculo de acento
        self._icon_obj = ft.Icon(
            self._icon, size=20, color=self._accent_color
        )
        self._icon_circle = ft.Container(
            width=40,
            height=40,
            border_radius=20,
            bgcolor=ft.Colors.with_opacity(
                0.14 if is_dark else 0.10, self._accent_color
            ),
            alignment=ft.Alignment.CENTER,
            content=self._icon_obj,
        )

        # Valor principal — grande y dominante
        self._value_text = ft.Text(
            self._main_value,
            size=40,
            weight=ft.FontWeight.W_700,
            color=ft.Colors.ON_SURFACE,
        )

        # Label pequeño, subordinado
        self._label_text = ft.Text(
            self._main_label,
            size=11,
            color=ft.Colors.ON_SURFACE_VARIANT,
            weight=ft.FontWeight.W_400,
        )

        # Chips secundarios — compactos
        chips_controls = []
        self._chip_containers = []
        for chip in self._chips_data:
            chip_icon = ft.Icon(chip["icon"], size=12, color=chip["color"])
            chip_text = ft.Text(
                chip["text"],
                size=10,
                color=ft.Colors.ON_SURFACE_VARIANT,
                weight=ft.FontWeight.W_500,
            )
            chip_container = ft.Container(
                content=ft.Row([chip_icon, chip_text], spacing=3, tight=True),
                bgcolor=ft.Colors.with_opacity(0.08, chip["color"]),
                border_radius=20,
                padding=ft.Padding.symmetric(horizontal=7, vertical=3),
            )
            self._chip_containers.append(chip_container)
            chips_controls.append(chip_container)

        chips_row = ft.Row(chips_controls, spacing=5, wrap=True)

        # Ícono de tendencia decorativo — esquina derecha, sutil
        self._trend_icon_obj = ft.Icon(
            self._trend_icon,
            size=44,
            color=ft.Colors.with_opacity(0.09, self._accent_color),
        )

        shadow_blur = 28 if is_dark else 18
        shadow_color = ft.Colors.with_opacity(
            0.18 if is_dark else 0.08, ft.Colors.ON_SURFACE
        )

        # Layout: ícono+valor en Row (top), label (medio), chips (bottom)
        # trend_icon flota en la esquina derecha via Stack
        content_col = ft.Column(
            [
                ft.Row(
                    [self._icon_circle, self._value_text],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._label_text,
                ft.Container(height=6),
                chips_row,
            ],
            spacing=3,
            expand=True,
        )

        return ft.Container(
            content=ft.Stack(
                [
                    ft.Container(
                        content=content_col,
                        padding=ft.Padding.only(
                            left=20, top=16, bottom=16, right=60
                        ),
                    ),
                    ft.Container(
                        content=self._trend_icon_obj,
                        right=8,
                        bottom=8,
                    ),
                ],
            ),
            border_radius=22,
            bgcolor=self._base_bgcolor,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=shadow_blur,
                offset=ft.Offset(0, 6),
                color=shadow_color,
            ),
            border=ft.Border.all(
                1,
                ft.Colors.with_opacity(
                    0.10 if is_dark else 0.06, ft.Colors.OUTLINE
                ),
            ),
            scale=1.0,
            animate=ft.Animation(200, ft.AnimationCurve.DECELERATE),
            animate_scale=ft.Animation(200, ft.AnimationCurve.DECELERATE),
            on_hover=self._on_hover,
        )

    def _on_hover(self, e):
        # e.data es bool Python en Flet 0.82 — NUNCA e.data == "true"
        is_hovered = e.data
        e.control.scale = 1.02 if is_hovered else 1.0
        e.control.bgcolor = (
            ft.Colors.SURFACE_CONTAINER_HIGH if is_hovered
            else self._base_bgcolor
        )

    def update_theme(self, theme_mode=None):
        """Muta colores sin reconstruir. Caller es responsable de page.update()."""
        if theme_mode is None:
            if mounted_page(self):
                theme_mode = self.page.theme_mode
            else:
                return

        is_dark = theme_mode == ft.ThemeMode.DARK
        self._base_bgcolor = (
            ft.Colors.SURFACE_CONTAINER if is_dark else ft.Colors.SURFACE
        )

        if self._inner:
            self._inner.bgcolor = self._base_bgcolor
            self._inner.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=28 if is_dark else 18,
                offset=ft.Offset(0, 6),
                color=ft.Colors.with_opacity(
                    0.18 if is_dark else 0.08, ft.Colors.ON_SURFACE
                ),
            )

        if self._icon_circle:
            self._icon_circle.bgcolor = ft.Colors.with_opacity(
                0.14 if is_dark else 0.10, self._accent_color
            )

        # ON_SURFACE y ON_SURFACE_VARIANT son semánticos → se adaptan automáticamente
        # Chip containers: con_opacity relativo al color del chip → no requiere update
