import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from techset_leadgen.database.local_db import DB_PATH

def audit_database():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    cursor = conn.cursor()

    print("\n==============================")
    print("DATABASE AUDIT")
    print("DB:", DB_PATH)
    print("==============================\n")

    cursor.execute("""
        SELECT name 
        FROM sqlite_master 
        WHERE type='table'
        ORDER BY name
    """)

    tables = cursor.fetchall()

    for table in tables:
        table_name = table[0]

        print(f"\n📊 TABLE: {table_name}")
        print("-" * 40)

        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()

        print("Columns:")
        for col in columns:
            cid, name, col_type, notnull, default, pk = col
            pk_flag = " (PK)" if pk else ""
            print(f"  - {name} : {col_type}{pk_flag}")

        cursor.execute(f"PRAGMA foreign_key_list({table_name})")
        fks = cursor.fetchall()

        if fks:
            print("\nForeign Keys:")
            for fk in fks:
                _, _, ref_table, from_col, to_col, *_ = fk
                print(f"  {from_col} → {ref_table}.{to_col}")

    conn.close()


if __name__ == "__main__":
    audit_database()

