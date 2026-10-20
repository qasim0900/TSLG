"""
Módulo de validaciones para clientes.
Contiene funciones de validación de datos de clientes.
"""
import re
from core.db import get_connection


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


def validate_client_data(name, cif, email, contact):
    """
    Valida todos los datos de un cliente.
    Retorna (es_válido, mensaje_error)
    """
    if not validate_name(name):
        return False, "The name must have at least 2 characters."
    
    if not validate_cif(cif):
        return False, "The tax ID (CIF/NIF) must have 7 to 12 letters or digits."
    
    if not validate_email(email):
        return False, "Enter a valid email address."
    
    if not validate_contact(contact):
        return False, "The contact name must have at least 2 characters."
    
    return True, ""


# ============================================================
#   VALIDACIONES DE DUPLICIDAD
# ============================================================

def client_exists_by_cif(cif, exclude_id=None):
    """
    Verifica si ya existe un cliente con el mismo CIF.
    
    Args:
        cif: CIF a verificar
        exclude_id: ID de cliente a excluir (para edición)
    
    Returns:
        True si existe otro cliente con ese CIF
    """
    conn = get_connection()
    cursor = conn.cursor()

    if exclude_id:
        cursor.execute(
            "SELECT id FROM clients WHERE UPPER(TRIM(cif)) = ? AND id != ?",
            (cif.strip().upper(), exclude_id)
        )
    else:
        cursor.execute(
            "SELECT id FROM clients WHERE UPPER(TRIM(cif)) = ?",
            (cif.strip().upper(),)
        )

    result = cursor.fetchone()
    conn.close()
    return result is not None


def client_exists_by_name(name, exclude_id=None):
    """
    Verifica si ya existe un cliente con el mismo nombre.
    
    Args:
        name: Nombre a verificar
        exclude_id: ID de cliente a excluir (para edición)
    
    Returns:
        True si existe otro cliente con ese nombre
    """
    conn = get_connection()
    cursor = conn.cursor()

    if exclude_id:
        cursor.execute(
            "SELECT id FROM clients WHERE LOWER(name) = LOWER(?) AND id != ?",
            (name.strip(), exclude_id)
        )
    else:
        cursor.execute(
            "SELECT id FROM clients WHERE LOWER(name) = LOWER(?)",
            (name.strip(),)
        )

    result = cursor.fetchone()
    conn.close()
    return result is not None
