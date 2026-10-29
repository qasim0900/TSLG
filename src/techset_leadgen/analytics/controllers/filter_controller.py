from typing import Optional, Tuple, Dict, Callable
from techset_leadgen.utils.date_range import normalize_iso, validate_range, last_n_days, current_month_full, current_year_full
from techset_leadgen.domain.filter_options import ALL_FILTER_KEY


class FilterController:
    def __init__(self):
        self.start_date: Optional[str] = None
        self.end_date: Optional[str] = None
        self.client_name: Optional[str] = None
        self.product_type: Optional[str] = None

        self.on_change: Optional[Callable[[], None]] = None
        self._notifications_suspended: bool = False
        self._pending_notification: bool = False


    def set_start_date(self, value: Optional[str]) -> Optional[str]:
        iso = normalize_iso(value)

        if self.start_date == iso:
            return iso if iso else "–"

        self.start_date = iso
        self._trigger_on_change()
        return iso if iso else "–"

    def set_end_date(self, value: Optional[str]) -> Optional[str]:
        iso = normalize_iso(value)

        if self.end_date == iso:
            return iso if iso else "–"

        self.end_date = iso
        self._trigger_on_change()
        return iso if iso else "–"

    def set_client(self, value: Optional[str]) -> Optional[str]:
        normalized = value.strip() if value and value != ALL_FILTER_KEY else None

        if self.client_name == normalized:
            return normalized

        self.client_name = normalized
        self._trigger_on_change()
        return normalized

    def set_product(self, value: Optional[str]) -> Optional[str]:
        normalized = value.strip() if value and value != ALL_FILTER_KEY else None

        if self.product_type == normalized:
            return normalized

        self.product_type = normalized
        self._trigger_on_change()
        return normalized


    def apply_quick_range(self, days: int) -> Tuple[str, str]:
        start_iso, end_iso = last_n_days(days)

        self.suspend_notifications()
        self._assign_filters(start_date=start_iso, end_date=end_iso)
        self.resume_notifications()

        return start_iso, end_iso

    def apply_month_range(self) -> Tuple[str, str]:
        start_iso, end_iso = current_month_full()

        self.suspend_notifications()
        self._assign_filters(start_date=start_iso, end_date=end_iso)
        self.resume_notifications()

        return start_iso, end_iso

    def apply_year_range(self) -> Tuple[str, str]:
        start_iso, end_iso = current_year_full()

        self.suspend_notifications()
        self._assign_filters(start_date=start_iso, end_date=end_iso)
        self.resume_notifications()

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
        return any([
            self.start_date is not None,
            self.end_date is not None,
            self.client_name is not None,
            self.product_type is not None,
        ])


    def get_filter_params(self) -> Dict[str, Optional[str]]:
        return {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'client_name': self.client_name,
            'product_type': self.product_type,
        }


    def clear(self) -> None:
        self.suspend_notifications()
        self._assign_filters(start_date=None, end_date=None, client_name=None, product_type=None)
        self.resume_notifications()

    def clear_dates(self) -> None:
        self.suspend_notifications()
        self._assign_filters(start_date=None, end_date=None)
        self.resume_notifications()


    def suspend_notifications(self) -> None:
        self._notifications_suspended = True

    def resume_notifications(self) -> None:
        self._notifications_suspended = False

        if self._pending_notification:
            self._pending_notification = False
            if self.on_change:
                self.on_change()

    def set_date_range(self, start: Optional[str], end: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
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
        if self._notifications_suspended:
            self._pending_notification = True
        else:
            if self.on_change:
                self.on_change()

