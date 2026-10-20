# Defect log

Severity: **P1** core workflow blocked, crash, or corrupted data · **P2** important feature broken or significant usability/performance issue · **P3** minor or cosmetic.

Status: **Verified** means the defect was reproduced, fixed, and the fix confirmed by a test or measurement. Regression tests live in `tests/test_audit_regressions.py` and are named after the defect ID (for example `test_def003_…`). "Mutation-checked" means the test was shown to fail when the defect was reintroduced in a scratch copy.

## Summary

| ID | Sev. | Defect | Status |
|---|---|---|---|
| DEF-001 | P1 | Interpreter aborted (heap corruption) after a rendered Sales page was destroyed; `pytest` exited 134 | Verified, mutation-checked |
| DEF-002 | P1 | `poetry build` failed; the package list omitted the GUI | Verified |
| DEF-003 | P1 | Marketing-spend files, including the app's own template, were imported as leads | Verified, mutation-checked |
| DEF-004 | P2 | Every Leads/Clients error opened two identical modal dialogs | Verified, mutation-checked |
| DEF-005 | P2 | Client form closed before server-side validation, discarding the user's input | Verified |
| DEF-006 | P2 | Numeric columns sorted as text; tables opened in accidental orders | Verified, mutation-checked |
| DEF-007 | P2 | OS locale leaked into English UI and reports; an Urdu month scrambled the dashboard sentence | Verified, mutation-checked |
| DEF-008 | P2 | Leads/Clients refresh was quadratic with one widget per row; row buttons clipped | Verified, mutation-checked |
| DEF-009 | P2 | Sales page overflowed horizontally at the minimum window size; charts never shrank | Verified, mutation-checked |
| DEF-010 | P3 | Product name and tagline clipped in the sidebar at the default window size | Verified |
| DEF-011 | P2 | Leads filter drop-downs had no visible labels | Verified |
| DEF-012 | P3 | Stale column stretch after responsive reflow left empty columns and a stretched button | Verified (visual) |
| DEF-013 | P3 | No drop-down arrows on combos/date fields; disabled fields looked enabled | Verified (visual) |
| DEF-014 | P3 | Dark-mode "Delete" text measured about 2.5:1 contrast | Verified (calculated, visual) |
| DEF-015 | P3 | Theme toggle label was wrong after restarting in dark mode | Verified |
| DEF-016 | P2 | Mismatched stock navigation icons; the Sales icon was invisible on the dark sidebar | Verified |
| DEF-017 | P3 | One WARNING per inconsistent lead on every refresh flooded the log | Verified |
| DEF-018 | P2 | Running the test suite overwrote the developer's saved theme preference | Verified |
| DEF-019 | P3 | Duplicate client-name check ignored case only for ASCII letters | Verified |
| DEF-020 | P2 | Marketing spend editor lost in the migration; spend could not be corrected or deleted | Verified |
| DEF-021 | P2 | Sales "Top clients" lost in the migration; bar charts merged equal labels | Verified, mutation-checked |
| DEF-022 | P3 | Leads marketing summary (spend, revenue, CPL, CAC, ROI) lost in the migration | Verified |
| DEF-023 | P3 | "Any date" calendar opened on January 1900 | Verified |
| DEF-024 | P2 | Keyboard focus invisible on navigation and filled buttons; 1.5:1 ring on light inputs | Verified, mutation-checked |
| DEF-025 | P3 | Names and search text that looked like HTML were rendered as rich text | Verified |
| DEF-026 | P2 | Client profile dialog was never released, leaking memory and risking a crash at exit | Verified, mutation-checked |
| DEF-027 | P3 | Responsive reflow and context menus leaked Qt objects | Verified |

No P1 or P2 defect found during the audit remains open.

## Details

### DEF-001 · P1 · Abort while destroying the Sales page
- **Reproduction:** `pytest tests/test_pyside_sales_page.py` aborted in 9 of 10 runs; under glibc malloc checking, gdb showed a segfault in `QObject::~QObject` inside PySide's exit cleanup.
- **Root cause:** Widgets were added to nested layouts *before* those layouts were attached to a parent widget. PySide only transfers ownership to the widget tree when the layout already has a parent, so 15 widgets were owned by both Python and Qt and could be freed twice.
- **Fix:** `SalesPage._build_ui` attaches each nested layout before populating it (`desktop_ui/pages/sales_page.py`). Visual order is unchanged.
- **Verification:** 0 aborts in 20 runs (previously 9 in 10). `test_def001_widgets_are_owned_by_their_qt_parents` audits ownership deterministically across the shell and dialogs and fails on the original code. A subprocess smoke test also destroys rendered pages, but the abort is probabilistic, so the ownership audit is the primary guard.

### DEF-002 · P1 · Broken package build
- **Reproduction:** `poetry build` → `components does not contain any element`.
- **Root cause:** `pyproject.toml` still listed the deleted `components`, `theme`, `ui`, and `views` packages and did not list `desktop_ui`.
- **Fix:** Package list updated; `desktop_ui`, `main.py`, and `branding.py` added to mypy's scope.
- **Verification:** Build succeeds; the wheel contains all 13 `desktop_ui` modules and the assets. The wheel was installed into an isolated directory and launched in isolated mode outside the repository: all pages loaded, exit code 0.

### DEF-003 · P1 · Spend files imported as leads
- **Reproduction:** Importing the dashboard's own "Spend CSV" template (`source, amount, date`) added 60 rows to `leads` and none to `marketing_spend`.
- **Root cause:** Detection checked leads before spend, and the generic `date` alias satisfies the lead `created_at` column, so spend files also "fit" the lead schema.
- **Fix:** `core/importer.py` prefers marketing spend when the file has a spend amount column and no lead-only header (lead IDs, status, meeting date, client ID, explicit creation time).
- **Verification:** All three templates and four realistic platform exports are classified correctly; the GUI round trip (download the template, import it) writes 2 spend rows and 0 leads.

### DEF-004 · P2 · Duplicate error dialogs
- **Reproduction:** Saving an invalid client or exporting to an unwritable path showed the same error twice.
- **Root cause:** Leads and Clients showed their own `QMessageBox` and also emitted the error to the shell, which showed another.
- **Fix:** Pages report; `MainWindow.show_status` is the single owner of error pop-ups.
- **Verification:** Exactly one dialog per error.

### DEF-005 · P2 · Client form discarded input
- **Reproduction:** Entering an invalid email closed the form, then showed the error; everything typed was lost.
- **Root cause:** The dialog only checked name length before closing; the controller validated afterwards.
- **Fix:** `ClientFormDialog` runs the save through an `on_submit` callback while open, shows rejections inline, disables Save during submission, and closes only on success. The duplicate-name message now suggests renaming or using **Merge duplicates**.
- **Verification:** The form stays open with the error and the user's text, then saves after correction (database checked).

### DEF-006 · P2 · Numeric sorting and default order
- **Reproduction:** Sorting the Leads "Leads" column descending gave `60, 55, 47, 32, 106`; Clients opened sorted by ID descending.
- **Root cause:** `QTableWidgetItem` compares display text. Enabling sorting re-sorted by column 0 descending. A fallback in the Sales page's numeric item called `super().__lt__`, which PySide routes back into the override (infinite recursion, latent).
- **Fix:** Shared `SortableItem`/`sortable_item` with a dedicated sort role and a text fallback that does not recurse; explicit default orders (clients by name, leads newest first, sources and spend by volume, products by total).
- **Verification:** Numeric columns sort by value; default orders asserted.

### DEF-007 · P2 · Locale leaked into English text
- **Reproduction:** With `LC_TIME=ur_PK`, the dashboard read "Last import: 20 600 .16:48 ,2026 اکتوبر sales rows…", and reports said "Generated on اکتوبر 20, 2026 5:17 ش".
- **Root cause:** Qt calls `setlocale()` at startup, so `strftime("%b")` and `"%p"` follow the OS locale; the right-to-left month name triggers bidirectional reordering.
- **Fix:** Locale-independent month abbreviations and AM/PM in `utils/formatting.py`, used by the dashboard, chart labels (`analysis/time_grouping.py`), and all reports.
- **Verification:** Test under a real non-English locale (skips where none is installed).

### DEF-008 · P2 · Quadratic tables with a widget per row
- **Reproduction:** With 5,000 leads, each search keystroke took about 525 ms and the session peaked at 927 MB. View/Edit/Delete buttons overflowed the row height.
- **Root cause:** One `QToolButton` cell widget per row, rebuilt on every filter change; and each `setItem` on a visible `ResizeToContents` table re-measured the whole column.
- **Fix:** `RowActionDelegate` paints the buttons and hit-tests clicks; Enter, double-click, the context menu, and the Delete key give keyboard access. `bulk_table_update` suspends sizing and sorting while filling, then sizes once. Leads search is debounced by 200 ms (Enter applies immediately).
- **Verification:** See [PERFORMANCE_AUDIT.md](PERFORMANCE_AUDIT.md). The test asserts no per-row widgets and bounded `sizeHint` calls, and that clicking a painted button opens the editor.

### DEF-009 · P2 · Horizontal overflow at the minimum window
- **Reproduction:** At 760 × 600 the Sales page scrolled horizontally and hid **Open report**.
- **Root cause:** Charts are `QLabel` pixmaps, and a label's minimum size is its pixmap size, so a chart could grow but never shrink (minimum 716 px against a 670 px viewport).
- **Fix:** `Ignored` size policy on the chart label; the pixmap is rescaled to the space the layout grants.
- **Verification:** Page minimum width 474 px; the test shrinks from 1360 to 760 px and asserts no horizontal scroll bar.

### DEF-010 · P3 · Clipped product name
Logo reduced to 36 px and the name to 18 px so "Techset LeadGen" and its tagline fit the sidebar. Test asserts the label's width covers its size hint.

### DEF-011 · P2 · Unlabeled Leads filters
Three drop-downs all read "All"/"All time". Added visible, buddy-linked labels (Search, Source, Stage, Period) via the shared `labeled_field()` helper. Test asserts the label for each control.

### DEF-012 · P3 · Stale column stretch
When the layout switched to fewer columns, stretch factors on unused columns remained, leaving empty half-width columns (Leads) and a stretched **Add client** (Clients). Reflow now resets every column. Verified with screenshots while resizing 1360 → 760 → 1360 px.

### DEF-013 · P3 · Missing drop-down affordances
The stylesheet hid the native arrows and left the date-edit buttons unstyled; disabled fields looked enabled. Added chevron SVGs (`assets/icons/`) and muted disabled styles. Verified in screenshots on both themes and on Wayland.

### DEF-014 · P3 · Dark-mode destructive text contrast
`#BA1A1A` on the dark surface is about 2.5:1. The row-action delegate uses `#FFB4AB` on dark surfaces (well above 4.5:1). Verified visually.

### DEF-015 · P3 · Theme toggle label after restart
The label was only updated on toggle, so a persisted dark theme started with "Dark mode". The shell now derives the label from the theme and listens to `theme_changed`. Test asserts the label with a persisted dark setting.

### DEF-016 · P2 · Navigation icons
Stock pixmaps (monitor, arrow, check mark, list) did not describe the pages; the black arrow vanished on the dark sidebar, where compact mode shows icons only. Replaced with painted line icons in the active text color (`desktop_ui/icons.py`). Test asserts icons change with the theme.

### DEF-017 · P3 · Log flooding
One WARNING per inconsistent lead on every load (388 lines, 44,672 bytes for a single load of 5,000 leads). Now one summary warning per load with counts and example IDs; per-lead detail at DEBUG. Session log: 344 bytes.

### DEF-018 · P2 · Tests overwrote the real saved theme
`test_app_shell` redirected `IniFormat` paths, but `ThemeManager` used the native-format constructor, so every `pytest` run wrote `dark=true` to `~/.config/Techset Solutions/Techset LeadGen.conf`. `ThemeManager` now uses `QSettings.defaultFormat()` explicitly (native in production) and the root `conftest.py` sandboxes `XDG_CONFIG_HOME`. Verified: the real file's modification time is unchanged by a full run. **Note:** runs before this fix, including the audit's own, set that file to `dark=true`; reset the theme in the app if needed.

### DEF-019 · P3 · ASCII-only duplicate detection
SQLite's `LOWER()` folds ASCII only, so "CAFÉ MÜLLER" was accepted next to "Café Müller". Comparison now uses Python `casefold()`. Test covers accented variants and editing a client's own name.

### DEF-020 · P2 · Spend editor missing
The Flet UI had an add/edit/delete editor; the PySide6 UI had none (the controller API already existed). Since spend imports are additive and the dashboard cannot clear spend, a wrong amount could not be fixed. Restored as **Leads → Marketing efficiency → Manage spend…** (`marketing_spend_dialog.py`) with inline validation that keeps input, European number formats, delete confirmation, and recalculation on close. Test covers invalid input, add, edit, delete-cancel, and delete.

### DEF-021 · P2 · Top clients missing; merged bars
The snapshot computed `top_clients` but nothing displayed it (the HTML report did). Added a **Top clients** chart tab. Bars are plotted at numeric positions because Matplotlib merges equal category labels (two clients both named "Acme Ltd", or two products truncated to the same 25 characters). Test asserts distinct bar positions.

### DEF-022 · P3 · Marketing summary missing
Spend, attributed revenue, CPL, CAC, and ROI for the active filters are shown above the per-source table; ratios read "—" when there is no spend. The summary reflows to three columns on narrow windows.

### DEF-023 · P3 · Calendar opened on January 1900
"Any date" is stored as the editor's minimum date, so the popup opened 126 years back. An event filter opens it on the current month without changing the value. Test clicks the drop-down and checks the page shown.

### DEF-024 · P2 · Invisible keyboard focus
Variant rules with ID selectors outranked the generic `:focus` rule, so navigation, primary, gold, and red buttons drew their focus border in their own fill color; gold rings on white inputs measured about 1.5:1. Focus colors are now chosen per variant. Measured on rendered pixels, every focus state differs from the unfocused edge by 3.02:1 to 10.79:1 across both themes. Test measures six control variants in both themes.

### DEF-025 · P3 · User data rendered as rich text
Qt labels default to `AutoText`, so a client named `<b>Bold</b>` or a search for `<h1>x</h1>` was formatted. Labels and dialogs that show user data now use plain text. Test covers the profile dialog and the Leads filter summary.

### DEF-026 · P2 · Profile dialog never released
- **Reproduction:** After viewing a client profile, the dialog stayed alive as a child of the Clients page, owned by both Python and Qt: the condition behind DEF-001's exit crash. (The exit crash observed during the audit also involved references held by the test helper, which was fixed separately.)
- **Root cause:** In PySide6 6.12, `QDialog.exec()` hands a parented dialog's ownership to Python. The profile's Export button was connected with a lambda capturing the dialog, which PySide keeps alive, so the dialog was never freed and ended up owned by both Python and its parent.
- **Fix:** Connect a bound method instead (`ClientDetailDialog._request_export`).
- **Verification:** Every dialog flow (profile, client add/edit/delete, lead edit, spend editor, error dialog) leaves no dialog or doubly-owned object behind; the test fails with the lambda restored.

### DEF-027 · P3 · Small Qt object leaks
`QLayout.takeAt()` returns C++-owned items in PySide, so each responsive reflow leaked them; replaced with `removeWidget()`. Each right-click leaked a `QMenu`; it is now deleted after use (0 left after three right-clicks).

## Open backlog (not fixed)

| ID | Sev. | Observation | Recommendation |
|---|---|---|---|
| OPEN-01 | P3 | Per-source marketing rows (screen and Leads report) show €0.00 CPL/CAC and 0.0% ROI where spend is zero, which reads as "free leads" | Show "—" for undefined ratios, as the new summary does |
| OPEN-02 | P3 | Wheel installs resolve the default `data/` and `logs/` inside `site-packages`, and install generic top-level packages (`core`, `utils`, …) | Documented in README; consider a per-user data directory and a package namespace |
| OPEN-03 | P3 | `flet`, `flet-desktop`, `flet-charts`, `flet-cli`, `flet-web`, the FastAPI pin, and `utils/ui_dispatch.py` are no longer used by any module | `poetry remove` the packages (regenerates the lock file) and delete the module |
| OPEN-04 | P3 | Compiled `__pycache__/*.pyc` files are tracked in git, so any test run modifies tracked files | `git rm -r --cached` them and add a `.gitignore` |
| OPEN-05 | P3 | Dashboard maintenance cannot clear all marketing spend at once | Add "Clear spend" if bulk removal is needed |
| OPEN-06 | P3 | At narrow widths the stretched first column of wide tables (for example the marketing Source column) is squeezed; the table scrolls inside its frame | Set a minimum width for the first column |
| OPEN-07 | P3 | Rejected-row CSVs write raw cell values; values starting with `=`, `+`, `-`, or `@` could be evaluated if opened in a spreadsheet. The values come from the user's own import file | Prefix such values with `'` when writing the file |
| OPEN-08 | P3 | Several instances of the app on one database are not coordinated: the import lock is per process and SQLite waits only 5 s | Document single-instance use or add a single-instance guard |
