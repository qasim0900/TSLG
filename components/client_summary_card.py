"""
Componente: Tarjeta de resumen de cliente individual.

Exporta:
  build_client_summary_card(client_info, product_dist, avg_ticket, theme_mode) → ft.Container

Extraído de views/ventas_view.py._populate_view_containers() líneas 684-764.
Se muestra cuando el usuario filtra por un cliente específico.
"""

import flet as ft
from theme import get_text_color
from utils.formatting import format_eur


def build_client_summary_card(
    client_info,
    product_dist,
    avg_ticket: float,
    theme_mode,
) -> ft.Container:
    """
    Construye un Container con 4 tarjetas coloreadas: compras, gastado, ticket, productos.

    Args:
        client_info: ClientRank del snapshot (top_clients[0] cuando se filtra por cliente).
        product_dist: ProductDistribution del snapshot.
        avg_ticket: Ticket medio del período.
        theme_mode: ft.ThemeMode para derivar colores.

    Returns:
        ft.Container con el resumen visual del cliente.
    """
    text_color = get_text_color(theme_mode)

    card_compras = ft.Container(
        padding=12,
        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.BLUE),
        border_radius=8,
        expand=True,
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.SHOPPING_BAG, size=24, color=ft.Colors.BLUE),
                ft.Text("Purchases", size=12, color=text_color, weight=ft.FontWeight.W_500),
            ], spacing=8),
            ft.Text(str(client_info.transactions), size=20, weight=ft.FontWeight.BOLD, color=text_color),
        ], spacing=4),
    )

    card_gastado = ft.Container(
        padding=12,
        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.GREEN),
        border_radius=8,
        expand=True,
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.EURO, size=24, color=ft.Colors.GREEN),
                ft.Text("Total spent", size=12, color=text_color, weight=ft.FontWeight.W_500),
            ], spacing=8),
            ft.Text(format_eur(client_info.total_sales), size=20, weight=ft.FontWeight.BOLD, color=text_color),
        ], spacing=4),
    )

    card_ticket = ft.Container(
        padding=12,
        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.ORANGE),
        border_radius=8,
        expand=True,
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.RECEIPT, size=24, color=ft.Colors.ORANGE),
                ft.Text("Average sale", size=12, color=text_color, weight=ft.FontWeight.W_500),
            ], spacing=8),
            ft.Text(format_eur(avg_ticket), size=20, weight=ft.FontWeight.BOLD, color=text_color),
        ], spacing=4),
    )

    # Mostrar productos del cliente desde el snapshot
    productos_text = "-"
    if product_dist and product_dist.labels:
        productos_list = [f"{label}" for label in product_dist.labels]
        productos_text = ", ".join(productos_list[:2])  # Mostrar primeros 2
        if len(product_dist.labels) > 2:
            productos_text += f", +{len(product_dist.labels) - 2}"

    card_productos = ft.Container(
        padding=12,
        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.PURPLE),
        border_radius=8,
        expand=True,
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.CATEGORY, size=24, color=ft.Colors.PURPLE),
                ft.Text("Products", size=12, color=text_color, weight=ft.FontWeight.W_500),
            ], spacing=8),
            ft.Text(productos_text, size=12, weight=ft.FontWeight.W_600, color=text_color),
        ], spacing=4),
    )

    client_summary = ft.Container(
        padding=12,
        bgcolor=ft.Colors.SURFACE,
        border_radius=8,
        content=ft.Column([
            ft.Text(
                "Client summary",
                size=18,
                weight=ft.FontWeight.BOLD,
                color=text_color,
            ),
            ft.Row([card_compras, card_gastado], spacing=10, expand=True),
            ft.Row([card_ticket, card_productos], spacing=10, expand=True),
        ], spacing=12),
    )

    return client_summary
