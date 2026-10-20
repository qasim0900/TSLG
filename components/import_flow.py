"""
components/import_flow.py

Helper reutilizable para el flujo de importación de archivos.

Responsabilidades:
    1. Abrir FilePicker
    2. Inspecionar headers con inspect_import_file()
    3. Detectar tipo de archivo (sales / leads / mixed / invalid)
    4. Guardar el prefijo de tipo en la vista (via callback)
    5. Rutear al método correcto del FileImportController

NO hace:
    - Refrescar vistas
    - Invalidar caches
    - Llamar page.update()
    - Mostrar resultados finales de importación

Esas responsabilidades pertenecen a cada vista.
"""

import asyncio
import logging
from utils.file_dialogs import pick_single_file
from core.importer import inspect_import_file
from components.import_preview_dialog import create_import_preview_dialog

logger = logging.getLogger(__name__)

# Texto UX por tipo detectado
_DETECTED_LABELS = {
    "sales": "SALES",
    "leads": "LEADS",
    "mixed": "MIXED (sales + leads)",
    "marketing_spend": "MARKETING SPEND",
}


async def run_import_flow(
    page,
    controller,
    notifications,
    set_detected_prefix,
):
    """
    Ejecuta el flujo completo de selección e inspección de archivo de importación.

    Parámetros:
        page               : ft.Page — página activa de Flet
        controller         : FileImportController — instancia del controlador a usar
        notifications      : NotificationManager — para mostrar errores de inspección
        set_detected_prefix: callable(str | None) — callback para guardar el prefijo
                             de tipo detectado en el estado de la vista, usado luego
                             por _on_import_success() para prefijar el mensaje final.

    Flujo:
        FilePicker → inspect_import_file() → routing a controller.import_*()

    Devuelve None siempre; los resultados se comunican mediante los callbacks
    del controller (on_success, on_error, on_start) que fueron inyectados al
    construir el FileImportController en cada vista.
    """
    # 1. Abrir FilePicker
    file_path = await pick_single_file(
        page,
        allowed_extensions=["csv", "xlsx"],
    )

    # 2. Archivo no seleccionado
    if not file_path:
        notifications.show_file_selected_error()
        return

    # 3. Inspeccionar headers (sin tocar la BD)
    result = await asyncio.to_thread(inspect_import_file, file_path)
    detected = result["detected_type"]

    logger.info("[import_flow] File inspected: %s → %s", file_path, detected)

    # 4. Archivo inválido → notificar y abortar
    if detected == "invalid":
        parts = []
        if result["missing_sales"]:
            parts.append("sales: " + ", ".join(result["missing_sales"]))
        if result["missing_leads"]:
            parts.append("leads: " + ", ".join(result["missing_leads"]))
        if result.get("missing_marketing_spend"):
            parts.append("marketing spend: " + ", ".join(result["missing_marketing_spend"]))
        detail = " | ".join(parts) if parts else "unrecognized format"
        notifications.show_import_error(
            f"Invalid file — missing columns ({detail})"
        )
        return

    # 5. Construir callbacks para el dialog
    def _on_confirm():
        # Registrar prefijo de tipo (debe hacerse antes de iniciar el hilo)
        set_detected_prefix(_DETECTED_LABELS.get(detected))
        # Rutear al controller — arranca hilo de fondo
        if detected == "sales":
            controller.import_sales(file_path)
        elif detected == "leads":
            controller.import_leads(file_path)
        elif detected == "marketing_spend":
            controller.import_marketing_spend(file_path)
        elif detected == "mixed":
            controller.import_both(file_path)

    # 6. Mostrar Preview Dialog y esperar confirmación del usuario
    dialog = create_import_preview_dialog(
        page=page,
        detected_type=detected,
        headers=result["headers"],
        row_count=result.get("row_count"),
        valid_rows=result.get("valid_rows"),
        invalid_rows=result.get("invalid_rows"),
        on_confirm=_on_confirm,
        on_cancel=lambda: None,
    )
    page.show_dialog(dialog)
