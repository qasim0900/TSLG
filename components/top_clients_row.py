"""
Componente: Fila de gráficos de top clientes (Patrón B).

Exporta:
  build_top_clients_row(top_clients, theme_mode, grafico_top, grafico_monto)
    → (row, grafico_top, grafico_monto)

Extraído de views/ventas_view.py._build_top_clients_row_from_snapshot().
Implementa el Patrón B: la view mantiene refs a los gráficos para theme updates.
"""

import flet as ft
from components.grafico_clientes import GraficoClientesTop, GraficoClientesMonto
from theme import get_text_color


def build_top_clients_row(
    top_clients,
    theme_mode,
    grafico_top=None,
    grafico_monto=None,
    existing_row=None,
):
    """
    Construye o actualiza la fila de gráficos de top clientes.

    Patrón B: Si ya existen gráficos, solo actualiza datos.
    Si no, crea estructura completa.

    Args:
        top_clients: list[ClientRank] del snapshot.
        theme_mode: ft.ThemeMode para derivar colores.
        grafico_top: GraficoClientesTop existente (None = primera vez).
        grafico_monto: GraficoClientesMonto existente (None = primera vez).
        existing_row: ft.Row existente (None = primera vez).

    Returns:
        Tuple (row, grafico_top, grafico_monto) — la view guarda las refs.
    """
    clients_data = [
        {
            'rank': c.rank,
            'name': c.client_name,
            'total_sales': c.transactions,
            'total_amount': c.total_sales,
            'percentage': c.percentage_of_total,
        }
        for c in top_clients
    ]

    # 🔥 CASO 1: Ya existen gráficos → solo actualizar datos
    if (
        grafico_top is not None
        and grafico_monto is not None
        and existing_row is not None
    ):
        grafico_top.update_from_data(clients_data)
        grafico_monto.update_from_data(clients_data)
        return existing_row, grafico_top, grafico_monto

    # 🔥 CASO 2: Primera construcción → crear estructura completa
    grafico_top = GraficoClientesTop(
        clients_data,
        theme_mode=theme_mode,
        limit=5,
    )

    grafico_monto = GraficoClientesMonto(
        clients_data,
        theme_mode=theme_mode,
        limit=5,
    )

    title_top = ft.Text(
        "Top clients (by purchases)",
        size=14,
        weight=ft.FontWeight.BOLD,
        color=get_text_color(theme_mode),
    )

    title_monto = ft.Text(
        "Clients by amount spent",
        size=14,
        weight=ft.FontWeight.BOLD,
        color=get_text_color(theme_mode),
    )

    row = ft.Row(
        [
            ft.Column(
                [title_top, grafico_top],
                spacing=8,
                expand=True,
            ),
            ft.Column(
                [title_monto, grafico_monto],
                spacing=8,
                expand=True,
            ),
        ],
        spacing=40,
        expand=True,
    )

    return row, grafico_top, grafico_monto
