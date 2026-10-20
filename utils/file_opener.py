"""
Utilidad cross-platform para abrir archivos con la aplicación predeterminada.

Extrae el patrón duplicado os.startfile / subprocess que existía en
ventas_view.py, leads_view.py y clientes_view.py.
"""

import os
import subprocess
import sys
import logging

logger = logging.getLogger(__name__)


def _opener_command(filepath: str) -> list[str]:
    if sys.platform == "darwin":
        return ["open", filepath]
    return ["xdg-open", filepath]


def open_file_cross_platform(filepath: str) -> bool:
    """
    Abre un archivo con la aplicación predeterminada del sistema operativo.

    - Windows: os.startfile()
    - macOS: open
    - Linux y otros Unix: xdg-open

    El proceso externo se lanza sin bloquear la UI. Si falla, registra un
    warning y devuelve False sin propagar la excepción.

    Args:
        filepath: Ruta del archivo a abrir.

    Returns:
        True si se lanzó la apertura, False en caso contrario.
    """
    path = os.path.abspath(filepath)
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        else:
            subprocess.Popen(
                _opener_command(path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return True
    except (OSError, AttributeError):
        logger.warning(
            "Could not open the file automatically: %s", path, exc_info=True
        )
        return False
