from techset_leadgen.utils.date_range import shift_year_iso
from techset_leadgen.domain import ComparePreset


class CompareController:
    def __init__(self):
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


    def _is_valid_period(self, start, end) -> bool:
        return bool(start and end and start <= end)

    def has_valid_periods(self) -> bool:
        return (
            self._is_valid_period(self.a_start, self.a_end)
            and self._is_valid_period(self.b_start, self.b_end)
        )


    def is_compare_active(self) -> bool:
        return (
            self._compare_active
            and self._is_valid_period(self.b_start, self.b_end)
        )

    def activate_compare(self):
        self._compare_active = True

    def deactivate_compare(self):
        self._compare_active = False


    def apply_preset(self, preset: ComparePreset) -> bool:
        if preset is None:
            return False

        if preset.requires_period_a:
            if not self._is_valid_period(self.a_start, self.a_end):
                return False

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

