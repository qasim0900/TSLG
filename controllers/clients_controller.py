"""
Controlador de lógica para gestión de clientes.
Separa la lógica de negocio de la UI.
"""
from models.client_manager import (
    add_client,
    add_client_with_id,
    get_clients,
    get_client_by_id,
    get_client_by_id_cached,
    update_client,
    delete_client,
    validate_name,
    validate_cif,
    validate_email,
    validate_contact,
    client_exists_by_cif,
    client_exists_by_name,
    find_duplicate_names_in_sales,
    merge_clients_by_name,
    get_duplicate_summary,
)
from analysis import get_all_clients_with_sales_data, get_sales_with_client_info
from utils import normalize_text
from utils.formatting import pluralize


class ClientsController:
    """Controlador centralizado para operaciones de clientes."""
    
    @staticmethod
    def get_all_clients_with_sales():
        """Obtiene todos los clientes con sus datos de ventas."""
        return get_all_clients_with_sales_data()
    
    @staticmethod
    def find_client(client_id):
        """
        Busca un cliente por ID.
        Primero en caché, luego en datos de ventas.
        Retorna tupla (client_id, name, cif, address, contact_person, email) o None.
        """
        # Intentar desde caché (más rápido)
        client = get_client_by_id_cached(client_id)
        if client:
            return client
        
        # Si no existe en clients table, buscar en datos de ventas
        all_clients_data = get_all_clients_with_sales_data()
        client_data = next(
            (c for c in all_clients_data if c['client_id'] == client_id),
            None
        )
        
        if client_data:
            return (
                client_data['client_id'],
                client_data['name'],
                client_data['cif'],
                client_data['address'],
                client_data['contact_person'],
                client_data['email']
            )
        
        return None
    
    @staticmethod
    def validate_client_fields(name, cif, email, contact):
        """
        Valida todos los campos de un cliente.
        Retorna (es_válido, mensaje_error).
        """
        if not validate_name(name):
            return False, "The name must have at least 2 characters."
        
        if not validate_cif(cif):
            return False, "The tax ID (CIF/NIF) must have 7 to 12 letters or digits."
        
        if not validate_email(email):
            return False, "Enter a valid email address."
        
        if not validate_contact(contact):
            return False, "The contact name must have at least 2 characters."
        
        return True, ""
    
    @staticmethod
    def create_client(name, cif, address, contact, email):
        """Crea un nuevo cliente. Retorna (éxito, mensaje)."""
        cif = normalize_text(cif).upper()
        is_valid, error_msg = ClientsController.validate_client_fields(
            name, cif, email, contact
        )
        
        if not is_valid:
            return False, error_msg
        
        try:
            # Verificar duplicidad de CIF
            if cif and client_exists_by_cif(cif):
                return False, f"A client with tax ID '{cif}' already exists."
            
            # Verificar duplicidad de nombre
            if client_exists_by_name(name):
                return False, f"A client named '{name}' already exists."
            
            add_client(name, cif, address, contact, email)
            return True, "✔ Client added."
        except Exception as e:
            return False, f"Could not add the client: {str(e)}"
    
    @staticmethod
    def update_client_info(client_id, name, cif, address, contact, email):
        """Actualiza información de un cliente. Retorna (éxito, mensaje)."""
        # Normalizar CIF antes de validar y guardar
        cif = normalize_text(cif).upper()
        is_valid, error_msg = ClientsController.validate_client_fields(
            name, cif, email, contact
        )
        
        if not is_valid:
            return False, error_msg
        
        try:
            # Verificar duplicidad de CIF (excluyendo el cliente actual)
            if cif and client_exists_by_cif(cif, exclude_id=client_id):
                return False, f"Another client with tax ID '{cif}' already exists."
            
            # Verificar duplicidad de nombre (excluyendo el cliente actual)
            if client_exists_by_name(name, exclude_id=client_id):
                return False, f"Another client named '{name}' already exists."
            
            # Si el cliente no existe en la tabla, crearlo MANTENIENDO el ID original
            existing = get_client_by_id(client_id)
            if not existing:
                add_client_with_id(client_id, name, cif, address, contact, email)
            else:
                update_client(client_id, name, cif, address, contact, email)
            
            return True, "✔ Client updated."
        except Exception as e:
            return False, f"Could not update the client: {str(e)}"
    
    @staticmethod
    def remove_client(client_id):
        """Elimina un cliente. Retorna (éxito, mensaje)."""
        try:
            client_info = ClientsController.find_client(client_id)
            if not client_info:
                return False, "Client not found."
            
            client_name = client_info[1]
            delete_client(client_id)
            return True, f"✔ {client_name} was deleted."
        except Exception as e:
            return False, f"Could not delete the client: {str(e)}"
    
    @staticmethod
    def get_client_sales_stats(client_id):
        """
        Obtiene estadísticas de ventas de un cliente.
        Retorna dict con total_sales, total_amount, avg_amount, sales_list.
        """
        all_sales = get_sales_with_client_info()
        client_sales = [s for s in all_sales if s['client_id'] == client_id]
        
        total_sales = len(client_sales)
        total_amount = sum(float(s['price']) for s in client_sales) if client_sales else 0
        avg_amount = total_amount / total_sales if total_sales > 0 else 0
        
        return {
            'total_sales': total_sales,
            'total_amount': total_amount,
            'avg_amount': avg_amount,
            'sales': client_sales[:10]  # Últimas 10 ventas
        }
    
    @staticmethod
    def search_clients_by_name(search_term: str):
        """
        Busca clientes por nombre (búsqueda parcial, case-insensitive).
        Retorna lista de clientes que coinciden con el término de búsqueda.
        """
        if not search_term or search_term.strip() == "":
            return ClientsController.get_all_clients_with_sales()
        
        search_lower = search_term.lower().strip()
        all_clients = ClientsController.get_all_clients_with_sales()
        
        return [
            client for client in all_clients
            if search_lower in client['name'].lower()
        ]

    @staticmethod
    def get_duplicates_info():
        """
        Obtiene información sobre clientes duplicados por nombre.
        Retorna (cantidad, mensaje_resumen).
        """
        return get_duplicate_summary()
    
    @staticmethod
    def merge_duplicate_clients():
        """
        Fusiona clientes duplicados por nombre.
        Retorna (éxito, mensaje).
        """
        try:
            merged_count, details = merge_clients_by_name()
            
            if merged_count == 0:
                return True, "No duplicate clients to merge."
            
            return True, f"✔ Merged {pluralize(merged_count, 'duplicate client')}."
        except Exception as e:
            return False, f"Could not merge clients: {str(e)}"
