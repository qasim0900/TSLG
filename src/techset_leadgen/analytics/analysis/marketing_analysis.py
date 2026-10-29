import logging

import polars as pl
from techset_leadgen.analytics.analysis.db_utils import get_db_connection

_ma_logger = logging.getLogger(__name__)


def get_leads_by_source():
    try:
        conn = get_db_connection()
        query = """
        SELECT source, COUNT(*) as leads
        FROM leads
        GROUP BY source
        ORDER BY leads DESC
        """
        df = pl.read_database(query, conn)
        conn.close()
        if df.is_empty():
            return []
        return df.to_dicts()
    except Exception:
        _ma_logger.exception("Could not load leads by source")
        return []


def get_customers_by_source():
    try:
        conn = get_db_connection()
        query = """
        WITH ranked_leads AS (
            SELECT
                client_id,
                source,
                created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY client_id
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM leads
            WHERE client_id IS NOT NULL
        ),
        first_lead AS (
            SELECT client_id, source
            FROM ranked_leads
            WHERE rn = 1
        )
        SELECT
            fl.source,
            COUNT(DISTINCT s.client_id) as customers
        FROM first_lead fl
        JOIN sales s
            ON s.client_id = fl.client_id
        GROUP BY fl.source
        ORDER BY customers DESC
        """
        df = pl.read_database(query, conn)
        conn.close()
        if df.is_empty():
            return []
        return df.to_dicts()
    except Exception:
        _ma_logger.exception("Could not load clients by source")
        return []


def get_revenue_by_source():
    try:
        conn = get_db_connection()
        query = """
        WITH ranked_leads AS (
            SELECT
                client_id,
                source,
                created_at,
                ROW_NUMBER() OVER (
                    PARTITION BY client_id
                    ORDER BY created_at ASC, id ASC
                ) AS rn
            FROM leads
            WHERE client_id IS NOT NULL
        ),
        first_lead AS (
            SELECT client_id, source
            FROM ranked_leads
            WHERE rn = 1
        )
        SELECT
            fl.source,
            SUM(CAST(s.price AS REAL)) as revenue
        FROM sales s
        JOIN first_lead fl
            ON s.client_id = fl.client_id
        GROUP BY fl.source
        ORDER BY revenue DESC
        """
        df = pl.read_database(query, conn)
        conn.close()
        if df.is_empty():
            return []
        return df.to_dicts()
    except Exception:
        _ma_logger.exception("Could not load revenue by source")
        return []


def get_marketing_spend_by_source():
    try:
        conn = get_db_connection()
        query = """
        SELECT
            source,
            SUM(CAST(amount AS REAL)) as spend
        FROM marketing_spend
        GROUP BY source
        ORDER BY spend DESC
        """
        df = pl.read_database(query, conn)
        conn.close()
        if df.is_empty():
            return []
        return df.to_dicts()
    except Exception:
        _ma_logger.exception("Could not load marketing spend by source")
        return []


def get_marketing_metrics():
    try:
        leads_data = get_leads_by_source()
        customers_data = get_customers_by_source()
        revenue_data = get_revenue_by_source()
        spend_data = get_marketing_spend_by_source()

        leads_dict = {item["source"]: item["leads"] for item in leads_data}
        customers_dict = {item["source"]: item["customers"] for item in customers_data}
        revenue_dict = {item["source"]: item["revenue"] for item in revenue_data}
        spend_dict = {item["source"]: item["spend"] for item in spend_data}

        all_sources = set()
        all_sources.update(leads_dict.keys())
        all_sources.update(customers_dict.keys())
        all_sources.update(revenue_dict.keys())
        all_sources.update(spend_dict.keys())

        metrics = []
        for source in sorted(all_sources):
            leads = leads_dict.get(source, 0)
            customers = customers_dict.get(source, 0)
            revenue = revenue_dict.get(source, 0.0)
            spend = spend_dict.get(source, 0.0)

            cpl = spend / leads if leads > 0 else 0.0
            cac = spend / customers if customers > 0 else 0.0
            roi = (revenue - spend) / spend if spend > 0 else 0.0

            metrics.append({
                "source": source,
                "leads": leads,
                "customers": customers,
                "revenue": round(revenue, 2),
                "spend": round(spend, 2),
                "cpl": round(cpl, 2),
                "cac": round(cac, 2),
                "roi": round(roi, 2),
            })

        metrics.sort(key=lambda x: x["revenue"], reverse=True)

        return metrics

    except Exception:
        _ma_logger.exception("Could not calculate marketing metrics")
        return []


def get_marketing_efficiency_summary():
    try:
        metrics = get_marketing_metrics()

        if not metrics:
            return {
                "total_leads": 0,
                "total_customers": 0,
                "total_revenue": 0.0,
                "total_spend": 0.0,
                "avg_cpl": 0.0,
                "avg_cac": 0.0,
                "overall_roi": 0.0,
                "conversion_rate": 0.0,
            }

        total_leads = sum(m["leads"] for m in metrics)
        total_customers = sum(m["customers"] for m in metrics)
        total_revenue = sum(m["revenue"] for m in metrics)
        total_spend = sum(m["spend"] for m in metrics)

        avg_cpl = total_spend / total_leads if total_leads > 0 else 0.0
        avg_cac = total_spend / total_customers if total_customers > 0 else 0.0
        overall_roi = (total_revenue - total_spend) / total_spend if total_spend > 0 else 0.0
        conversion_rate = total_customers / total_leads if total_leads > 0 else 0.0

        return {
            "total_leads": total_leads,
            "total_customers": total_customers,
            "total_revenue": round(total_revenue, 2),
            "total_spend": round(total_spend, 2),
            "avg_cpl": round(avg_cpl, 2),
            "avg_cac": round(avg_cac, 2),
            "overall_roi": round(overall_roi, 2),
            "conversion_rate": round(conversion_rate, 4),
        }

    except Exception:
        _ma_logger.exception("Could not calculate the marketing efficiency summary")
        return {}


from collections import defaultdict


def get_revenue_per_client() -> dict:
    try:
        conn = get_db_connection()
        cursor = conn.execute(
            "SELECT client_id, SUM(CAST(price AS REAL)) FROM sales "
            "WHERE client_id IS NOT NULL GROUP BY client_id"
        )
        result = {row[0]: row[1] or 0.0 for row in cursor.fetchall()}
        conn.close()
        return result
    except Exception:
        _ma_logger.exception("Could not load revenue by client")
        return {}


def get_spend_by_source_as_dict() -> dict:
    try:
        spend_list = get_marketing_spend_by_source()
        return {item["source"]: item["spend"] for item in spend_list}
    except Exception:
        _ma_logger.exception("Could not load spend by source")
        return {}


def compute_marketing_metrics_from_leads(
    leads: list,
    spend_by_source: dict,
    revenue_by_client: dict,
) -> list:
    source_leads: dict[str, list] = defaultdict(list)
    for lead in leads:
        source = lead.get("source") or "unknown"
        source_leads[source].append(lead)

    all_sources = set(source_leads.keys()) | set(spend_by_source.keys())

    first_touch_source: dict = {}
    for lead in sorted(leads, key=lambda x: (x.get("created_at") or "", str(x.get("id") or ""))):
        cid = lead.get("client_id")
        if cid and lead.get("status") == "converted" and cid not in first_touch_source:
            first_touch_source[cid] = lead.get("source") or "unknown"

    clients_by_source: dict[str, list] = defaultdict(list)
    for cid, src in first_touch_source.items():
        clients_by_source[src].append(cid)

    metrics = []
    for source in sorted(all_sources):
        leads_count = len(source_leads.get(source, []))
        attributed_clients = clients_by_source.get(source, [])

        customers_count = len(attributed_clients)
        revenue = sum(revenue_by_client.get(cid, 0.0) for cid in attributed_clients)
        spend = spend_by_source.get(source, 0.0)

        cpl = round(spend / leads_count, 2) if leads_count > 0 else 0.0
        cac = round(spend / customers_count, 2) if customers_count > 0 else 0.0
        roi = round((revenue - spend) / spend, 4) if spend > 0 else 0.0

        metrics.append({
            "source": source,
            "leads": leads_count,
            "customers": customers_count,
            "revenue": round(revenue, 2),
            "spend": round(spend, 2),
            "cpl": cpl,
            "cac": cac,
            "roi": roi,
        })

    metrics.sort(key=lambda x: x["revenue"], reverse=True)
    return metrics


def compute_marketing_summary_from_metrics(metrics: list) -> dict:
    total_spend = sum(m["spend"] for m in metrics)
    total_revenue = sum(m["revenue"] for m in metrics)
    total_leads = sum(m["leads"] for m in metrics)
    total_customers = sum(m["customers"] for m in metrics)

    avg_cpl = round(total_spend / total_leads, 2) if total_leads > 0 else 0.0
    avg_cac = round(total_spend / total_customers, 2) if total_customers > 0 else 0.0
    overall_roi = round((total_revenue - total_spend) / total_spend, 4) if total_spend > 0 else 0.0
    conversion_rate = round(total_customers / total_leads, 4) if total_leads > 0 else 0.0

    return {
        "total_leads": total_leads,
        "total_customers": total_customers,
        "total_revenue": round(total_revenue, 2),
        "total_spend": round(total_spend, 2),
        "avg_cpl": avg_cpl,
        "avg_cac": avg_cac,
        "overall_roi": overall_roi,
        "conversion_rate": conversion_rate,
    }

