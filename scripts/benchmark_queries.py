import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from techset_leadgen.database.local_db import DB_PATH

QUERY = """
SELECT product_type, SUM(price) AS total, COUNT(*) AS cantidad
FROM sales
WHERE date >= ? AND date <= ?
GROUP BY product_type
"""


def timed_query(conn, start, end):
    t0 = time.perf_counter()
    rows = conn.execute(QUERY, (start, end)).fetchall()
    return time.perf_counter() - t0, len(rows)


def main(start="2025-01-01", end="2025-12-31", runs=5):
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 1
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        for _ in range(3):
            timed_query(conn, start, end)
        timings = [timed_query(conn, start, end) for _ in range(runs)]
        best = min(t for t, _ in timings)
        print(f"Best time of {runs} runs: {best:.4f} s, rows: {timings[0][1]}")
        print("Indexes on sales:")
        for idx in conn.execute("PRAGMA index_list('sales')").fetchall():
            print(idx)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
