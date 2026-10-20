"""Generador de plantillas CSV de ejemplo para importación.

Crea archivos CSV temporales con las columnas y datos de ejemplo
que el importador espera, y los abre con la app predeterminada del SO.
No modifica ninguna lógica de importación.
"""
import csv
import os
import tempfile

from utils.file_opener import open_file_cross_platform


# ------------------------------------------------------------------
# Datos de ejemplo — reflejan exactamente lo que acepta core/importer.py
# ------------------------------------------------------------------

_LEADS_HEADERS = ["external_id", "created_at", "source", "status", "meeting_date", "client_id"]
_LEADS_ROWS = [
    ["L001", "2026-03-01", "Facebook", "new", "2026-03-05", "C001"],
    ["L002", "2026-03-03", "Google", "contacted", "", "C002"],
    ["L003", "2026-03-07", "LinkedIn", "meeting", "2026-03-12", ""],
    ["L004", "2026-03-10", "Instagram", "new", "", "C001"],
    ["L005", "2026-03-15", "TikTok", "contacted", "2026-03-20", "C003"],
]

_SALES_HEADERS = ["client_name", "client_id", "product_type", "price", "date"]
_SALES_ROWS = [
    ["Alpha Inc.", "C001", "Product A", "1200", "2026-03-05"],
    ["Alpha Inc.", "C001", "Product B", "850", "2026-03-12"],
    ["Beta Corp", "C002", "Product A", "2400", "2026-03-08"],
    ["Gamma LLC", "C003", "Product C", "3100", "2026-03-14"],
    ["Beta Corp", "C002", "Product B", "1750", "2026-03-18"],
]

_MARKETING_SPEND_HEADERS = ["source", "amount", "date"]
_MARKETING_SPEND_ROWS = [
    ["Facebook", "1200.00", "2026-03-01"],
    ["Google", "2500.00", "2026-03-01"],
    ["LinkedIn", "800.00", "2026-03-01"],
    ["TikTok", "600.00", "2026-03-15"],
    ["Instagram", "900.00", "2026-03-15"],
]


def generate_template(template_type: str) -> str:
    """Genera un CSV de ejemplo y retorna la ruta del archivo.

    Args:
        template_type: "leads" o "sales"

    Returns:
        Ruta absoluta del archivo generado.
    """
    if template_type == "leads":
        headers, rows = _LEADS_HEADERS, _LEADS_ROWS
        prefix = "leads_template_"
    elif template_type == "marketing_spend":
        headers, rows = _MARKETING_SPEND_HEADERS, _MARKETING_SPEND_ROWS
        prefix = "marketing_spend_template_"
    else:
        headers, rows = _SALES_HEADERS, _SALES_ROWS
        prefix = "sales_template_"

    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".csv")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    return path


def download_and_open_template(template_type: str) -> None:
    """Genera y abre la plantilla con la app predeterminada."""
    path = generate_template(template_type)
    open_file_cross_platform(path)
