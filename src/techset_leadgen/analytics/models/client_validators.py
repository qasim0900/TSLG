import re
from techset_leadgen.database.local_db import get_connection


def validate_name(name):
    return bool(name) and len(name.strip()) >= 2


def validate_cif(cif):
    if not cif or cif.strip() == "":
        return True
    cleaned = re.sub(r"[-.\s]", "", cif.strip())
    return bool(re.match(r"^[A-Za-z0-9]{7,12}$", cleaned))


def validate_email(email):
    if not email or email.strip() == "":
        return True
    return bool(re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email.strip()))


def validate_contact(contact):
    if not contact or contact.strip() == "":
        return True
    return len(contact.strip()) >= 2


def client_field_errors(name, cif, email, contact):
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
    errors = client_field_errors(name, cif, email, contact)
    if errors:
        return False, next(iter(errors.values()))
    return True, ""


def client_exists_by_cif(cif, exclude_id=None, connection=None):
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

