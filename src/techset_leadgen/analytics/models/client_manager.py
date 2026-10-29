import secrets
import string
from techset_leadgen.database.local_db import get_connection

from techset_leadgen.analytics.models.client_validators import (
    validate_name,
    validate_cif,
    validate_email,
    validate_contact,
    validate_client_data,
    client_exists_by_cif,
    client_exists_by_name,
)

from techset_leadgen.analytics.models.client_duplicates import (
    find_duplicate_names_in_sales,
    get_duplicate_summary,
)
from techset_leadgen.analytics.models.client_duplicates import merge_clients_by_name as _merge_clients


_clients_cache: dict[str, tuple] = {}
_cache_loaded = False


def _invalidate_cache():
    global _cache_loaded
    _cache_loaded = False
    _clients_cache.clear()

def invalidate_clients_cache():
    _invalidate_cache()

def _load_clients_cache():
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
    _load_clients_cache()
    if client_id in _clients_cache:
        name, cif, address, contact_person, email = _clients_cache[client_id]
        return (client_id, name, cif, address, contact_person, email)
    return None


def _generate_client_id():
    alphabet = string.ascii_uppercase + string.digits
    return "M_" + "".join(secrets.choice(alphabet) for _ in range(6))


def add_client(name, cif, address, contact_person, email):
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
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients")
    data = cursor.fetchall()
    conn.close()
    return data


def get_client_by_id(client_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
    data = cursor.fetchone()
    conn.close()
    return data


def update_client(client_id, name, cif, address, contact_person, email):
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
    global _cache_loaded
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    _invalidate_cache()


def merge_clients_by_name():
    return _merge_clients(invalidate_cache_callback=_invalidate_cache)

