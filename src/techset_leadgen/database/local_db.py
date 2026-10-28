"""Conexión SQLite, inicialización de esquema y migraciones automáticas.

Provee get_connection() como punto único de acceso a la base de datos,
init_db() para crear tablas e índices, y migraciones idempotentes.
"""

import os
import sqlite3
import logging
from pathlib import Path
import sys

_logger = logging.getLogger("fdt.db")


def get_base_path():
    """
    Retorna la carpeta que contiene data/ y logs/.
    - Si ejecuta desde .exe (PyInstaller): Path del ejecutable
    - Si ejecuta desde el repositorio (src/techset_leadgen): Raíz del repositorio
    - Si ejecuta como paquete instalado: carpeta de datos del usuario
    """
    if getattr(sys, 'frozen', False):
        # Ejecutando como .exe compilado con PyInstaller
        return Path(sys.executable).parent
    checkout = Path(__file__).resolve().parents[3]  # <repo>/src/techset_leadgen/database/local_db.py
    if (checkout / "pyproject.toml").is_file():
        return checkout
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "TechsetLeadGen"
    data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(data_home) if data_home else Path.home() / ".local" / "share") / "TechsetLeadGen"


def _path_from_env(var_name: str, default: Path) -> Path:
    value = os.environ.get(var_name, "").strip()
    return Path(value).expanduser().resolve() if value else default


BASE_PATH = get_base_path()
DATA_PATH = _path_from_env("FDT_DATA_DIR", BASE_PATH / "data")
LOGS_PATH = _path_from_env("FDT_LOG_DIR", BASE_PATH / "logs")
DB_PATH = DATA_PATH / "sales.db"
DB_NAME = str(DB_PATH)

_BASE_TABLES = frozenset({
    "clients", "sales", "leads", "marketing_spend", "import_metadata", "funnel_events",
})
_BASE_INDEXES = frozenset({
    "idx_sales_date", "idx_sales_client_name", "idx_sales_product_type", "idx_sales_client_id",
    "idx_leads_client_id", "idx_leads_created_at", "idx_leads_source", "idx_leads_status",
    "idx_leads_source_created", "idx_leads_external_source", "idx_spend_source", "idx_spend_date",
    "idx_funnel_events_client", "idx_funnel_events_event_type", "idx_funnel_events_date",
})


def get_data_dir() -> Path:
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    return DATA_PATH


def get_logs_dir() -> Path:
    LOGS_PATH.mkdir(parents=True, exist_ok=True)
    return LOGS_PATH


def get_connection():
    """
    Devuelve una conexión SQLite configurada de forma coherente
    para toda la aplicación.
    Crea la carpeta data/ si no existe.
    """
    get_data_dir()

    conn = sqlite3.connect(DB_NAME, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def base_schema_needs_migration() -> bool:
    """Read-only preflight for the changes made by :func:`init_db`.

    Startup uses this before touching an existing database so it can create a
    consistent backup first.  A missing/empty file is a new installation, not
    a migration.
    """
    if not DB_PATH.is_file() or DB_PATH.stat().st_size == 0:
        return False
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        indexes = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )}
        if _BASE_TABLES - tables or _BASE_INDEXES - indexes:
            return True
        client_columns = connection.execute("PRAGMA table_info(clients)").fetchall()
        if any(row[1] == "id" and str(row[2]).upper() == "INTEGER" for row in client_columns):
            return True
        sales_fks = connection.execute("PRAGMA foreign_key_list(sales)").fetchall()
        return not any(
            row[2] == "clients" and row[3] == "client_id" and row[6] == "CASCADE"
            for row in sales_fks
        )
    finally:
        connection.close()


def create_base_tables(cursor) -> None:
    """Create the original analytics tables and indexes if missing (idempotent).

    The single definition of the base schema: ``init_db()`` runs it on the
    configured file, and the first CRM migration runs it so a brand-new database
    created by migrations alone has the same tables.
    """
    # Tabla de clientes (tabla base, sin dependencias)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS clients(
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cif TEXT NOT NULL,
            address TEXT,
            contact_person TEXT,
            email TEXT
        )
        """
    )

    # Tabla de ventas (depende de clients)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sales(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT NOT NULL,
            client_id TEXT NOT NULL,
            product_type TEXT NOT NULL,
            price REAL NOT NULL,
            date TEXT NOT NULL,
            FOREIGN KEY (client_id)
                REFERENCES clients(id)
                ON DELETE CASCADE
        )
        """
    )

    # Tabla de leads (depende de clients, embudo comercial)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS leads(
            id TEXT PRIMARY KEY,
            external_id TEXT,
            created_at TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            meeting_date TEXT,
            client_id TEXT,
            FOREIGN KEY (client_id)
                REFERENCES clients(id)
                ON DELETE SET NULL
        )
        """
    )

    # Tabla de gasto en marketing (sin dependencias)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS marketing_spend(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            amount REAL NOT NULL,
            date TEXT NOT NULL
        )
        """
    )

    # Tabla de metadata de importación (sin dependencias)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS import_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imported_at TEXT NOT NULL,
            file_name TEXT,
            total_rows INTEGER,
            valid_rows INTEGER,
            rejected_rows INTEGER,
            duration_seconds REAL
        )
        """
    )

    # Índices
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_client_name ON sales(client_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_product_type ON sales(product_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_client_id ON sales(client_id)")

    # Índices para leads
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_client_id ON leads(client_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_source_created ON leads(source, created_at)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_external_source ON leads(external_id, source)")

    # Índices para marketing_spend
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_spend_source ON marketing_spend(source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_spend_date ON marketing_spend(date)")

    # Tabla de eventos del funnel comercial (sin dependencias de sales)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS funnel_events(
            id TEXT PRIMARY KEY,
            client_id TEXT,
            lead_id TEXT,
            event_type TEXT NOT NULL,
            source TEXT,
            event_date TEXT NOT NULL,
            metadata TEXT,
            FOREIGN KEY (client_id)
                REFERENCES clients(id)
                ON DELETE SET NULL,
            FOREIGN KEY (lead_id)
                REFERENCES leads(id)
                ON DELETE SET NULL
        )
        """
    )

    # Índices para funnel_events
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_funnel_events_client ON funnel_events(client_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_funnel_events_event_type ON funnel_events(event_type)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_funnel_events_date ON funnel_events(event_date)"
    )


def init_db():
    """
    Inicializa la base de datos y ejecuta migraciones necesarias.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        create_base_tables(cursor)

        conn.commit()

    finally:
        conn.close()

    # Migraciones puntuales
    _migrate_clients_table()
    _migrate_sales_foreign_keys()


def _migrate_clients_table():
    """
    Migra la tabla clients de INTEGER id a TEXT id si es necesario.
    Operación atómica y protegida por transacción.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(clients)")
        columns = cursor.fetchall()

        needs_migration = any(
            col[1] == "id" and col[2].upper() == "INTEGER"
            for col in columns
        )

        if not needs_migration:
            return

        _logger.info("Migrating clients table: INTEGER id → TEXT id")

        cursor.execute("PRAGMA foreign_keys=OFF")
        try:
            cursor.execute("BEGIN")

            cursor.execute(
                "SELECT id, name, cif, address, contact_person, email FROM clients"
            )
            old_data = cursor.fetchall()

            cursor.execute("DROP TABLE clients")

            cursor.execute(
                """
                CREATE TABLE clients(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    cif TEXT NOT NULL,
                    address TEXT,
                    contact_person TEXT,
                    email TEXT
                )
                """
            )

            cursor.executemany(
                """
                INSERT INTO clients (id, name, cif, address, contact_person, email)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [(str(row[0]), row[1], row[2], row[3], row[4], row[5]) for row in old_data],
            )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.execute("PRAGMA foreign_keys=ON")

        _logger.info("Clients migration finished (%d records)", len(old_data))

    except Exception:
        _logger.exception("Clients migration failed")
        raise

    finally:
        conn.close()


def ensure_leads_table():
    """
    Garantiza que la tabla leads existe con todos sus índices.
    Idempotente — segura de llamar múltiples veces y en cualquier orden.

    Útil para scripts externos, tests y setups programáticos.
    En producción, init_db() ya incluye esta lógica vía CREATE TABLE IF NOT EXISTS.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS leads(
                id TEXT PRIMARY KEY,
                external_id TEXT,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                meeting_date TEXT,
                client_id TEXT,
                FOREIGN KEY (client_id)
                    REFERENCES clients(id)
                    ON DELETE SET NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_client_id ON leads(client_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_source_created ON leads(source, created_at)"
        )
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_external_source ON leads(external_id, source)"
        )
        conn.commit()
    except Exception:
        conn.rollback()
        _logger.exception("ensure_leads_table failed")
        raise
    finally:
        conn.close()


def clear_table(table_name: str) -> bool:
    """Vacía completamente una tabla por nombre.

    Args:
        table_name: Nombre de la tabla a vaciar (debe ser una tabla conocida).

    Returns:
        True si se vació correctamente, False en caso de error.
    """
    _ALLOWED_TABLES = {"sales", "clients", "leads", "marketing_spend", "funnel_events"}
    if table_name not in _ALLOWED_TABLES:
        _logger.error("clear_table: table '%s' is not allowed", table_name)
        return False

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"DELETE FROM {table_name}")
        conn.commit()
        return True
    except Exception:
        _logger.exception("Could not clear table %s", table_name)
        return False
    finally:
        conn.close()


# Aliases retrocompatibles
def clear_sales_table() -> bool:
    """Vacía completamente la tabla de ventas."""
    return clear_table("sales")


def clear_clients_table() -> bool:
    """Vacía completamente la tabla de clientes."""
    return clear_table("clients")


def clear_leads_table() -> bool:
    """Vacía completamente la tabla de leads."""
    return clear_table("leads")

        
def _migrate_sales_foreign_keys():
    """
    Verifica si la tabla sales tiene el FOREIGN KEY correcto con ON DELETE CASCADE.
    Si no, recrea la tabla con la definición correcta.

    PROBLEMA: CREATE TABLE IF NOT EXISTS no actualiza FOREIGN KEYs en tablas existentes.
    SOLUCIÓN: Verificar vía PRAGMA foreign_key_list y recrear si es necesario.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Verificar FOREIGN KEYs actuales en la tabla sales
        cursor.execute("PRAGMA foreign_key_list(sales)")
        fk_list = cursor.fetchall()

        # Buscar si existe FK con ON DELETE CASCADE hacia clients
        has_correct_fk = any(
            fk[2] == "clients" and fk[3] == "client_id" and fk[6] == "CASCADE"
            for fk in fk_list
        )

        if has_correct_fk:
            return  # Nada que hacer

        _logger.info(
            "Migrating sales table: updating FOREIGN KEY to ON DELETE CASCADE"
        )

        # Desactivar FK solo para esta migración
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("BEGIN")

        try:
            # Backup de datos
            cursor.execute("SELECT * FROM sales")
            sales_data = cursor.fetchall()

            # Eliminar tabla antigua
            cursor.execute("DROP TABLE IF EXISTS sales")

            # Recrear tabla con FK correcta
            cursor.execute(
                """
                CREATE TABLE sales(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_name TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    product_type TEXT NOT NULL,
                    price REAL NOT NULL,
                    date TEXT NOT NULL,
                    FOREIGN KEY (client_id)
                        REFERENCES clients(id)
                        ON DELETE CASCADE
                )
                """
            )

            # Recrear índices
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_client_name ON sales(client_name)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_product_type ON sales(product_type)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_sales_client_id ON sales(client_id)"
            )

            # Restaurar datos
            for row in sales_data:
                cursor.execute(
                    """
                    INSERT INTO sales
                        (id, client_name, client_id, product_type, price, date)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    row,
                )

            conn.commit()
            _logger.info(
                "Sales migration finished: FOREIGN KEY updated (%d records)",
                len(sales_data),
            )

        except Exception:
            conn.rollback()
            raise

        finally:
            # Reactivar FK siempre (PRAGMA es por conexión)
            cursor.execute("PRAGMA foreign_keys=ON")

    except Exception:
        _logger.exception(
            "Sales FOREIGN KEY migration failed"
        )
        raise

    finally:
        conn.close()
