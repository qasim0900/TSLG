"""Diálogos de selección y guardado de archivos (FilePicker Flet 0.82)."""

import flet as ft
from typing import Optional, List


async def pick_single_file(
    page: ft.Page,
    allowed_extensions: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Abre un FilePicker para seleccionar UN archivo (patrón oficial Flet 0.80.5).
    Devuelve la ruta del archivo o None si el usuario cancela.
    
    FLUJO:
    1. Crea una NUEVA instancia de FilePicker (sin reutilizar)
    2. Llama pickup_files() de forma asíncrona (await)
    3. pick_files() retorna una LISTA de FilePickerFile (pueden ser vacía)
    4. Accede al primer archivo: result[0].path (es un objeto con propiedades id, name, size, path)
    5. Devuelve la ruta completa del archivo seleccionado o None
    
    Notas:
    - FilePicker es un Service, no un Control (NO se agrega a overlay)
    - Sin callbacks legacy (on_result=...) como en versiones viejas
    - Sin estado persistente: cada llamada es independiente
    - Si allowed_extensions=["csv", "xlsx"], solo muestra esos tipos
    """
    # 1️⃣ Crear instancia nueva (NO reutilizar como atributo)
    picker = ft.FilePicker()

    # 2️⃣ Llamar async/await (patrón oficial)
    result = await picker.pick_files(
        allow_multiple=False,  # Solo 1 archivo
        allowed_extensions=allowed_extensions,
    )

    # 3️⃣ Validar resultado (lista vacía = usuario canceló)
    if not result or len(result) == 0:
        return None

    # 4️⃣ Retornar ruta del primer (único) archivo
    return result[0].path


async def save_html_file(
    page: ft.Page,
    default_name: str,
) -> Optional[str]:
    """
    Abre un diálogo Guardar archivo HTML (patrón oficial Flet 0.80.5).
    Devuelve la ruta completa del archivo o None si el usuario cancela.
    
    FLUJO:
    1. Crea una NUEVA instancia de FilePicker (sin reutilizar)
    2. Llama save_file() de forma asíncrona (await)
    3. save_file() retorna DIRECTAMENTE el path (string) o None (no es un objeto)
    4. Valida que el usuario no haya cancelado
    5. Devuelve la ruta completa o None
    
    Parámetros:
    - page: para acceso a servicios (aunque FilePicker no necesita overlay)
    - default_name: nombre sugerido en el diálogo (ej: "Informe_Ventas_20260208.html")
    
    Notas:
    - FilePicker es un Service, no un Control (NO se agrega a overlay)
    - allowed_extensions=["html"] fuerza extensión .html
    - Sin estado persistente: cada llamada es independiente
    - Usuario puede cambiar nombre y ubicación en el diálogo
    """
    # 1️⃣ Crear instancia nueva (NO reutilizar como atributo)
    picker = ft.FilePicker()

    # 2️⃣ Llamar async/await (patrón oficial)
    result = await picker.save_file(
        file_name=default_name,
        allowed_extensions=["html"],  # Fuerza extensión .html
    )

    # 3️⃣ Validar resultado (None = usuario canceló)
    # IMPORTANTE: save_file retorna STRING o None (no un objeto)
    if not result:
        return None

    # 4️⃣ Retornar ruta (ya está validada por el sistema)
    return result
