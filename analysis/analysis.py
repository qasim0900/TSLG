"""Fachada de reexportes del paquete analysis."""
from .db_utils import get_db_connection
from .clients_analysis import get_all_clients_with_sales_data, get_unique_clients, get_clients_sales_stats
from .sales_analysis import get_unique_products, get_sales_summary, get_sales_with_client_info
from .date_analysis import get_date_range
from .evolution_analysis import get_sales_evolution
