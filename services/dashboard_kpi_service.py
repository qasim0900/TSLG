"""Servicio de KPIs del Dashboard.

Construye DashboardKPISnapshot consultando directamente SQLite
para máximo rendimiento en la pantalla de inicio.
"""

from datetime import datetime
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
            # -------------------------
            # Conteos básicos
            # -------------------------
            cursor.execute("SELECT COUNT(*) FROM sales")
            sales_rows = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM clients")
            clients_rows = cursor.fetchone()[0]

            has_data = sales_rows > 0

            # -------------------------
            # Última importación (opcional)
            # -------------------------
            last_import: Optional[str] = None
            try:
                cursor.execute(
                    """
                    SELECT imported_at
                    FROM import_metadata
                    ORDER BY imported_at DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
                if row:
                    last_import = row[0]
            except Exception:
                # La tabla puede no existir todavía → tolerante
                last_import = None

            # -------------------------
            # Datos de leads
            # -------------------------
            total_leads = 0
            leads_with_meeting = 0
            leads_with_client = 0
            leads_this_month = 0
            try:
                cursor.execute("SELECT COUNT(*) FROM leads")
                total_leads = cursor.fetchone()[0] or 0

                cursor.execute(
                    "SELECT COUNT(*) FROM leads WHERE status IN ('meeting', 'converted')"
                )
                leads_with_meeting = cursor.fetchone()[0] or 0

                cursor.execute("SELECT COUNT(*) FROM leads WHERE client_id IS NOT NULL")
                leads_with_client = cursor.fetchone()[0] or 0

                current_month = datetime.now().strftime("%Y-%m")
                cursor.execute(
                    "SELECT COUNT(*) FROM leads WHERE strftime('%Y-%m', created_at) = ?",
                    (current_month,),
                )
                leads_this_month = cursor.fetchone()[0] or 0
            except Exception:
                pass

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
