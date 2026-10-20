"""Background file imports with process-wide mutual exclusion and callbacks."""

import logging
import os
import re
import threading
from typing import Callable, Optional
from core.importer import import_csv_to_db, import_leads_to_db, import_marketing_spend_to_db, inspect_import_file
from models.client_manager import invalidate_clients_cache
from utils.formatting import pluralize

logger = logging.getLogger(__name__)

IMPORT_IN_PROGRESS_MESSAGE = "An import is already running. Wait for it to finish."

_IMPORT_LOCK = threading.Lock()


def is_import_running() -> bool:
    return _IMPORT_LOCK.locked()


class FileImportController:
    """Controlador centralizado para la importación de archivos."""

    def __init__(self, on_success: Callable, on_error: Callable, on_start: Callable):
        """
        Inicializa el controlador.

        Args:
            on_success: Callback(message) cuando la importación es exitosa
            on_error: Callback(message) cuando hay un error
            on_start: Callback() cuando inicia la importación
        """
        self.on_success = on_success
        self.on_error = on_error
        self.on_start = on_start
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        """Return whether this controller still owns a live import worker."""
        return self._thread is not None and self._thread.is_alive()

    def wait_for_completion(self, timeout: float | None = None) -> bool:
        """Wait for a worker during orderly shutdown; return whether it finished."""
        worker = self._thread
        if worker is None or worker is threading.current_thread():
            return True
        worker.join(timeout)
        return not worker.is_alive()

    def validate_file(self, file_path: Optional[str]) -> tuple[bool, Optional[str]]:
        """
        Valida que el archivo exista y sea accesible.

        Retorna: (es_valido, mensaje_error_o_none)
        """
        if not file_path:
            return False, "No file selected"

        if not os.path.exists(file_path):
            return False, "The file does not exist or cannot be accessed"

        return True, None

    def _start_import(self, file_path: Optional[str], job: Callable[[], tuple[bool, str]], error_prefix: str) -> None:
        is_valid, error_msg = self.validate_file(file_path)
        if not is_valid:
            self.on_error(error_msg)
            return

        if not _IMPORT_LOCK.acquire(blocking=False):
            self.on_error(IMPORT_IN_PROGRESS_MESSAGE)
            return

        try:
            self.on_start()
            self._thread = threading.Thread(
                target=self._run_job,
                args=(job, error_prefix),
                daemon=False,
                name="techset-import-worker",
            )
            self._thread.start()
        except BaseException:
            _IMPORT_LOCK.release()
            raise

    def _run_job(self, job: Callable[[], tuple[bool, str]], error_prefix: str) -> None:
        try:
            ok, msg = job()
        except Exception as e:
            logger.exception("Import failed")
            ok, msg = False, f"{error_prefix}: {e}"
        finally:
            invalidate_clients_cache()
            _IMPORT_LOCK.release()

        if ok:
            self.on_success(msg)
        else:
            self.on_error(msg)
        self._thread = None

    def import_file(self, file_path: str) -> None:
        """
        Importa un archivo de ventas en un hilo de fondo.

        Valida el archivo y ejecuta la importación de forma asincrónica.
        Dispara los callbacks correspondientes.
        """
        self._start_import(
            file_path,
            lambda: import_csv_to_db(file_path),
            "Import failed",
        )

    def import_sales(self, file_path: str) -> None:
        """Alias explícito para importar ventas (delega a import_file)."""
        self.import_file(file_path)

    def import_leads(self, file_path: str) -> None:
        """Importa leads en un hilo de fondo."""
        self._start_import(
            file_path,
            lambda: import_leads_to_db(file_path),
            "Lead import failed",
        )

    def import_marketing_spend(self, file_path: str) -> None:
        """Importa marketing_spend en un hilo de fondo."""
        self._start_import(
            file_path,
            lambda: import_marketing_spend_to_db(file_path),
            "Marketing spend import failed",
        )

    def import_both(self, file_path: str) -> None:
        """Importa leads + ventas desde el mismo archivo (tipo mixed) en un solo hilo."""
        if self.validate_file(file_path)[0]:
            try:
                total_rows = inspect_import_file(file_path).get("row_count", 0)
            except Exception:
                logger.exception("Could not count the rows of the mixed file")
                total_rows = None
        else:
            total_rows = None

        self._start_import(
            file_path,
            lambda: self._import_mixed(file_path, total_rows),
            "Mixed import failed",
        )

    @staticmethod
    def _parse_count(msg: str) -> int:
        """Extrae el número de filas importadas del mensaje del importer."""
        m = re.search(r"OK (\d+)", msg)
        return int(m.group(1)) if m else 0

    def _import_mixed(self, file_path: str, total_rows: Optional[int]) -> tuple[bool, str]:
        lead_count = 0
        sale_count = 0
        error_parts = []
        success_parts = []

        try:
            ok_sales, msg_sales = import_csv_to_db(file_path)
            if ok_sales:
                sale_count = self._parse_count(msg_sales)
                success_parts.append(f"Sales: {msg_sales}")
            else:
                error_parts.append(f"Sales: {msg_sales}")
        except Exception as e:
            logger.exception("Could not import sales from the mixed file")
            error_parts.append(f"Sales error: {e}")

        try:
            ok_leads, msg_leads = import_leads_to_db(file_path)
            if ok_leads:
                lead_count = self._parse_count(msg_leads)
                success_parts.append(f"Leads: {msg_leads}")
            else:
                error_parts.append(f"Leads: {msg_leads}")
        except Exception as e:
            logger.exception("Could not import leads from the mixed file")
            error_parts.append(f"Leads error: {e}")

        if error_parts:
            return False, " | ".join(error_parts + success_parts)

        # Filas genuinamente inválidas = filas totales - leads importados - ventas importadas
        # (las "rechazadas esperadas" de cada importer son exactamente las filas del otro tipo)
        msg = f"Imported {pluralize(sale_count, 'sale')} and {pluralize(lead_count, 'lead')}."
        if total_rows is not None:
            genuine_invalid = total_rows - lead_count - sale_count
            if genuine_invalid > 0:
                msg += f" ⚠ Skipped {pluralize(genuine_invalid, 'invalid row')}."

        return True, msg
