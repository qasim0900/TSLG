from datetime import date, datetime, timedelta
from typing import Optional, Tuple
from dateutil.relativedelta import relativedelta


def _to_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def last_n_months(months: int, today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()
    start = today - relativedelta(months=months)
    return _to_iso(start), _to_iso(today)


def current_week_full(today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return _to_iso(start), _to_iso(end)

def _quarter_bounds(year: int, quarter: int) -> Tuple[date, date]:
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
    if today is None:
        today = date.today()

    quarter = (today.month - 1) // 3 + 1
    start, _ = _quarter_bounds(today.year, quarter)

    return _to_iso(start), _to_iso(today)

def previous_quarter_full(today: Optional[date] = None) -> Tuple[str, str]:
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
    if today is None:
        today = date.today()

    quarter = (today.month - 1) // 3 + 1
    start, end = _quarter_bounds(today.year - 1, quarter)

    return _to_iso(start), _to_iso(end)


def current_semester_to_date(today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()

    if today.month <= 6:
        start = date(today.year, 1, 1)
    else:
        start = date(today.year, 7, 1)

    return _to_iso(start), _to_iso(today)

def current_semester_full(today: Optional[date] = None) -> Tuple[str, str]:
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
    if today is None:
        today = date.today()

    if today.month <= 6:
        year = today.year - 1
        start = date(year, 7, 1)
        end = date(year, 12, 31)
    else:
        year = today.year
        start = date(year, 1, 1)
        end = date(year, 6, 30)

    return _to_iso(start), _to_iso(end)


def last_n_days(days: int, today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()
    start = today - timedelta(days=days - 1)
    return _to_iso(start), _to_iso(today)


def current_month_full(today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()
    start = today.replace(day=1)
    end = (start + relativedelta(months=1)) - timedelta(days=1)
    return _to_iso(start), _to_iso(end)

def previous_month_full(today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()

    first_day_this_month = today.replace(day=1)

    last_day_prev_month = first_day_this_month - timedelta(days=1)

    start = last_day_prev_month.replace(day=1)
    end = last_day_prev_month

    return _to_iso(start), _to_iso(end)


def current_year_full(today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()
    start = today.replace(month=1, day=1)
    end = today.replace(month=12, day=31)
    return _to_iso(start), _to_iso(end)

def previous_year_full(today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()

    year = today.year - 1
    start = date(year, 1, 1)
    end = date(year, 12, 31)

    return _to_iso(start), _to_iso(end)


def current_month_to_date(today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()
    start = today.replace(day=1)
    return _to_iso(start), _to_iso(today)

def current_year_to_date(today: Optional[date] = None) -> Tuple[str, str]:
    if today is None:
        today = date.today()
    start = today.replace(month=1, day=1)
    return _to_iso(start), _to_iso(today)

def shift_year_iso(date_iso: str, delta_years: int) -> str:
    dt = datetime.strptime(date_iso, "%Y-%m-%d")
    shifted = dt + relativedelta(years=delta_years)
    return shifted.strftime("%Y-%m-%d")


def normalize_iso(value: Optional[object]) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")

    if isinstance(value, datetime):
        return value.date().strftime("%Y-%m-%d")

    s = str(value).strip()
    if not s:
        return None

    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def validate_range(
    start_iso: Optional[str],
    end_iso: Optional[str],
) -> Tuple[bool, Optional[str]]:
    if start_iso and end_iso and start_iso > end_iso:
        return False, "The end date cannot be before the start date."

    return True, None

