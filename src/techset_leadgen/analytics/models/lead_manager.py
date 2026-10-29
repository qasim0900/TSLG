from techset_leadgen.domain.lead_stages import LEAD_STATUSES
import re
import secrets
import string
from datetime import date as _date
from techset_leadgen.database.local_db import get_connection

VALID_LEAD_STATUSES = frozenset(LEAD_STATUSES)


def _generate_lead_id() -> str:
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
    return bool(status) and status.lower().strip() in VALID_LEAD_STATUSES


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_meeting_date(meeting_date: str | None) -> bool:
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

