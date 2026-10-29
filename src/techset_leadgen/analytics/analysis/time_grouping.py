from datetime import datetime, timedelta
from typing import List, TypedDict

from techset_leadgen.utils.formatting import month_abbr

class TimeSeriesRow(TypedDict):
    key: str
    label: str
    total: float


def group_time_series(
    rows: List[tuple[str, float]],
    grouping: str,
) -> List[TimeSeriesRow]:
    if not rows:
        return []

    grouped: dict[str, TimeSeriesRow] = {}

    for date_str, value in rows:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue

        if grouping == "day":
            key = date_obj.strftime("%Y-%m-%d")
            label = date_obj.strftime("%m/%d")

        elif grouping == "week":
            year, week, _ = date_obj.isocalendar()
            key = f"{year}-W{week:02d}"
            label = f"Wk {week}"

        elif grouping == "month":
            key = date_obj.strftime("%Y-%m")
            label = f"{month_abbr(date_obj.month)} {date_obj:%y}"

        elif grouping == "quarter":
            quarter = (date_obj.month - 1) // 3 + 1
            key = f"{date_obj.year}-Q{quarter}"
            label = f"Q{quarter} {str(date_obj.year)[-2:]}"

        elif grouping == "year":
            key = date_obj.strftime("%Y")
            label = key

        else:
            raise ValueError(f"Unsupported grouping: {grouping}")

        if key not in grouped:
            grouped[key] = {
                "key": key,
                "label": label,
                "total": 0.0,
            }

        grouped[key]["total"] += float(value)

    return [grouped[k] for k in sorted(grouped.keys())]


def _get_group_key_and_range(date_obj, grouping: str):
    if grouping == "day":
        key = date_obj.isoformat()
        label = date_obj.strftime("%m/%d")
        start = end = date_obj

    elif grouping == "week":
        start = date_obj - timedelta(days=date_obj.weekday())
        end = start + timedelta(days=6)
        year, week, _ = start.isocalendar()

        key = f"{year}-W{week:02d}"
        label = f"Wk {week}"

    elif grouping == "month":
        start = date_obj.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)

        key = start.strftime("%Y-%m")
        label = f"{month_abbr(start.month)} {start:%y}"

    elif grouping == "quarter":
        quarter = (date_obj.month - 1) // 3 + 1
        start_month = (quarter - 1) * 3 + 1

        start = date_obj.replace(month=start_month, day=1)
        end_month = start_month + 2
        end = (
            start.replace(month=end_month, day=28)
            + timedelta(days=4)
        ).replace(day=1) - timedelta(days=1)

        key = f"{date_obj.year}-Q{quarter}"
        label = f"Q{quarter} {str(date_obj.year)[-2:]}"

    elif grouping == "year":
        start = date_obj.replace(month=1, day=1)
        end = date_obj.replace(month=12, day=31)

        key = str(date_obj.year)
        label = key

    else:
        raise ValueError(f"Unsupported grouping: {grouping}")

    return key, label, start, end


GRANULARITY_LEVEL = {
    "day": 0,
    "week": 1,
    "month": 2,
    "quarter": 3,
    "year": 4,
}


def is_valid_regroup(current_grouping: str, new_grouping: str) -> bool:
    cur = GRANULARITY_LEVEL.get(current_grouping, -1)
    new = GRANULARITY_LEVEL.get(new_grouping, -1)
    if cur < 0 or new < 0:
        return False
    return new >= cur


def regroup_evolution_comparison(
    snapshot,
    new_grouping: str,
):
    from techset_leadgen.domain.analysis_snapshot import EvolutionData, TimeGrouping, AnalysisMode
    from techset_leadgen.analytics.snapshot_builder import _build_evolution_comparison_v2

    if snapshot.metadata.mode != AnalysisMode.COMPARE:
        raise ValueError("regroup_evolution_comparison: snapshot must be in COMPARE mode")

    if snapshot.period_a.evolution_raw is None:
        raise ValueError("regroup_evolution_comparison: period_a.evolution_raw is None")
    if snapshot.period_b is None or snapshot.period_b.evolution_raw is None:
        raise ValueError("regroup_evolution_comparison: period_b.evolution_raw is None")

    if not is_valid_regroup("day", new_grouping):
        raise ValueError(f"regroup_evolution_comparison: invalid regroup from day to {new_grouping}")

    grouped_a = group_time_series(snapshot.period_a.evolution_raw, new_grouping)
    grouped_b = group_time_series(snapshot.period_b.evolution_raw, new_grouping)

    tg = TimeGrouping(new_grouping)

    evolution_a = EvolutionData(
        labels=[row["key"] for row in grouped_a],
        values=[row["total"] for row in grouped_a],
        grouping=tg,
    )

    evolution_b = EvolutionData(
        labels=[row["key"] for row in grouped_b],
        values=[row["total"] for row in grouped_b],
        grouping=tg,
    )

    return _build_evolution_comparison_v2(
        evolution_a=evolution_a,
        evolution_b=evolution_b,
        filters_a=snapshot.period_a.filters,
        filters_b=snapshot.period_b.filters,
        grouping=tg,
    )

