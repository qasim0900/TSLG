"""
Controlador de Filtros - Responsabilidad: Fachada de Dominio

Este controlador es la FACHADA CENTRALIZADA para gestionar todos los filtros:
- Fecha (inicio y fin)
- Cliente
- Producto

Proporciona UNA SOLA INTERFAZ para acceder a lógica de filtros desde cualquier
componente sin duplicación de responsabilidades.

NOTA IMPORTANTE: FilterController y Date FilterController comparten métodos para
rangos rápidos (last_n_days, current_month_full, etc.). Esta duplicación es CONOCIDA y
CONTROLADA:

1. DateFilterController: UX/UI - maneja eventos UI y prepara datos para mostrar
2. FilterController: Fachada de dominio - acceso centralizado para consultas

NO hacer refactor ahora. Mantener así hasta consolidar FilterController como
la única fachada de acceso desde toda la aplicación.
"""

from typing import Optional, Tuple, Dict, Callable
from techset_leadgen.utils.date_range import normalize_iso, validate_range, last_n_days, current_month_full, current_year_full
from techset_leadgen.domain.filter_options import ALL_FILTER_KEY


class FilterController:
    """
    Gestiona el estado de TODOS los filtros:
    - Fecha (inicio y fin)
    - Cliente
    - Producto
    
    Proporciona métodos para:
    - Actualizar filtros individuales
    - Validar estado
    - Obtener parámetros listos para consultas
    - Limpiar filtros
    
    FASE 0: Infraestructura reactiva
    - on_change: Callback opcional para sincronización UI
    - suspend/resume: Batching de notificaciones
    """
    
    def __init__(self):
        """Inicializa el controlador de filtros."""
        self.start_date: Optional[str] = None
        self.end_date: Optional[str] = None
        self.client_name: Optional[str] = None
        self.product_type: Optional[str] = None
        
        # ============================================================
        # FASE 0: INFRAESTRUCTURA REACTIVA
        # ============================================================
        self.on_change: Optional[Callable[[], None]] = None
        self._notifications_suspended: bool = False
        self._pending_notification: bool = False
    
    # ============================================================
    #   SETTERS DE FILTROS (FASE 0: con notificaciones reactivas)
    # ============================================================
    
    def set_start_date(self, value: Optional[str]) -> Optional[str]:
        """Establece y normaliza la fecha de inicio."""
        iso = normalize_iso(value)
        
        # Defensivo: no notificar si valor no cambia
        if self.start_date == iso:
            return iso if iso else "–"
        
        self.start_date = iso
        self._trigger_on_change()
        return iso if iso else "–"
    
    def set_end_date(self, value: Optional[str]) -> Optional[str]:
        """Establece y normaliza la fecha de fin."""
        iso = normalize_iso(value)
        
        # Defensivo: no notificar si valor no cambia
        if self.end_date == iso:
            return iso if iso else "–"
        
        self.end_date = iso
        self._trigger_on_change()
        return iso if iso else "–"
    
    def set_client(self, value: Optional[str]) -> Optional[str]:
        """Establece el filtro de cliente."""
        normalized = value.strip() if value and value != ALL_FILTER_KEY else None
        
        # Defensivo: no notificar si valor no cambia
        if self.client_name == normalized:
            return normalized
        
        self.client_name = normalized
        self._trigger_on_change()
        return normalized
    
    def set_product(self, value: Optional[str]) -> Optional[str]:
        """Establece el filtro de tipo de producto."""
        normalized = value.strip() if value and value != ALL_FILTER_KEY else None
        
        # Defensivo: no notificar si valor no cambia
        if self.product_type == normalized:
            return normalized
        
        self.product_type = normalized
        self._trigger_on_change()
        return normalized
    
    # ============================================================
    #   RANGOS RÁPIDOS (FASE 0: con batching)
    # ============================================================
    
    def apply_quick_range(self, days: int) -> Tuple[str, str]:
        """Aplica un rango rápido de X días (ej. 7, 30)."""
        start_iso, end_iso = last_n_days(days)
        
        # Batching: una sola notificación para ambos cambios
        self.suspend_notifications()
        self._assign_filters(start_date=start_iso, end_date=end_iso)
        self.resume_notifications()
        
        return start_iso, end_iso
    
    def apply_month_range(self) -> Tuple[str, str]:
        """Aplica rango del mes actual."""
        start_iso, end_iso = current_month_full()
        
        # Batching: una sola notificación para ambos cambios
        self.suspend_notifications()
        self._assign_filters(start_date=start_iso, end_date=end_iso)
        self.resume_notifications()
        
        return start_iso, end_iso
    
    def apply_year_range(self) -> Tuple[str, str]:
        """Aplica rango del año actual."""
        start_iso, end_iso = current_year_full()
        
        # Batching: una sola notificación para ambos cambios
        self.suspend_notifications()
        self._assign_filters(start_date=start_iso, end_date=end_iso)
        self.resume_notifications()
        
        return start_iso, end_iso
    
    # ============================================================
    #   VALIDACIÓN
    # ============================================================
    
    def validate(self) -> Tuple[bool, Optional[str]]:
        """
        Valida que start_date <= end_date.
        Retorna: (es_válido, mensaje_error_o_none)
        """
        if not self.start_date and not self.end_date:
            return True, None  # Sin filtro es válido
        
        if self.start_date and not self.end_date:
            return True, None  # Solo inicio es válido
        
        if not self.start_date and self.end_date:
            return True, None  # Solo fin es válido
        
        # Ambos definidos, validar rango
        return validate_range(self.start_date, self.end_date)
    
    def has_active_filter(self) -> bool:
        """Retorna True si hay algún filtro activo."""
        return any([
            self.start_date is not None,
            self.end_date is not None,
            self.client_name is not None,
            self.product_type is not None,
        ])
    
    # ============================================================
    #   ACCESO A PARÁMETROS
    # ============================================================
    
    def get_filter_params(self) -> Dict[str, Optional[str]]:
        """
        Retorna diccionario con TODOS los parámetros de filtro.
        Formato: {
            'start_date': '2025-12-01',
            'end_date': '2025-12-10',
            'client_name': 'TechNova',
            'product_type': 'Servicio'
        }
        """
        return {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'client_name': self.client_name,
            'product_type': self.product_type,
        }
    
    # ============================================================
    #   RESETEO (FASE 0: con batching)
    # ============================================================
    
    def clear(self) -> None:
        """Limpia TODOS los filtros."""
        # Batching: una sola notificación para todos los cambios
        self.suspend_notifications()
        self._assign_filters(start_date=None, end_date=None, client_name=None, product_type=None)
        self.resume_notifications()
    
    def clear_dates(self) -> None:
        """Limpia solo los filtros de fecha."""
        # Batching: una sola notificación para ambos cambios
        self.suspend_notifications()
        self._assign_filters(start_date=None, end_date=None)
        self.resume_notifications()
    
    # ============================================================
    #   FASE 0: INFRAESTRUCTURA REACTIVA
    # ============================================================
    
    def suspend_notifications(self) -> None:
        """Suspende temporalmente las notificaciones on_change."""
        self._notifications_suspended = True
    
    def resume_notifications(self) -> None:
        """
        Reanuda las notificaciones on_change.
        Si hubo cambios pendientes, dispara on_change una sola vez.
        """
        self._notifications_suspended = False
        
        if self._pending_notification:
            self._pending_notification = False
            if self.on_change:
                self.on_change()
    
    def set_date_range(self, start: Optional[str], end: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """
        Establece rango de fechas con batching automático.
        Una sola notificación on_change para ambos valores.
        
        Returns:
            Tuple con (start_normalizado, end_normalizado)
        """
        self.suspend_notifications()
        start_iso = self.set_start_date(start)
        end_iso = self.set_end_date(end)
        self.resume_notifications()
        
        return start_iso, end_iso
    
    def _assign_filters(self, **values: Optional[str]) -> None:
        changed = False
        for name, value in values.items():
            if getattr(self, name) != value:
                setattr(self, name, value)
                changed = True
        if changed:
            self._trigger_on_change()

    def _trigger_on_change(self) -> None:
        """
        Dispara on_change si está configurado y notificaciones activas.
        Si notificaciones suspendidas, marca pending.
        """
        if self._notifications_suspended:
            self._pending_notification = True
        else:
            if self.on_change:
                self.on_change()
