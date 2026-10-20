# Test execution report

Audit date 2026-10-20. Environment as in [BASELINE_AUDIT.md](BASELINE_AUDIT.md). Every result below was produced by an executed command; nothing is extrapolated.

## Automated checks: baseline and final

| Check | Command | Baseline | Final |
|---|---|---|---|
| Test suite | `poetry run pytest` | 16 passed, then **aborted** (exit 134, core dump) | **47 passed, exit 0** |
| Stability | full suite, repeated | aborted on every run | Final code: 3 of 3 runs exited 0. Earlier code states during the audit: 14 of 14 |
| Lint | `poetry run ruff check .` | passed | passed |
| Types | `poetry run mypy` | passed, 50 files (GUI excluded) | passed, **65 files including `desktop_ui/`, `main.py`, `branding.py`** |
| Security | `poetry run bandit -c pyproject.toml -r . --severity-level medium --confidence-level high` | not run | no findings |
| Dependencies | `poetry run pip-audit` | not run | no known vulnerabilities |
| Metadata | `poetry check` | passed | passed |
| Build | `poetry build` | **failed** | wheel and sdist built; wheel contains all 13 `desktop_ui` modules and the assets |
| Installed wheel | installed with `--no-deps` into an isolated directory, launched with `python -I` | not possible | all pages loaded, exit 0 |
| Coverage | `poetry run pytest --cov` | not measured | 68 % overall; `desktop_ui` modules 79–100 % |

Exit codes were captured directly from pytest (`> log; echo $?`), not from a pipeline.

## Test suites

| File | Tests | Scope |
|---|---:|---|
| `tests/test_app_shell.py` | 3 | Shell, pages, theme toggle, compact navigation, assets |
| `tests/test_core_workflow.py` | 2 | Real import → analytics on the sandbox database; dry run |
| `tests/test_pyside_crm_pages.py` | 2 | Leads and Clients pages with injected controllers |
| `tests/test_pyside_sales_page.py` | 2 | Sales rendering, filters, sorting, export |
| `tests/test_query_scaling.py` | 4 | SQL statement counts independent of dataset size |
| `tests/test_report_branding.py` | 3 | Report branding and masking |
| `tests/test_audit_regressions.py` | 31 | One or more tests per defect in [DEFECT_LOG.md](DEFECT_LOG.md), plus an end-to-end workflow |

The end-to-end test imports sales and leads through the real file dialog and preview, checks the Dashboard and Sales figures, edits a lead through its dialog, cancels and then confirms a client deletion (verifying the cascade), and opens a fresh window to confirm persistence.

One existing test changed intentionally: `test_leads_page_filters_and_exports_current_snapshot` now waits for the debounced search (DEF-008) instead of asserting synchronously.

## Mutation checks

Each defect was reintroduced in a scratch copy of the repository and the matching test was run there.

| Defect reintroduced | Test result on the defective copy |
|---|---|
| DEF-001 layouts populated before attaching | ownership audit failed (the subprocess crash test passed in that run; the abort is probabilistic) |
| DEF-003 leads detected before spend | 3 tests failed |
| DEF-004 page-level error pop-up restored | failed |
| DEF-006 text-only sort items | failed |
| DEF-007 `strftime("%b")` month names | failed |
| DEF-008 per-cell column re-measurement | failed (the run took 280 s, showing the quadratic cost) |
| DEF-009 `Expanding` chart label | failed |
| DEF-021 label-based bar positions | failed |
| DEF-024 original focus rules | failed: `navigation: focus ring contrast 1.00:1` |
| DEF-026 lambda on the Export button | failed: `client profile` dialog left behind |

## GUI and workflow execution beyond the suite

Exploratory scripts drove the real `MainWindow` against scratch databases. Results were cross-checked against SQL where data was involved:

- Leads KPIs (302 leads, 112 meetings, 48 converted, 59 lost) and every tested filter combination matched SQL counts exactly; the Sales "This year" filter matched SQL (133,996 rows).
- Imports: valid sales, leads, mixed sales-and-leads, and spend files; unsupported schema, binary data, and a damaged `.xlsx` (clear message, nothing written); a partially invalid file (1 row imported, 3 written to `failed_rows_*.csv` with reasons); cancel at the file picker, at inspection, and at the preview; a second import while one was running ("already running" message).
- Throughput through the real event loop: 20,000 rows imported in 0.4 s; a 300,000-row (13.7 MB) file inspected in about 2.9 s and imported in about 1.9 s. Closing the window during that import was refused with "Import in progress"; after it finished, the app closed with exit code 0.
- HTML reports with `<script>`, `<img onerror>`, and `<svg onload>` payloads imported through the importer: every payload was escaped in all three reports.
- Startup with an unwritable data directory: the error was logged, a "startup error" dialog explained it, and the process exited with code 1.
- Native platform: two runs on the Wayland session (HDMI-1, 1920 × 1080, DPR 1.0) opened every page with the window visible and active and exited with code 0.

## Test-harness findings (not application defects)

These affected only how the tests drive Qt. They are recorded so future tests avoid them.

| Issue | Effect | Resolution in `tests/qt_helpers.py` |
|---|---|---|
| Dialog wrappers tracked by `id()` | Qt's static dialogs reuse wrapper ids, so a second dialog was never answered and the run hung | Dialogs are marked with a Qt dynamic property |
| Retained dialog references | After `exec()` PySide hands parented dialogs to Python; a retained reference left them owned twice and could crash at exit | No dialog references are kept; the poll timer is disconnected on exit |
| `QTest.qWait` holds the GIL | A 0.4 s import never finished within 60 s in the test process | `wait_until` sleeps with `time.sleep`, which releases the GIL |
| `QFileDialog.selectFile()` + `accept()` | Rejected before the dialog's file model loaded | The helper types the path and presses Return |
| Offscreen window activation | After modals, the offscreen window is not re-activated, so window-scoped shortcuts (F5) do not fire | Shortcuts were verified on a freshly activated window; F5 refreshes Leads and Clients |
| Pre-existing test isolation | Tests wrote the developer's real `QSettings` (DEF-018) | `XDG_CONFIG_HOME` sandboxed; `ThemeManager` honours test redirects |

## Not executed, and why

| Area | Reason |
|---|---|
| Windows and macOS | No such hosts available |
| Device-pixel ratio above 1 and fractional scaling | Only a DPR 1.0 screen was available |
| Screen readers (Orca, NVDA, VoiceOver) | Not available; accessible names were checked in code only |
| Operating-system file pickers | Under the offscreen platform Qt uses its own dialog; native pickers were not driven |
| **Open report** in the browser | Not executed, to avoid launching a browser on the user's desktop |
| Printing exported reports | No printer workflow available |
| Several app instances writing one database | Not tested (see OPEN-08 in the defect log) |
| Installers and auto-update | The repository defines none |
