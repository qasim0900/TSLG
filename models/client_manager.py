"""
Módulo principal de gestión de clientes.
Proporciona operaciones CRUD y re-exporta funciones de validación y duplicados.

Estructura del módulo models/:
- client_manager.py: CRUD de clientes y punto de entrada principal
- client_validators.py: Validaciones de formato y duplicidad
- client_duplicates.py: Detección y fusión de duplicados
"""

import random
import string
from core.db import get_connection

# Re-exportar funciones de validación para mantener compatibilidad
from models.client_validators import (
    validate_name,
    validate_cif,
    validate_email,
    validate_contact,
    validate_client_data,
    client_exists_by_cif,
    client_exists_by_name,
)

# Re-exportar funciones de duplicados
from models.client_duplicates import (
    find_duplicate_names_in_sales,
    get_duplicate_summary,
)
from models.client_duplicates import merge_clients_by_name as _merge_clients


# ============================================================
#   CACHÉ DE CLIENTES
# ============================================================

_clients_cache: dict[str, tuple] = {}
_cache_loaded = False


def _invalidate_cache():
    """Invalida el caché de clientes."""
    global _cache_loaded
    _cache_loaded = False
    _clients_cache.clear()

def invalidate_clients_cache():
    _invalidate_cache()

def _load_clients_cache():
    """Carga clientes en caché una sola vez."""
    global _clients_cache, _cache_loaded
    if _cache_loaded:
        return
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, cif, address, contact_person, email FROM clients")
    data = cursor.fetchall()
    conn.close()
    
    _clients_cache.clear()
    for row in data:
        client_id, name, cif, address, contact_person, email = row
        _clients_cache[client_id] = (name, cif, address, contact_person, email)
    
    _cache_loaded = True


def get_client_by_id_cached(client_id):
    """Obtiene cliente por ID desde caché (muy rápido)."""
    _load_clients_cache()
    if client_id in _clients_cache:
        name, cif, address, contact_person, email = _clients_cache[client_id]
        return (client_id, name, cif, address, contact_person, email)
    return None


# ============================================================
#   CRUD DE CLIENTES
# ============================================================

def _generate_client_id():
    """Genera un ID único para clientes manuales (formato M_XXXXXX)."""
    return "M_" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def add_client(name, cif, address, contact_person, email):
    """
    Añade un nuevo cliente con ID auto-generado.
    
    Returns:
        El ID generado del nuevo cliente
    """
    global _cache_loaded
    client_id = _generate_client_id()
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO clients (id, name, cif, address, contact_person, email) VALUES (?, ?, ?, ?, ?, ?)",
        (client_id, name, cif, address, contact_person, email),
    )
    conn.commit()
    conn.close()
    _invalidate_cache()
    return client_id


def add_client_with_id(client_id, name, cif, address, contact_person, email):
    """
    Añade un cliente con un ID específico (para mantener consistencia con ventas).
    """
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO clients (id, name, cif, address, contact_person, email)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                cif = excluded.cif,
                address = excluded.address,
                contact_person = excluded.contact_person,
                email = excluded.email
            """,
            (str(client_id), name, cif, address, contact_person, email),
        )
        conn.commit()
    finally:
        conn.close()
    _invalidate_cache()


def get_clients():
    """Obtiene todos los clientes de la base de datos."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients")
    data = cursor.fetchall()
    conn.close()
    return data


def get_client_by_id(client_id):
    """Obtiene un cliente por su ID directamente de la base de datos."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
    data = cursor.fetchone()
    conn.close()
    return data


def update_client(client_id, name, cif, address, contact_person, email):
    """Actualiza los datos de un cliente existente."""
    global _cache_loaded
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE clients SET name=?, cif=?, address=?, contact_person=?, email=? WHERE id=?",
        (name, cif, address, contact_person, email, client_id),
    )
    conn.commit()
    conn.close()
    _invalidate_cache()


def delete_client(client_id):
    """Elimina un cliente por su ID."""
    global _cache_loaded
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    conn.commit()
    # Forzar WAL checkpoint para que todas las conexiones vean el cambio
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    _invalidate_cache()


# ============================================================
#   FUSIÓN DE DUPLICADOS (wrapper)
# ============================================================

def merge_clients_by_name():
    """
    Fusiona clientes duplicados por nombre.
    Wrapper que pasa el callback de invalidación de caché.
    """
    return _merge_clients(invalidate_cache_callback=_invalidate_cache)
