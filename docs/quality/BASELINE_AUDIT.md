# Baseline audit

Techset LeadGen desktop application · audit date 2026-10-20 · branch `main` at `f99a58e` plus the uncommitted Flet → PySide6 migration in the working tree.

This document records the state **before** the audit changed anything. The other files in this folder record what changed and how it was verified.

## Environment

| Item | Value |
|---|---|
| Operating system | Linux 6.8, glibc 2.35, Wayland session, one 1920 × 1080 screen at device-pixel ratio 1.0 |
| Python | 3.15.0 in the project's Poetry environment |
| Qt binding | PySide6 and shiboken6 6.12.0 |
| Tooling | Poetry 2.4.1, pytest 9.1.1, ruff 0.17.1, mypy 2.4.0, bandit 1.9.4, pip-audit 2.10.1 |

## Working tree at the start

The Flet interface (`components/`, `ui/`, `views/`, `theme/`, and four `utils/` modules) had been deleted but not committed. Its PySide6 replacement in `desktop_ui/` was untracked, as were `tests/` and `docs/`. Tracked `__pycache__/*.pyc` files were already modified. The audit did not revert or discard any of these changes.

## Architecture as found

Techset LeadGen is a single-process, local-first desktop application. It has no server, network calls, authentication, or cloud storage.

| Layer | Location | Responsibility |
|---|---|---|
| Entry point | `main.py` | Logging, `QApplication`, database initialization, theme, main window, startup error dialog |
| GUI | `desktop_ui/` | Sidebar shell with lazily created Dashboard, Sales, Leads, and Clients pages; import bridge with background file inspection |
| Coordination | `controllers/`, `services/` | Filters, validation, analysis snapshots, background import worker with a process-wide lock |
| Data | `analysis/`, `models/`, `core/` | SQLite (WAL mode, foreign keys), CSV/XLSX import engine |
| Output | `reports/` | Self-contained HTML reports with embedded Matplotlib charts |

The project database `data/sales.db` existed with every table empty. The audit never wrote to it: all testing used scratch copies selected through `FDT_DATA_DIR`, `FDT_LOG_DIR`, and `XDG_CONFIG_HOME`.

## Baseline checks

| Check | Command | Result |
|---|---|---|
| Test suite | `poetry run pytest` | 16 tests passed, then the interpreter aborted with `malloc_consolidate(): unaligned fastbin chunk detected` (exit code 134, core dump) |
| Crash isolation | `pytest tests/test_pyside_sales_page.py`, repeated | Aborted in 3 of 3 runs, then in 9 of 10 |
| Lint | `poetry run ruff check .` | Passed |
| Type check | `poetry run mypy` | Passed for 50 files; `desktop_ui/`, `main.py`, and `branding.py` were not in scope |
| Package metadata | `poetry check` | Passed |
| Package build | `poetry build` | **Failed:** `components does not contain any element` |
| Security scans | bandit, pip-audit | Not run before changes. First run after changes; the audit did not change dependencies |
| Application launch | Real entry point, offscreen, visiting all pages and closing | Exit code 0 in 15 of 15 runs |

## Critical risks at baseline

1. **The test suite could not pass in CI.** Every run aborted after the tests had passed, which indicated heap corruption in the GUI layer.
2. **The application could not be packaged.** The build failed, and the package list did not include the new GUI at all.
3. **The documentation described the retired Flet interface**, including setup steps, the module map, and the threading model.

## Verification strategy

- Drive the real widgets headlessly (`QT_QPA_PLATFORM=offscreen`) with `QTest`. `tests/qt_helpers.ModalPilot` answers the production dialogs (message boxes, file pickers, forms) instead of mocking them.
- Run the real entry point end to end, and repeat smoke runs on the native Wayland session.
- Build datasets with a deterministic generator and load them through the application's own importer: 600 sales, 300 leads, and 41 clients; 20,000 sales, 5,000 leads, and 400 clients; and a 300,000-row file for import throughput.
- For each defect: reproduce it, find the root cause, fix it, add a regression test, and rerun the suite. Key regression tests were mutation-checked by reintroducing the defect in a scratch copy and confirming that the test fails.
