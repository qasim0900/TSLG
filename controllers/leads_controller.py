"""
Controlador de lógica para gestión de leads.
Separa la lógica de negocio de la UI.
"""
from analysis import (
    get_leads,
    get_leads_stats,
    get_leads_with_client_info,
    get_unique_sources,
    get_unique_statuses,
)
from models.lead_manager import (
    update_lead_status_and_meeting,
    validate_lead_status,
    validate_meeting_date,
)
import logging

logger = logging.getLogger(__name__)


class LeadsController:
    """Controlador centralizado para operaciones de leads."""
    
    @staticmethod
    def get_leads_data(start_date=None, end_date=None, source=None, status=None):
        """
        Obtiene lista de leads con filtros opcionales.
        
        Args:
            start_date: Fecha de inicio (YYYY-MM-DD)
            end_date: Fecha de fin (YYYY-MM-DD)
            source: Filtrar por source
            status: Filtrar por status
        
        Returns:
            list: Leads obtenidos
        """
        try:
            return get_leads(
                start_date=start_date,
                end_date=end_date,
                source=source,
                status=status
            )
        except Exception:
            logger.exception("Could not load leads")
            return []
    
    @staticmethod
    def get_leads_stats():
        """
        Obtiene estadísticas de leads.
        
        Returns:
            dict: {"total_leads", "with_meeting", "with_client"}
        """
        try:
            return get_leads_stats()
        except Exception:
            logger.exception("Could not load lead statistics")
            return {
                "total_leads": 0,
                "with_meeting": 0,
                "with_client": 0,
            }
    
    @staticmethod
    def get_leads_enriched(start_date=None, end_date=None, source=None, status=None):
        """
        Obtiene leads con información del cliente.
        
        Returns:
            list: Leads con datos de cliente asociado
        """
        try:
            return get_leads_with_client_info(
                start_date=start_date,
                end_date=end_date,
                source=source,
                status=status
            )
        except Exception:
            logger.exception("Could not load enriched leads")
            return []
    
    @staticmethod
    def get_available_sources():
        """Obtiene lista de fuentes disponibles."""
        try:
            return get_unique_sources()
        except Exception:
            logger.exception("Could not load lead sources")
            return []
    
    @staticmethod
    def get_available_statuses():
        """Obtiene lista de estados disponibles."""
        try:
            return get_unique_statuses()
        except Exception:
            logger.exception("Could not load lead statuses")
            return []

    @staticmethod
    def get_funnel_stats(leads: list) -> dict:
        """
        Calcula estadísticas del funnel sobre una lista de leads en memoria.

        Wrapper puro: no realiza queries. Delega a analysis.leads_analysis.

        Args:
            leads: Lista de leads enriched (ya cargados).

        Returns:
            dict con total, meetings, converted, porcentajes y tiempos.
        """
        from analysis.leads_analysis import get_funnel_stats
        return get_funnel_stats(leads)

    @staticmethod
    def group_leads_by_source(leads: list) -> dict:
        """
        Agrupa leads por fuente con métricas de conversión (en memoria).

        Wrapper puro: no realiza queries. Delega a analysis.leads_analysis.

        Args:
            leads: Lista de leads enriched (ya cargados).

        Returns:
            dict[source] = {total, meetings, clients, meeting_to_client_pct, avg_time_to_meeting}
        """
        from analysis.leads_analysis import group_leads_by_source
        return group_leads_by_source(leads)

    @staticmethod
    def get_spend_by_source() -> dict:
        """
        Obtiene gasto de marketing por fuente como dict {source: spend}.

        Diseñado para cargarse UNA VEZ al iniciar la vista y usarse en memoria.
        """
        try:
            from analysis.marketing_analysis import get_spend_by_source_as_dict
            return get_spend_by_source_as_dict()
        except Exception:
            logger.exception("Could not load spend by source")
            return {}

    @staticmethod
    def get_revenue_by_client() -> dict:
        """
        Obtiene revenue total por cliente como dict {client_id: revenue}.

        Diseñado para cargarse UNA VEZ al iniciar la vista y usarse en memoria.
        """
        try:
            from analysis.marketing_analysis import get_revenue_per_client
            return get_revenue_per_client()
        except Exception:
            logger.exception("Could not load revenue by client")
            return {}

    @staticmethod
    def get_marketing_data(
        leads: list | None = None,
        spend_by_source: dict | None = None,
        revenue_by_client: dict | None = None,
    ) -> dict:
        """
        Obtiene métricas consolidadas de marketing.

        - leads=None → marketing global desde BD (inicio frío)
        - leads!=None → marketing reactivo in-memory (post-filtro)

        Args:
            leads: Lista de leads filtrados. None = usar datos globales de BD.
            spend_by_source: {source: spend} precargado. Requerido si leads != None.
            revenue_by_client: {client_id: revenue} precargado. Requerido si leads != None.

        Returns:
            dict: {"summary": dict, "metrics": list}
        """
        try:
            if leads is None:
                from analysis.marketing_analysis import (
                    get_marketing_efficiency_summary,
                    get_marketing_metrics,
                )
                return {
                    "summary": get_marketing_efficiency_summary() or {},
                    "metrics": get_marketing_metrics() or [],
                }
            else:
                from analysis.marketing_analysis import (
                    compute_marketing_metrics_from_leads,
                    compute_marketing_summary_from_metrics,
                )
                metrics = compute_marketing_metrics_from_leads(
                    leads,
                    spend_by_source or {},
                    revenue_by_client or {},
                )
                summary = compute_marketing_summary_from_metrics(metrics)
                return {"summary": summary, "metrics": metrics}
        except Exception:
            logger.exception("Could not load marketing data")
            return {"summary": {}, "metrics": []}

    @staticmethod
    def update_lead_info(lead_id: str, status: str, meeting_date: str | None):
        """
        Actualiza status y meeting_date de un lead.

        Args:
            lead_id: ID del lead.
            status: Nuevo estado del lead.
            meeting_date: Fecha ISO o cadena vacía/None.

        Returns:
            tuple: (success: bool, message: str)
        """
        if not lead_id:
            return False, "Lead ID is missing."

        if not validate_lead_status(status):
            return False, "Invalid lead status."

        if not validate_meeting_date(meeting_date):
            return False, "The meeting date must use the YYYY-MM-DD format."

        # Normalizar meeting_date vacío a None
        clean_meeting = meeting_date.strip() if meeting_date else None
        if clean_meeting == "":
            clean_meeting = None

        try:
            update_lead_status_and_meeting(lead_id, status.lower().strip(), clean_meeting)
            return True, "✔ Lead updated."
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Could not update the lead: {e}"
