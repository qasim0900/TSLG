# Unified desktop audit and consolidation — 2026-10-21

This records why the application was consolidated, what was duplicated, the decisions taken, what changed, how it was verified, and what remains open. It complements [Architecture](../ARCHITECTURE.md) and [core/SCHEMA.md](../../core/SCHEMA.md).

## 1. Starting point

- **The original application** (committed): a PySide6 desktop app with four areas — Dashboard, Sales, Leads, Clients — over one SQLite file, `data/sales.db`, written by raw `sqlite3` code in `core/`, `models/`, `analysis/`, and `controllers/`. No accounts or roles.
- **A CRM added earlier the same day** (uncommitted): a business-rule package (`crm/`: Argon2 sign-in, sessions, seven roles, audit trail, companies, contacts, leads with a stage machine, tasks, activities, CSV import/export) in a **second database**, `data/crm.db`, and a **"CRM" sidebar entry with its own tab bar** (Overview, Companies, Contacts, Leads, Tasks, Users, Audit log, Settings).

## 2. Duplication found

| Existing | Duplicate | Verdict | Resolution |
|---|---|---|---|
| Dashboard | CRM Overview | Two dashboards | Overview removed; Dashboard gained **My work** (your tasks, overdue/today, your open leads, unassigned new leads) |
| Leads (`sales.db.leads`) | CRM Leads (`crm.db.leads`) | Same business record in two databases with two stage vocabularies | One `leads` table. The workflow (owner, priority, stage moves with reasons, history, follow-ups, timeline) now runs on the imported lead rows |
| Clients (`sales.db.clients`) | CRM Companies | Same customer record twice | One `clients` table, extended with owner, status, industry, domain, location, notes |
| Clients' contact person/email | CRM Contacts | Extension, not a copy | `contacts` table for additional people, managed in the client profile |
| Import (sales, leads, spend) | CRM CSV import/export | Two import paths | CRM CSV import/export removed; the existing importer is the only import, now permission-checked and audited |
| Sidebar | CRM tab bar | Second navigation system | Removed; one sidebar |

Genuinely new, with no prior equivalent: sign-in and sessions, users and roles, audit log, tasks/follow-ups, activity log, lead qualification and loss reasons with stage history, settings and backups.

## 3. Decisions (made by the product owner)

1. **One local SQLite file** (`data/sales.db`) for every record. The shared-PostgreSQL option built for the separate CRM was dropped: the analytics use SQLite-specific SQL in about 70 places. Several accounts can use one computer; sharing between computers is not supported.
2. **Sign in to open the application**; roles apply everywhere, including analytics, imports, exports, and maintenance.
3. **Lead stages**: the original Lead, Contacted, Meeting, Client, Lost plus **Qualified** and **Nurture**; a reason is required for Qualified and Lost.

## 4. What changed

**Navigation** — Dashboard · Sales · Leads · Clients · Tasks · Users · Audit log · Settings, filtered by role (Ctrl+1…Ctrl+8). The top bar adds search (Ctrl+K: clients, contacts, leads), the overdue/due-today task badge, and the account menu. Sign-in, first-run setup, activation/reset codes, and connection problems are shown inside the same window.

**Data** — `core.db.create_base_tables()` remains the only definition of the original tables. Alembic revision `0001` adds the account, audit, contact, task, activity, and stage-history tables and optional columns on `clients` and `leads` using `ALTER TABLE … ADD COLUMN` only. Startup backs the file up before an upgrade and checks the resulting layout. Accounts from the earlier `crm.db` are carried over once (passwords keep working); the file itself is never modified, and if it holds business records the carry-over is refused rather than silently ignoring them.

**One definition per rule** — lead stages and transitions: `domain/lead_stages.py` (used by importer, funnel analytics, filters, reports, services, screens). Client format and duplicate rules: `models/client_validators.py` (used by the original controller and the new client service, inside the service's transaction). Manual IDs: the original `M_XXXXXX` / `L_XXXXXX` generators.

**Permissions** — enforced in `crm/services` (`Actor.require`, `require_on` with own/all scopes). Operations that predate accounts keep their implementation and are wrapped by `AppContext.guarded`: duplicate merge (`clients.merge`), marketing spend (`marketing.manage`), table clearing (`data.clear`), imports (`data.import`), report exports (`data.export`).

**Screens** — the existing Leads page keeps all funnel and marketing analytics; its management table adds Lead, Owner, Priority, and Follow-up columns, Open/Stage row actions, New lead, Assign selected, and an owner filter. The existing Clients page adds Owner and Status columns, an Account tab in the client form, and Contacts/Leads/Activity/Tasks tabs in the profile. Tasks, Users, Audit log, and Settings are new pages built on one shared record-list component.

**Removed** — the CRM workspace and tab bar, the Overview/Companies/Contacts/CRM-Leads pages, the CSV transfer service and dialog, the Companies and CRM-dashboard services, the PostgreSQL configuration and driver, and the unused Flet/Flet-web/FastAPI dependencies (OPEN-03).

## 5. Defects found and fixed during this work

| Defect | Effect | Fix |
|---|---|---|
| SQLite savepoints committed early | With Python's default `sqlite3` transaction handling, releasing a savepoint opened before any write committed it, so a "check without saving" could persist data | `BEGIN IMMEDIATE` issued by SQLAlchemy and driver transaction handling disabled (`crm/db.py`); regression test |
| Optional 0–100 field crashed forms | With pydantic 2.14 a range on `int \| None` was applied to `None` (TypeError) | Range applied to the integer branch only |
| `MessageDialog` measured −1 px tall without a stylesheet | Size policy replaced after `setWordWrap` dropped height-for-width | Policy keeps height-for-width |
| `MetricTile.metric` shadowed `QPaintDevice.metric()` | Theme change raised TypeErrors | Attribute renamed |
| Dialogs kept alive by lambdas in Qt connections (DEF-026 pattern) | Memory growth per opened profile/form | Bound methods; form change callbacks receive the dialog |
| Importer stored unknown stage names verbatim | "Client" was saved as `client`, invisible to the funnel | Labels mapped to codes; unknown stages rejected per row |
| Locale month names (e.g. Urdu) inside English dates | Mixed-direction text | Fixed English month abbreviations |
| Client Name column squeezed to "Glo…" with twelve columns | Unreadable list (cf. OPEN-06) | Name column keeps a readable width; table scrolls sideways |
| Four regression tests expected the pre-`MessageDialog` UI | Failing baseline | Expectations updated (test-only) |

## 6. Verification

- **Automated:** `pytest` — 267 tests, all passing at the end of this work (business rules incl. role matrix and stage transitions, migrations on empty and populated files, the original analytics/regression suite, and end-to-end tests that drive the real window and dialogs offscreen). `ruff check .` and `mypy` (112 files) clean.
- **Real window:** launched on a Wayland desktop with scratch data resembling an existing installation; first-run setup, every sidebar area, the lead window, stage dialog, client profile and form, dark mode, a narrow window, and sign-out were captured and reviewed.
- **Packaging:** the PyInstaller spec builds and the Linux executable starts, upgrades a fresh database with the bundled migrations, and opens the window.
- **Upgrade of the real database:** `data/sales.db` was upgraded by a launch of the new version; the pre-upgrade backup exists in `data/backups/`, and the account from `crm.db` signs in.

## 7. Not verified / open

- The Windows executable has not been built or run on Windows (PyInstaller does not cross-compile). Build with `scripts/build_windows.ps1` and smoke-test on Windows.
- Multi-computer use: SQLite on a network share is not supported. A shared server would need the analytics layer ported off SQLite-specific SQL.
- Operations kept from the original code (merge, spend, clearing, import) record their audit entry in a second transaction after succeeding; a crash between the two would leave a change without its audit entry.
- Sensitive client fields in the client list are masked in the screen for every role, but the list query itself still returns them; only contact details and searches are filtered in the service layer for roles without `clients.view_sensitive`.
- `data/sales.db` is tracked by git in this checkout; remove it from version control separately (without deleting the local file).
- `desktop_ui/sheet.py` (an embedded-dialog helper from an earlier session) is not used by any module.
