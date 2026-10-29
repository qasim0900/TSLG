from datetime import date, timedelta

from techset_leadgen.domain.lead_stages import LEAD_STATUSES
from techset_leadgen.domain.source_labels import SOURCE_LABELS as _SOURCE_LABELS


ALL_SOURCES = "All"
ALL_STAGES = "All"
ALL_TIME = "All time"
ALL_LEADS_DESCRIPTION = "All leads"

_DATE_RANGE_OPTIONS: list[tuple[str, int | None]] = [
    ("Last 7 days", 7),
    ("Last 30 days", 30),
    ("Last 90 days", 90),
    (ALL_TIME, None),
]

_STAGE_STATUS_MAP: dict[str, str] = {label: code for code, label in LEAD_STATUSES.items()}


def filter_leads(
    all_leads: list,
    source: str | None = None,
    stage: str | None = None,
    date_label: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    search_term: str | None = None,
    owner: str | None = None,
    current_user_id: str | None = None,
) -> list:
    cutoff_date = None
    if not start_date and not end_date and date_label and date_label != ALL_TIME:
        for label, days in _DATE_RANGE_OPTIONS:
            if label == date_label and days is not None:
                cutoff_date = (date.today() - timedelta(days=days)).isoformat()
                break

    filtered = all_leads

    if source and source != ALL_SOURCES:
        filtered = [ld for ld in filtered if ld.get("source") == source]

    if stage and stage != ALL_STAGES:
        status_filter = _STAGE_STATUS_MAP.get(stage)
        if status_filter:
            filtered = [ld for ld in filtered if ld.get("status") == status_filter]

    if start_date or end_date:
        filtered = [
            ld for ld in filtered
            if (
                (not start_date or (ld.get("created_at") or "")[:10] >= start_date)
                and (not end_date or (ld.get("created_at") or "")[:10] <= end_date)
            )
        ]
    elif cutoff_date:
        filtered = [ld for ld in filtered if (ld.get("created_at") or "")[:10] >= cutoff_date]

    if owner == "me":
        filtered = [ld for ld in filtered if current_user_id and ld.get("owner_id") == current_user_id]
    elif owner == "none":
        filtered = [ld for ld in filtered if not ld.get("owner_id")]
    elif owner:
        filtered = [ld for ld in filtered if ld.get("owner_id") == owner]

    if search_term:
        term = search_term.strip().lower()
        if term:
            filtered = [
                ld for ld in filtered
                if term in " ".join([
                    str(ld.get("id", "")),
                    _SOURCE_LABELS.get(ld.get("source", ""), ld.get("source", "")),
                    ld.get("client_name") or "",
                    ld.get("source", ""),
                    ld.get("title") or "",
                    ld.get("owner_name") or "",
                ]).lower()
            ]

    return filtered

