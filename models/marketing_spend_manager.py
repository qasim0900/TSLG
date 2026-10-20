"""
Módulo de gestión de marketing_spend — operaciones CRUD.

Operaciones disponibles:
  insert_spend()       — crear un registro de inversión
  update_spend()       — actualizar un registro existente
  delete_spend()       — eliminar un registro por ID
  get_all_spend()      — listar todos los registros (ORDER BY date DESC)
  get_spend_by_id()    — obtener un registro por ID
"""

import re
from datetime import date as _date
from core.db import get_connection
from utils.formatting import parse_amount

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_source(source: str) -> str:
    """Valida y normaliza el campo source usando la normalización del importer."""
    if not source or not source.strip():
        raise ValueError("The source is required.")
    from core.importer import _normalize_source
    return _normalize_source(source.strip())


def _validate_amount(amount) -> float:
    """Valida que amount sea numérico y > 0."""
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
    """Valida formato ISO YYYY-MM-DD. Si vacío, usa fecha actual."""
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
    """
    Inserta un registro de inversión en marketing_spend.

    Args:
        source:   Fuente de marketing (se normaliza automáticamente).
        amount:   Monto de inversión (debe ser > 0).
        date_str: Fecha ISO (YYYY-MM-DD). Si vacío, usa fecha actual.

    Returns:
        ID del registro insertado.

    Raises:
        ValueError: Si algún campo es inválido.
    """
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
    """
    Actualiza un registro de marketing_spend existente.

    Returns:
        True si se actualizó, False si no se encontró el ID.

    Raises:
        ValueError: Si algún campo es inválido.
    """
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
    """
    Elimina un registro de marketing_spend por ID.

    Returns:
        True si se eliminó, False si no existía.
    """
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
    """
    Obtiene todos los registros de marketing_spend ordenados por fecha DESC.

    Returns:
        Lista de dicts con claves: id, source, amount, date.
    """
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
    """
    Obtiene un registro de marketing_spend por ID.

    Returns:
        dict con claves id, source, amount, date; o None si no existe.
    """
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
