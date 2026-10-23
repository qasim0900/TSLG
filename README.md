# Techset LeadGen

Techset LeadGen is a local-first, native desktop application for sales analytics, lead operations, client records, follow-ups, and branded reporting. It uses Python, PySide6 (Qt Widgets), SQLite, Polars, and Matplotlib. It is not a web application and does not require a browser for its primary interface.

The product keeps the established Techset Solutions identity: the official logo and icon, green/gold palette, warm light surfaces, dark mode, and the bundled Plus Jakarta Sans and JetBrains Mono typefaces.

## One application, one navigation system

There is no separate CRM tab and no second copy of Dashboard, Sales, Leads, or Clients. The `crm/` directory is an internal business-service and persistence package; it is not another frontend.

The signed-in desktop shell exposes these areas according to the user's role:

| Area | Responsibility |
|---|---|
| **Dashboard** | Real sales/client/lead KPIs, the signed-in user's work, the weekly revenue trend, import shortcuts, and templates. |
| **Sales** | Date/client/product filters, totals, product and client rankings, trend charts, period comparison, and HTML export. |
| **Leads** | The existing funnel and marketing analytics plus lead creation, assignment, stage changes, timelines, meetings, and follow-ups on the same lead rows. |
| **Clients** | Search, client CRUD, sales/lead context, contacts, activity, tasks, duplicate merge, and client-profile export. |
| **Tasks** | Paged personal/team follow-ups linked to leads and clients. |
| **Users** | Administrator account invitation, roles, activation/reset codes, and account status. |
| **Audit log** | Administrator view of sign-ins and record changes. Entries are read-only. |
| **Settings** | Profile, password, organization, session, database, and backup information, plus a permission-gated **Danger zone** for clearing sales, leads, or clients. |

Global search opens a matching lead in Leads or a matching company/contact in Clients; it does not create a parallel record view.

## Security and roles

The first launch asks for the organization name and creates the first Super Admin. Later launches open the sign-in screen. Passwords must pass four rules, checked locally (length, not only numbers, not on the bundled common-password list, not like the user's name or email; see `crm/security/passwords.py` and `crm/security/COMMON_PASSWORDS.md`). They are stored as Argon2 hashes, session tokens are kept only in memory and hashed in the database, repeated failed sign-ins are throttled, and sessions can be revoked.

Available roles are Super Admin, Sales Manager, Lead Researcher, BDR, Account Executive, Marketing, and Read Only. Navigation visibility is a convenience; service methods enforce the same permissions again at the data boundary. Sensitive client fields are masked for roles without the corresponding permission.

Invitation and password-reset codes are intentionally displayed to an administrator for out-of-band delivery. This local desktop build does not send email.

## Data architecture

The active database is one SQLite file: `data/sales.db` by default. Sales, clients, leads, contacts, tasks, accounts, and the audit trail all live there.

- The original analytics/import code uses short-lived `sqlite3` connections.
- Authenticated record workflows use SQLAlchemy services mapped onto the same `clients` and `leads` tables.
- Alembic manages the unified account/workflow schema.
- Startup takes a consistent SQLite backup before an existing schema is changed.
- WAL mode and foreign-key enforcement are enabled.

`data/crm.db`, when present, is an untouched legacy input from an earlier standalone implementation. It is never the live store during normal startup. Compatible organization/account data can be carried forward once. A legacy file containing unsupported business records is rejected rather than silently discarding them.

Runtime databases, WAL/SHM files, rejected-row exports, and backups are local data and must not be committed or bundled into a release. If this checkout already tracks a database, review and remove it from version control separately without deleting the user's local copy.

See [Architecture](docs/ARCHITECTURE.md), [Schema](core/SCHEMA.md), and the [current unified-desktop audit](docs/quality/UNIFIED_DESKTOP_AUDIT_2026-10-21.md).

## Installation and launch

Prerequisites:

- Python 3.12 or newer, but lower than 3.16
- Poetry 2.x
- A desktop session supported by Qt 6

From the project root:

```bash
poetry install
poetry run python main.py
```

The package also declares a GUI launcher:

```bash
poetry run techset-leadgen
```

Useful command-line operations:

```bash
poetry run python main.py --version
poetry run python main.py --issue-reset-code person@example.com
```

The reset-code command prints a one-time code for an administrator to deliver securely. On Linux, a missing `xcb` platform-plugin dependency may require the distribution's Qt runtime packages (for example `libxcb-cursor0` on Debian/Ubuntu).

## First-run workflow

1. Launch the application. It migrates the local database only after making any required pre-migration backup.
2. Enter the organization name, first administrator's name and work email, and a password of at least 8 characters that is not only numbers, not a common password, and not like the name or email.
3. Import a `.csv` or `.xlsx` file from Dashboard or Sales.
4. Use the existing Sales, Leads, and Clients areas; add Tasks or invite Users as permitted.
5. Use Settings → **Back up now…** before moving the installation or performing manual maintenance.

The default window is 1360 × 860 and supports a 760 × 600 minimum. The sidebar collapses to icon buttons at compact widths; tooltips and accessible names retain the labels.

## Import formats

The desktop importer inspects the file in a worker so the interface remains responsive. It previews the detected type and schema before writing accepted rows in a transaction.

| Detected type | Required logical columns | Optional logical columns |
|---|---|---|
| Sales | `client_name`, `client_id`, `product_type`, `price` | `date` |
| Leads | `created_at`, `source` | `external_id`, `status`, `meeting_date`, `client_id` |
| Marketing spend | `source`, `amount` | `date` |
| Mixed sales/leads | Both required sets | The optional columns above |

CSV detection supports UTF-8, UTF-8 with BOM, Windows-1252, and comma/semicolon/tab/pipe delimiters. Excel `.xlsx` is supported; the importer also understands `.xlsm` when invoked directly. The maximum file size is 50 MB.

Important behavior:

- Missing sales or spend dates default to the current date.
- Sales imports create missing client rows.
- Lead source and stage names are normalized to the shared application vocabulary.
- `(external_id, source)` prevents duplicate lead imports when an external ID exists.
- Mixed imports write sales first so their clients can be linked to leads.
- Invalid rows are written to a local `failed_*.csv` with a reason; valid rows can still commit.
- Sales and spend imports are additive.

Use ISO `YYYY-MM-DD` dates for unambiguous results. Slash-form dates are interpreted day-first.

## Reports

Sales, Leads, and Client exports are self-contained branded HTML documents. Report data comes from the same active snapshot shown in the desktop screen; report generation does not query a parallel CRM store or upload anything. Matplotlib charts are embedded as base64 images.

The operating system may open an exported report in the default browser, but the application itself remains a Qt desktop application.

## Configuration

The following environment variables are compatibility interfaces and should not be renamed casually:

| Variable | Default | Purpose |
|---|---|---|
| `FDT_DATA_DIR` | `<project>/data` | Directory containing the active `sales.db` and rejected-row files. |
| `FDT_LOG_DIR` | `<project>/logs` | Directory containing rotating application/import logs. |
| `TSLG_LOG_LEVEL` | `INFO` | Application log level; takes precedence over legacy `FDT_LOG_LEVEL`. |
| `FDT_LOG_LEVEL` | `INFO` | Legacy log-level override. |
| `TSLG_SESSION_IDLE_MINUTES` | `30` | Session idle timeout. |
| `TSLG_SESSION_ABSOLUTE_HOURS` | `12` | Maximum session lifetime. |
| `TSLG_LOGIN_MAX_FAILURES` | `5` | Failed sign-ins allowed in the configured window. |
| `TSLG_LOGIN_WINDOW_MINUTES` | `15` | Failed-sign-in window. |
| `TSLG_TOKEN_TTL_HOURS` | `72` | Invitation/reset-code lifetime. |

For source and wheel installs, point data and logs at user-writable locations when the project/package directory is not writable:

```bash
FDT_DATA_DIR=/path/to/data FDT_LOG_DIR=/path/to/logs poetry run python main.py
```

## Backup and recovery

Use Settings → **Back up now…** for a consistent online SQLite backup. For a manual copy, close the application and copy `sales.db` together with any non-empty `sales.db-wal` and `sales.db-shm` files. Automatic pre-migration backups are placed under the active data directory's `backups/` folder.

Client deletion removes that client's sales, contacts, client-linked activity, and client-linked tasks. Linked leads remain and are detached. Every destructive screen action requires confirmation and permission.

## Development checks

Tests redirect the data directory, log directory, Matplotlib cache, and Qt settings into temporary paths; they do not intentionally modify the repository databases.

```bash
poetry check --lock
poetry build
poetry run pytest
poetry run pytest --cov
poetry run ruff check .
poetry run mypy
poetry run bandit -c pyproject.toml -r . --severity-level medium --confidence-level high
poetry run pip-audit
```

Qt widget tests run with the real PySide6 widgets using the offscreen platform. Native file pickers, operating-system window behavior, and opening a report still require a manual desktop smoke test.

## Windows packaging

PyInstaller builds for the operating system on which it runs. On a clean Windows machine:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

The script installs development dependencies, runs the test suite, builds a windowed one-folder executable, and creates `dist\TechsetLeadGen-<version>-windows.zip`. It is a portable bundle, not an MSI/MSIX installer, and the repository does not currently define code signing or an installer upgrade channel. Test the Windows artifact on Windows before release; a Linux PyInstaller build does not validate Windows behavior.

The executable stores data beside itself unless `FDT_DATA_DIR` is set, so extract/install it to a user-writable location.

## Project map

```text
TSLG/
├── main.py                 # QApplication, logging, startup, small admin CLI
├── branding.py             # Product identity and asset names
├── assets/                 # Official logo/icon, UI fonts, control indicators
├── desktop_ui/             # PySide6 shell, shared UI, dialogs, workflows
│   └── pages/              # Authoritative pages plus distinct admin/work pages
├── crm/                    # Internal auth, permissions, ORM models, services, migrations
├── controllers/            # Existing screen/application controllers
├── services/               # KPI and snapshot assembly
├── analysis/               # SQL/Polars analytics
├── models/                 # Legacy-compatible raw persistence adapters
├── core/                   # SQLite bootstrap, importer, schema documentation
├── reports/                # Branded self-contained HTML reports
├── packaging/              # PyInstaller specification
├── scripts/                # Diagnostics, benchmarks, Windows build
├── tests/                  # Business, database, regression, and real-widget tests
└── docs/                   # Architecture, branding, and quality evidence
```

## Current boundaries

- The default deployment is one local desktop process and one local SQLite database; there is no cloud synchronization.
- The interface is English while some established internal names/comments remain Spanish for compatibility.
- Money is displayed in euros and dates are stored in explicit text/date-time formats documented in the schema.
- Invitation/reset codes require an out-of-band administrator workflow; no mail provider is configured.
- A populated legacy standalone `crm.db` with richer business records needs an explicit migration tool; startup must stop rather than import only part of it.
- Windows packaging must be built and smoke-tested on Windows.

The repository has no root software-license file. The bundled fonts (Plus Jakarta Sans, JetBrains Mono, Inter) are licensed under the SIL Open Font License in `assets/fonts/OFL*.txt`; Techset Solutions brand assets remain subject to the brand owner's rights.
