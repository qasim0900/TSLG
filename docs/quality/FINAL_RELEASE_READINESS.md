# Final release readiness

Audit date 2026-10-20 · Techset LeadGen 0.1.0 (PySide6 desktop) · Linux 6.8, Python 3.15, PySide6 6.12.

## Recommendation: READY FOR RELEASE REVIEW

Every P1 and P2 defect found during the audit is fixed and verified by a regression test, the suite passes repeatedly with exit code 0, the package builds and runs from an installed wheel, and the primary workflows pass end to end against a real database. The recommendation is limited to **Linux** (the only platform available) and to the **current working tree**, which is not yet committed. The risks below are for the release reviewers to accept or address.

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| Builds in the available environment | Met | `poetry build` produces a wheel containing all 13 GUI modules (failed at baseline) |
| Launches and completes primary workflows | Met | Real entry point exited 0 on the final code (3 offscreen runs) and on Wayland (2 runs during the audit); end-to-end test covers import → analytics → edit → delete → restart |
| Every discovered interactive item has an explicit status | Met | 75 items: 46 Pass, 25 Pass after fix, 3 Partial, 1 Not tested ([GUI_TEST_INVENTORY.md](GUI_TEST_INVENTORY.md)) |
| Critical and high-severity defects fixed and verified | Met | 3 P1 and 13 P2 defects verified; 10 key tests mutation-checked ([DEFECT_LOG.md](DEFECT_LOG.md)) |
| Important workflows pass end to end | Met | Import (all file types, failures, cancel, concurrency), sales analysis and comparison, lead editing, spend editing, client CRUD and merge, all three reports |
| Regression tests pass | Met | 47 tests; the final code passed 3 of 3 full runs with exit 0 ([TEST_EXECUTION_REPORT.md](TEST_EXECUTION_REPORT.md)) |
| No unexplained new failures | Met | ruff, mypy (65 files, now including the GUI), bandit, and pip-audit are clean |
| Data integrity and persistence | Met | KPIs and filters cross-checked with SQL; delete cascade, cancel paths, and persistence after reopening verified; spend no longer imported as leads |
| N+1 issues resolved or documented | Met | None at the database level (statement counts constant from small to large datasets); the GUI-level quadratic cost was fixed ([PERFORMANCE_AUDIT.md](PERFORMANCE_AUDIT.md)) |
| Major UI/UX and accessibility issues addressed | Met | Focus visibility, labels, contrast, layout at the minimum size, locale-safe dates ([UI_UX_AUDIT.md](UI_UX_AUDIT.md)) |
| Security boundaries reviewed | Met | No network access; imported text is escaped in HTML reports (script payloads tested); plain-text rendering of user data in the UI; parameterized SQL; bandit and pip-audit clean |
| Packaging and startup verified for testable targets | Met for Linux | Wheel installed in isolation and launched; startup failure shows a dialog and exits with code 1 |
| Limitations documented | Met | Below and in the test report |

## Remaining risks

1. **Platforms not verified.** Windows, macOS, scaling above 1.0, screen readers, operating-system file pickers, printing, and opening reports in the browser were not exercised.
2. **Uncommitted migration.** The Flet → PySide6 migration and every audit change are in the working tree only. Review the full diff before committing; compiled `__pycache__` files are tracked in git and change with every run (OPEN-04).
3. **Legacy dependencies.** Flet packages and a FastAPI pin are still declared but unused (OPEN-03). They enlarge installs but do not run.
4. **Wheel installs.** Default data and log folders resolve inside `site-packages`, and the top-level package names are generic (OPEN-02). Set `FDT_DATA_DIR` and `FDT_LOG_DIR`, and install into a dedicated virtual environment.
5. **Single-instance assumption.** Several instances on one database are not coordinated (OPEN-08). Three instances were running on the audit machine during testing; they were not touched.
6. **Saved theme preference.** Test runs before the DEF-018 fix, including early runs in this audit, set the real `Techset LeadGen.conf` to `dark=true`. Reset the theme in the app if that is not the intended choice.
7. **Remaining P3 items:** zero-spend ratios shown as €0.00 per source (OPEN-01), no bulk "Clear spend" (OPEN-05), squeezed first column in wide tables at narrow widths (OPEN-06), and rejected-row CSVs not guarded against spreadsheet formulas (OPEN-07).

## Recommended next steps before release

1. Review and commit the working tree; stop tracking `__pycache__`.
2. Run the suite and a smoke test on Windows and macOS, including the operating-system file pickers and **Open report**.
3. Remove the unused Flet dependencies with `poetry remove`, then rebuild and rerun the checks.
4. Decide on a per-user data directory for wheel installs, or document the environment variables in the release notes.
