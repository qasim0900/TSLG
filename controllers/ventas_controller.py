"""
Controlador para la vista de Ventas.
Maneja el estado de la vista y orquesta las llamadas a servicios.
"""

import logging
import time

logger = logging.getLogger(__name__)
from typing import Optional, Tuple
from controllers.filter_controller import FilterController

from services.snapshot_builder import build_sales_snapshot
from services.period_data_builder import build_period_data
from domain.analysis_snapshot import (
    AnalysisSnapshot,
    AnalysisMode,
    TimeGrouping,
    Filters,
)

class VentasController:
    """
    Orquesta la lógica de la vista de Ventas:
    - Gestiona filtros (delegando a FilterController)
    - Gestiona estado de vista (summary vs both)
    - Prepara datos para componentes
    - Coordina con servicios
    """
    
    def __init__(self):
        """
        Inicializa el controlador.
        
        Args:
            page: Página de Flet para acceso a theme_mode
        """
        self.filter_controller = FilterController()
        self.current_view_mode: str = "both"  # "both" o "summary"
        
        # ============================================================
        # MEJORA A: SNAPSHOT CACHING
        # ============================================================
        self._snapshot_cache = {}  # Cache de snapshots: {key: snapshot}
        self._dataset_version = 0  # Contador que incrementa en cada import
        self._last_snapshot_key = None  # Última clave usada
    
    # ============================================================
    #   GESTIÓN DE FILTROS (Delegación)
    # ============================================================
    
    def set_start_date(self, value: Optional[str]) -> Optional[str]:
        """Establece la fecha de inicio."""
        return self.filter_controller.set_start_date(value)
    
    def set_end_date(self, value: Optional[str]) -> Optional[str]:
        """Establece la fecha de fin."""
        return self.filter_controller.set_end_date(value)
    
    def set_client(self, client_name: Optional[str]) -> None:
        """Establece el filtro de cliente."""
        self.filter_controller.set_client(client_name)
    
    def set_product(self, product_type: Optional[str]) -> None:
        """Establece el filtro de producto."""
        self.filter_controller.set_product(product_type)
    
    def apply_quick_range(self, days: int) -> Tuple[str, str]:
        """Aplica rango rápido de X días."""
        return self.filter_controller.apply_quick_range(days)
    
    def apply_month_range(self) -> Tuple[str, str]:
        """Aplica rango del mes actual."""
        return self.filter_controller.apply_month_range()
    
    def apply_year_range(self) -> Tuple[str, str]:
        """Aplica rango del año actual."""
        return self.filter_controller.apply_year_range()
    
    def validate_filters(self) -> Tuple[bool, Optional[str]]:
        """Valida los filtros activos."""
        return self.filter_controller.validate()
    
    def has_active_filters(self) -> bool:
        """Retorna True si hay filtros activos."""
        return self.filter_controller.has_active_filter()
    
    def clear_filters(self) -> None:
        """Limpia todos los filtros."""
        self.filter_controller.clear()
    
    def get_filter_params(self):
        """Retorna diccionario con todos los parámetros de filtro."""
        return self.filter_controller.get_filter_params()
    
    def get_filter_display_text(self) -> str:
        """
        Retorna texto legible para mostrar filtros activos.
        Ej: "Fecha: 2025-12-01 a 2025-12-10 | Cliente: TechNova | Producto: Software"
        """
        params = self.filter_controller.get_filter_params()
        parts = []
        
        # Fecha
        start = params['start_date'] or 'start'
        end = params['end_date'] or 'end'
        parts.append(f"Dates: {start} to {end}")
        
        # Cliente
        if params['client_name']:
            parts.append(f"Client: {params['client_name']}")
        
        # Producto
        if params['product_type']:
            parts.append(f"Product: {params['product_type']}")
        
        return " | ".join(parts)
    
    # ============================================================
    #   MEJORA A: SNAPSHOT CACHING - KEY GENERATION
    # ============================================================
    
    def build_snapshot_key(self, date_start: str, date_end: str, client_name: str, product_type: str, grouping: str = "day") -> str:
        """
        Construye una clave determinista para cachear snapshots.
        
        Incluye: fecha range + cliente + producto + versión dataset + agrupación
        
        Args:
            date_start: ISO format (YYYY-MM-DD)
            date_end: ISO format (YYYY-MM-DD)
            client_name: Nombre del cliente (o None)
            product_type: Tipo de producto (o None)
            grouping: Agrupación temporal ("day", "week", "month", etc)
        
        Returns:
            String determinista para usar como clave de cache
        """
        import hashlib
        
        # Normalizar None a "all"
        client_str = client_name or "all"
        product_str = product_type or "all"
        
        # Construir componentes de clave
        key_components = f"{date_start}|{date_end}|{client_str}|{product_str}|{grouping}|v{self._dataset_version}"
        
        # Usar hash para compactar
        key_hash = hashlib.md5(key_components.encode(), usedforsecurity=False).hexdigest()
        
        return key_hash
    
    def invalidate_snapshot_cache(self) -> None:
        """Invalida TODO el cache de snapshots."""
        self._snapshot_cache.clear()
        self._dataset_version += 1
        self._last_snapshot_key = None
    
    # ============================================================
    #   GESTIÓN DE VISTA
    # ============================================================
    
    def set_view_mode(self, mode: str) -> None:
        """
        Establece el modo de vista.
        
        Args:
            mode: "summary" (tabla + evolución) | "both" (tabla + gráficos + evolución)
        """
        if mode in ("summary", "both"):
            self.current_view_mode = mode
    
    # ============================================================
    #   ESTADÍSTICAS GENERALES
    # ============================================================
    
    # ============================================================
    #   SNAPSHOT (INTEGRACIÓN NUEVA)
    # ============================================================
    
    def get_sales_snapshot(
    self,
    grouping: str = "day",
    compare_controller=None,
) -> Optional[AnalysisSnapshot]:

        # ============================================================
        # NORMALIZACIÓN DEFENSIVA
        # ============================================================
        valid_groupings = {"day", "week", "month", "quarter", "year"}
    
        if isinstance(grouping, str):
            grouping = grouping.lower()
        else:
            grouping = "day"
    
        if grouping not in valid_groupings:
            grouping = "day"
    
        # ============================================================
        # OBTENER PARÁMETROS ACTUALES
        # ============================================================
        params = self.get_filter_params()
    
        key = self.build_snapshot_key(
            date_start=params["start_date"],
            date_end=params["end_date"],
            client_name=params["client_name"],
            product_type=params["product_type"],
            grouping=grouping,
        )
    
        # ============================================================
        # 🔥 CACHE REAL SOLO EN MODO NORMAL
        # ============================================================
        is_compare = compare_controller is not None and compare_controller.is_compare_active()
    
        if not is_compare and key in self._snapshot_cache:
            logger.debug("CACHE HIT: Returning cached snapshot")
            return self._snapshot_cache[key]
    
        # ============================================================
        # MEDICIÓN DE RENDIMIENTO
        # ============================================================
        PERF_LOGGING = True
        t_total_start = time.perf_counter() if PERF_LOGGING else 0
    
        try:
            from analysis import get_sales_summary
    
            # ============================================================
            # =================== MODO NORMAL ============================
            # ============================================================
            if not is_compare:
            
                start_date = self.filter_controller.start_date
                end_date = self.filter_controller.end_date
                client_name = self.filter_controller.client_name
                product_type = self.filter_controller.product_type
    
                df_a, _ = get_sales_summary(
                    start_date=start_date,
                    end_date=end_date,
                    client_name=client_name,
                    product_type=product_type,
                )
    
                if df_a is None or df_a.is_empty():
                    return None
    
                period_a_data = build_period_data(
                    df_summary=df_a,
                    start_date=start_date,
                    end_date=end_date,
                    grouping=grouping,
                    client_name=client_name,
                    product_type=product_type,
                )
    
                filters_a = Filters(
                    date_start=start_date,
                    date_end=end_date,
                    client_name=client_name,
                    product_type=product_type,
                )
    
                snapshot = build_sales_snapshot(
                    mode=AnalysisMode.NORMAL,
                    grouping=TimeGrouping(grouping),
                    filters_a=filters_a,
                    period_a_data=period_a_data,
                    app_version="1.0",
                )
    
            # ============================================================
            # =================== MODO COMPARE ===========================
            # ============================================================
            else:
            
                df_a, _ = get_sales_summary(
                    start_date=self.filter_controller.start_date,
                    end_date=self.filter_controller.end_date,
                    client_name=self.filter_controller.client_name,
                    product_type=self.filter_controller.product_type,
                )
    
                df_b, _ = get_sales_summary(
                    start_date=compare_controller.b_start,
                    end_date=compare_controller.b_end,
                    client_name=compare_controller.client_b,
                    product_type=compare_controller.product_b,
                )
    
                if df_a is None or df_b is None:
                    return None
    
                period_a_data = build_period_data(
                    df_summary=df_a,
                    start_date=self.filter_controller.start_date,
                    end_date=self.filter_controller.end_date,
                    grouping=grouping,
                    client_name=self.filter_controller.client_name,
                    product_type=self.filter_controller.product_type,
                    is_compare=True,
                )
    
                period_b_data = build_period_data(
                    df_summary=df_b,
                    start_date=compare_controller.b_start,
                    end_date=compare_controller.b_end,
                    grouping=grouping,
                    client_name=compare_controller.client_b,
                    product_type=compare_controller.product_b,
                    is_compare=True,
                )
    
                filters_a = Filters(
                    date_start=self.filter_controller.start_date,
                    date_end=self.filter_controller.end_date,
                    client_name=self.filter_controller.client_name,
                    product_type=self.filter_controller.product_type,
                )
    
                filters_b = Filters(
                    date_start=compare_controller.b_start,
                    date_end=compare_controller.b_end,
                    client_name=compare_controller.client_b,
                    product_type=compare_controller.product_b,
                )
    
                snapshot = build_sales_snapshot(
                    mode=AnalysisMode.COMPARE,
                    grouping=TimeGrouping(grouping),
                    filters_a=filters_a,
                    period_a_data=period_a_data,
                    period_b_data=period_b_data,
                    filters_b=filters_b,
                    app_version="1.0",
                )
    
            # ============================================================
            # VALIDACIÓN Y CACHE STORE
            # ============================================================
            if snapshot and snapshot.validate():
            
                if not is_compare:
                    self._snapshot_cache[key] = snapshot
                    self._last_snapshot_key = key
                    logger.debug("CACHE STORE: Snapshot stored")
    
                if PERF_LOGGING:
                    logger.debug(
                        "[PERF][SNAPSHOT] TOTAL: %.4fs",
                        time.perf_counter() - t_total_start,
                    )
    
                return snapshot
    
            return None
    
        except Exception:
            logger.exception("Error generando AnalysisSnapshot")
            return None
