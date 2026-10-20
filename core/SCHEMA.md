# Database Schema — sales.db

**Engine:** SQLite 3 (WAL mode, `PRAGMA foreign_keys=ON` on every connection)
**File:** `data/sales.db` next to the project (or next to the compiled executable).
The folder can be changed with the `FDT_DATA_DIR` environment variable.

The source of truth for the schema is `core/db.py` → `init_db()`.

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
| `status` | TEXT | ✅ | `new`, `contacted`, `meeting`, `converted`, `lost` (default `new`) |
| `meeting_date` | TEXT | — | Date `YYYY-MM-DD` |
| `client_id` | TEXT | — | FK → `clients.id` |

**FK:** `client_id` → `clients.id` ON DELETE SET NULL.
**Unique index:** `(external_id, source)`.

The interface shows the statuses as Lead, Contacted, Meeting, Client and Lost, and the sources as Meta Ads, Google Ads, LinkedIn Ads and TikTok Ads; the stored values are the codes above.

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

---

## Automatic Migrations (`init_db()`)

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
