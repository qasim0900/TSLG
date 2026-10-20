"""
Módulo para detección y fusión de clientes duplicados.
Maneja la lógica de encontrar y fusionar clientes con nombres duplicados.
"""
from core.db import get_connection
from utils.formatting import pluralize


def find_duplicate_names_in_sales():
    """
    Encuentra nombres de clientes duplicados en la tabla de ventas.
    
    Returns:
        Lista de diccionarios con información de duplicados:
        [{'name': 'Empresa X', 'client_ids': ['X1234', 'X5678'], 'count': 2}, ...]
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Buscar nombres que aparecen con diferentes client_id
    cursor.execute("""
        SELECT client_name, GROUP_CONCAT(DISTINCT client_id) as ids, COUNT(DISTINCT client_id) as id_count
        FROM sales
        GROUP BY LOWER(client_name)
        HAVING COUNT(DISTINCT client_id) > 1
        ORDER BY id_count DESC
    """)
    
    duplicates = []
    for row in cursor.fetchall():
        duplicates.append({
            'name': row[0],
            'client_ids': row[1].split(','),
            'count': row[2]
        })
    
    conn.close()
    return duplicates


def _get_client_data_for_merge(cursor, client_ids):
    """
    Obtiene datos de clientes para el proceso de fusión.
    
    Args:
        cursor: Cursor de base de datos
        client_ids: Lista de IDs a verificar
    
    Returns:
        Tupla (ids_with_data, ids_without_data, client_data_map)
    """
    ids_with_data = []
    ids_without_data = []
    client_data_map = {}
    
    for client_id in client_ids:
        cursor.execute("SELECT * FROM clients WHERE id = ?", (client_id,))
        client_row = cursor.fetchone()
        
        if client_row:
            # Tiene datos: (id, name, cif, address, contact_person, email)
            ids_with_data.append(client_id)
            client_data_map[client_id] = {
                'name': client_row[1],
                'cif': client_row[2],
                'address': client_row[3],
                'contact_person': client_row[4],
                'email': client_row[5]
            }
        else:
            ids_without_data.append(client_id)
    
    return ids_with_data, ids_without_data, client_data_map


def _combine_client_data(primary_data, other_data):
    """
    Combina datos de clientes, llenando campos vacíos del primario con datos del otro.
    
    Args:
        primary_data: Diccionario con datos del cliente principal
        other_data: Diccionario con datos del otro cliente
    
    Returns:
        primary_data modificado
    """
    for field in ['cif', 'address', 'contact_person', 'email']:
        if (not primary_data[field] or primary_data[field] == '-') and other_data[field] and other_data[field] != '-':
            primary_data[field] = other_data[field]
    return primary_data


def _merge_single_duplicate(cursor, dup):
    """
    Fusiona un grupo de clientes duplicados.
    
    Args:
        cursor: Cursor de base de datos
        dup: Diccionario con info del duplicado {'name', 'client_ids', 'count'}
    
    Returns:
        Lista de strings con detalles de la fusión
    """
    name = dup['name']
    ids = dup['client_ids']
    details = []
    
    # Obtener datos de cada ID
    ids_with_data, ids_without_data, client_data_map = _get_client_data_for_merge(cursor, ids)
    
    # Determinar el ID principal (priorizar el que tiene datos)
    if ids_with_data:
        primary_id = ids_with_data[0]
        primary_data = client_data_map[primary_id]
        
        # Si hay varios con datos, combinar información
        for other_id in ids_with_data[1:]:
            other_data = client_data_map[other_id]
            _combine_client_data(primary_data, other_data)
        
        # Actualizar el registro principal con datos combinados
        cursor.execute(
            """UPDATE clients SET name=?, cif=?, address=?, contact_person=?, email=? WHERE id=?""",
            (primary_data['name'], primary_data['cif'], primary_data['address'], 
             primary_data['contact_person'], primary_data['email'], primary_id)
        )
        
        secondary_ids = ids_without_data + ids_with_data[1:]
    else:
        # Ninguno tiene datos, usar el primer ID
        primary_id = ids[0]
        secondary_ids = ids[1:]
        cursor.execute(
            "INSERT OR IGNORE INTO clients (id, name, cif) VALUES (?, ?, '-')",
            (primary_id, name)
        )
    
    # Actualizar ventas y eliminar registros secundarios
    for sec_id in secondary_ids:
        cursor.execute(
            "UPDATE sales SET client_id = ? WHERE client_id = ?",
            (primary_id, sec_id)
        )
        rows_updated = cursor.rowcount

        cursor.execute(
            "UPDATE leads SET client_id = ? WHERE client_id = ?",
            (primary_id, sec_id)
        )
        cursor.execute(
            "UPDATE funnel_events SET client_id = ? WHERE client_id = ?",
            (primary_id, sec_id)
        )

        cursor.execute("DELETE FROM clients WHERE id = ?", (sec_id,))
        
        details.append(f"'{name}': {sec_id} -> {primary_id} ({pluralize(rows_updated, 'sale')})")
    
    return details


def merge_clients_by_name(invalidate_cache_callback=None):
    """
    Fusiona clientes duplicados por nombre en la tabla de ventas.
    PRIORIZA el client_id que ya tiene datos en la tabla clients.
    Si ninguno tiene datos, usa el primer ID.
    Si varios tienen datos, combina la información.
    
    Args:
        invalidate_cache_callback: Función para invalidar caché (opcional)
    
    Returns:
        Tupla (cantidad_fusionados, detalles)
        detalles es lista de strings describiendo cada fusión
    """
    duplicates = find_duplicate_names_in_sales()
    
    if not duplicates:
        return 0, ["No duplicates by name were found."]
    
    conn = get_connection()
    cursor = conn.cursor()
    
    merged_count = 0
    all_details = []
    
    try:
        cursor.execute("BEGIN")
        for dup in duplicates:
            details = _merge_single_duplicate(cursor, dup)
            all_details.extend(details)
            merged_count += len(details)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    
    # Invalidar caché si se proporcionó callback
    if invalidate_cache_callback:
        invalidate_cache_callback()
    
    return merged_count, all_details


def get_duplicate_summary():
    """
    Obtiene un resumen de los duplicados encontrados para mostrar al usuario.
    
    Returns:
        Tupla (total_duplicados, mensaje_resumen)
    """
    duplicates = find_duplicate_names_in_sales()
    
    if not duplicates:
        return 0, "No clients share the same name."
    
    total = sum(d['count'] - 1 for d in duplicates)  # -1 porque uno se mantiene
    
    # Crear resumen de los primeros 5
    summary_lines = []
    for dup in duplicates[:5]:
        summary_lines.append(f"• {dup['name']}: {dup['count']} different IDs")
    
    if len(duplicates) > 5:
        summary_lines.append(f"... and {len(duplicates) - 5} more")
    
    summary = "\n".join(summary_lines)
    
    return total, f"Found {pluralize(len(duplicates), 'client name')} used by more than one ID:\n\n{summary}"
