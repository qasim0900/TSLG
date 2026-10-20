"""
Funciones de análisis de ventas y productos.
"""

import logging
import polars as pl

logger = logging.getLogger(__name__)
from .db_utils import get_db_connection
from models.client_manager import get_client_by_id_cached

def get_unique_products():
    """Obtiene la lista de productos únicos de la tabla de ventas."""
    try:
        conn = get_db_connection()
        query = """
        SELECT DISTINCT product_type
        FROM sales
        ORDER BY product_type
        """
        df = pl.read_database(query, conn)
        conn.close()
        if df.is_empty():
            return []
        return df.select(pl.col("product_type")).to_series().to_list()
    except Exception:
        logger.exception("Could not load products")
        return []

def get_sales_summary(start_date=None, end_date=None, client_name=None, product_type=None):
    """
    Obtiene resumen de ventas agrupado por tipo de producto.
    Retorna tuplas: (product_type, total_vendido, cantidad_transacciones, precio_promedio, precio_min, precio_max)
    """
    try:
        conn = get_db_connection()
        query = """
        SELECT 
            product_type, 
            SUM(CAST(price AS REAL)) as total,
            COUNT(*) as cantidad,
            AVG(CAST(price AS REAL)) as promedio,
            MIN(CAST(price AS REAL)) as minimo,
            MAX(CAST(price AS REAL)) as maximo
        FROM sales
        """
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
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " GROUP BY product_type ORDER BY total DESC"
        cursor = conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        df = pl.DataFrame(rows, schema=columns, orient="row") if rows else pl.DataFrame(schema={"product_type": pl.Utf8, "total": pl.Float64, "cantidad": pl.Int64, "promedio": pl.Float64, "minimo": pl.Float64, "maximo": pl.Float64})
    except Exception:
        logger.exception("Could not read sales data")
        return None, None
    if df.is_empty():
        logger.warning("No data available")
        return None, None
    try:
        total_vendido = df.select(pl.col("total")).sum().item()
        cantidad_total = df.select(pl.col("cantidad")).sum().item()
        promedio = total_vendido / cantidad_total if cantidad_total > 0 else 0
    except Exception:
        promedio = 0
    return df, promedio


def get_sales_with_client_info(start_date=None, end_date=None, client_name=None, product_type=None):
    """
    Obtiene ventas con información del cliente enriquecida.
    OPTIMIZADO: Usa caché para búsquedas de clientes (sin queries adicionales).
    """
    try:
        conn = get_db_connection()
        query = """
        SELECT 
            date,
            client_id,
            client_name,
            product_type,
            price
        FROM sales
        """
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
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY date DESC"
        cursor = conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        df = pl.DataFrame(rows, schema=columns, orient="row") if rows else pl.DataFrame(schema={"date": pl.Utf8, "client_id": pl.Int64, "client_name": pl.Utf8, "product_type": pl.Utf8, "price": pl.Float64})
        if df.is_empty():
            return []
        sales_list = df.to_dicts()
        enriched_sales = []
        for sale in sales_list:
            client_id = sale.get('client_id')
            client_info = get_client_by_id_cached(client_id)
            enriched_sale = {
                'date': sale['date'],
                'client_id': client_id,
                'client_name': sale['client_name'],
                'product_type': sale['product_type'],
                'price': sale['price'],
            }
            if client_info:
                _, name, cif, address, contact_person, email = client_info
                enriched_sale.update({
                    'client_cif': cif,
                    'client_email': email,
                    'client_phone': contact_person,
                    'client_address': address,
                })
            else:
                enriched_sale.update({
                    'client_cif': '-',
                    'client_email': '-',
                    'client_phone': '-',
                    'client_address': '-',
                })
            enriched_sales.append(enriched_sale)
        return enriched_sales
    except Exception:
        logger.exception("Could not enrich sales data")
        return []
