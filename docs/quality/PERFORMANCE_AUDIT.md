# Performance audit

Audit date 2026-10-20. Measurements ran on the environment in [BASELINE_AUDIT.md](BASELINE_AUDIT.md) with the offscreen platform, so they include Qt layout and painting but not compositor time. Each figure is a single run, not a statistical benchmark; treat differences under about 20 % as noise.

## Datasets

Generated deterministically and loaded through the application's own importer into scratch databases:

| Name | Sales | Leads | Clients | Spend records |
|---|---:|---:|---:|---:|
| Small | 600 | 300 | 41 | 60 |
| Large | 20,000 | 5,000 | 400 | 60 |
| Import file | 300,000 sales rows (13.7 MB CSV) | | | |

## N+1 queries

SQL statements were counted with a SQLite trace callback on every connection while each page refreshed.

| Operation | Small | Large | Verdict |
|---|---:|---:|---|
| Dashboard refresh | 2 | 2 | constant |
| Sales, first open | 6 | 6 | constant |
| Sales reload (snapshot cache hit) | 0 | 0 | constant |
| Leads refresh | 3 | 3 | constant |
| Clients refresh | 2 | 2 | constant |
| Leads or Clients search keystroke | 0 | 0 | in-memory filtering |

**No N+1 query pattern exists at the database level:** statement counts do not grow with the data. `tests/test_query_scaling.py` already guards the data-layer functions. The real bottleneck was in the GUI layer.

## GUI bottleneck (DEF-008)

Profiling Leads filtering at 5,000 leads showed `_populate_leads_table` taking 4.8 s of 4.95 s across three refreshes: 1.66 s in `setCellWidget` for 15,000 per-row buttons, about 1.1 s laying out and styling them, and about 1 s creating items. A second, quadratic cost appeared once the widgets were removed: each `setItem` on a visible table with `ResizeToContents` columns re-measured the whole column (200 rows produced 400,200 `sizeHint` calls).

Changes:

1. Row buttons are painted by `RowActionDelegate` instead of being widgets.
2. `bulk_table_update` suspends column sizing and sorting while a table is filled, then sizes once (Qt limits the measurement to 1,000 rows).
3. Text-only cells use native `QTableWidgetItem`s; only numeric cells use the Python `SortableItem`.
4. Leads search is debounced by 200 ms; Enter applies immediately. Clients search, at about 50 ms per keystroke, is not debounced.

## Results on the large dataset

| Operation | Before | After |
|---|---:|---:|
| Open Leads (first time) | 2,073 ms | 494 ms |
| Leads refresh | 1,085 ms | 304 ms |
| Open Clients (first time) | 588 ms | 242 ms |
| Clients refresh | 383 ms | 111 ms |
| Leads search, 8 keystrokes | 4,209 ms | 1,232 ms without debounce; one refresh after the typing pause with it |
| Clients search, 8 keystrokes | 2,893 ms | 400 ms |
| Peak memory (RSS) for the session | 927 MB | 264 MB |
| Per-row widgets in the Leads table | 5,000 | 0 |

Clients refresh scaling after the change, with only the row count varied: 15 ms (50 rows), 41 ms (200), 77 ms (400), which is linear. With the intermediate version (painted buttons but per-cell re-measurement), refreshes took 770 ms at 50 rows, 2,814 ms at 100, and 11,148 ms at 200.

Pages unaffected by the change, for reference: Dashboard refresh 6–8 ms; Sales first open 350–415 ms (Matplotlib rendering of three to four charts); application start to Dashboard about 50 ms.

## Other measured improvements

| Item | Before | After |
|---|---:|---:|
| `app.log` growth for one Leads load at 5,000 leads (DEF-017) | 388 lines, 44,672 bytes | 1 line, 344 bytes for the whole session |
| Sales page minimum width (DEF-009) | 716 px (charts could not shrink) | 474 px |

## Import throughput (measured through the real event loop)

| File | Inspection | Import | Notes |
|---|---:|---:|---|
| 20,000 sales rows | n/a | 0.4 s | UI stayed responsive; the window could not be closed until it finished |
| 300,000 sales rows (13.7 MB) | about 2.9 s | about 1.9 s | Close request during the import was refused; close succeeded afterwards |

## Not changed

- **Sales chart rendering** (about 170 ms per reload) is Matplotlib's Agg rendering of three to four figures. It was not a measured problem, so it was left alone.
- **Indexes.** The schema already indexes the filtered columns (`sales.date`, `client_name`, `product_type`, `client_id`, and several lead columns). No database operation stood out: profiling attributed the Leads cost to widget work, and the Dashboard's two aggregate queries complete within its 6–8 ms refresh. No indexes were added, and query plans were not examined.
- **Caching.** The Sales controller already caches snapshots by filter and dataset version; no further caching was justified.
