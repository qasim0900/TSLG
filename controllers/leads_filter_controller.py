"""
Controlador de filtros client-side para la vista de Leads.

Extraído de views/leads_view.py._on_filter_changed() — lógica pura.
No toca UI. Recibe parámetros de filtro y retorna lista filtrada.

Capa: controllers/
Consumidores: views/leads_view.py
"""

from datetime import date, timedelta

from domain.source_labels import SOURCE_LABELS as _SOURCE_LABELS

# ── Constantes de filtro (movidas desde leads_view.py) ─────────

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

_STAGE_STATUS_MAP: dict[str, str] = {
    "Lead":       "new",
    "Contacted":  "contacted",
    "Meeting":    "meeting",
    "Client":     "converted",
    "Lost":       "lost",
}


def filter_leads(
    all_leads: list,
    source: str | None = None,
    stage: str | None = None,
    date_label: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    search_term: str | None = None,
) -> list:
    """
    Aplica hasta 4 filtros client-side sobre la lista completa de leads.

    Args:
        all_leads: Lista original completa de leads enriched.
        source: Valor del dropdown de fuente (None o "Todas" = sin filtro).
        stage: Valor del dropdown de stage (None o "Todos" = sin filtro).
        date_label: Label del dropdown de período ("7 días", "30 días", etc.).
        start_date: Fecha inicial ISO YYYY-MM-DD para rango específico.
        end_date: Fecha final ISO YYYY-MM-DD para rango específico.
        search_term: Texto libre de búsqueda (case-insensitive).

    Returns:
        Lista filtrada de leads (subconjunto de all_leads).
    """
    # Fecha específica tiene prioridad sobre presets rápidos.
    cutoff_date = None
    if not start_date and not end_date and date_label and date_label != ALL_TIME:
        for label, days in _DATE_RANGE_OPTIONS:
            if label == date_label and days is not None:
                cutoff_date = (date.today() - timedelta(days=days)).isoformat()
                break

    # Start from the full dataset; apply each filter only when non-default
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

    if search_term:
        term = search_term.strip().lower()
        if term:
            filtered = [
                ld for ld in filtered
                if term in " ".join([
                    str(ld.get("id", "")),
                    _SOURCE_LABELS.get(ld.get("source", ""), ld.get("source", "")),
                    ld.get("client_name", ""),
                    ld.get("source", ""),
                ]).lower()
            ]

    return filtered
