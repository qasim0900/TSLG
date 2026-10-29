from techset_leadgen.database.local_db import clear_sales_table, clear_clients_table, clear_leads_table
from techset_leadgen.analytics.models.client_manager import invalidate_clients_cache
from techset_leadgen.analytics.dashboard_kpi_service import DashboardKPIService
from techset_leadgen.domain.dashboard_kpi_snapshot import DashboardKPISnapshot


class DashboardController:
    @staticmethod
    def clear_sales():
        if clear_sales_table():
            return True, "✔ Sales data cleared"
        return False, "Could not clear sales data"

    @staticmethod
    def clear_clients():
        cleared = clear_clients_table()
        invalidate_clients_cache()
        if cleared:
            return True, "✔ Client data cleared"
        return False, "Could not clear client data"

    @staticmethod
    def clear_leads():
        if clear_leads_table():
            return True, "✔ Lead data cleared"
        return False, "Could not clear lead data"

    @staticmethod
    def get_weekly_revenue(weeks: int = 8) -> list[tuple[str, float]]:
        try:
            return DashboardKPIService.weekly_revenue(weeks)
        except Exception:
            return []

    @staticmethod
    def get_dashboard_kpi_snapshot() -> DashboardKPISnapshot:
        try:
            return DashboardKPIService.build_snapshot()
        except Exception:
            return DashboardKPISnapshot.empty()

