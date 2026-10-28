"""
Módulo de validaciones para clientes.
Contiene funciones de validación de datos de clientes.
"""
import re
from techset_leadgen.database.local_db import get_connection


# ============================================================
#   VALIDACIONES DE FORMATO
# ============================================================

def validate_name(name):
    """Valida que el nombre tenga al menos 2 caracteres."""
    return bool(name) and len(name.strip()) >= 2


def validate_cif(cif):
    """Valida que el CIF/NIF/NIE tenga formato razonable. CIF vacío es válido."""
    if not cif or cif.strip() == "":
        return True
    # Eliminar separadores comunes (guiones, puntos, espacios) antes de validar
    cleaned = re.sub(r"[-.\s]", "", cif.strip())
    return bool(re.match(r"^[A-Za-z0-9]{7,12}$", cleaned))


def validate_email(email):
    """Valida que el email tenga formato válido. Email vacío es válido."""
    if not email or email.strip() == "":
        return True
    return bool(re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email.strip()))


def validate_contact(contact):
    """Valida que el contacto tenga al menos 2 caracteres. Contacto vacío es válido."""
    if not contact or contact.strip() == "":
        return True
    return len(contact.strip()) >= 2


def client_field_errors(name, cif, email, contact):
    """Return ``{field: message}`` for every invalid client field (empty when all are valid).

    The single statement of the client format rules, used by the clients
    controller and by the CRM client service.
    """
    errors = {}
    if not validate_name(name):
        errors["name"] = "The name must have at least 2 characters."
    if not validate_cif(cif):
        errors["cif"] = "The tax ID (CIF/NIF) must have 7 to 12 letters or digits."
    if not validate_email(email):
        errors["email"] = "Enter a valid email address."
    if not validate_contact(contact):
        errors["contact_person"] = "The contact name must have at least 2 characters."
    return errors


def validate_client_data(name, cif, email, contact):
    """
    Valida todos los datos de un cliente.
    Retorna (es_válido, mensaje_error)
    """
    errors = client_field_errors(name, cif, email, contact)
    if errors:
        return False, next(iter(errors.values()))
    return True, ""


# ============================================================
#   VALIDACIONES DE DUPLICIDAD
# ============================================================

def client_exists_by_cif(cif, exclude_id=None, connection=None):
    """
    Verifica si ya existe un cliente con el mismo CIF.

    Args:
        cif: CIF a verificar
        exclude_id: ID de cliente a excluir (para edición)
        connection: conexión abierta a reutilizar (p. ej. la transacción de un
            servicio); si se omite se abre y se cierra una propia.

    Returns:
        True si existe otro cliente con ese CIF
    """
    conn = connection or get_connection()
    try:
        if exclude_id:
            result = conn.execute(
                "SELECT id FROM clients WHERE UPPER(TRIM(cif)) = ? AND id != ?",
                (cif.strip().upper(), exclude_id)
            ).fetchone()
        else:
            result = conn.execute(
                "SELECT id FROM clients WHERE UPPER(TRIM(cif)) = ?",
                (cif.strip().upper(),)
            ).fetchone()
    finally:
        if connection is None:
            conn.close()
    return result is not None


def client_exists_by_name(name, exclude_id=None, connection=None):
    """
    Verifica si ya existe un cliente con el mismo nombre.

    Args:
        name: Nombre a verificar
        exclude_id: ID de cliente a excluir (para edición)
        connection: conexión abierta a reutilizar; si se omite se abre una propia.

    Returns:
        True si existe otro cliente con ese nombre
    """
    # SQLite's LOWER() only folds ASCII, so "CAFÉ MÜLLER" slipped past an
    # existing "Café Müller". Compare with Unicode case folding instead.
    target = name.strip().casefold()
    conn = connection or get_connection()
    try:
        rows = conn.execute("SELECT id, name FROM clients").fetchall()
    finally:
        if connection is None:
            conn.close()
    return any(
        str(existing or "").strip().casefold() == target
        and not (exclude_id and client_id == exclude_id)
        for client_id, existing in rows
    )
