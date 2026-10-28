"""Modelo inmutable de KPIs del Dashboard (Home).

Define DashboardKPISnapshot como dataclass frozen con métricas operativas:
ventas, clientes, última importación y estadísticas de leads.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DashboardKPISnapshot:
    """
    Estado operativo del sistema para el Home.
    """
    has_data: bool
    sales_rows: int
    clients_rows: int
    last_import: Optional[str]

    # Campos de leads (para info_box y lógica de vista)
    total_leads: int
    leads_with_meeting: int
    leads_conversion_rate: float
    leads_this_month: int

    @staticmethod
    def empty():
        return DashboardKPISnapshot(
            has_data=False,
            sales_rows=0,
            clients_rows=0,
            last_import=None,
            total_leads=0,
            leads_with_meeting=0,
            leads_conversion_rate=0.0,
            leads_this_month=0,
        )
