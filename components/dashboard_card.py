"""
Componente de tarjeta para el Dashboard.
"""
import flet as ft


def create_dashboard_card(
    icon: str,
    title: str,
    description: str,
    colors: dict,
    on_click=None,
    on_hover=None,
):
    """
    Crea una tarjeta estilizada para el dashboard.
    
    Args:
        icon: Icono de Flet (ft.Icons.XXX)
        title: Título de la tarjeta
        description: Descripción de la tarjeta
        colors: Diccionario con colores del tema (bg_card, icon, text, subtitle)
        on_click: Callback al hacer clic
        on_hover: Callback al hacer hover
    
    Returns:
        ft.Container con la tarjeta estilizada
    """
    return ft.Container(
        padding=20,
        width=300,
        height=170,
        bgcolor=colors["bg_card"],
        border_radius=16,
        ink=True,
        animate=ft.Animation(250, ft.AnimationCurve.EASE_OUT),
        content=ft.Column(
            [
                ft.Icon(icon, size=40, color=colors["icon"]),
                ft.Text(
                    title,
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=colors["text"],
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    description,
                    size=14,
                    color=colors["subtitle"],
                    text_align=ft.TextAlign.CENTER,
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        on_click=on_click,
        on_hover=on_hover,
    )
