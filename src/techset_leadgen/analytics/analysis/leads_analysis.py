"""
Funciones de análisis de leads.
Consultas especializadas para obtener datos del pipeline de marketing.
No modifica la base de datos.

Fuente de verdad: campo `status` — nunca `meeting_date` como condición lógica.

Mapeo de estados:
    new       → lead nuevo
    contacted → contacto inicial
    meeting   → reunión agendada (lead activo en esta etapa)
    converted → cliente (pasó por reunión o fue directo)
    lost      → perdido
"""

import logging
from datetime import date
from techset_leadgen.domain.lead_stages import LEAD_STATUSES, MEETING_OR_LATER

from techset_leadgen.analytics.analysis.db_utils import get_db_connection

logger = logging.getLogger(__name__)

_VALID_STATUSES = frozenset(LEAD_STATUSES)
_MEETING_SQL = ", ".join(f"'{status}'" for status in sorted(MEETING_OR_LATER))


def get_leads(start_date=None, end_date=None, source=None, status=None, client_id=None):
    """
    Obtiene lista de leads con filtros opcionales.
    Enriquece con client_name vía JOIN — sin N+1.

    Args:
        start_date: Fecha de inicio ISO (YYYY-MM-DD)
        end_date: Fecha de fin ISO (YYYY-MM-DD)
        source: Filtrar por source (ej: "meta_ads", "google_ads")
        status: Filtrar por status (ej: "new", "contacted", "meeting")
        client_id: Filtrar por cliente asociado

    Returns:
        list: [{"id", "external_id", "created_at", "source", "status",
                "meeting_date", "client_id", "client_name"}, ...]
    """
    try:
        conn = get_db_connection()
        base = """
            SELECT l.id, l.external_id, l.created_at, l.source, l.status,
                   l.meeting_date, l.client_id,
                   COALESCE(c.name, '—') AS client_name
            FROM leads l
            LEFT JOIN clients c ON c.id = l.client_id
        """

        clauses, params = [], []
        if start_date:
            clauses.append("l.created_at >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("l.created_at <= ?")
            params.append(end_date)
        if source:
            clauses.append("l.source = ?")
            params.append(source)
        if status:
            clauses.append("l.status = ?")
            params.append(status)
        if client_id:
            clauses.append("l.client_id = ?")
            params.append(client_id)

        query = base + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY l.created_at DESC"

        cursor = conn.execute(query, params)
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        conn.close()
        return rows

    except Exception:
        logger.exception("Could not load leads")
        return []


def get_leads_stats():
    """
    Obtiene estadísticas generales de leads directamente desde la BD.

    Fuente de verdad: `status` — los conteos usan status, no meeting_date.

    Returns:
        dict: {
            "total_leads": int,
            "with_meeting": int,   # status IN MEETING_OR_LATER
            "with_client": int,    # client_id IS NOT NULL
            "by_source": dict      # {source: count}
        }
    """
    try:
        conn = get_db_connection()

        result_total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()
        total_leads = result_total[0] if result_total else 0

        # Leads que alcanzaron o superaron la etapa de reunión
        result_meeting = conn.execute(
            f"SELECT COUNT(*) FROM leads WHERE status IN ({_MEETING_SQL})"  # nosec B608 - module constants
        ).fetchone()
        with_meeting = result_meeting[0] if result_meeting else 0

        result_client = conn.execute(
            "SELECT COUNT(*) FROM leads WHERE client_id IS NOT NULL"
        ).fetchone()
        with_client = result_client[0] if result_client else 0

        # Conteo por fuente
        cursor = conn.execute(
            "SELECT source, COUNT(*) FROM leads GROUP BY source ORDER BY source"
        )
        by_source = {row[0]: row[1] for row in cursor.fetchall()}

        conn.close()

        return {
            "total_leads": total_leads,
            "with_meeting": with_meeting,
            "with_client": with_client,
            "by_source": by_source,
        }

    except Exception:
        logger.exception("Could not load lead statistics")
        return {"total_leads": 0, "with_meeting": 0, "with_client": 0, "by_source": {}}


def get_leads_with_client_info(start_date=None, end_date=None, source=None, status=None):
    """
    Obtiene leads enriquecidos con información del cliente.
    El enriquecimiento se realiza vía JOIN en get_leads() — sin N+1 ni imports de models/.

    Returns:
        list: [{"id", "external_id", "created_at", "source", "status",
                "meeting_date", "client_id", "client_name"}, ...]
    """
    try:
        leads = get_leads(
            start_date=start_date,
            end_date=end_date,
            source=source,
            status=status,
        )

        _log_lead_consistency(leads)
        return leads

    except Exception:
        logger.exception("Error enriqueciendo leads")
        return []


_CONSISTENCY_EXAMPLES = 3


def _log_lead_consistency(leads: list) -> None:
    """Log status/field inconsistencies once per load instead of once per lead.

    One WARNING per lead on every refresh produced hundreds of lines per visit
    to the Leads page, rotating real errors out of the size-limited log.
    Per-lead detail remains available at DEBUG level.
    """
    issues: dict[str, list[str]] = {}

    def note(issue: str, lead: dict) -> None:
        lead_id = str(lead.get("id"))
        issues.setdefault(issue, []).append(lead_id)
        logger.debug("Lead %s: %s", lead_id, issue)

    for lead in leads:
        s = (lead.get("status") or "").lower().strip()
        if s and s not in _VALID_STATUSES:
            note(f"unknown status value '{lead.get('status')}'", lead)
        if s == "meeting" and not lead.get("meeting_date"):
            note("status='meeting' but meeting_date is NULL", lead)
        if s == "converted" and not lead.get("client_id"):
            note("status='converted' but client_id is NULL", lead)
        if s == "new" and lead.get("meeting_date"):
            note("status='new' but meeting_date is set", lead)
        if s == "new" and lead.get("client_id"):
            note("status='new' but client_id is set", lead)
        if s == "contacted" and lead.get("client_id"):
            note("status='contacted' but client_id is set", lead)

    if issues:
        logger.warning(
            "Lead data consistency: %s",
            "; ".join(
                f"{len(ids)} with {issue} (e.g. {', '.join(ids[:_CONSISTENCY_EXAMPLES])})"
                for issue, ids in issues.items()
            ),
        )


def get_unique_sources():
    """Obtiene lista de fuentes de leads únicas."""
    try:
        conn = get_db_connection()
        cursor = conn.execute("SELECT DISTINCT source FROM leads ORDER BY source")
        sources = [row[0] for row in cursor.fetchall()]
        conn.close()
        return sources
    except Exception:
        logger.exception("Could not load lead sources")
        return []


def get_unique_statuses():
    """Obtiene lista de estados de leads únicos."""
    try:
        conn = get_db_connection()
        cursor = conn.execute("SELECT DISTINCT status FROM leads ORDER BY status")
        statuses = [row[0] for row in cursor.fetchall()]
        conn.close()
        return statuses
    except Exception:
        logger.exception("Could not load lead statuses")
        return []


# ---------------------------------------------------------------------------
# Analytics puras — trabajan sobre listas de leads ya cargadas (sin queries).
# Usadas por la vista y sus componentes.
# ---------------------------------------------------------------------------

def get_funnel_stats(leads: list) -> dict:
    """
    Calcula estadísticas del funnel a partir de una lista de leads enriched.

    Fuente de verdad: campo `status`.
    - meetings = status in MEETING_OR_LATER (meeting, qualified, converted) → reached the meeting stage
    - converted = status == "converted"
    - lost      = status == "lost"
    - meeting_to_client_pct = converted_from_meeting / meetings

    Args:
        leads: Lista de dicts con clave 'status', 'meeting_date', 'created_at'.

    Returns:
        dict con total, meetings, converted, lost, porcentajes y tiempos.
    """
    total = len(leads)

    # meetings: leads que alcanzaron o superaron la etapa de reunión
    meetings = len([ld for ld in leads if ld.get("status") in MEETING_OR_LATER])
    converted = len([ld for ld in leads if ld.get("status") == "converted"])
    lost = len([ld for ld in leads if ld.get("status") == "lost"])

    # Converted leads that also have a meeting_date (passed through meeting stage)
    converted_from_meeting = len([
        ld for ld in leads
        if ld.get("status") == "converted" and ld.get("meeting_date")
    ])

    lead_to_meeting_pct = (meetings / total * 100) if total > 0 else 0.0
    # Denominator is meetings (all leads that reached meeting stage)
    meeting_to_client_pct = (
        converted_from_meeting / meetings * 100
    ) if meetings > 0 else 0.0

    # Average days from lead creation to meeting — only leads with both dates
    valid = [
        ld for ld in leads
        if ld.get("meeting_date") and ld.get("created_at")
    ]
    if valid:
        deltas = []
        for ld in valid:
            try:
                delta = (
                    date.fromisoformat(str(ld["meeting_date"])[:10])
                    - date.fromisoformat(str(ld["created_at"])[:10])
                ).days
                deltas.append(delta)
            except (ValueError, TypeError):
                pass
        avg_time_to_meeting = sum(deltas) / len(deltas) if deltas else 0.0
    else:
        avg_time_to_meeting = 0.0

    return {
        "total": total,
        "meetings": meetings,
        "converted": converted,
        "lost": lost,
        "lead_to_meeting_pct": lead_to_meeting_pct,
        "meeting_to_client_pct": meeting_to_client_pct,
        "lead_dropoff": total - meetings,
        "meeting_dropoff": meetings - converted,
        "converted_from_meeting": converted_from_meeting,
        "avg_time_to_meeting": avg_time_to_meeting,
    }


def group_leads_by_source(leads: list) -> dict:
    """
    Agrupa leads por fuente de origen.

    Fuente de verdad: campo `status`.
    - meetings: status in ("meeting", "converted")
    - clients:  status == "converted"

    Args:
        leads: Lista de dicts con claves 'source', 'status', 'meeting_date', 'created_at'.

    Returns:
        dict[source] = {
            "total": int,
            "meetings": int,           # alcanzaron etapa reunión
            "clients": int,            # convirtieron
            "clients_from_meeting": int,
            "meeting_to_client_pct": float,
            "avg_time_to_meeting": float,
        }
    """
    sources_data: dict = {}
    for ld in leads:
        src = ld.get("source") or "unknown"
        if src not in sources_data:
            sources_data[src] = {
                "total": 0,
                "meetings": 0,
                "clients": 0,
                "clients_from_meeting": 0,
                "time_to_meeting_days_total": 0.0,
                "time_to_meeting_count": 0,
            }
        sources_data[src]["total"] += 1
        if ld.get("status") in ("meeting", "converted"):
            sources_data[src]["meetings"] += 1
        if ld.get("status") == "converted":
            sources_data[src]["clients"] += 1
        if ld.get("status") == "converted" and ld.get("meeting_date"):
            sources_data[src]["clients_from_meeting"] += 1
        if ld.get("meeting_date") and ld.get("created_at"):
            try:
                delta = (
                    date.fromisoformat(str(ld["meeting_date"])[:10])
                    - date.fromisoformat(str(ld["created_at"])[:10])
                ).days
                sources_data[src]["time_to_meeting_days_total"] += delta
                sources_data[src]["time_to_meeting_count"] += 1
            except (ValueError, TypeError):
                pass  # malformed date — skip safely

    # Compute derived per-source rates
    for src_data in sources_data.values():
        mtgs = src_data["meetings"]
        src_data["meeting_to_client_pct"] = (
            src_data["clients_from_meeting"] / mtgs * 100
        ) if mtgs > 0 else 0.0
        cnt = src_data["time_to_meeting_count"]
        src_data["avg_time_to_meeting"] = (
            src_data["time_to_meeting_days_total"] / cnt
        ) if cnt > 0 else 0.0

    return sources_data
