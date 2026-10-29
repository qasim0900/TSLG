from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from techset_leadgen.utils.formatting import month_abbr
from techset_leadgen.domain.analysis_snapshot import (
    AnalysisSnapshot,
    AnalysisMode,
    TimeGrouping,
    Metadata,
    Filters,
    PeriodSnapshot,
    ComparisonSnapshot,
    ComparisonMetrics,
    EvolutionComparisonV2,
    EvolutionPointV2,
    ProductComparison,
    TableRow,
    PeriodMetrics,
    EvolutionData,
    ProductDistribution,
    ClientRank,
    PieChartSnapshot,
    PieChartSegmentSnapshot,
)


def build_sales_snapshot(
    *,
    mode: AnalysisMode,
    grouping: TimeGrouping,
    filters_a: Filters,
    period_a_data: Dict[str, Any],
    period_b_data: Optional[Dict[str, Any]] = None,
    filters_b: Optional[Filters] = None,
    app_version: str = "1.0",
) -> AnalysisSnapshot:

    if mode == AnalysisMode.COMPARE:
        if period_b_data is None:
            raise ValueError(
                "mode == COMPARE requires period_b_data not None"
            )
        if filters_b is None:
            raise ValueError(
                "mode == COMPARE requires filters_b not None"
            )
    elif mode == AnalysisMode.NORMAL:
        if period_b_data is not None:
            raise ValueError(
                "mode == NORMAL must not have period_b_data"
            )
        if filters_b is not None:
            raise ValueError(
                "mode == NORMAL must not have filters_b"
            )


    metadata = Metadata(
        mode=mode,
        grouping=grouping,
        generated_at=datetime.now(),
        app_version=app_version,
    )


    period_a = _build_period_snapshot(
        label="Main period",
        filters=filters_a,
        data=period_a_data,
    )


    period_b = None
    comparison = None

    if mode == AnalysisMode.COMPARE and filters_b is not None and period_b_data is not None:
        period_b = _build_period_snapshot(
            label="Comparison period",
            filters=filters_b,
            data=period_b_data,
        )

        comparison = _build_comparison_snapshot(
            period_a=period_a,
            period_b=period_b,
            grouping=grouping,
        )


    snapshot = AnalysisSnapshot(
        metadata=metadata,
        filters=filters_a,
        period_a=period_a,
        period_b=period_b,
        comparison=comparison,
    )


    if not snapshot.validate():
        raise ValueError(
            "AnalysisSnapshot is not valid. "
            "Check the structure of inputs."
        )


    if snapshot.period_a.evolution.grouping != metadata.grouping:
        raise ValueError(
            f"Grouping mismatch in period_a: "
            f"metadata.grouping={metadata.grouping} "
            f"but period_a.evolution.grouping={snapshot.period_a.evolution.grouping}"
        )

    if snapshot.period_b is not None:
        if snapshot.period_b.evolution.grouping != metadata.grouping:
            raise ValueError(
                f"Grouping mismatch in period_b: "
                f"metadata.grouping={metadata.grouping} "
                f"but period_b.evolution.grouping={snapshot.period_b.evolution.grouping}"
            )

    return snapshot


def _build_pie_chart_snapshot(
    distribution: ProductDistribution,
    title: str = "Sales distribution",
) -> PieChartSnapshot:
    segments = [
        PieChartSegmentSnapshot(
            label=label,
            value=value,
            percentage=percentage,
            color_index=index,
        )
        for index, (label, value, percentage) in enumerate(
            zip(
                distribution.labels,
                distribution.values,
                distribution.percentages,
            )
        )
    ]

    return PieChartSnapshot(
        title=title,
        segments=segments,
    )


def _build_period_snapshot(
    label: str,
    filters: Filters,
    data: Dict[str, Any],
) -> PeriodSnapshot:
    required_keys = {
        "table_data",
        "metrics",
        "evolution",
        "product_distribution",
        "top_clients",
    }

    missing = required_keys - set(data.keys())
    if missing:
        raise ValueError(
            f"period_data missing fields: {missing}"
        )

    return PeriodSnapshot(
        label=label,
        filters=filters,
        table_data=data["table_data"],
        metrics=data["metrics"],
        evolution=data["evolution"],
        product_distribution=data["product_distribution"],
        top_clients=data["top_clients"],
        pie_chart=_build_pie_chart_snapshot(
            data["product_distribution"]
        ),
        evolution_raw=data.get("evolution_raw"),
    )


def _build_comparison_snapshot(
    period_a: PeriodSnapshot,
    period_b: PeriodSnapshot,
    grouping: TimeGrouping,
) -> ComparisonSnapshot:

    metrics_a = period_a.metrics
    metrics_b = period_b.metrics

    absolute_changes = {
        "total_sales": metrics_b.total_sales - metrics_a.total_sales,
        "transactions": metrics_b.transactions - metrics_a.transactions,
        "avg_ticket": metrics_b.avg_ticket - metrics_a.avg_ticket,
        "total_quantity": metrics_b.total_quantity - metrics_a.total_quantity,
        "unique_clients": metrics_b.unique_clients - metrics_a.unique_clients,
    }

    percentage_changes = {}
    for key, value_a in {
        "total_sales": metrics_a.total_sales,
        "transactions": metrics_a.transactions,
        "avg_ticket": metrics_a.avg_ticket,
        "total_quantity": metrics_a.total_quantity,
        "unique_clients": metrics_a.unique_clients,
    }.items():
        if value_a != 0:
            pct = (absolute_changes[key] / value_a) * 100
        else:
            pct = 100.0 if absolute_changes[key] != 0 else 0.0
        percentage_changes[key] = pct

    comparison_metrics = ComparisonMetrics(
        absolute_changes=absolute_changes,
        percentage_changes=percentage_changes,
    )


    evolution_comparison = _build_evolution_comparison_v2(
        period_a.evolution,
        period_b.evolution,
        period_a.filters,
        period_b.filters,
        grouping,
    )


    product_comparison = _compare_product_distributions(
        period_a.product_distribution,
        period_b.product_distribution,
    )

    return ComparisonSnapshot(
        metrics=comparison_metrics,
        evolution=evolution_comparison,
        products=product_comparison,
    )


def _build_evolution_comparison_v2(
    evolution_a: EvolutionData,
    evolution_b: EvolutionData,
    filters_a: Filters,
    filters_b: Filters,
    grouping: TimeGrouping,
) -> EvolutionComparisonV2:
    if evolution_a.grouping != grouping:
        raise ValueError(
            f"evolution_a.grouping ({evolution_a.grouping}) != grouping ({grouping})"
        )
    if evolution_b.grouping != grouping:
        raise ValueError(
            f"evolution_b.grouping ({evolution_b.grouping}) != grouping ({grouping})"
        )

    map_a = {label: value for label, value in zip(evolution_a.labels, evolution_a.values)}
    map_b = {label: value for label, value in zip(evolution_b.labels, evolution_b.values)}

    all_keys = sorted(set(evolution_a.labels) | set(evolution_b.labels))

    try:
        filter_start_a = _parse_filter_bound(filters_a.date_start, is_end=False)
        filter_end_a = _parse_filter_bound(filters_a.date_end, is_end=True)
        filter_start_b = _parse_filter_bound(filters_b.date_start, is_end=False)
        filter_end_b = _parse_filter_bound(filters_b.date_end, is_end=True)
    except ValueError as e:
        raise ValueError(f"Invalid filter dates: {e}") from e

    points = []

    for key in all_keys:
        val_a = map_a.get(key, 0.0)
        val_b = map_b.get(key, 0.0)
        difference = val_b - val_a

        label, start, end = _parse_key_and_generate_interval(key, grouping)

        is_partial_a = _is_interval_partial(start, end, filter_start_a, filter_end_a)
        is_partial_b = _is_interval_partial(start, end, filter_start_b, filter_end_b)
        is_partial = is_partial_a or is_partial_b

        point = EvolutionPointV2(
            key=key,
            label=label,
            start=start,
            end=end,
            value_a=val_a,
            value_b=val_b,
            difference=difference,
            is_partial=is_partial,
        )
        points.append(point)

    sorted_points = sorted(points, key=lambda p: p.key)

    if [p.key for p in sorted_points] != all_keys:
        raise ValueError("Points are not strictly ordered by key after sorting")

    return EvolutionComparisonV2(points=sorted_points)


def _parse_key_and_generate_interval(
    key: str,
    grouping: TimeGrouping,
) -> tuple[str, datetime, datetime]:
    if grouping == TimeGrouping.DAY:
        try:
            dt = datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            label = dt.strftime("%m/%d")
            start = dt
            end = dt + timedelta(days=1) - timedelta(microseconds=1)
        except ValueError as e:
            raise ValueError(f"Invalid day key '{key}': {e}")

    elif grouping == TimeGrouping.WEEK:
        try:
            parts = key.split("-W")
            if len(parts) != 2:
                raise ValueError("Invalid week key format")
            year = int(parts[0])
            week = int(parts[1])
            jan4 = datetime(year, 1, 4, tzinfo=timezone.utc)
            week_1_monday = jan4 - timedelta(days=jan4.weekday())
            start = week_1_monday + timedelta(weeks=week - 1)
            end = start + timedelta(days=7) - timedelta(microseconds=1)
            label = f"Wk {week}"
        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid week key '{key}': {e}")

    elif grouping == TimeGrouping.MONTH:
        try:
            dt = datetime.strptime(key, "%Y-%m").replace(tzinfo=timezone.utc)
            label = f"{month_abbr(dt.month)} {dt:%y}"
            start = dt
            next_month = start + timedelta(days=32)
            end = next_month.replace(day=1) - timedelta(microseconds=1)
        except ValueError as e:
            raise ValueError(f"Invalid month key '{key}': {e}")

    elif grouping == TimeGrouping.QUARTER:
        try:
            parts = key.split("-Q")
            if len(parts) != 2:
                raise ValueError("Invalid quarter key format")
            year = int(parts[0])
            quarter = int(parts[1])
            if quarter not in (1, 2, 3, 4):
                raise ValueError("Quarter must be 1-4")
            start_month = (quarter - 1) * 3 + 1
            start = datetime(year, start_month, 1, tzinfo=timezone.utc)
            end_month = start_month + 2
            next_quarter_start = datetime(year, end_month + 1, 1, tzinfo=timezone.utc) if end_month < 12 else datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            end = next_quarter_start - timedelta(microseconds=1)
            label = f"Q{quarter} {str(year)[-2:]}"
        except (ValueError, IndexError) as e:
            raise ValueError(f"Invalid quarter key '{key}': {e}")

    elif grouping == TimeGrouping.YEAR:
        try:
            year = int(key)
            start = datetime(year, 1, 1, tzinfo=timezone.utc)
            end = datetime(year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
            label = key
        except ValueError as e:
            raise ValueError(f"Invalid year key '{key}': {e}")

    else:
        raise ValueError(f"Unsupported grouping: {grouping}")

    return label, start, end


def _parse_filter_bound(value: Optional[str], *, is_end: bool) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if is_end and len(value) == 10:
        dt = dt + timedelta(days=1) - timedelta(microseconds=1)
    return dt


def _is_interval_partial(
    start: datetime,
    end: datetime,
    filter_start: Optional[datetime],
    filter_end: Optional[datetime],
) -> bool:
    if filter_start is None and filter_end is None:
        return False

    if filter_end is not None and start > filter_end:
        return False

    if filter_start is not None and end < filter_start:
        return False

    if filter_start is not None and start < filter_start:
        return True

    if filter_end is not None and end > filter_end:
        return True

    return False


def _compare_product_distributions(
    dist_a: ProductDistribution,
    dist_b: ProductDistribution,
) -> ProductComparison:
    map_a = {label: value for label, value in zip(dist_a.labels, dist_a.values)}
    map_b = {label: value for label, value in zip(dist_b.labels, dist_b.values)}

    all_products = sorted(set(dist_a.labels) | set(dist_b.labels))

    aligned_a = []
    aligned_b = []
    differences = []
    percentage_diff = []

    for product in all_products:
        val_a = map_a.get(product, 0.0)
        val_b = map_b.get(product, 0.0)

        aligned_a.append(val_a)
        aligned_b.append(val_b)
        differences.append(val_b - val_a)

        if val_a != 0:
            pct = ((val_b - val_a) / val_a) * 100
        else:
            pct = 100.0 if val_b != 0 else 0.0
        percentage_diff.append(pct)

    return ProductComparison(
        labels=all_products,
        series_a=aligned_a,
        series_b=aligned_b,
        differences=differences,
        percentage_diff=percentage_diff,
    )


def build_normal_snapshot(
    *,
    grouping: TimeGrouping,
    filters: Filters,
    period_data: Dict[str, Any],
    app_version: str = "1.0",
) -> AnalysisSnapshot:
    return build_sales_snapshot(
        mode=AnalysisMode.NORMAL,
        grouping=grouping,
        filters_a=filters,
        period_a_data=period_data,
        period_b_data=None,
        filters_b=None,
        app_version=app_version,
    )
