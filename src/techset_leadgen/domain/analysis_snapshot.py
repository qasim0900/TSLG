from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime, timezone
from enum import Enum


class AnalysisMode(str, Enum):
    NORMAL = "normal"
    COMPARE = "compare"


class TimeGrouping(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


@dataclass
class Metadata:
    mode: AnalysisMode
    grouping: TimeGrouping
    generated_at: datetime
    app_version: str = "1.0"


@dataclass
class Filters:
    date_start: str
    date_end: str
    client_name: Optional[str] = None
    product_type: Optional[str] = None


@dataclass
class TableRow:
    product_type: str
    quantity: int
    total_sales: float
    avg_price: float
    min_price: float
    max_price: float


@dataclass
class PeriodMetrics:
    total_sales: float
    transactions: int
    avg_ticket: float
    total_quantity: int
    unique_clients: int


@dataclass
class EvolutionData:
    labels: List[str]
    values: List[float]
    grouping: TimeGrouping


@dataclass
class ProductDistribution:
    labels: List[str]
    values: List[float]
    percentages: List[float]


@dataclass
class ClientRank:
    rank: int
    client_name: str
    total_sales: float
    transactions: int
    percentage_of_total: float


@dataclass
class PeriodSnapshot:
    label: str
    filters: Filters
    table_data: List[TableRow]
    metrics: PeriodMetrics
    evolution: EvolutionData
    product_distribution: ProductDistribution
    top_clients: List[ClientRank]
    pie_chart: Optional["PieChartSnapshot"] = None
    evolution_raw: Optional[List[tuple]] = None


@dataclass
class ComparisonMetrics:
    absolute_changes: dict
    percentage_changes: dict


@dataclass
class EvolutionPointV2:
    key: str
    label: str
    start: datetime
    end: datetime
    value_a: float
    value_b: float
    difference: float
    is_partial: bool = False


@dataclass
class EvolutionComparisonV2:
    points: List[EvolutionPointV2]


@dataclass
class ProductComparison:
    labels: List[str]
    series_a: List[float]
    series_b: List[float]
    differences: List[float]
    percentage_diff: List[float]


@dataclass
class ComparisonSnapshot:
    metrics: ComparisonMetrics
    evolution: EvolutionComparisonV2
    products: ProductComparison


@dataclass
class PieChartSegmentSnapshot:
    label: str
    value: float
    percentage: float
    color_index: int


@dataclass
class PieChartSnapshot:
    title: str
    segments: List[PieChartSegmentSnapshot]


@dataclass
class AnalysisSnapshot:
    metadata: Metadata
    filters: Filters
    period_a: PeriodSnapshot
    period_b: Optional[PeriodSnapshot] = None
    comparison: Optional[ComparisonSnapshot] = None

    def is_normal_mode(self) -> bool:
        return self.metadata.mode == AnalysisMode.NORMAL

    def is_compare_mode(self) -> bool:
        return self.metadata.mode == AnalysisMode.COMPARE

    def validate(self) -> bool:
        if self.is_normal_mode():
            if self.period_b is not None:
                raise ValueError("NORMAL mode: period_b must be None")
            if self.comparison is not None:
                raise ValueError("NORMAL mode: comparison must be None")

        elif self.is_compare_mode():
            if self.period_b is None:
                raise ValueError("COMPARE mode: period_b must not be None")
            if self.comparison is None:
                raise ValueError("COMPARE mode: comparison must not be None")


            evolution = self.comparison.evolution

            if not hasattr(evolution, 'points'):
                raise ValueError("comparison.evolution has no attribute 'points'")

            if not isinstance(evolution.points, list):
                raise ValueError(f"comparison.evolution.points must be a list, got {type(evolution.points)}")

            if len(evolution.points) == 0:
                raise ValueError("comparison.evolution.points cannot be empty")


            prev_key = None

            for idx, point in enumerate(evolution.points):
                required_fields = ['key', 'label', 'start', 'end', 'value_a', 'value_b', 'difference', 'is_partial']
                for field in required_fields:
                    if not hasattr(point, field):
                        raise ValueError(f"Point[{idx}] missing field '{field}'")

                if not isinstance(point.start, datetime):
                    raise ValueError(f"Point[{idx}].start must be a datetime, got {type(point.start)}")
                if not isinstance(point.end, datetime):
                    raise ValueError(f"Point[{idx}].end must be a datetime, got {type(point.end)}")

                if point.start.tzinfo is None:
                    raise ValueError(f"Point[{idx}].start must be timezone-aware, got a naive datetime")
                if point.end.tzinfo is None:
                    raise ValueError(f"Point[{idx}].end must be timezone-aware, got a naive datetime")

                if point.start.tzinfo != timezone.utc:
                    raise ValueError(f"Point[{idx}].start timezone must be UTC, got {point.start.tzinfo}")
                if point.end.tzinfo != timezone.utc:
                    raise ValueError(f"Point[{idx}].end timezone must be UTC, got {point.end.tzinfo}")

                if point.start >= point.end:
                    raise ValueError(f"Point[{idx}]: start ({point.start}) must be < end ({point.end})")

                expected_diff = point.value_b - point.value_a
                if abs(point.difference - expected_diff) > 1e-9:
                    raise ValueError(
                        f"Point[{idx}]: difference ({point.difference}) != "
                        f"value_b ({point.value_b}) - value_a ({point.value_a}) ({expected_diff})"
                    )

                self._validate_key_format(point.key, self.metadata.grouping, idx)

                if prev_key is not None:
                    if point.key <= prev_key:
                        raise ValueError(
                            f"Point[{idx}]: key '{point.key}' must be > previous key '{prev_key}' (not strictly ordered)"
                        )
                prev_key = point.key


            for idx in range(len(evolution.points) - 1):
                current = evolution.points[idx]
                next_point = evolution.points[idx + 1]

                if current.end > next_point.start:
                    raise ValueError(
                        f"Points[{idx}] and [{idx + 1}] overlap: "
                        f"end[{idx}] ({current.end}) > start[{idx + 1}] ({next_point.start})"
                    )

        return True

    def _validate_key_format(self, key: str, grouping: TimeGrouping, point_idx: int) -> None:
        import re

        if grouping == TimeGrouping.DAY:
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', key):
                raise ValueError(f"Point[{point_idx}]: DAY key '{key}' must use the format YYYY-MM-DD")
            try:
                datetime.strptime(key, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"Point[{point_idx}]: DAY key '{key}' is not a valid date")

        elif grouping == TimeGrouping.WEEK:
            if not re.match(r'^\d{4}-W\d{2}$', key):
                raise ValueError(f"Point[{point_idx}]: WEEK key '{key}' must use the format YYYY-Www")
            try:
                parts = key.split('-W')
                int(parts[0])
                week = int(parts[1])
                if not (1 <= week <= 53):
                    raise ValueError(f"Week {week} out of range 1-53")
            except (ValueError, IndexError) as e:
                raise ValueError(f"Point[{point_idx}]: WEEK key '{key}' is invalid: {e}")

        elif grouping == TimeGrouping.MONTH:
            if not re.match(r'^\d{4}-\d{2}$', key):
                raise ValueError(f"Point[{point_idx}]: MONTH key '{key}' must use the format YYYY-MM")
            try:
                datetime.strptime(key, "%Y-%m")
            except ValueError:
                raise ValueError(f"Point[{point_idx}]: MONTH key '{key}' is not valid")

        elif grouping == TimeGrouping.QUARTER:
            if not re.match(r'^\d{4}-Q[1-4]$', key):
                raise ValueError(f"Point[{point_idx}]: QUARTER key '{key}' must use the format YYYY-Qn where n is 1-4")

        elif grouping == TimeGrouping.YEAR:
            if not re.match(r'^\d{4}$', key):
                raise ValueError(f"Point[{point_idx}]: YEAR key '{key}' must use the format YYYY")
            try:
                int(key)
            except ValueError:
                raise ValueError(f"Point[{point_idx}]: YEAR key '{key}' is not a valid year")

