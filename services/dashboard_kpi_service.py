"""Servicio de KPIs del Dashboard.

Construye DashboardKPISnapshot consultando directamente SQLite
para máximo rendimiento en la pantalla de inicio.
"""

from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Optional

from core.db import get_connection
from domain.dashboard_kpi_snapshot import DashboardKPISnapshot
from utils.formatting import format_datetime_us



class DashboardKPIService:
    """
    Servicio responsable de construir el snapshot del Dashboard (Home).
    NO reutiliza lógica de análisis.
    """

    @staticmethod
    def build_snapshot() -> DashboardKPISnapshot:
        conn = get_connection()
        cursor = conn.cursor()

        try:
            sales_rows, clients_rows, last_import = cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM sales),
                    (SELECT COUNT(*) FROM clients),
                    (SELECT MAX(imported_at) FROM import_metadata)
                """
            ).fetchone()
            has_data = sales_rows > 0

            month_start = datetime.now().replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            next_month = month_start + relativedelta(months=1)
            lead_row = cursor.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(CASE
                        WHEN status IN ('meeting', 'converted') THEN 1 ELSE 0
                    END), 0),
                    COALESCE(SUM(CASE
                        WHEN client_id IS NOT NULL THEN 1 ELSE 0
                    END), 0),
                    COALESCE(SUM(CASE
                        WHEN created_at >= ? AND created_at < ? THEN 1 ELSE 0
                    END), 0)
                FROM leads
                """,
                (month_start.date().isoformat(), next_month.date().isoformat()),
            ).fetchone()
            total_leads, leads_with_meeting, leads_with_client, leads_this_month = lead_row

            leads_conversion_rate = (
                round(leads_with_client / total_leads * 100, 1) if total_leads > 0 else 0.0
            )

            return DashboardKPISnapshot(
                has_data=has_data,
                sales_rows=sales_rows,
                clients_rows=clients_rows,
                last_import=last_import,
                total_leads=total_leads,
                leads_with_meeting=leads_with_meeting,
                leads_conversion_rate=leads_conversion_rate,
                leads_this_month=leads_this_month,
            )

        finally:
            conn.close()

    @staticmethod
    def _format_last_import(value: Optional[str]) -> str:
        if not value:
            return "—"
        try:
            dt = datetime.fromisoformat(value)
            return format_datetime_us(dt)
        except Exception:
            return value
