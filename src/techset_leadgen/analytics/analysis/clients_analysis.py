import logging
import polars as pl
from techset_leadgen.analytics.analysis.db_utils import get_db_connection
from techset_leadgen.analytics.analysis.sales_analysis import get_sales_with_client_info

# ------------------------------
# :: Logger Configuration
# ------------------------------

"""
This module provides functions for analyzing client data, including retrieving clients with sales data, 
counting unique clients, and calculating sales statistics for clients. It also includes error handling and logging for debugging
"""

logger = logging.getLogger(__name__)


# ------------------------------
# :: get Rod Width Function
# ------------------------------

"""
This module provides utility functions for determining chart dimensions based on the number of bars in a chart. It includes functions 
to calculate the width of the rods (bars) and the interval for labels on the x-axis, as well as a function to round values to "nice" 
numbers for better readability in charts.
"""


def get_all_clients_with_sales_data():
    """Return every known client and its lifetime sales aggregates in one query.

    The union keeps legacy sales-only identities visible while avoiding the old
    four-query/full-sales-table Python enrichment path.
    """
    conn = None
    try:
        conn = get_db_connection()
        rows = conn.execute(
            """
            WITH sales_agg AS (
                SELECT
                    client_id,
                    MIN(client_name) AS sales_name,
                    COUNT(*) AS total_sales,
                    SUM(CAST(price AS REAL)) AS total_amount,
                    AVG(CAST(price AS REAL)) AS avg_amount,
                    MIN(CAST(price AS REAL)) AS min_amount,
                    MAX(CAST(price AS REAL)) AS max_amount
                FROM sales
                GROUP BY client_id
            ),
            known_ids AS (
                SELECT id AS client_id FROM clients
                UNION
                SELECT client_id FROM sales_agg
            )
            SELECT
                ids.client_id,
                CASE WHEN c.id IS NULL THEN s.sales_name ELSE c.name END,
                CASE WHEN c.id IS NULL THEN '-' ELSE c.cif END,
                CASE WHEN c.id IS NULL THEN '-' ELSE c.address END,
                CASE WHEN c.id IS NULL THEN '-' ELSE c.contact_person END,
                CASE WHEN c.id IS NULL THEN '-' ELSE c.email END,
                COALESCE(s.total_sales, 0),
                COALESCE(s.total_amount, 0),
                COALESCE(s.avg_amount, 0),
                COALESCE(s.min_amount, 0),
                COALESCE(s.max_amount, 0)
            FROM known_ids ids
            LEFT JOIN clients c ON c.id = ids.client_id
            LEFT JOIN sales_agg s ON s.client_id = ids.client_id
            ORDER BY ids.client_id
            """
        ).fetchall()
        fields = (
            "client_id",
            "name",
            "cif",
            "address",
            "contact_person",
            "email",
            "total_sales",
            "total_amount",
            "avg_amount",
            "min_amount",
            "max_amount",
        )
        return [dict(zip(fields, row, strict=True)) for row in rows]
    except Exception:
        logger.exception("Could not load clients with sales data")
        return []
    finally:
        if conn is not None:
            conn.close()


def get_unique_clients():
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


def get_clients_sales_stats(
    start_date=None, end_date=None, client_name=None, product_type=None
):
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
        cid = s.get("client_id")
        if cid is None:
            continue
        if cid not in by_client:
            by_client[cid] = {
                "client_id": cid,
                "name": s.get("client_name") or "-",
                "total_sales": 0,
                "total_amount": 0.0,
                "products": set(),
            }
        by_client[cid]["total_sales"] += 1
        try:
            by_client[cid]["total_amount"] += float(s.get("price") or 0)
        except Exception:
            pass
        p = s.get("product_type")
        if p:
            by_client[cid]["products"].add(str(p))
    result = []
    for cid, d in by_client.items():
        total_sales = d["total_sales"]
        total_amount = d["total_amount"]
        avg_amount = (total_amount / total_sales) if total_sales else 0.0
        result.append(
            {
                "client_id": cid,
                "name": d["name"],
                "total_sales": total_sales,
                "total_amount": total_amount,
                "avg_amount": avg_amount,
                "products": sorted(list(d["products"])),
            }
        )
    return result


def count_unique_clients(
    start_date: str | None = None,
    end_date: str | None = None,
    client_name: str | None = None,
    product_type: str | None = None,
) -> int:
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
