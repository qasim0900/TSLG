# controllers/date_filter_controller.py

"""
Controlador de Filtros de Fecha - Responsabilidad: UX / UI

Este controlador gestiona LA EXPERIENCIA DE USUARIO en torno a filtros de fecha:
- Procesa eventos de UI (clicks en rangos rápidos, cambios de fecha)
- Aplica rangos rápidos (7 días, 30 días, mes, año…)
- Normaliza fechas para mostrar en UI
- Valida rangos de usuario

NOTA IMPORTANTE: DateFilterController y FilterController comparten métodos para
rangos rápidos (last_n_days, current_month_full, etc.). Esta duplicación es CONOCIDA y
CONTROLADA:

1. DateFilterController: UX/UI - maneja eventos UI y prepara datos para mostrar
2. FilterController: Fachada de dominio - acceso centralizado para consultas

NO hacer refactor ahora. Mantener así hasta que FilterController se consolide
como la única fachada de acceso.

NO contiene lógica de negocio pura.
NO importa Flet (los eventos vienen del exterior).
"""

from datetime import date, datetime
from typing import Optional, Tuple

from core.date_range import (
    last_n_days,
    last_n_months,

    current_week_full,          # semana completa (lunes-domingo)
    current_month_full,         # mes completo
    current_year_full,          # año completo

    current_month_to_date,
    current_quarter_to_date,
    current_semester_to_date,
    current_year_to_date,

    normalize_iso,
    validate_range,
)


class DateFilterController:
    def __init__(self) -> None:
        self.start_date: Optional[str] = None
        self.end_date: Optional[str] = None

    # ------------------------------------------------------------
    #  ESTABLECER FECHAS
    # ------------------------------------------------------------
    def set_date(self, which: str, value: Optional[date | datetime | str]) -> Optional[str]:
        """
        Recibe una fecha (date/datetime/string) y la normaliza a ISO.
        Devuelve el texto ya formateado para mostrar ("YYYY-MM-DD" o "–").
        """
        iso = normalize_iso(value)

        if which == "start":
            self.start_date = iso
        elif which == "end":
            self.end_date = iso

        if iso is None:
            return "–"
        return iso

    # ------------------------------------------------------------
    #  RANGOS RÁPIDOS
    # ------------------------------------------------------------
    def apply_last_n_months(self, months: int) -> Tuple[str, str]:
        """Aplica un rango de últimos N meses."""
        start, end = last_n_months(months)
        self.start_date = start
        self.end_date = end
        return start, end

    def apply_current_week(self) -> Tuple[str, str]:
        """
        Aplica rango desde lunes de esta semana hasta hoy.
        """
        start, _ = current_week_full()
        end = date.today().strftime("%Y-%m-%d")

        self.start_date = start
        self.end_date = end
        return start, end

    def apply_current_quarter(self) -> Tuple[str, str]:
        """
        Aplica rango desde inicio del quarter hasta hoy.
        """
        start, end = current_quarter_to_date()
        self.start_date = start
        self.end_date = end
        return start, end


    def apply_current_semester(self) -> Tuple[str, str]:
        """
        Aplica rango desde inicio del semestre hasta hoy.
        """
        start, end = current_semester_to_date()
        self.start_date = start
        self.end_date = end
        return start, end


    def apply_quick_range(self, days: int) -> Tuple[str, str]:
        """Aplica un rango rápido de X días (ej. 7, 30)."""
        start_iso, end_iso = last_n_days(days)
        self.start_date = start_iso
        self.end_date = end_iso
        return start_iso, end_iso

    def apply_month_range(self) -> Tuple[str, str]:
        """Aplica rango del mes actual (mes completo)."""
        start_iso, end_iso = current_month_full()
        self.start_date = start_iso
        self.end_date = end_iso
        return start_iso, end_iso

    def apply_year_range(self) -> Tuple[str, str]:
        """Aplica rango del año actual (año completo)."""
        start_iso, end_iso = current_year_full()
        self.start_date = start_iso
        self.end_date = end_iso
        return start_iso, end_iso

    def apply_current_month(self) -> Tuple[str, str]:
        """Aplica rango desde inicio de mes hasta hoy."""
        start_iso, end_iso = current_month_to_date()
        self.start_date = start_iso
        self.end_date = end_iso
        return start_iso, end_iso

    def apply_current_year(self) -> Tuple[str, str]:
        """Aplica rango desde inicio de año hasta hoy."""
        start_iso, end_iso = current_year_to_date()
        self.start_date = start_iso
        self.end_date = end_iso
        return start_iso, end_iso

    # ------------------------------------------------------------
    #  VALIDACIÓN
    # ------------------------------------------------------------
    def validate(self) -> Tuple[bool, Optional[str]]:
        """Valida que start_date <= end_date."""
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
        return self.start_date is not None or self.end_date is not None

    # ------------------------------------------------------------
    #  ACCESO A PARÁMETROS
    # ------------------------------------------------------------
    def get_filter_params(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Devuelve (start_date, end_date) ya normalizados,
        listos para usar en get_sales_summary().
        """
        return self.start_date, self.end_date

    # ------------------------------------------------------------
    #  RESETEO
    # ------------------------------------------------------------
    def clear(self) -> None:
        """Limpia todas las fechas."""
        self.start_date = None
        self.end_date = None
