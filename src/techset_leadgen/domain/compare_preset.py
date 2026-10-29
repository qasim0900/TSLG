from datetime import date, timedelta
from dataclasses import dataclass
from typing import Callable, Optional, List
from techset_leadgen.utils.date_range import (
    current_month_to_date,
    current_quarter_to_date,
    previous_month_full,
    same_quarter_previous_year,
    current_year_to_date,
    previous_year_full,
    current_semester_to_date,
    previous_semester_full,
    shift_year_iso,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from techset_leadgen.analytics.controllers.compare_controller import CompareController

@dataclass(frozen=True)
class ComparePreset:
    id: str
    label: str
    description: str
    grouping_hint: Optional[str]
    apply_func: Callable[["CompareController"], None]
    affects: List[str]
    requires_period_a: bool = True
class ComparePresetRegistry:
    def __init__(self):
        self._presets: dict[str, ComparePreset] = {}

    def register(self, preset: ComparePreset) -> None:
        if preset.id in self._presets:
            raise ValueError(f"Preset '{preset.id}' is already registered")
        self._presets[preset.id] = preset

    def get(self, preset_id: str) -> Optional[ComparePreset]:
        return self._presets.get(preset_id)

    def list_all(self) -> List[ComparePreset]:
        return list(self._presets.values())

    def list_by_affect(self, affect: str) -> List[ComparePreset]:
        return [p for p in self._presets.values() if affect in p.affects]

PRESET_REGISTRY = ComparePresetRegistry()


def _apply_same_period_as_a(controller):
    if not controller.a_start or not controller.a_end:
        return

    controller.b_start = controller.a_start
    controller.b_end = controller.a_end

    controller.client_b = controller.client_a
    controller.product_b = controller.product_a
    controller.client_b_overridden = False
    controller.product_b_overridden = False


same_period_as_a = ComparePreset(
    id="same_period_as_a",
    label="Same period as A",
    description="Uses exactly the same date range as period A.",
    grouping_hint=None,
    apply_func=_apply_same_period_as_a,
    affects=["dates"],
    requires_period_a=True,
)

PRESET_REGISTRY.register(same_period_as_a)


def _apply_period_vs_previous_year(controller):
    if not controller.a_start or not controller.a_end:
        return

    controller.b_start = shift_year_iso(controller.a_start, -1)
    controller.b_end = shift_year_iso(controller.a_end, -1)

    controller.client_b = controller.client_a
    controller.product_b = controller.product_a

    controller.client_b_overridden = False
    controller.product_b_overridden = False


period_vs_previous_year = ComparePreset(
    id="period_vs_previous_year",
    label="Same period, previous year",
    description="Compares the selected period with the same range one year earlier.",
    grouping_hint=None,
    apply_func=_apply_period_vs_previous_year,
    affects=["dates"],
    requires_period_a=True,)

PRESET_REGISTRY.register(period_vs_previous_year)


def _apply_current_vs_previous(controller):
    if not controller.a_start or not controller.a_end:
        return

    a_start = date.fromisoformat(controller.a_start)
    a_end = date.fromisoformat(controller.a_end)

    delta_days = (a_end - a_start).days + 1

    b_end = a_start - timedelta(days=1)
    b_start = b_end - timedelta(days=delta_days - 1)

    controller.b_start = b_start.isoformat()
    controller.b_end = b_end.isoformat()

    controller.client_b = controller.client_a
    controller.product_b = controller.product_a
    controller.client_b_overridden = False
    controller.product_b_overridden = False


current_vs_previous = ComparePreset(
    id="current_vs_previous",
    label="Current vs. previous period",
    description="Compares the current period with the period right before it.",
    grouping_hint="day",
    apply_func=_apply_current_vs_previous,
    affects=["dates"],
    requires_period_a=True,
)

PRESET_REGISTRY.register(current_vs_previous)


def _apply_current_month_vs_previous(controller):
    a_start, a_end = current_month_to_date()
    b_start, b_end = previous_month_full()

    controller.a_start = a_start
    controller.a_end = a_end
    controller.b_start = b_start
    controller.b_end = b_end

    controller.client_b = controller.client_a
    controller.product_b = controller.product_a
    controller.client_b_overridden = False
    controller.product_b_overridden = False


current_month_vs_previous = ComparePreset(
    id="current_month_vs_previous",
    label="This month vs. last month",
    description="Compares this month (to date) with the whole previous month.",
    grouping_hint="week",
    apply_func=_apply_current_month_vs_previous,
    affects=["dates"],
    requires_period_a=False,
)

PRESET_REGISTRY.register(current_month_vs_previous)

def _apply_quarter_vs_previous_year(controller):
    a_start, a_end = current_quarter_to_date()
    b_start, b_end = same_quarter_previous_year()

    controller.a_start = a_start
    controller.a_end = a_end
    controller.b_start = b_start
    controller.b_end = b_end

    controller.client_b = controller.client_a
    controller.product_b = controller.product_a
    controller.client_b_overridden = False
    controller.product_b_overridden = False


quarter_vs_previous_year = ComparePreset(
    id="quarter_vs_previous_year",
    label="This quarter vs. a year ago",
    description="Compares the current calendar quarter with the same quarter last year.",
    grouping_hint="month",
    apply_func=_apply_quarter_vs_previous_year,
    affects=["dates"],
    requires_period_a=False,
)

PRESET_REGISTRY.register(quarter_vs_previous_year)

def _apply_current_year_vs_previous(controller):
    a_start, a_end = current_year_to_date()
    b_start, b_end = previous_year_full()

    controller.a_start = a_start
    controller.a_end = a_end
    controller.b_start = b_start
    controller.b_end = b_end

    controller.client_b = controller.client_a
    controller.product_b = controller.product_a
    controller.client_b_overridden = False
    controller.product_b_overridden = False

current_year_vs_previous = ComparePreset(
    id="current_year_vs_previous",
    label="This year vs. last year",
    description="Compares this year (to date) with the whole previous year.",
    grouping_hint="month",
    apply_func=_apply_current_year_vs_previous,
    affects=["dates"],
    requires_period_a=False,
)

PRESET_REGISTRY.register(current_year_vs_previous)

def _apply_current_semester_vs_previous(controller):
    a_start, a_end = current_semester_to_date()
    b_start, b_end = previous_semester_full()

    controller.a_start = a_start
    controller.a_end = a_end
    controller.b_start = b_start
    controller.b_end = b_end

    controller.client_b = controller.client_a
    controller.product_b = controller.product_a
    controller.client_b_overridden = False
    controller.product_b_overridden = False

current_semester_vs_previous = ComparePreset(
    id="current_semester_vs_previous",
    label="This half-year vs. previous",
    description="Compares this half-year (to date) with the whole previous half-year.",
    grouping_hint="month",
    apply_func=_apply_current_semester_vs_previous,
    affects=["dates"],
    requires_period_a=False,
)

PRESET_REGISTRY.register(current_semester_vs_previous)

