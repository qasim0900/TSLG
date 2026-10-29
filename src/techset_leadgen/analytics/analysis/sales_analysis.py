import logging
import polars as pl

logger = logging.getLogger(__name__)
from techset_leadgen.analytics.analysis.db_utils import get_db_connection

def get_unique_products():
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
    conn = None
    try:
        conn = get_db_connection()
        query = """
        SELECT 
            s.date,
            s.client_id,
            s.client_name,
            s.product_type,
            s.price,
            COALESCE(c.cif, '-'),
            COALESCE(c.email, '-'),
            COALESCE(c.contact_person, '-'),
            COALESCE(c.address, '-')
        FROM sales s
        LEFT JOIN clients c ON c.id = s.client_id
        """
        clauses = []
        params = []
        if start_date:
            clauses.append("s.date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("s.date <= ?")
            params.append(end_date)
        if client_name:
            clauses.append("s.client_name = ?")
            params.append(client_name)
        if product_type:
            clauses.append("s.product_type = ?")
            params.append(product_type)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY s.date DESC, s.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [
            {
                "date": row[0],
                "client_id": row[1],
                "client_name": row[2],
                "product_type": row[3],
                "price": row[4],
                "client_cif": row[5],
                "client_email": row[6],
                "client_phone": row[7],
                "client_address": row[8],
            }
            for row in rows
        ]
    except Exception:
        logger.exception("Could not enrich sales data")
        return []
    finally:
        if conn is not None:
            conn.close()

