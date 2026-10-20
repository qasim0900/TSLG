"""
Módulo core: lógica central de la aplicación.

Para mantener compatibilidad con imports existentes, re-exportamos
desde los módulos de nivel raíz.
"""
# Re-export desde módulos raíz para mantener compatibilidad
from .db import init_db, DB_NAME, clear_sales_table, clear_clients_table
from core.date_range import normalize_iso
## Eliminado: cada módulo debe importar directamente desde analysis
from .date_range import last_n_days, current_month_full, current_year_full, shift_year_iso

# Lazy import para import_csv_to_db (evita cargar openpyxl si no se usa)
def __getattr__(name):
    if name == "import_csv_to_db":
        from core.importer import import_csv_to_db
        return import_csv_to_db
    raise AttributeError(f"module {__name__} has no attribute {name}")

__all__ = [
    # db
    "init_db",
    "DB_NAME",
    "clear_sales_table",
    "clear_clients_table",

    # importer
    "import_csv_to_db",

    # date_range
    "last_n_days",
    "current_month_full",
    "current_year_full",

    # core.date_range
    "shift_year_iso",
    "normalize_iso",
]