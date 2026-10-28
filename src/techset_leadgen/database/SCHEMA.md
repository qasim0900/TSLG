# Database Schema — sales.db

**Engine:** SQLite 3 (WAL mode, `PRAGMA foreign_keys=ON` on every connection)
**File:** `data/sales.db` next to the project (or next to the compiled executable).
The folder can be changed with the `FDT_DATA_DIR` environment variable.

One file holds everything: sales, clients, leads, marketing spend, and the account,
audit, contact, task, and lead-workflow data. Two parts of the code own its schema:

- **`core/db.py` → `create_base_tables()` / `init_db()`** — the original analytics tables
  (`clients`, `sales`, `leads`, `marketing_spend`, `import_metadata`, `funnel_events`).
- **`crm/migrations/` (Alembic)** — everything added for accounts and workflows: new
  tables, and optional columns on `clients` and `leads`. Revision `0001` adds columns with
  `ALTER TABLE … ADD COLUMN` only; rebuilding `clients` would drop it and, with foreign
  keys on, cascade to its sales.

The original analytics/import code reads and writes the same `clients` and `leads` rows
as the account-aware services; there are no duplicate client or lead tables.

---

## Tables

### `clients`
Client catalog. Primary key: `id` (text).

| Column | Type | NOT NULL | Description |
|--------|------|----------|-------------|
| `id` | TEXT | ✅ PK | Client ID (from the imported file, or `M_XXXXXX` when created by hand) |
| `name` | TEXT | ✅ | Business name |
| `cif` | TEXT | ✅ | Tax ID (CIF/NIF; `-` when the client was created by a sales import) |
| `address` | TEXT | — | Mailing address |
| `contact_person` | TEXT | — | Contact person |
| `email` | TEXT | — | Contact email |
| `primary_domain` | VARCHAR(253) | — | Normalized web domain; **unique when present** |
| `website_url` | VARCHAR(500) | — | http(s) URL only |
| `industry`, `employee_range`, `country`, `city` | — | — | Account details |
| `account_status` | VARCHAR(16) | — | `prospect`, `active`, `former`, `not_a_fit` (empty for imported rows) |
| `owner_id` | VARCHAR(36) | — | FK → `users.id` ON DELETE SET NULL |
| `notes` | TEXT | — | Free text |
| `created_by_id`, `created_at`, `updated_at` | — | — | Set when changed through the application (empty for imported rows) |
| `version` | INTEGER | ✅ (default 1) | Optimistic locking: a save from an outdated copy is refused |

Rows created by a sales import get `cif = '-'` and none of the added columns; they can be
completed later on the Clients page.

---

### `sales`
Sales records. Primary key: `id` (INTEGER AUTOINCREMENT).

| Column | Type | NOT NULL | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | ✅ PK | Auto-increment ID |
| `client_name` | TEXT | ✅ | Client name (denormalized) |
| `client_id` | TEXT | ✅ | FK → `clients.id` |
| `product_type` | TEXT | ✅ | Product or service type |
| `price` | REAL | ✅ | Sale amount (finite and > 0) |
| `date` | TEXT | ✅ | Date in `YYYY-MM-DD` format |

**FK:** `client_id` → `clients.id` ON DELETE CASCADE (deleting a client deletes its sales).

> `client_name` is denormalized on purpose to keep the historical name
> even if the client is renamed later.

---

### `leads`
Sales funnel. Primary key: `id` (text).

| Column | Type | NOT NULL | Description |
|--------|------|----------|-------------|
| `id` | TEXT | ✅ PK | `external_id` from the file, or a deterministic hash when there is none |
| `external_id` | TEXT | — | ID on the source platform |
| `created_at` | TEXT | ✅ | Date `YYYY-MM-DD` |
| `source` | TEXT | ✅ | Normalized source (`meta_ads`, `google_ads`, `linkedin_ads`, `tiktok_ads`, …) |
| `status` | TEXT | ✅ | `new`, `contacted`, `meeting`, `qualified`, `nurture`, `converted`, `lost` (default `new`) |
| `meeting_date` | TEXT | — | Date `YYYY-MM-DD` |
| `client_id` | TEXT | — | FK → `clients.id` |
| `title` | VARCHAR(200) | — | Set for leads added by hand; imported leads are named after their client or source |
| `owner_id` | VARCHAR(36) | — | FK → `users.id` ON DELETE SET NULL |
| `priority` | VARCHAR(8) | ✅ (default `medium`) | `low`, `medium`, `high`, `urgent` |
| `notes` | TEXT | — | Free text |
| `qualification_reason`, `lost_reason` | TEXT | — | Required when moving to Qualified / Lost |
| `next_follow_up_at` | DATETIME (UTC) | — | Earliest due date of the lead's open tasks (derived) |
| `last_activity_at` | DATETIME (UTC) | — | Latest logged activity |
| `created_by_id`, `updated_at` | — | — | Set when changed through the application |
| `version` | INTEGER | ✅ (default 1) | Optimistic locking |

Manual leads get IDs `L_XXXXXX`. **FK:** `client_id` → `clients.id` ON DELETE SET NULL.
**Unique index:** `(external_id, source)`.

Stages are defined once in `domain/lead_stages.py` and shown as Lead, Contacted, Meeting,
Qualified, Nurture, Client (`converted`), and Lost. The funnel counts `meeting`,
`qualified`, and `converted` as having reached the meeting stage. Imports accept codes
or labels (e.g. "Client") and reject unknown stages row by row. Through the screens only
the moves in `LEAD_TRANSITIONS` are allowed; marking a lead Client requires a linked client.

---

### `marketing_spend`
Marketing spend per source.

| Column | Type | NOT NULL | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | ✅ PK | Auto-increment ID |
| `source` | TEXT | ✅ | Normalized source (same normalization as `leads.source`) |
| `amount` | REAL | ✅ | Amount (finite and > 0) |
| `date` | TEXT | ✅ | Date `YYYY-MM-DD` |

---

### `import_metadata`
History of Excel/CSV file imports.

| Column | Type | NOT NULL | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | ✅ PK | Auto-increment ID |
| `imported_at` | TEXT | ✅ | ISO 8601 timestamp of the import |
| `file_name` | TEXT | — | Name of the imported file (prefixed with `leads:` / `marketing_spend:`) |
| `total_rows` | INTEGER | — | Total rows processed |
| `valid_rows` | INTEGER | — | Valid rows |
| `rejected_rows` | INTEGER | — | Rows rejected by validation |
| `duration_seconds` | REAL | — | Import duration in seconds |

---

### `funnel_events`
Funnel events (reserved; the application does not write to it yet).

| Column | Type | NOT NULL | Description |
|--------|------|----------|-------------|
| `id` | TEXT | ✅ PK | Event ID |
| `client_id` | TEXT | — | FK → `clients.id` ON DELETE SET NULL |
| `lead_id` | TEXT | — | FK → `leads.id` ON DELETE SET NULL |
| `event_type` | TEXT | ✅ | Event type |
| `source` | TEXT | — | Source |
| `event_date` | TEXT | ✅ | Event date |
| `metadata` | TEXT | — | Additional data |

---

### Tables added by Alembic revision `0001`

| Table | Purpose |
|-------|---------|
| `organization` | One row: the organization name shown in Settings |
| `users` | Accounts: email (unique, lower-case), name, role, Argon2 `password_hash` (empty until an invitation is accepted), active flag, time zone |
| `user_sessions` | Signed-in sessions; only the SHA-256 of each session token is stored, with expiry, last-seen time, revocation, and computer name |
| `user_tokens` | One-time activation / password-reset codes (hashed), with expiry and use time |
| `auth_attempts` | Sign-in attempts, used to throttle repeated failures |
| `audit_logs` | Who changed what and when, from which computer; field changes as JSON (contact emails and phone numbers recorded only as "[changed]") |
| `contacts` | People at a client (FK → `clients.id` ON DELETE CASCADE); email unique when present; do-not-contact flag with a required reason |
| `lead_status_history` | Every stage change with its reason (FK → `leads.id` ON DELETE CASCADE) |
| `activities` | Calls, emails, meetings, and notes for a client and/or lead |
| `tasks` | Follow-ups: title, due time (UTC), priority, status `open`/`done`/`cancelled`, assignee; linked lead (CASCADE) and client (CASCADE) |
| `alembic_version` | The schema revision |

All timestamps added by the migration are stored as UTC.

### Tables added by Alembic revision `0002` (LinkedIn outreach)

`prospects`, `assignment_batches`, `prospect_assignments`, `outreach_events`, `notifications`, and
the follow-up columns on `tasks` (`kind`, `prospect_id`, `assignment_id`, `outcome`, `request_id`)
plus `organization.timezone`. Their relationships, uniqueness rules, status transitions, and
permissions are documented in `docs/DOMAIN_MODEL.md`. On the PostgreSQL team database the same
revisions create the same tables (the original tables come from a PostgreSQL branch of `0001`).

## Relationship Diagram

```
clients (id PK)
    ├── sales         (client_id FK → clients.id  ON DELETE CASCADE)
    ├── leads         (client_id FK → clients.id  ON DELETE SET NULL)
    └── funnel_events (client_id FK → clients.id  ON DELETE SET NULL)
leads (id PK)
    └── funnel_events (lead_id FK → leads.id      ON DELETE SET NULL)
```

`marketing_spend` and `import_metadata` have no relationships with other tables.

Added by revision `0001`:

```
clients ──┬── contacts      (client_id, ON DELETE CASCADE)
          ├── activities    (client_id, ON DELETE CASCADE)
          └── tasks         (client_id, ON DELETE CASCADE)
leads ────┬── lead_status_history (lead_id, ON DELETE CASCADE)
          ├── activities    (lead_id, ON DELETE CASCADE)
          └── tasks         (lead_id, ON DELETE CASCADE)
users ──── owner_id / created_by_id / assigned_to_id / actor columns (ON DELETE SET NULL)
```

---

## Automatic Migrations

On every start the application runs `init_db()` (below), then compares the Alembic
revision with the one it ships. If the database is older, it first copies it to
`data/backups/sales-before-<revision>-<time>.db` (SQLite online backup), then upgrades,
then checks that the tables match the unified layout before opening it.

### Original tables (`init_db()`)

- `clients.id` INTEGER → TEXT (old databases). Runs with `foreign_keys=OFF`
  inside a transaction so the `DROP TABLE` does not trigger cascades.
- `sales` without the `ON DELETE CASCADE` FK → the table is recreated with the correct FK,
  also with `foreign_keys=OFF` and inside a transaction.

## Implementation Notes

- All connections come from `core.db.get_connection()`.
- Date format: always `YYYY-MM-DD` (TEXT, not a native DATE).
- Leads without an `external_id` get the ID `sha1(client_id_created_at_source)`; if the
  same file contains several rows with that key, the n-th repetition adds the
  suffix `#n` before hashing. Re-importing the same file does not duplicate leads.
