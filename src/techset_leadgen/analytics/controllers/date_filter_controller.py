from datetime import date, datetime
from typing import Optional, Tuple

from techset_leadgen.utils.date_range import (
    last_n_days,
    last_n_months,

    current_week_full,
    current_month_full,
    current_year_full,

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

    def set_date(self, which: str, value: Optional[date | datetime | str]) -> Optional[str]:
        iso = normalize_iso(value)

        if which == "start":
            self.start_date = iso
        elif which == "end":
            self.end_date = iso

        if iso is None:
            return "–"
        return iso

    def apply_last_n_months(self, months: int) -> Tuple[str, str]:
        start, end = last_n_months(months)
        self.start_date = start
        self.end_date = end
        return start, end

    def apply_current_week(self) -> Tuple[str, str]:
        start, _ = current_week_full()
        end = date.today().strftime("%Y-%m-%d")

        self.start_date = start
        self.end_date = end
        return start, end

    def apply_current_quarter(self) -> Tuple[str, str]:
        start, end = current_quarter_to_date()
        self.start_date = start
        self.end_date = end
        return start, end


    def apply_current_semester(self) -> Tuple[str, str]:
        start, end = current_semester_to_date()
        self.start_date = start
        self.end_date = end
        return start, end


    def apply_quick_range(self, days: int) -> Tuple[str, str]:
        start_iso, end_iso = last_n_days(days)
        self.start_date = start_iso
        self.end_date = end_iso
        return start_iso, end_iso

    def apply_month_range(self) -> Tuple[str, str]:
        start_iso, end_iso = current_month_full()
        self.start_date = start_iso
        self.end_date = end_iso
        return start_iso, end_iso

    def apply_year_range(self) -> Tuple[str, str]:
        start_iso, end_iso = current_year_full()
        self.start_date = start_iso
        self.end_date = end_iso
        return start_iso, end_iso

    def apply_current_month(self) -> Tuple[str, str]:
        start_iso, end_iso = current_month_to_date()
        self.start_date = start_iso
        self.end_date = end_iso
        return start_iso, end_iso

    def apply_current_year(self) -> Tuple[str, str]:
        start_iso, end_iso = current_year_to_date()
        self.start_date = start_iso
        self.end_date = end_iso
        return start_iso, end_iso

    def validate(self) -> Tuple[bool, Optional[str]]:
        if not self.start_date and not self.end_date:
            return True, None

        if self.start_date and not self.end_date:
            return True, None

        if not self.start_date and self.end_date:
            return True, None

        return validate_range(self.start_date, self.end_date)

    def has_active_filter(self) -> bool:
        return self.start_date is not None or self.end_date is not None

    def get_filter_params(self) -> Tuple[Optional[str], Optional[str]]:
        return self.start_date, self.end_date

    def clear(self) -> None:
        self.start_date = None
        self.end_date = None

