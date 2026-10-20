"""
Utilidades de formateo para presentación consistente de valores monetarios.

Proporciona funciones centralizadas para formatear moneda en formato europeo (€)
con período para miles y coma para decimales, garantizando consistencia entre
UI y exportación HTML.
"""


import math
from datetime import date, datetime


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


# English month abbreviations. ``strftime("%b")`` and ``"%p"`` follow the
# process LC_TIME locale, which Qt applies at startup, so they would insert
# e.g. Urdu or Arabic month names into English UI copy and reports.
_MONTH_ABBREVIATIONS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def month_abbr(month: int) -> str:
    """Return the locale-independent English abbreviation for ``month`` (1-12)."""
    return _MONTH_ABBREVIATIONS[month - 1]


def format_datetime_us(value: datetime) -> str:
    hour = value.hour % 12 or 12
    meridiem = "AM" if value.hour < 12 else "PM"
    return f"{month_abbr(value.month)} {value.day}, {value.year} {hour}:{value.minute:02d} {meridiem}"


def format_day_month_year_time(value: datetime) -> str:
    """Format as ``20 Oct 2026, 16:48`` regardless of the OS locale."""
    return f"{value.day:02d} {month_abbr(value.month)} {value.year}, {value.hour:02d}:{value.minute:02d}"


def format_date_range_us(start: date, end: date) -> str:
    if start.year == end.year:
        return f"{month_abbr(start.month)} {start.day} – {month_abbr(end.month)} {end.day}, {end.year}"
    return (
        f"{month_abbr(start.month)} {start.day}, {start.year} – "
        f"{month_abbr(end.month)} {end.day}, {end.year}"
    )


def parse_amount(value) -> float:
    if isinstance(value, bool):
        raise ValueError(f"Amount is not a number: {value!r}")
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value or "").strip().replace("€", "").replace(" ", "")
        if not text:
            raise ValueError("Amount is empty")
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif text.count(",") == 1:
            text = text.replace(",", ".")
        try:
            number = float(text)
        except ValueError:
            raise ValueError(f"Amount is not a number: {value!r}") from None
    if not math.isfinite(number):
        raise ValueError(f"Amount must be a finite number: {value!r}")
    return number


def format_eur(value: float, decimals: int = 2) -> str:
    """
    Format a number as US-style euros: "€1,234.56" (negative: "-€1,234.56").

    Example:
        >>> format_eur(1234.56)
        '€1,234.56'
        >>> format_eur(-1234.56)
        '-€1,234.56'
    """
    try:
        number = float(value)
    except (ValueError, TypeError):
        return f"€{0:.{decimals}f}"
    sign = "-" if number < 0 else ""
    return f"{sign}€{abs(number):,.{decimals}f}"


def format_eur_no_symbol(value: float, decimals: int = 2) -> str:
    """
    Format a number with US separators and no currency symbol: "1,234.56".

    Example:
        >>> format_eur_no_symbol(1234.56)
        '1,234.56'
    """
    try:
        return f"{float(value):,.{decimals}f}"
    except (ValueError, TypeError):
        return f"{0:.{decimals}f}"


def format_eur_signed(value: float, decimals: int = 2) -> str:
    """
    Format a change with an explicit sign: "+1,234.56" or "-1,234.56".

    Example:
        >>> format_eur_signed(1234.56)
        '+1,234.56'
    """
    try:
        return f"{float(value):+,.{decimals}f}"
    except (ValueError, TypeError):
        return f"{0:+.{decimals}f}"


def mask_sensitive(value: str) -> str:
    """
    Enmascara un valor sensible para mostrar en UI con patrón hover-reveal.

    Los valores vacíos y los placeholders ("—", "-") pasan sin cambios.
    Todos los demás se reemplazan por "••••••••" hasta que el usuario
    pase el cursor sobre el control (ver _make_masked_cell / _masked_info_row).

    Args:
        value: Valor a enmascarar (CIF, email, teléfono, persona de contacto…)

    Returns:
        "••••••••" o el valor original si está vacío / es placeholder.
    """
    if not value or str(value).strip() in ("—", "-", ""):
        return value
    return "••••••••"
