"""
Módulo de gestión de leads — operaciones de escritura.

Operaciones disponibles:
  insert_lead()                      — crear un nuevo lead
  update_lead_status_and_meeting()   — actualizar status y meeting_date
  get_lead_by_id()                   — leer un lead por ID
  get_latest_lead_per_client()       — lead más reciente por cliente
"""

from domain.lead_stages import LEAD_STATUSES
import re
import secrets
import string
from datetime import date as _date
from core.db import get_connection

# Vocabulario válido de estados de lead (consistente con importer y tabla_leads)
VALID_LEAD_STATUSES = frozenset(LEAD_STATUSES)


def _generate_lead_id() -> str:
    """Genera un ID único para leads manuales (formato L_XXXXXX)."""
    alphabet = string.ascii_uppercase + string.digits
    return "L_" + "".join(secrets.choice(alphabet) for _ in range(6))


def insert_lead(
    source: str,
    status: str = "new",
    meeting_date: str | None = None,
    client_id: str | None = None,
    created_at: str | None = None,
    external_id: str | None = None,
) -> str:
    """
    Inserta un nuevo lead con ID auto-generado.

    Args:
        source:       Fuente del lead (ej: "meta_ads", "google_ads").
        status:       Estado inicial — debe estar en VALID_LEAD_STATUSES.
        meeting_date: Fecha ISO de reunión (YYYY-MM-DD) o None.
        client_id:    ID del cliente asociado o None.
        created_at:   Fecha ISO de creación. Si es None, usa la fecha actual.
        external_id:  ID externo opcional (ej: id del CRM de origen).

    Returns:
        ID del lead insertado (formato L_XXXXXX).

    Raises:
        ValueError: Si el status no es válido.
    """
    if status not in VALID_LEAD_STATUSES:
        raise ValueError(f"Invalid status: '{status}'. Valid values: {sorted(VALID_LEAD_STATUSES)}")

    lead_id = _generate_lead_id()
    created = created_at or _date.today().isoformat()

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO leads (id, external_id, created_at, source, status, meeting_date, client_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lead_id, external_id, created, source, status, meeting_date, client_id),
        )
        conn.commit()
        return lead_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_lead_by_id(lead_id: str) -> dict | None:
    """
    Obtiene un lead por su ID.

    Returns:
        dict con campos del lead, o None si no existe.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, external_id, created_at, source, status, meeting_date, client_id "
            "FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "external_id": row[1],
            "created_at": row[2],
            "source": row[3],
            "status": row[4],
            "meeting_date": row[5],
            "client_id": row[6],
        }
    finally:
        conn.close()


def update_lead_status_and_meeting(
    lead_id: str, status: str, meeting_date: str | None
) -> None:
    """
    Actualiza status y meeting_date de un lead.

    Args:
        lead_id: ID del lead a actualizar.
        status: Nuevo estado (debe estar en VALID_LEAD_STATUSES).
        meeting_date: Fecha ISO (YYYY-MM-DD) o None.

    Raises:
        ValueError: Si el lead_id no existe.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE leads SET status = ?, meeting_date = ? WHERE id = ?",
            (status, meeting_date or None, lead_id),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"Lead not found: {lead_id}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def validate_lead_status(status: str) -> bool:
    """Valida que el status pertenezca al vocabulario conocido."""
    return bool(status) and status.lower().strip() in VALID_LEAD_STATUSES


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_meeting_date(meeting_date: str | None) -> bool:
    """Valida formato ISO de meeting_date. Vacío/None es válido."""
    if not meeting_date or meeting_date.strip() == "":
        return True
    clean = meeting_date.strip()
    if not _ISO_DATE_RE.match(clean):
        return False
    try:
        _date.fromisoformat(clean)
    except ValueError:
        return False
    return True


def get_latest_lead_per_client() -> dict[str, dict]:
    """
    Returns the most recent lead for each client_id that has one.

    Uses a window function to avoid N+1 queries.

    Returns:
        dict mapping client_id → lead dict with keys:
        id, external_id, created_at, source, status, meeting_date, client_id
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, external_id, created_at, source, status, meeting_date, client_id
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY client_id ORDER BY created_at DESC
                ) AS rn
                FROM leads
                WHERE client_id IS NOT NULL
            )
            WHERE rn = 1
            """,
        ).fetchall()
        result: dict[str, dict] = {}
        for row in rows:
            result[row[6]] = {
                "id": row[0],
                "external_id": row[1],
                "created_at": row[2],
                "source": row[3],
                "status": row[4],
                "meeting_date": row[5],
                "client_id": row[6],
            }
        return result
    except Exception:
        return {}
    finally:
        conn.close()
