"""
Módulo models: gestión de datos y clientes.

Estructura:
- client_manager.py: CRUD de clientes y punto de entrada principal
- client_validators.py: Validaciones de formato y duplicidad
- client_duplicates.py: Detección y fusión de duplicados
"""
from .client_manager import (
    # CRUD
    get_clients,
    add_client,
    add_client_with_id,
    update_client,
    delete_client,
    get_client_by_id,
    get_client_by_id_cached,
    # Validaciones (re-exportadas desde client_validators)
    validate_name,
    validate_cif,
    validate_email,
    validate_contact,
    validate_client_data,
    client_exists_by_cif,
    client_exists_by_name,
    # Duplicados (re-exportadas desde client_duplicates)
    find_duplicate_names_in_sales,
    get_duplicate_summary,
    merge_clients_by_name,
)
