"""
Funciones utilitarias para conexión y helpers de base de datos.
"""
from core.db import get_connection


def get_db_connection():
    """Obtiene conexión a la base de datos SQLite (con WAL y FK activos)."""
    return get_connection()
