import logging
from typing import Optional, TypedDict, List, Tuple

logger = logging.getLogger(__name__)
import polars as pl
from techset_leadgen.analytics.analysis.db_utils import get_db_connection
from techset_leadgen.analytics.analysis.time_grouping import group_time_series

class CompareRow(TypedDict):
    label: str
    A: float
    B: float

class CompareMeta(TypedDict):
    grouping: str
    range_a: Tuple[str, str]
    range_b: Tuple[str, str]

class CompareEvolutionResult(TypedDict):
    rows: List[CompareRow]
    meta: CompareMeta


def get_sales_evolution(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    client_name: Optional[str] = None,
    product_type: Optional[str] = None,
    grouping: str = "day",
):
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

        if clauses:
            where_clause = " WHERE " + " AND ".join(clauses)
        else:
            where_clause = ""

        if grouping == "week":
            query = f"""
            SELECT
                date,
                SUM(CAST(price AS REAL)) as total
            FROM sales
            {where_clause}
            GROUP BY date
            ORDER BY date ASC
            """
            cursor = conn.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            daily_df = pl.DataFrame(rows, schema=columns, orient="row") if rows else pl.DataFrame(schema={"date": pl.Utf8, "total": pl.Float64})

            conn.close()

            if daily_df.is_empty():
                return None

            daily_rows = [(row["date"], float(row["total"])) for row in daily_df.to_dicts()]
            grouped_rows = group_time_series(daily_rows, "week")
            df = pl.DataFrame(
                {
                    "date": [row["key"] for row in grouped_rows],
                    "total": [row["total"] for row in grouped_rows],
                }
            ) if grouped_rows else pl.DataFrame(schema={"date": pl.Utf8, "total": pl.Float64})
        else:
            if grouping == "day":
                group_expr = "date"
            elif grouping == "month":
                group_expr = "strftime('%Y-%m', date)"
            elif grouping == "quarter":
                group_expr = "strftime('%Y', date) || '-Q' || CAST((CAST(strftime('%m', date) AS INTEGER) - 1) / 3 + 1 AS TEXT)"
            elif grouping == "year":
                group_expr = "strftime('%Y', date)"
            else:
                group_expr = "date"

            query = f"""
            SELECT 
                {group_expr} as date, 
                SUM(CAST(price AS REAL)) as total
            FROM sales
            {where_clause}
            GROUP BY {group_expr} ORDER BY {group_expr} ASC
            """

            cursor = conn.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            conn.close()
            df = pl.DataFrame(rows, schema=columns, orient="row") if rows else pl.DataFrame(schema={"date": pl.Utf8, "total": pl.Float64})
    except Exception:
        logger.exception("Could not read sales trend data")
        return None
    if df.is_empty():
        return None
    return df

def get_compare_evolution_rows(
    start_a: str,
    end_a: str,
    start_b: str,
    end_b: str,
    grouping: str = "day",
    client_a: Optional[str] = None,
    product_a: Optional[str] = None,
    client_b: Optional[str] = None,
    product_b: Optional[str] = None,
) -> CompareEvolutionResult:
    def _fetch_raw(start, end, client, product) -> List[tuple[str, float]]:
        conn = get_db_connection()
        query = """
        SELECT
            date,
            SUM(CAST(price AS REAL)) AS total
        FROM sales
        """
        clauses = []
        params = []
        if start:
            clauses.append("date >= ?")
            params.append(start)
        if end:
            clauses.append("date <= ?")
            params.append(end)
        if client:
            clauses.append("client_name = ?")
            params.append(client)
        if product:
            clauses.append("product_type = ?")
            params.append(product)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)

        query += " GROUP BY date ORDER BY date ASC"

        cursor = conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        df = pl.DataFrame(rows, schema=columns, orient="row") if rows else pl.DataFrame(schema={"date": pl.Utf8, "total": pl.Float64})

        if df.is_empty():
            return []

        return [(row["date"], float(row["total"])) for row in df.to_dicts()]

    raw_a = _fetch_raw(start_a, end_a, client_a, product_a)
    raw_b = _fetch_raw(start_b, end_b, client_b, product_b)

    grouped_a = group_time_series(raw_a, grouping)
    grouped_b = group_time_series(raw_b, grouping)


    map_a = {row["key"]: row["total"] for row in grouped_a}
    map_b = {row["key"]: row["total"] for row in grouped_b}

    labels_map = {}
    for row in grouped_a + grouped_b:
        labels_map[row["key"]] = row["label"]

    all_keys = sorted(set(map_a.keys()) | set(map_b.keys()))

    rows: List[CompareRow] = []
    for key in all_keys:
        rows.append(
            {
                "label": labels_map.get(key, str(key)),
                "A": map_a.get(key, 0.0),
                "B": map_b.get(key, 0.0),
            }
        )

    return {
        "rows": rows,
        "meta": {
            "grouping": grouping,
            "range_a": (start_a, end_a),
            "range_b": (start_b, end_b),
        },
    }

