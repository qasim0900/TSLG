import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from techset_leadgen.database.local_db import get_connection, DB_NAME

def main():
    print(f"🔍 IMPORT DIAGNOSTICS")
    print(f"=" * 60)
    print(f"Database: {DB_NAME}")
    print()

    db_path = Path(DB_NAME)
    if db_path.exists():
        print(f"✅ Database exists: {db_path}")
        print(f"   Size: {db_path.stat().st_size} bytes")
    else:
        print(f"❌ Database does NOT exist: {db_path}")
        return

    print()

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' ORDER BY name
        """)
        tables = cursor.fetchall()

        if tables:
            print(f"✅ Tables found:")
            for (table_name,) in tables:
                print(f"   - {table_name}")
        else:
            print(f"❌ The database has NO tables")
            conn.close()
            return

        print()

        print(f"📊 ROWS PER TABLE:")
        for (table_name,) in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"   {table_name}: {count} rows")

        print()

        cursor.execute("SELECT COUNT(*) FROM sales")
        sales_count = cursor.fetchone()[0]

        if sales_count > 0:
            print(f"✅ Sales found: {sales_count}")
            cursor.execute("""
                SELECT client_name, client_id, product_type, price, date
                FROM sales 
                ORDER BY date DESC 
                LIMIT 3
            """)
            print(f"   Last 3 sales:")
            for row in cursor.fetchall():
                print(f"      {row}")
        else:
            print(f"⚠️  The database has NO sales")

        print()

        cursor.execute("SELECT COUNT(*) FROM clients")
        clients_count = cursor.fetchone()[0]
        print(f"👥 Clients: {clients_count}")

        if clients_count > 0:
            cursor.execute("""
                SELECT id, name FROM clients LIMIT 3
            """)
            print(f"   First 3 clients:")
            for client_id, name in cursor.fetchall():
                print(f"      {client_id}: {name}")

        print()

        cursor.execute("SELECT COUNT(*) FROM import_metadata")
        metadata_count = cursor.fetchone()[0]
        print(f"📋 Recorded imports: {metadata_count}")

        if metadata_count > 0:
            cursor.execute("""
                SELECT imported_at, file_name, total_rows, valid_rows, rejected_rows
                FROM import_metadata
                ORDER BY imported_at DESC
                LIMIT 3
            """)
            print(f"   Last 3 imports:")
            for row in cursor.fetchall():
                print(f"      {row}")

        conn.close()

    except Exception as e:
        print(f"❌ Could not connect to the database: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

