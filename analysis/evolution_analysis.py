"""
Funciones de análisis de evolución/series temporales.
"""
import logging
from typing import Optional, TypedDict, List, Tuple

logger = logging.getLogger(__name__)
import polars as pl
from .db_utils import get_db_connection
from .time_grouping import group_time_series

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
    """
    Obtiene la evolución de ventas agrupado según el grouping especificado.
    Retorna tuplas: (date_key, total_vendido)

    Args:
        grouping: 'day', 'week', 'month', 'quarter', 'year'

    Nota:
    - Mantiene compatibilidad: si no se pasan filtros de cliente/producto,
      el comportamiento es idéntico al anterior.
    - El formato de date_key depende del grouping:
      - day: 'YYYY-MM-DD'
      - week: 'YYYY-Wnn' (ej: '2024-W01')
      - month: 'YYYY-MM'
      - quarter: 'YYYY-Qn' (ej: '2024-Q1')
      - year: 'YYYY'
    """
    try:
        conn = get_db_connection()

        # Agregar filtros si existen (fechas + segmentación)
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
            # Semanas ISO: agrupar en Python para compartir semantica con regrouping local.
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
            # Determinar la expresión de agrupación SQL según grouping
            if grouping == "day":
                group_expr = "date"
            elif grouping == "month":
                group_expr = "strftime('%Y-%m', date)"
            elif grouping == "quarter":
                # Calcular trimestre: Q1 (ene-mar), Q2 (abr-jun), Q3 (jul-sep), Q4 (oct-dic)
                group_expr = "strftime('%Y', date) || '-Q' || CAST((CAST(strftime('%m', date) AS INTEGER) - 1) / 3 + 1 AS TEXT)"
            elif grouping == "year":
                group_expr = "strftime('%Y', date)"
            else:
                # Fallback a día
                group_expr = "date"
            
            # Query: agrupar según grouping y sumar price
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
    grouping: str = "day",  # day | week | month | quarter | year
    client_a: Optional[str] = None,
    product_a: Optional[str] = None,
    client_b: Optional[str] = None,
    product_b: Optional[str] = None,
) -> CompareEvolutionResult:
    """
    Devuelve filas comparables A vs B ya alineadas temporalmente.

    Retorna:
    {
        "rows": [
            {
                "label": str,
                "A": float,
                "B": float,
            },
            ...
        ],
        "meta": {
            "grouping": str,
            "range_a": (start_a, end_a),
            "range_b": (start_b, end_b),
        }
    }
    """

    def _fetch_raw(start, end, client, product) -> List[tuple[str, float]]:
        """Obtiene (date, total) sin agrupar."""
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

    # -----------------------------
    # 1️⃣ Datos crudos A y B
    # -----------------------------
    raw_a = _fetch_raw(start_a, end_a, client_a, product_a)
    raw_b = _fetch_raw(start_b, end_b, client_b, product_b)

    # -----------------------------
    # 2️⃣ Agrupación temporal
    # -----------------------------
    grouped_a = group_time_series(raw_a, grouping)
    grouped_b = group_time_series(raw_b, grouping)

    # grouped_* = [
    #   {
    #     "key": sortable_key,
    #     "label": str,
    #     "value": float
    #   }
    # ]

    map_a = {row["key"]: row["total"] for row in grouped_a}
    map_b = {row["key"]: row["total"] for row in grouped_b}

    labels_map = {}
    for row in grouped_a + grouped_b:
        labels_map[row["key"]] = row["label"]

    # -----------------------------
    # 3️⃣ Unión ordenada de periodos
    # -----------------------------
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

    # -----------------------------
    # 4️⃣ Resultado final
    # -----------------------------
    return {
        "rows": rows,
        "meta": {
            "grouping": grouping,
            "range_a": (start_a, end_a),
            "range_b": (start_b, end_b),
        },
    }
