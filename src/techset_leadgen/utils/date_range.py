"""Helpers de rangos de fechas para filtros y presets.

Todas las funciones devuelven tuplas (start_iso, end_iso) en formato
'YYYY-MM-DD'. Incluye rangos relativos (últimos N días/meses),
períodos calendario (semana, mes, trimestre, semestre, año) y
utilidades de normalización y validación.
"""

from datetime import date, datetime, timedelta
from typing import Optional, Tuple
from dateutil.relativedelta import relativedelta


# ============================================================
#   HELPERS DE FECHAS → SIEMPRE DEVUELVEN CADENAS ISO (YYYY-MM-DD)
# ============================================================

def _to_iso(d: date) -> str:
    """Convierte un objeto date a cadena ISO YYYY-MM-DD."""
    return d.strftime("%Y-%m-%d")

def last_n_months(months: int, today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()
    start = today - relativedelta(months=months)
    return _to_iso(start), _to_iso(today)


def current_week_full(today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()
    start = today - timedelta(days=today.weekday())  # lunes
    end = start + timedelta(days=6)
    return _to_iso(start), _to_iso(end)

def _quarter_bounds(year: int, quarter: int) -> Tuple[date, date]:
    """
    Devuelve (start_date, end_date) para un quarter concreto.
    Quarter: 1..4
    """
    start_month = (quarter - 1) * 3 + 1
    start = date(year, start_month, 1)
    end = start + relativedelta(months=3) - timedelta(days=1)
    return start, end


def current_quarter_full(today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()
    quarter = (today.month - 1) // 3
    start_month = quarter * 3 + 1
    start = today.replace(month=start_month, day=1)
    end = start + relativedelta(months=3) - timedelta(days=1)
    return _to_iso(start), _to_iso(end)

def current_quarter_to_date(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el quarter actual hasta hoy.
    """
    if today is None:
        today = date.today()

    quarter = (today.month - 1) // 3 + 1
    start, _ = _quarter_bounds(today.year, quarter)

    return _to_iso(start), _to_iso(today)

def previous_quarter_full(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el quarter calendario anterior.
    """
    if today is None:
        today = date.today()

    quarter = (today.month - 1) // 3 + 1

    if quarter == 1:
        year = today.year - 1
        quarter = 4
    else:
        year = today.year
        quarter -= 1

    start, end = _quarter_bounds(year, quarter)
    return _to_iso(start), _to_iso(end)

def same_quarter_previous_year(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el mismo quarter del año anterior.
    """
    if today is None:
        today = date.today()

    quarter = (today.month - 1) // 3 + 1
    start, end = _quarter_bounds(today.year - 1, quarter)

    return _to_iso(start), _to_iso(end)




def current_semester_to_date(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el semestre actual hasta hoy.

    Semestres:
    - S1: enero a junio
    - S2: julio a diciembre
    """
    if today is None:
        today = date.today()

    if today.month <= 6:
        start = date(today.year, 1, 1)
    else:
        start = date(today.year, 7, 1)

    return _to_iso(start), _to_iso(today)

def current_semester_full(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el semestre calendario actual completo.

    Semestres:
    - S1: enero a junio
    - S2: julio a diciembre
    """
    if today is None:
        today = date.today()

    if today.month <= 6:
        start = date(today.year, 1, 1)
        end = date(today.year, 6, 30)
    else:
        start = date(today.year, 7, 1)
        end = date(today.year, 12, 31)

    return _to_iso(start), _to_iso(end)

def previous_semester_full(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el semestre calendario anterior completo.
    """
    if today is None:
        today = date.today()

    if today.month <= 6:
        # Estamos en S1 → anterior es S2 del año pasado
        year = today.year - 1
        start = date(year, 7, 1)
        end = date(year, 12, 31)
    else:
        # Estamos en S2 → anterior es S1 del mismo año
        year = today.year
        start = date(year, 1, 1)
        end = date(year, 6, 30)

    return _to_iso(start), _to_iso(end)



def last_n_days(days: int, today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para los últimos `days` días, incluyendo hoy.
    Formato: 'YYYY-MM-DD'.
    """
    if today is None:
        today = date.today()
    start = today - timedelta(days=days - 1)
    return _to_iso(start), _to_iso(today)


def current_month_full(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el mes actual.

    - start_iso: Primer día del mes en formato ISO.
    - end_iso: Último día del mes en formato ISO.
    """
    if today is None:
        today = date.today()
    start = today.replace(day=1)
    end = (start + relativedelta(months=1)) - timedelta(days=1)
    return _to_iso(start), _to_iso(end)

def previous_month_full(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el mes calendario anterior completo.

    Ejemplo:
        today = 2024-05-15 → ("2024-04-01", "2024-04-30")
        today = 2024-01-10 → ("2023-12-01", "2023-12-31")
    """
    if today is None:
        today = date.today()

    # Primer día del mes actual
    first_day_this_month = today.replace(day=1)

    # Último día del mes anterior
    last_day_prev_month = first_day_this_month - timedelta(days=1)

    # Primer día del mes anterior
    start = last_day_prev_month.replace(day=1)
    end = last_day_prev_month

    return _to_iso(start), _to_iso(end)



def current_year_full(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el año actual.

    - start_iso: Primer día del año en formato ISO.
    - end_iso: Último día del año en formato ISO.
    """
    if today is None:
        today = date.today()
    start = today.replace(month=1, day=1)
    end = today.replace(month=12, day=31)
    return _to_iso(start), _to_iso(end)

def previous_year_full(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el año calendario anterior completo.

    Ejemplo:
        today = 2026-05-10
        → ("2025-01-01", "2025-12-31")
    """
    if today is None:
        today = date.today()

    year = today.year - 1
    start = date(year, 1, 1)
    end = date(year, 12, 31)

    return _to_iso(start), _to_iso(end)


def current_month_to_date(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el período desde inicio de mes hasta hoy.

    - start_iso: Primer día del mes en formato ISO.
    - end_iso: Hoy en formato ISO (YYYY-MM-DD).

    Útil para: "Ventas del mes hasta ahora"
    """
    if today is None:
        today = date.today()
    start = today.replace(day=1)
    return _to_iso(start), _to_iso(today)

def current_year_to_date(today: Optional[date] = None) -> Tuple[str, str]:
    """
    Devuelve (start_iso, end_iso) para el período desde inicio de año hasta hoy.

    - start_iso: 1 de enero en formato ISO.
    - end_iso: Hoy en formato ISO (YYYY-MM-DD).

    Útil para: "Ventas del año hasta ahora"
    """
    if today is None:
        today = date.today()
    start = today.replace(month=1, day=1)
    return _to_iso(start), _to_iso(today)

def shift_year_iso(date_iso: str, delta_years: int) -> str:
    """
    Desplaza una fecha ISO (YYYY-MM-DD) X años.
    Ejemplo:
        shift_year_iso("2024-03-15", -1) → "2023-03-15"
    """
    dt = datetime.strptime(date_iso, "%Y-%m-%d")
    shifted = dt + relativedelta(years=delta_years)
    return shifted.strftime("%Y-%m-%d")



# ============================================================
#   NORMALIZACIÓN ISO Y VALIDACIÓN
# ============================================================

def normalize_iso(value: Optional[object]) -> Optional[str]:
    """
    Normaliza cualquier representación de fecha a 'YYYY-MM-DD'.
    Acepta:
        - None → None
        - date / datetime → ISO
        - str en varios formatos comunes.
    Si no reconoce el formato, devuelve None (no lanza excepción).
    """
    if value is None:
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")

    if isinstance(value, datetime):
        return value.date().strftime("%Y-%m-%d")

    # Asumimos string u otro → lo convertimos a str
    s = str(value).strip()
    if not s:
        return None

    # Si ya parece ISO 'YYYY-MM-DD', lo dejamos tal cual
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s

    # Intentar parsear algunos formatos habituales (por si acaso)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Formato desconocido
    return None


def validate_range(
    start_iso: Optional[str],
    end_iso: Optional[str],
) -> Tuple[bool, Optional[str]]:
    """
    Valida que el rango (start_iso, end_iso) sea coherente.
    Las fechas deben venir ya en formato 'YYYY-MM-DD' o None.
    Devuelve:
        (True, None)  si es válido
        (False, "mensaje") si es inválido
    """
    if start_iso and end_iso and start_iso > end_iso:
        return False, "The end date cannot be before the start date."

    return True, None
