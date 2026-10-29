import logging
from typing import Optional

from techset_leadgen.analytics.analysis import (
    get_sales_evolution,
    get_clients_sales_stats,
)
from techset_leadgen.analytics.analysis.clients_analysis import count_unique_clients
from techset_leadgen.analytics.analysis.time_grouping import group_time_series
from techset_leadgen.domain.analysis_snapshot import (
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
    rows = df_summary.rows() if hasattr(df_summary, 'rows') else []


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


    total_sales = sum(float(row[1]) for row in rows) if rows else 0.0
    total_quantity = sum(int(row[2]) for row in rows) if rows else 0
    avg_ticket = total_sales / total_quantity if total_quantity > 0 else 0.0

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


    query_grouping = "day" if is_compare else grouping

    evolution_raw_df = get_sales_evolution(
        start_date=start_date,
        end_date=end_date,
        client_name=client_name,
        product_type=product_type,
        grouping=query_grouping,
    )

    daily_raw_tuples = []
    if evolution_raw_df is not None:
        for record in evolution_raw_df.to_dicts():
            date_key = str(record.get('date', ''))
            daily_raw_tuples.append((date_key, float(record.get('total', 0))))

    if is_compare and grouping != "day":
        grouped = group_time_series(daily_raw_tuples, grouping)
        evolution_labels = [row["key"] for row in grouped]
        evolution_values = [row["total"] for row in grouped]
    else:
        evolution_labels = [t[0] for t in daily_raw_tuples]
        evolution_values = [t[1] for t in daily_raw_tuples]

    evolution = EvolutionData(
        labels=evolution_labels,
        values=evolution_values,
        grouping=TimeGrouping(grouping),
    )


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


    clients_stats = get_clients_sales_stats(
        start_date=start_date,
        end_date=end_date,
        client_name=client_name,
        product_type=product_type,
    )

    top_clients = []
    if clients_stats:
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

