from .db_utils import get_db_connection
from .clients_analysis import get_all_clients_with_sales_data, get_unique_clients, get_clients_sales_stats, count_unique_clients
from .sales_analysis import get_unique_products, get_sales_summary, get_sales_with_client_info
from .date_analysis import get_date_range
from .evolution_analysis import get_sales_evolution
from .leads_analysis import (
    get_leads,
    get_leads_stats,
    get_leads_with_client_info,
    get_unique_sources,
    get_unique_statuses,
)
from .marketing_analysis import (
    get_leads_by_source,
    get_customers_by_source,
    get_revenue_by_source,
    get_marketing_spend_by_source,
    get_marketing_metrics,
    get_marketing_efficiency_summary,
)
