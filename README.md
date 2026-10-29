# Techset LeadGen

A native desktop application (Python, PySide6) for a team doing LinkedIn outreach by hand.
A manager imports LinkedIn profiles and assigns them to team members for a work day; members
record what happened on LinkedIn, schedule follow-ups, and complete their work; everyone has
general tasks; managers see workload, overdue follow-ups, and an end-of-day summary.

Nothing runs in a web browser, and the application never contacts LinkedIn: members open
profiles in their own browser and record the outcome here.

## How it is deployed

* **Team server** – every computer runs the desktop application and connects to one shared
  PostgreSQL database on the office server (`DATABASE_URL` in `.env`, `TSLG_DATABASE_URL`, or `data/database.ini`).
* **Single computer** – one local SQLite file, `data/sales.db`. The earlier sales, lead, and client
  analytics remain available here as the **Archive**.

There is no offline mode: without the server the application says so and saves nothing.
Setup, backups, restore, and upgrades: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Using it

[docs/USER_GUIDE.md](docs/USER_GUIDE.md): My Work, Daily Assignments, Prospects, Follow-ups,
Tasks, Team performance, Notifications, roles, and settings.

## Run from source

Python 3.12–3.15 and Poetry:

```bash
poetry install --with dev
poetry run python -m techset_leadgen          # data in ./data (or FDT_DATA_DIR)
poetry run python -m techset_leadgen --version
```

Administrator commands (also on the Windows executable):

```text
--upgrade-database            create or upgrade the database schema (team database: once per release)
--copy-local-to-server [FILE] move a single-computer database into the new, empty team database
--backup-team-database [DIR]  verified pg_dump backup of the team database
--restore-team-database FILE  restore a backup into the configured new, empty database
--issue-reset-code EMAIL      one-time password-reset code when no administrator can sign in
```

## Demo data

```bash
poetry run python scripts/seed_outreach_demo.py            # a demo team, ~150 prospects, a week of outreach
poetry run python scripts/seed_outreach_demo.py --remove   # deletes exactly the demo data again
```

It writes to the database the app uses (team database or local file), through the app's services.
Demo accounts: `ayesha.malik@demo.techset.example` (manager), `bilal.ahmed@demo.techset.example`
(team member), password `Demo-Kettle-2026`. (`scripts/seed_demo_data.py` is for the Archive, local file only.)

## Development checks

```bash
QT_QPA_PLATFORM=offscreen poetry run pytest -q        # PostgreSQL tests skip without a server
TSLG_TEST_POSTGRES_URL=postgresql://admin:pw@localhost:5432/postgres poetry run pytest -q -m postgres
poetry run ruff check src tests scripts
poetry run mypy
poetry run bandit -r src -c pyproject.toml
poetry run python scripts/benchmark_outreach.py [--postgres ADMIN_URL]
```

Windows build: `powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1` (or the
`Build Windows app` GitHub workflow). The script copies the project's `.env` next to
`TechsetLeadGen.exe`, so its folder and zip connect to the team database; the GitHub build never
contains it, so put `.env` next to the downloaded exe yourself.

## Project map

```text
src/techset_leadgen/
├── desktop/      PySide6 shell, pages, dialogs, theme, tables
├── services/     authenticated workflows (permissions, validation, audit)
├── domain/       vocabularies and pure rules (stages, transitions, workload balance)
├── database/     ORM models, Alembic migrations, engine, team-database tools
├── security/     passwords, tokens, role permissions
├── reports/, analytics/   branded reports; the retired analytics (Archive)
└── main.py, cli.py, config.py
tests/            unit, integration (incl. PostgreSQL), ui (real widgets, offscreen), performance
docs/             architecture, domain model, deployment, user guide, audit, implementation log
packaging/, scripts/       PyInstaller spec, build, seed, and benchmark scripts
```

Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md). What changed and what was verified:
[docs/IMPLEMENTATION_LOG.md](docs/IMPLEMENTATION_LOG.md).
