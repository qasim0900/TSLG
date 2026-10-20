# GUI test inventory

Audit date 2026-10-20. An **item** is one user-facing control, dialog, or workflow step.

**Method**
- **GUI**: real input events (`QTest` mouse or keyboard) on the widget, with production dialogs answered by `tests/qt_helpers.ModalPilot`.
- **Call**: the page method a control's signal invokes, called directly (same code path, no input event).
- **SQL**: the outcome was cross-checked against the database.
- **Visual**: screenshot review, offscreen and on the native Wayland session.

**Status**: **Pass** · **Pass after fix** (a defect was found, fixed, and re-verified) · **Partial** (part of the behavior verified; see note) · **Not tested** (reason given).

**Evidence**: a test in `tests/`, or "session" for audit scripts run against scratch databases (not committed; results are summarized in [TEST_EXECUTION_REPORT.md](TEST_EXECUTION_REPORT.md)).

## Totals

| Status | Items |
|---|---:|
| Pass | 46 |
| Pass after fix | 25 |
| Partial | 3 |
| Not tested | 1 |
| **Total** | **75** |

No item is in a failed state. The open P3 observations (OPEN-01 to OPEN-08) are listed in [DEFECT_LOG.md](DEFECT_LOG.md).

## Application shell

| # | Item | Method | Status | Evidence |
|---:|---|---|---|---|
| 1 | Sidebar navigation to all four pages | GUI (keyboard), Call | Pass | `test_shell_uses_brand_assets_and_all_native_pages`; session |
| 2 | Shortcuts Ctrl+1–Ctrl+4 and Ctrl+I | GUI | Pass | session |
| 3 | Theme toggle, label, and persistence | Call, settings file | Pass after fix (DEF-015, DEF-016) | `test_def015_…`, `test_def016_…` |
| 4 | Compact sidebar below 980 px | GUI resize | Pass | `test_theme_toggle_and_compact_navigation` |
| 5 | Minimum size 760 × 600 and resizing both ways | GUI resize, Visual | Pass after fix (DEF-009, DEF-012) | `test_def009_…`; session |
| 6 | Status bar messages | Observed | Pass | session |
| 7 | Error dialog | GUI | Pass after fix (DEF-004) | `test_def004_…` |
| 8 | Closing the window | Real entry point | Pass | exit code 0: 15 offscreen runs at baseline, 3 on the final code, 2 on Wayland |
| 9 | Close refused during an import | Real event loop | Pass | session (300,000-row import) |
| 10 | Startup failure (unwritable data folder) | Real entry point | Pass | session: dialog, log entry, exit code 1 |
| 11 | Visible keyboard focus | Rendered pixels | Pass after fix (DEF-024) | `test_def024_…` |

## Dashboard

| # | Item | Method | Status | Evidence |
|---:|---|---|---|---|
| 12 | KPI cards (4) | SQL | Pass | session; `test_end_to_end_…` |
| 13 | Refresh | Call | Pass | session |
| 14 | Import data | GUI | Pass | `test_end_to_end_…`; `test_def003_downloaded_spend_…` |
| 15 | Quick actions: Sales analytics, Leads, Clients | GUI | Pass | session |
| 16 | Template downloads: Sales, Leads, Spend | GUI, file | Pass | `test_def003_downloaded_spend_…`; session |
| 17 | Template save to an unwritable path | GUI | Pass (one clear error) | session |
| 18 | Data status text | Visual | Pass after fix (DEF-007) | `test_def007_…` |
| 19 | Clear sales, leads, clients with Cancel and Yes | GUI, SQL | Pass (client cascade verified) | session |

## Sales

| # | Item | Method | Status | Evidence |
|---:|---|---|---|---|
| 20 | From and To date fields, calendar popup | GUI, Call | Pass after fix (DEF-023) | `test_def023_…`; session |
| 21 | Client and Product filters | Call | Partial: options populated after import; filtering by one client was not cross-checked with SQL | session |
| 22 | Group trend by | Call | Pass | session |
| 23 | Quick ranges (4) | GUI | Pass (dates verified) | session |
| 24 | Apply filters | GUI, SQL | Pass (133,996 rows for "This year") | session |
| 25 | Reset | GUI, SQL | Pass | session |
| 26 | Start date after end date | GUI | Pass (inline message) | session |
| 27 | Compare with another period | Call, GUI | Pass (Period B auto-filled, deltas, comparison tab) | session |
| 28 | KPI cards (5) | Data | Pass | `test_sales_page_renders_snapshot_and_filters` |
| 29 | Product table sorting and default order | Call | Pass after fix (DEF-006) | `test_sales_page_renders_…`; `test_def006_…` |
| 30 | Chart tabs: Trend, Products, Top clients, Period comparison | Data, Visual | Pass after fix (DEF-021) | `test_def021_…` |
| 31 | Import data (page button) | GUI | Pass | session |
| 32 | Export HTML | GUI, file | Pass after fix (DEF-007) | `test_sales_page_exports_the_visible_snapshot`; session |
| 33 | Open report | — | Not tested: would launch a browser on the user's desktop | — |

## Leads

| # | Item | Method | Status | Evidence |
|---:|---|---|---|---|
| 34 | Search (debounced; Enter applies) | GUI | Pass after fix (DEF-008) | `test_leads_page_filters_and_exports_current_snapshot`; session |
| 35 | Source, Stage, and Period filters | Call, SQL | Pass | session |
| 36 | From and To dates, including From after To | Call, SQL | Pass | session |
| 37 | Clear filters | GUI | Pass | session |
| 38 | KPI cards (8) and funnel | SQL | Pass (302 / 112 / 48 / 59 matched) | session |
| 39 | Source performance tab sorting | Call | Pass after fix (DEF-006) | `test_def006_…` |
| 40 | Marketing efficiency tab and summary | Data | Pass after fix (DEF-022); per-source zero-spend display is OPEN-01 | `test_def022_…` |
| 41 | Manage spend: add, edit, delete, validation | GUI, SQL | Pass after fix (DEF-020) | `test_def020_…` |
| 42 | Upcoming meetings | Data | Pass | session |
| 43 | Painted Edit button in each row | GUI | Pass after fix (DEF-008) | `test_def008_lead_rows_…` |
| 44 | Enter or double-click opens the editor | GUI | Pass | session |
| 45 | Row context menu | — | Partial: not exercised on Leads; the shared helper is verified on Clients | `test_def008_client_row_actions_…` |
| 46 | Edit lead dialog: Save persists, Cancel does not | GUI, SQL | Pass | `test_end_to_end_…`; session |
| 47 | Export HTML (button and Ctrl+E), including an unwritable path | GUI, file | Pass after fix (DEF-004) | `test_leads_page_…`; session |
| 48 | Ctrl+F and F5 | GUI | Pass | session |
| 49 | Filter summary text | Data | Pass after fix (DEF-025) | `test_def025_…` |

## Clients

| # | Item | Method | Status | Evidence |
|---:|---|---|---|---|
| 50 | Add client (button and Ctrl+N), validation | GUI, SQL | Pass after fix (DEF-005) | `test_def005_…` |
| 51 | Search | GUI | Pass | `test_clients_page_search_masks_and_exports` |
| 52 | KPI cards (3) | Data | Pass | session |
| 53 | Table sorting and default order | Call | Pass after fix (DEF-006) | `test_def006_…` |
| 54 | Delete key and context menu | GUI | Pass | `test_def008_client_row_actions_…` |
| 55 | Painted View, Edit, Delete buttons | Call | Partial: same delegate as item 43 (GUI-tested there); on Clients the actions ran through page methods | session |
| 56 | Delete: Cancel keeps; Delete cascades sales and unlinks leads | GUI, SQL | Pass | `test_end_to_end_…`; session |
| 57 | Edit client, including the linked-lead tab | GUI, SQL | Pass after fix (DEF-005) | session |
| 58 | Merge duplicates: Cancel, Yes, nothing to merge | GUI, SQL | Pass | session |
| 59 | Profile dialog: masking and reveal, history, export | GUI | Pass after fix (DEF-026) | `test_def026_…`; session |
| 60 | Duplicate names with accents | Call | Pass after fix (DEF-019) | `test_def019_…` |

## Import workflow

| # | Item | Method | Status | Evidence |
|---:|---|---|---|---|
| 61 | Cancel at the file picker | GUI | Pass | session |
| 62 | Cancel during file inspection | GUI | Pass | session |
| 63 | Preview: Cancel and Import data | GUI | Pass | session; `test_end_to_end_…` |
| 64 | Sales, leads, and mixed files | GUI, SQL | Pass | session; `test_end_to_end_…` |
| 65 | Marketing-spend files | GUI, SQL | Pass after fix (DEF-003) | `test_def003_…` |
| 66 | Unsupported schema, binary data, damaged `.xlsx` | GUI | Pass (clear message, nothing written) | session |
| 67 | Partially invalid rows and the rejected-rows CSV | GUI, file | Pass | session |
| 68 | Second import while one is running | GUI | Pass ("already running") | session |
| 69 | Large files (20,000 and 300,000 rows) | Real event loop | Pass | session |

## Reports

| # | Item | Method | Status | Evidence |
|---:|---|---|---|---|
| 70 | Sales, Leads, and Client report content and branding | File | Pass | `test_report_branding.py`; session |
| 71 | Script-injection payloads from imported data | File | Pass (all escaped) | session |
| 72 | English dates under a non-English locale | File, unit | Pass after fix (DEF-007) | `test_def007_…` |

## Themes and rendering

| # | Item | Method | Status | Evidence |
|---:|---|---|---|---|
| 73 | Light and dark themes at three window sizes | Visual | Pass after fix (DEF-010, DEF-012–DEF-014, DEF-016) | session |
| 74 | Native Wayland rendering | Visual | Pass | session (2 runs) |
| 75 | User data rendered as plain text | Data | Pass after fix (DEF-025) | `test_def025_…` |
