from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DashboardKPISnapshot:
    has_data: bool
    sales_rows: int
    clients_rows: int
    last_import: Optional[str]

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

