"""
Funciones de análisis de clientes.
"""

import logging
import polars as pl
from .db_utils import get_db_connection
from models.client_manager import get_client_by_id_cached
from .sales_analysis import get_sales_with_client_info

logger = logging.getLogger(__name__)

def get_all_clients_with_sales_data():
    """
    Obtiene todos los clientes (de ambas tablas) con sus estadísticas de ventas.
    Combina datos de clients.db y sales.client_id para info completa.
    """
    try:
        conn = get_db_connection()
        query = """
        SELECT DISTINCT client_id, client_name
        FROM sales
        ORDER BY client_id
        """
        df_sales = pl.read_database(query, conn)
        conn.close()
        clients_dict = {}
        if not df_sales.is_empty():
            for row in df_sales.to_dicts():
                client_id = row['client_id']
                client_name = row['client_name']
                client_info = get_client_by_id_cached(client_id)
                if client_info:
                    _, name, cif, address, contact_person, email = client_info
                else:
                    name = client_name
                    cif = '-'
                    address = '-'
                    contact_person = '-'
                    email = '-'
                clients_dict[client_id] = {
                    'client_id': client_id,
                    'name': name,
                    'cif': cif,
                    'address': address,
                    'contact_person': contact_person,
                    'email': email,
                    'total_sales': 0,
                    'total_amount': 0,
                    'avg_amount': 0,
                    'min_amount': float('inf'),
                    'max_amount': 0,
                }
        from models.client_manager import get_clients
        all_clients = get_clients()
        for client_id, name, cif, address, contact_person, email in all_clients:
            if client_id not in clients_dict:
                clients_dict[client_id] = {
                    'client_id': client_id,
                    'name': name,
                    'cif': cif,
                    'address': address,
                    'contact_person': contact_person,
                    'email': email,
                    'total_sales': 0,
                    'total_amount': 0,
                    'avg_amount': 0,
                    'min_amount': 0,
                    'max_amount': 0,
                }
        all_sales = get_sales_with_client_info()
        for sale in all_sales:
            client_id = sale['client_id']
            price = float(sale['price'])
            if client_id in clients_dict:
                clients_dict[client_id]['total_sales'] += 1
                clients_dict[client_id]['total_amount'] += price
                clients_dict[client_id]['min_amount'] = min(clients_dict[client_id]['min_amount'], price)
                clients_dict[client_id]['max_amount'] = max(clients_dict[client_id]['max_amount'], price)
        for client_id in clients_dict:
            total_sales = clients_dict[client_id]['total_sales']
            if total_sales > 0:
                clients_dict[client_id]['avg_amount'] = clients_dict[client_id]['total_amount'] / total_sales
            else:
                clients_dict[client_id]['min_amount'] = 0
            if clients_dict[client_id]['min_amount'] == float('inf'):
                clients_dict[client_id]['min_amount'] = 0
        return list(clients_dict.values())
    except Exception:
        logger.exception("Could not load clients with sales data")
        return []

def get_unique_clients():
    """Obtiene la lista de clientes únicos de la tabla de ventas."""
    try:
        conn = get_db_connection()
        query = """
        SELECT DISTINCT client_name
        FROM sales
        ORDER BY client_name
        """
        df = pl.read_database(query, conn)
        conn.close()
        if df.is_empty():
            return []
        return df.select(pl.col("client_name")).to_series().to_list()
    except Exception:
        logger.exception("Could not load clients")
        return []

def get_clients_sales_stats(start_date=None, end_date=None, client_name=None, product_type=None):
    """
    Obtiene estadísticas agregadas por cliente, respetando filtros.
    """
    sales = get_sales_with_client_info(
        start_date=start_date,
        end_date=end_date,
        client_name=client_name,
        product_type=product_type,
    )
    if not sales:
        return []
    by_client = {}
    for s in sales:
        cid = s.get('client_id')
        if cid is None:
            continue
        if cid not in by_client:
            by_client[cid] = {
                'client_id': cid,
                'name': s.get('client_name') or '-',
                'total_sales': 0,
                'total_amount': 0.0,
                'products': set(),
            }
        by_client[cid]['total_sales'] += 1
        try:
            by_client[cid]['total_amount'] += float(s.get('price') or 0)
        except Exception:
            pass
        p = s.get('product_type')
        if p:
            by_client[cid]['products'].add(str(p))
    result = []
    for cid, d in by_client.items():
        total_sales = d['total_sales']
        total_amount = d['total_amount']
        avg_amount = (total_amount / total_sales) if total_sales else 0.0
        result.append({
            'client_id': cid,
            'name': d['name'],
            'total_sales': total_sales,
            'total_amount': total_amount,
            'avg_amount': avg_amount,
            'products': sorted(list(d['products'])),
        })
    return result


def count_unique_clients(
    start_date: str | None = None,
    end_date: str | None = None,
    client_name: str | None = None,
    product_type: str | None = None,
) -> int:
    """
    Cuenta clientes únicos en la tabla sales respetando filtros.

    Usa COALESCE(client_id, client_name) como identificador de cliente
    para manejar ventas sin client_id asociado.

    Args:
        start_date: Fecha inicio (ISO format, inclusive).
        end_date: Fecha fin (ISO format, inclusive).
        client_name: Filtro por nombre de cliente.
        product_type: Filtro por tipo de producto.

    Returns:
        Número de clientes únicos que cumplen los filtros.
    """
    conn = None
    try:
        conn = get_db_connection()
        clauses = []
        params = []
        if start_date:
            clauses.append("date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("date <= ?")
            params.append(end_date)
        if client_name:
            clauses.append("client_name = ?")
            params.append(client_name)
        if product_type:
            clauses.append("product_type = ?")
            params.append(product_type)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        result = conn.execute(
            f"SELECT COUNT(DISTINCT COALESCE(client_id, client_name)) FROM sales{where}",
            params,
        ).fetchone()
        return result[0] if result and result[0] else 0
    except Exception as e:
        logger.debug("count_unique_clients error: %s", e)
        return 0
    finally:
        if conn:
            conn.close()
