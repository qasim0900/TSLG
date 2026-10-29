from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from urllib.request import pathname2url

from sqlalchemy import Connection, Integer, MetaData, Table, create_engine, func, inspect, pool, select, text, update

from techset_leadgen.database import migrations_util

CHUNK = 1000
_SKIP = frozenset({"alembic_version", "sqlite_sequence"})


class TransferRefused(RuntimeError):
    pass


def _count(connection: Connection, table: Table) -> int:
    return int(connection.scalar(select(func.count()).select_from(table)) or 0)


def _self_references(table: Table) -> list[str]:
    return [element.parent.name for constraint in table.foreign_key_constraints
            for element in constraint.elements if element.column.table.name == table.name]


def copy_local_to_server(source: Path, target_url: str, say: Callable[[str], None] = print) -> dict[str, int]:
    if not source.is_file() or source.stat().st_size == 0:
        raise TransferRefused(f"{source} does not exist or is empty.")
    address = f"file:{pathname2url(str(source.resolve()))}?mode=ro"
    local = create_engine("sqlite://", creator=lambda: sqlite3.connect(address, uri=True), poolclass=pool.NullPool)
    server = create_engine(target_url, poolclass=pool.NullPool)
    try:
        with local.connect() as reader, server.connect() as writer:
            for name, connection in (("The local file", reader), ("The team database", writer)):
                state = migrations_util.schema_state(connection)
                if not state.ready:
                    raise TransferRefused(
                        f"{name} has schema {state.current or 'none'}; this version needs {state.head}. "
                        "Open the local file once with this version, and run --upgrade-database for the team "
                        "database, then try again.")
            source_tables = set(inspect(reader).get_table_names()) - _SKIP
            target_meta = MetaData()
            target_meta.reflect(writer)
            tables = [table for table in target_meta.sorted_tables if table.name not in _SKIP]
            missing = sorted(source_tables - {table.name for table in tables})
            if missing:
                raise TransferRefused(f"The team database has no table for: {', '.join(missing)}.")
            occupied = [table.name for table in tables if _count(writer, table)]
            if occupied:
                raise TransferRefused("The team database already has data (" + ", ".join(occupied) + "). "
                                      "Copying is only allowed into a new, empty team database.")
            source_meta = MetaData()
            source_meta.reflect(reader, only=[table.name for table in tables if table.name in source_tables])
            copied: dict[str, int] = {}
            for table in tables:
                if table.name not in source_tables:
                    copied[table.name] = 0
                    continue
                copied[table.name] = _copy_table(reader, writer, source_meta.tables[table.name], table)
                if copied[table.name]:
                    say(f"{table.name}: {copied[table.name]} rows")
            for table in tables:
                if _count(writer, table) != copied[table.name]:
                    raise TransferRefused(f"Row counts differ for {table.name}; nothing was saved.")
            _reset_sequences(writer, tables)
            writer.commit()
            return copied
    finally:
        local.dispose()
        server.dispose()


def _copy_table(reader: Connection, writer: Connection, source: Table, target: Table) -> int:
    columns = [column.name for column in target.columns if column.name in source.columns]
    deferred = _self_references(target)
    later: list[dict[str, object]] = []
    total = 0
    result = reader.execution_options(stream_results=True).execute(select(*(source.c[name] for name in columns)))
    for chunk in result.mappings().partitions(CHUNK):
        rows = [dict(row) for row in chunk]
        for row in rows:
            if deferred and any(row.get(name) is not None for name in deferred):
                later.append({**{key: row[key] for key in target.primary_key.columns.keys()},
                              **{name: row[name] for name in deferred}})
                row.update(dict.fromkeys(deferred))
        writer.execute(target.insert(), rows)
        total += len(rows)
    keys = list(target.primary_key.columns.keys())
    for row in later:
        writer.execute(update(target).where(*(target.c[key] == row[key] for key in keys))
                       .values({name: row[name] for name in deferred}))
    return total


def _reset_sequences(writer: Connection, tables: list[Table]) -> None:
    for table in tables:
        for column in table.primary_key.columns:
            if isinstance(column.type, Integer) and column.autoincrement in (True, "auto"):
                sequence = writer.scalar(text("SELECT pg_get_serial_sequence(:table, :column)"),
                                         {"table": table.name, "column": column.name})
                if sequence:
                    highest = writer.scalar(select(func.max(column)))
                    writer.execute(text("SELECT setval(:sequence, :value, :used)"),
                                   {"sequence": sequence, "value": highest or 1, "used": highest is not None})


__all__ = ["TransferRefused", "copy_local_to_server"]

