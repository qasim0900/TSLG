import re
from datetime import date as _date
from techset_leadgen.database.local_db import get_connection
from techset_leadgen.utils.formatting import parse_amount

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_source(source: str) -> str:
    if not source or not source.strip():
        raise ValueError("The source is required.")
    from techset_leadgen.analytics.importer import _normalize_source
    return _normalize_source(source.strip())


def _validate_amount(amount) -> float:
    if amount is None:
        raise ValueError("The amount is required.")
    try:
        val = parse_amount(amount)
    except ValueError:
        raise ValueError(
            f"The amount must be a finite number, got: {amount!r}"
        ) from None
    if val <= 0:
        raise ValueError(f"The amount must be greater than 0, got: {val}")
    return round(val, 2)


def _validate_date(date_str: str) -> str:
    if not date_str or not date_str.strip():
        return _date.today().isoformat()
    clean = date_str.strip()
    if not _ISO_DATE_RE.match(clean):
        raise ValueError(f"Invalid date: '{clean}'. Expected format: YYYY-MM-DD")
    try:
        _date.fromisoformat(clean)
    except ValueError:
        raise ValueError(f"Invalid date: '{clean}'. That day does not exist") from None
    return clean


def insert_spend(source: str, amount, date_str: str = "") -> int:
    norm_source = _validate_source(source)
    norm_amount = _validate_amount(amount)
    norm_date = _validate_date(date_str)

    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO marketing_spend (source, amount, date) VALUES (?, ?, ?)",
            (norm_source, norm_amount, norm_date),
        )
        conn.commit()
        return cursor.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_spend(spend_id: int, source: str, amount, date_str: str) -> bool:
    norm_source = _validate_source(source)
    norm_amount = _validate_amount(amount)
    norm_date = _validate_date(date_str)

    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE marketing_spend SET source = ?, amount = ?, date = ? WHERE id = ?",
            (norm_source, norm_amount, norm_date, spend_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_spend(spend_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM marketing_spend WHERE id = ?",
            (spend_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_all_spend() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, source, amount, date FROM marketing_spend ORDER BY date DESC, id DESC"
        ).fetchall()
        return [
            {"id": r[0], "source": r[1], "amount": r[2], "date": r[3]}
            for r in rows
        ]
    finally:
        conn.close()


def get_spend_by_id(spend_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, source, amount, date FROM marketing_spend WHERE id = ?",
            (spend_id,),
        ).fetchone()
        if not row:
            return None
        return {"id": row[0], "source": row[1], "amount": row[2], "date": row[3]}
    finally:
        conn.close()

