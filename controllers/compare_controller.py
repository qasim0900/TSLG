"""Controlador de estado para el modo COMPARE.

Mantiene los filtros de período A y B, gestiona presets de comparación
y auto-copia de cliente/producto de A a B. No calcula métricas ni consulta BD.
"""

from core import shift_year_iso
from domain import ComparePreset


class CompareController:
    """
    Controller de estado para el modo COMPARE.
    NO calcula métricas.
    NO consulta analysis.
    SOLO mantiene filtros y contexto.
    """

    def __init__(self):
        # Periodo A
        self.a_start = None
        self.a_end = None
        self.client_a = None
        self.product_a = None

        # Periodo B
        self.b_start = None
        self.b_end = None
        self.client_b = None
        self.product_b = None

        # Herencia A → B
        self.client_b_overridden = False
        self.product_b_overridden = False

        # Agrupación temporal
        self.grouping = "day"
        
        # FASE 1: Activación explícita de modo COMPARE
        self._compare_active = False

    # ---------------- setters ----------------

    def set_period_a(self, start=None, end=None):
        self.a_start = start
        self.a_end = end

    def set_period_b(self, start=None, end=None):
        self.b_start = start
        self.b_end = end

    def set_client_a(self, client):
        self.client_a = client
        if not self.client_b_overridden:
            self.client_b = client

    def set_client_b(self, client):
        self.client_b = client
        self.client_b_overridden = True

    def set_product_a(self, product):
        self.product_a = product
        if not self.product_b_overridden:
            self.product_b = product

    def set_product_b(self, product):
        self.product_b = product
        self.product_b_overridden = True

    def set_grouping(self, grouping):
        self.grouping = grouping

    # ---------------- helpers ----------------

    def _is_valid_period(self, start, end) -> bool:
        return bool(start and end and start <= end)

    def has_valid_periods(self) -> bool:
        return (
            self._is_valid_period(self.a_start, self.a_end)
            and self._is_valid_period(self.b_start, self.b_end)
        )
    
    # ============================================================
    # FASE 1: ACTIVACIÓN EXPLÍCITA DE MODO COMPARE
    # ============================================================
    
    def is_compare_active(self) -> bool:
        """
        Returns True if compare mode is explicitly active
        AND period B is valid.
        """
        return (
            self._compare_active
            and self._is_valid_period(self.b_start, self.b_end)
        )
    
    def activate_compare(self):
        """Activa explícitamente el modo COMPARE."""
        self._compare_active = True
    
    def deactivate_compare(self):
        """Desactiva explícitamente el modo COMPARE."""
        self._compare_active = False
    
    # ==============================
    # PRESETS
    # ==============================

    def apply_preset(self, preset: ComparePreset) -> bool:
        """
        Aplica un ComparePreset al estado actual.

        Reglas:
        - Si el preset requiere período A y no es válido → NO hace nada
        - Si falla la ejecución → NO hace nada
        - NO genera snapshot
        - NO toca UI
        """

        if preset is None:
            return False

        # Validar precondición
        if preset.requires_period_a:
            if not self._is_valid_period(self.a_start, self.a_end):
                return False

        # Snapshot del estado actual (rollback implícito)
        prev_state = (
            self.a_start, self.a_end,
            self.b_start, self.b_end,
            self.client_b, self.product_b,
            self.client_b_overridden,
            self.product_b_overridden,
            self.grouping,
        )

        try:
            preset.apply_func(self)
            return True
        except Exception:
            # Rollback defensivo
            (
                self.a_start, self.a_end,
                self.b_start, self.b_end,
                self.client_b, self.product_b,
                self.client_b_overridden,
                self.product_b_overridden,
                self.grouping,
            ) = prev_state
            return False
  
    def clear_comparison(self):
        self.b_start = None
        self.b_end = None
        self.client_b = self.client_a
        self.product_b = self.product_a
        self.client_b_overridden = False
        self.product_b_overridden = False

    def clear(self):
        """Limpia TODO el estado de comparación (período A y B)."""
        self.a_start = None
        self.a_end = None
        self.client_a = None
        self.product_a = None

        self.b_start = None
        self.b_end = None
        self.client_b = None
        self.product_b = None

        self.client_b_overridden = False
        self.product_b_overridden = False

        self.grouping = "day"
        self._compare_active = False
