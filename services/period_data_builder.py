"""
Construye el diccionario de datos de un período para AnalysisSnapshot.

Extraído de ventas_controller.py._build_period_data() para separar
la lógica de construcción de datos de la capa de controlador.

Capa: services/ (orquestación de análisis)
Consumidores: controllers/ventas_controller.py
"""

import logging
from typing import Optional

from analysis import (
    get_sales_evolution,
    get_clients_sales_stats,
)
from analysis.clients_analysis import count_unique_clients
from analysis.time_grouping import group_time_series
from domain.analysis_snapshot import (
    TableRow,
    PeriodMetrics,
    EvolutionData,
    TimeGrouping,
    ProductDistribution,
    ClientRank,
)

logger = logging.getLogger(__name__)


def build_period_data(
    df_summary,
    start_date: Optional[str],
    end_date: Optional[str],
    grouping: str,
    client_name: Optional[str] = None,
    product_type: Optional[str] = None,
    is_compare: bool = False,
) -> dict:
    """
    Construye un dict con todos los datos necesarios para un período.

    If is_compare=True, always queries daily granularity first,
    then regroups with group_time_series(). This stores evolution_raw
    (daily tuples) for later local regrouping without SQL queries.

    Args:
        df_summary: DataFrame de resumen de productos (de get_sales_summary)
        start_date: Fecha de inicio
        end_date: Fecha de fin
        grouping: Tipo de agrupación temporal
        client_name: Filtro de cliente (optional)
        product_type: Filtro de producto (optional)
        is_compare: Si True, guarda datos diarios crudos para regrouping

    Returns:
        Dict con keys: table_data, metrics, evolution, product_distribution,
        top_clients, evolution_raw
    """

    rows = df_summary.rows() if hasattr(df_summary, 'rows') else []

    # ============================================================
    # TABLE DATA
    # ============================================================

    table_data = []
    for row in rows:
        table_data.append(
            TableRow(
                product_type=str(row[0]),
                quantity=int(row[2]),
                total_sales=float(row[1]),
                avg_price=float(row[3]),
                min_price=float(row[4]),
                max_price=float(row[5]),
            )
        )

    # ============================================================
    # METRICS
    # ============================================================

    total_sales = sum(float(row[1]) for row in rows) if rows else 0.0
    total_quantity = sum(int(row[2]) for row in rows) if rows else 0
    avg_ticket = total_sales / total_quantity if total_quantity > 0 else 0.0

    # Contar clientes únicos respetando todos los filtros activos
    unique_clients = count_unique_clients(
        start_date=start_date,
        end_date=end_date,
        client_name=client_name,
        product_type=product_type,
    )

    metrics = PeriodMetrics(
        total_sales=total_sales,
        transactions=total_quantity,
        avg_ticket=avg_ticket,
        total_quantity=total_quantity,
        unique_clients=unique_clients,
    )

    # ============================================================
    # EVOLUTION
    # ============================================================

    # In COMPARE mode: always query daily first, then regroup.
    # This enables local regrouping without SQL queries when user changes grouping.
    # In NORMAL mode: query at requested grouping directly (no need for raw cache).
    query_grouping = "day" if is_compare else grouping

    evolution_raw_df = get_sales_evolution(
        start_date=start_date,
        end_date=end_date,
        # IMPORTANT: evolution must respect the same segment filters as df_summary,
        # otherwise comparing same date range with different clients/products will look wrong.
        client_name=client_name,
        product_type=product_type,
        grouping=query_grouping,
    )

    # Extract raw tuples from DataFrame
    daily_raw_tuples = []
    if evolution_raw_df is not None:
        for record in evolution_raw_df.to_dicts():
            date_key = str(record.get('date', ''))
            daily_raw_tuples.append((date_key, float(record.get('total', 0))))

    if is_compare and grouping != "day":
        # Regroup daily data to requested grouping using pure function
        grouped = group_time_series(daily_raw_tuples, grouping)
        evolution_labels = [row["key"] for row in grouped]
        evolution_values = [row["total"] for row in grouped]
    else:
        # Direct use (NORMAL mode or grouping is already "day")
        evolution_labels = [t[0] for t in daily_raw_tuples]
        evolution_values = [t[1] for t in daily_raw_tuples]

    evolution = EvolutionData(
        labels=evolution_labels,
        values=evolution_values,
        grouping=TimeGrouping(grouping),
    )

    # ============================================================
    # PRODUCT DISTRIBUTION
    # ============================================================

    product_labels = [str(row[0]) for row in rows]
    product_values = [float(row[1]) for row in rows]

    total = sum(product_values) if product_values else 1.0
    product_percentages = [
        (val / total) * 100 if total > 0 else 0.0
        for val in product_values
    ]

    product_distribution = ProductDistribution(
        labels=product_labels,
        values=product_values,
        percentages=product_percentages,
    )

    # ============================================================
    # TOP CLIENTS
    # ============================================================

    clients_stats = get_clients_sales_stats(
        start_date=start_date,
        end_date=end_date,
        client_name=client_name,
        product_type=product_type,
    )

    top_clients = []
    if clients_stats:
        # Ordenar por total_amount descendente y tomar top 5
        sorted_clients = sorted(
            clients_stats,
            key=lambda x: float(x.get('total_amount', 0)),
            reverse=True,
        )[:5]

        for rank, client in enumerate(sorted_clients, 1):
            client_total = float(client.get('total_amount', 0))
            pct = (client_total / total_sales * 100) if total_sales > 0 else 0.0

            top_clients.append(
                ClientRank(
                    rank=rank,
                    client_name=str(client.get('name', 'Unknown')),
                    total_sales=client_total,
                    transactions=int(client.get('total_sales', 0)),
                    percentage_of_total=pct,
                )
            )

    return {
        'table_data': table_data,
        'metrics': metrics,
        'evolution': evolution,
        'product_distribution': product_distribution,
        'top_clients': top_clients,
        'evolution_raw': daily_raw_tuples if is_compare else None,
    }
