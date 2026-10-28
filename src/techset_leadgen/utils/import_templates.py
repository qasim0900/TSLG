"""Generate import templates without depending on a UI framework."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path


_TEMPLATES = {
    "leads": (
        ["external_id", "created_at", "source", "status", "meeting_date", "client_id"],
        [
            ["L001", "2026-03-01", "Facebook", "new", "2026-03-05", "C001"],
            ["L002", "2026-03-03", "Google", "contacted", "", "C002"],
            ["L003", "2026-03-07", "LinkedIn", "meeting", "2026-03-12", ""],
        ],
    ),
    "sales": (
        ["client_name", "client_id", "product_type", "price", "date"],
        [
            ["Alpha Inc.", "C001", "Consulting", "1200", "2026-03-05"],
            ["Beta Corp", "C002", "Support", "850", "2026-03-12"],
        ],
    ),
    "marketing_spend": (
        ["source", "amount", "date"],
        [
            ["Facebook", "1200.00", "2026-03-01"],
            ["Google", "2500.00", "2026-03-01"],
        ],
    ),
}


def write_template(template_type: str, path: str | Path) -> Path:
    key = template_type if template_type in _TEMPLATES else "sales"
    headers, rows = _TEMPLATES[key]
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return destination


def generate_template(template_type: str) -> str:
    key = template_type if template_type in _TEMPLATES else "sales"
    file_descriptor, path = tempfile.mkstemp(prefix=f"{key}_template_", suffix=".csv")
    os.close(file_descriptor)
    return str(write_template(key, path))


__all__ = ["generate_template", "write_template"]
