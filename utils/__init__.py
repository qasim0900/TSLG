# Archivo vacío para convertir utils/ en paquete Python


def normalize_text(value):
    """Normaliza texto: None → '', strip whitespace. Seguro para comparaciones y BD."""
    return (value or "").strip()