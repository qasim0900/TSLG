# FDT Sales Manager 📊

**Desktop CRM application for sales pipeline management, client tracking, and lead analysis — built with Python + Flet**

![Python](https://img.shields.io/badge/Python-3.13+-blue?style=flat-square) ![Flet](https://img.shields.io/badge/Flet-0.82.0+-purple?style=flat-square) ![SQLite](https://img.shields.io/badge/SQLite-3-green?style=flat-square) ![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)

---

## 📸 Screenshots

Captured from the current build with fictional demo data (200 sales, 62 leads).

### Dashboard
| Light | Dark |
|:---:|:---:|
| ![Dashboard with KPI cards, quick actions and recent activity](screenshots/en/dashboard.png) | ![Dashboard in dark mode](screenshots/en/dashboard-dark.png) |
| *KPI cards, quick actions, import guide and recent activity* | *Dark theme* |

### Data Import
| Import Preview |
|:---:|
| ![Import preview showing 140 rows, 138 valid and 2 invalid](screenshots/en/import-preview.png) |
| *Detected file type, valid and invalid rows, and the file's columns before anything is written* |

### Sales Analytics
| Filters & Presets | Summary & Distribution | Period A vs. B | 1024 px Window |
|:---:|:---:|:---:|:---:|
| ![Sales KPI cards, date filters and comparison presets](screenshots/en/sales-filters.png) | ![Product summary table and sales distribution donut](screenshots/en/sales-summary-and-distribution.png) | ![Comparison cards and chart for this year vs. last year](screenshots/en/sales-compare.png) | ![Sales view in a 1024 by 700 window](screenshots/en/sales-1024px.png) |
| *KPI cards, date filters, quick ranges and comparison presets* | *Per-product totals and share of sales* | *This year vs. last year: totals, transactions and average sale, each scaled to the higher period* | *KPI cards wrap on narrow windows* |

### Lead Management
| Funnel | Lead List | Lead List (Dark) |
|:---:|:---:|:---:|
| ![Lead funnel and pipeline metrics](screenshots/en/leads-funnel.png) | ![Recent leads with stage badges and upcoming meetings](screenshots/en/leads-list.png) | ![Recent leads in dark mode](screenshots/en/leads-list-dark.png) |
| *Filters, funnel and pipeline metrics* | *Lead age, source, stage and upcoming meetings* | *Dark theme* |

### Client Management
| Client List | Client Profile | Edit Client |
|:---:|:---:|:---:|
| ![Client list with totals and lead information](screenshots/en/clients.png) | ![Client profile with lead and sales statistics](screenshots/en/client-profile.png) | ![Client edit form with lead information](screenshots/en/client-edit.png) |
| *Lifetime totals, lead source and stage per client* | *Client information, linked lead and sales history* | *Client details and lead status in one form* |

---

## 🚀 What this project demonstrates

- Data processing & analytics with Polars on top of SQLite
- Layered architecture (UI → controllers → services → analysis → core), Flet only in the UI layers
- 586 automated pytest tests, including headless GUI tests of the real Flet control tree
- Real-world data handling: CSV/Excel import with encoding detection, validation and per-row error reports
- Measured performance: a full sales snapshot over 50,000 sales builds in ~0.4 s (see [Performance](#-performance))

## 🎯 Problem Statement

Sales teams waste hours managing spreadsheets, tracking pipeline progress manually, and losing visibility into client relationships. **FDT Sales Manager** centralizes all sales data—clients, leads, sales history, and performance metrics—in a single, interactive desktop application with real-time analytics.

---

## 💡 Why This Project Matters

Building a full desktop CRM from scratch in Python required solving real software engineering challenges: layered architecture, reactive UI state, Polars-powered analytics, safe data import, and a comprehensive automated test suite. This project demonstrates practical **Python backend development** skills applied to a real business domain.

---

## ✨ Key Features

- **Dashboard**: sales record and client counts, total leads, lead conversion rate, meetings, leads this month, last import, import guide with downloadable CSV templates, and guarded "clear data" actions
- **Data Import**: CSV/XLSX import of sales, leads, marketing spend, or mixed files; the file type is detected automatically and previewed before import
- **Sales Analytics**: filters by date range (with quick ranges), client and product; KPI cards, product summary table, product distribution, top clients and sales evolution grouped by day/week/month/quarter/year
- **Period Comparison (A vs. B)**: presets such as "Same period, previous year" or "This month vs. last month", aligned evolution chart and metric deltas
- **Lead Management**: lead funnel (stored statuses `new → contacted → meeting → converted / lost`, shown as Lead, Contacted, Meeting, Client and Lost), per-source conversion, filters (source, stage, date, search), editable lead status and meeting date
- **Marketing Performance**: CPL, CAC and ROI per source with first-touch attribution, and an editor for marketing spend
- **Client Management**: searchable client list with lifetime totals, client profile with sales history, create / edit / delete, and merge of duplicate clients by name
- **HTML Reports**: sales (normal and compare mode), client profile and leads reports with embedded Matplotlib charts
- **Dark/Light Theme**

## 🌐 Language and Formats

The interface, reports, notifications and log messages are in American English. Amounts are in euros and use US separators: `€1,234.56`, negative `-€1,234.56`. Dates in text are written `Oct 20, 2026 6:14 PM`; compact chart labels are month first (`10/20`). Tables and date pickers show ISO dates (`2026-10-20`). Stored data and import files are unchanged by this: the database keeps ISO dates, and Spanish column headers in import files are still recognized.

## 🏗️ Architecture

```
Layered architecture
├── main.py         (initialization, logging)
├── ui/             (routing & navigation)
├── views/          (dashboard, sales, clients, leads)
├── components/     (reusable Flet widgets)
├── controllers/    (input validation, service coordination, import threading)
├── services/       (analysis orchestration, snapshot building)
├── analysis/       (Polars/SQL metrics calculation)
├── models/         (CRUD for clients, leads, marketing spend)
├── domain/         (pure data models)
├── reports/        (HTML report generation)
└── core/           (database, schema & migrations, importer, date ranges)
```

**Key principle**: lower layers never import Flet or the UI packages (`components/`, `views/`, `ui/`). Long-running imports run in a background thread, and their result callbacks are marshalled back onto the Flet event loop (`utils/ui_dispatch.py`).

## 🛠️ Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| **Framework** | Flet (Flutter Desktop) | 0.82.0 |
| **Language** | Python | 3.13 |
| **Database** | SQLite3 | Built-in |
| **Data Analysis** | Polars | 1.44.2 |
| **Charts** | flet-charts | 0.82.0 |
| **Excel/CSV Import** | openpyxl | 3.1.5 |
| **HTML Reports** | Matplotlib | 3.11.2 |
| **Testing** | pytest | 9.1.1 |

## 🚀 Quick Start

Requires **Python 3.13**. On Linux the Flet desktop client also needs `libmpv` (Ubuntu/Debian: `sudo apt install libmpv1`).

```bash
git clone https://github.com/EduardoRaffo/flet-sales-manager
cd flet-sales-manager
python3.13 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

With [uv](https://docs.astral.sh/uv/): `uv venv --python 3.13 .venv && uv pip install -r requirements.txt`.

### First Run
1. The application creates `data/sales.db` automatically on first launch
2. Use **Import data** on the dashboard to load data from CSV/Excel (templates are available in the import guide)
3. Navigate Dashboard → Sales → Leads → Clients
4. Set date filters to analyze specific periods

## ⚙️ Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `FDT_DATA_DIR` | `<project or .exe folder>/data` | Folder containing `sales.db` and the `failed_*.csv` reports of rejected rows |
| `FDT_LOG_DIR` | `<project or .exe folder>/logs` | Folder for `app.log` and `importer.log` (rotating, 1 MB × 3) |
| `FDT_LOG_LEVEL` | `INFO` | Level of `app.log` (`DEBUG`, `INFO`, `WARNING`, …) |

When running as a compiled executable the default folders are created next to the executable, so it must be installed in a user-writable location (or `FDT_DATA_DIR` / `FDT_LOG_DIR` must point to one).

## 📥 Import Formats

| Type | Required columns | Optional columns |
|------|------------------|------------------|
| Sales | `client_name`, `client_id`, `product_type`, `price` | `date` (today if absent) |
| Leads | `created_at`, `source` | `status` (default `new`), `external_id`, `meeting_date`, `client_id` |
| Marketing spend | `source`, `amount` | `date` |

- Spanish header aliases are accepted (`cliente`, `producto`, `precio`, `fecha`, `importe`, `gasto`, …).
- CSV files may be UTF-8 (with or without BOM) or Windows-1252; the delimiter (`,` `;` tab `|`) is detected automatically.
- Dates: `YYYY-MM-DD`, `DD/MM/YYYY`, ISO 8601 timestamps from ad platforms (`2024-03-01T12:34:56+0000`) and native Excel dates. Slash dates are read **day first**, so US-style `MM/DD/YYYY` values are misread or rejected: use `YYYY-MM-DD` when in doubt.
- Invalid rows are skipped and written to `data/failed_<type>_<timestamp>.csv` with the reason.
- Re-importing a leads file does not duplicate leads. Sales and marketing spend imports are **not** de-duplicated: importing the same sales file twice adds the rows twice.
- Leads whose `client_id` does not exist yet are imported without a client link (the result message says how many). In mixed files sales are imported first, so their clients exist when the leads are linked.
- Only one import can run at a time.

## 🧪 Testing

```bash
pip install -r requirements-dev.txt
pytest                      # all 586 tests (tests/ and analysis/tests/)
pytest --cov                # with coverage report
pytest -m gui               # only the headless GUI tests
```

The suite never touches `data/` or `logs/`: the root `conftest.py` redirects `FDT_DATA_DIR` and `FDT_LOG_DIR` to a temporary folder that is removed at the end.

The GUI tests (`tests/test_gui_smoke.py`) build the real application against a Flet session with an in-memory connection: every view is constructed, serialized and navigated, the theme is toggled, and an import is run end-to-end. They do not render pixels; visual checks still require running the desktop app.

## 🔍 Static Analysis

```bash
ruff check .                         # lint (rules in pyproject.toml)
mypy                                 # type check of the non-UI packages (list in pyproject.toml)
bandit -c pyproject.toml -r . --severity-level medium --confidence-level high   # security lint gate
pip-audit -r requirements.txt        # known vulnerabilities in dependencies
```

The same checks run in GitHub Actions on every push to `main` and on pull requests (`.github/workflows/ci.yml`). The bandit gate fails on medium- or high-severity findings reported with high confidence; the remaining lower-confidence findings (SQL strings built only from fixed clauses, `?` placeholders or a table whitelist) were reviewed and are not exploitable.

## ⚡ Performance

Measured on an 8-core x86_64 Linux machine with synthetic data (50 clients, 20 products, 5 years), median of 5 runs:

| Sales rows | Import (CSV) | Sales snapshot (cold) | Compare A vs B | Clients list |
|-----------:|-------------:|----------------------:|---------------:|-------------:|
| 10,000 | 0.17 s | 0.06 s | 0.10 s | 0.05 s |
| 50,000 | 0.64 s (40,000 rows) | 0.41 s | 0.50 s | 0.28 s |

Repeated snapshots with the same filters are served from an in-memory cache. Benchmark your own database (read-only) with `python scripts/benchmark_queries.py`.

UI patch cost (a `page.update()` with no changes, 140 sales / 60 leads, median of 7): Dashboard 8 ms, Sales 23 ms, Leads 47 ms, Clients 4 ms. Flet 0.82–1.0.4 builds eager debug f-strings that `repr()` whole control lists during every diff; `utils/flet_perf.py` (called from `main()`) keeps control `repr()` short, which brought Leads down from 3.5 s.

## 💾 Backup & Recovery

- All data lives in `data/sales.db`. Close the application and copy `sales.db` (plus `sales.db-wal` / `sales.db-shm` if present) to back it up; restore by copying the files back while the app is closed.
- `python scripts/audit_db.py` prints a read-only summary of every table.
- "Clear clients" on the dashboard also deletes all sales of those clients (`ON DELETE CASCADE`); the confirmation dialog says so.

## 🛟 Troubleshooting

| Symptom | Fix |
|---------|-----|
| `libmpv.so.1: cannot open shared object file` on Linux | `sudo apt install libmpv1` |
| Exported reports do not open automatically on Linux | Install `xdg-utils`; the file is saved anyway at the chosen path |
| "The application could not start" window | Details are in `logs/app.log`; usually the data folder is not writable (set `FDT_DATA_DIR`) |
| Rows rejected during import | See the `data/failed_*.csv` file named in `logs/importer.log` |

## ⚠️ Known Limitations

- Sales and marketing-spend imports are not de-duplicated.
- Comma decimals (`1200,50`) are accepted in the marketing-spend editor but not in CSV imports, where `1,200` would be ambiguous.
- Imported slash dates are read day first (`DD/MM/YYYY`); see [Import Formats](#-import-formats).
- Pie-chart slice labels can overflow small slices; the legend next to the chart always lists every product, amount and share.
- The headless GUI tests do not cover pixel rendering, file pickers or native dialogs.
- `utils/flet_perf.py` works around an upstream Flet performance issue; re-measure it when upgrading Flet.

## 📈 Future Roadmap

- [ ] Team Collaboration: Multi-user support with role-based access
- [ ] Forecasting: Predictive analytics for pipeline forecast
- [ ] Mobile App: Companion app for iOS/Android
- [ ] API: RESTful API for third-party integrations (Slack, Zapier)
- [ ] Reporting Automation: Scheduled email reports

## 📝 Project Structure

```
flet-sales-manager/
├── main.py                # Application entry point
├── requirements.txt       # Runtime dependencies (pinned)
├── requirements-dev.txt   # Test & analysis tools
├── pyproject.toml         # pytest, coverage, ruff, mypy and bandit configuration
├── .github/workflows/     # CI quality gates
├── conftest.py            # Test sandbox for data/ and logs/
├── data/                  # sales.db and rejected-row reports (auto-created, git-ignored)
├── logs/                  # app.log, importer.log (auto-created, git-ignored)
├── assets/                # Icons and logos
├── screenshots/en/        # App screenshots (current English UI)
├── analysis/              # Metrics calculation (Polars/SQL)
├── components/            # Flet widgets
├── controllers/           # Input validation & coordination
├── core/                  # Database, schema (SCHEMA.md), import, date ranges
├── domain/                # Pure data models
├── models/                # CRUD for clients, leads, marketing spend
├── reports/               # HTML report generation
├── scripts/               # DB audit, import diagnosis, query benchmark
├── services/              # Analysis orchestration
├── theme/                 # Color system & theming
├── ui/                    # Navigation & routing
├── utils/                 # Formatting, dialogs, notifications, UI-thread dispatch
├── views/                 # Dashboard, sales, clients, leads
└── tests/                 # pytest suite
```

## 📄 License

MIT License - free for personal and commercial use.

## 👤 Author

**Eduardo Raffo** - Python Developer  
- GitHub: [github.com/EduardoRaffo](https://github.com/EduardoRaffo)
- LinkedIn: [linkedin.com/in/eduardo-raffo-benitez](https://linkedin.com/in/eduardo-raffo-benitez)

---

*Made with ❤️ for sales teams who want to work smarter*
