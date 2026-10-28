"""Regression tests that keep read-query counts independent of dataset size.

These tests deliberately measure SQL statements rather than elapsed time. Wall-clock
timings vary across CI hosts, while a query count catches an accidental N+1 reliably.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any

import pytest

from techset_leadgen.analytics.analysis.leads_analysis import get_leads_with_client_info
from techset_leadgen.analytics.controllers.clients_controller import ClientsController
from techset_leadgen.database import local_db as db
from techset_leadgen.database.local_db import get_connection, init_db
from techset_leadgen.analytics.models.client_manager import invalidate_clients_cache
from techset_leadgen.analytics.models.client_duplicates import merge_clients_by_name
from techset_leadgen.analytics.dashboard_kpi_service import DashboardKPIService


@dataclass
class ReadQueryCounter:
    """Collect SELECT/CTE statements emitted by newly opened connections."""

    statements: list[str] = field(default_factory=list)

    def trace(self, statement: str) -> None:
        normalized = " ".join(statement.split())
        command = normalized.lstrip().upper()
        if command.startswith(("SELECT ", "WITH ")):
            self.statements.append(normalized)

    def measure(self, operation: Callable[[], Any]) -> tuple[Any, tuple[str, ...]]:
        self.statements.clear()
        result = operation()
        return result, tuple(self.statements)


@pytest.fixture()
def query_counter(monkeypatch: pytest.MonkeyPatch) -> ReadQueryCounter:
    """Attach one trace callback to every connection created during a test."""

    counter = ReadQueryCounter()
    real_connect = sqlite3.connect

    def counting_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(counter.trace)
        return connection

    monkeypatch.setattr(db.sqlite3, "connect", counting_connect)
    return counter


@pytest.fixture(autouse=True)
def isolated_database() -> None:
    """Reset the pytest-only database around every query-scaling scenario."""

    init_db()
    _clear_database()
    yield
    _clear_database()


def _clear_database() -> None:
    with closing(get_connection()) as connection:
        with connection:
            for table in (
                "funnel_events",
                "leads",
                "sales",
                "marketing_spend",
                "import_metadata",
                "clients",
            ):
                connection.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed whitelist
    invalidate_clients_cache()


def _seed_dataset(client_count: int) -> None:
    """Create clients with two sales and one joined lead each."""

    clients = [
        (
            f"C-{index:04d}",
            f"Client {index:04d}",
            f"CIF{index:08d}",
            f"{index} Market Street",
            f"Contact {index:04d}",
            f"client{index:04d}@example.com",
        )
        for index in range(client_count)
    ]
    sales = [
        (
            f"Client {index:04d}",
            f"C-{index:04d}",
            product,
            float(100 + index + offset),
            f"2026-10-{(index % 20) + 1:02d}",
        )
        for index in range(client_count)
        for offset, product in enumerate(("Automation", "Support"))
    ]
    leads = [
        (
            f"L-{index:04d}",
            f"EXT-{index:04d}",
            f"2026-10-{(index % 20) + 1:02d}",
            ("meta_ads", "google_ads", "referral")[index % 3],
            "converted",
            f"2026-10-{(index % 20) + 2:02d}",
            f"C-{index:04d}",
        )
        for index in range(client_count)
    ]

    with closing(get_connection()) as connection:
        with connection:
            connection.executemany(
                """
                INSERT INTO clients (id, name, cif, address, contact_person, email)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                clients,
            )
            connection.executemany(
                """
                INSERT INTO sales (client_name, client_id, product_type, price, date)
                VALUES (?, ?, ?, ?, ?)
                """,
                sales,
            )
            connection.executemany(
                """
                INSERT INTO leads
                    (id, external_id, created_at, source, status, meeting_date, client_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                leads,
            )
            connection.execute(
                """
                INSERT INTO import_metadata
                    (imported_at, file_name, total_rows, valid_rows, rejected_rows,
                     duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("2026-10-20T10:30:00", "seed.csv", len(sales), len(sales), 0, 0.1),
            )
    invalidate_clients_cache()


def _measure_at_scales(
    counter: ReadQueryCounter,
    operation: Callable[[], Any],
    *,
    small_size: int = 3,
    large_size: int = 250,
) -> tuple[tuple[Any, tuple[str, ...]], tuple[Any, tuple[str, ...]]]:
    _seed_dataset(small_size)
    small = counter.measure(operation)

    _clear_database()
    _seed_dataset(large_size)
    large = counter.measure(operation)
    return small, large


def _seed_duplicate_group(size: int) -> None:
    clients = [
        (f"D-{index:04d}", "Duplicate Ltd", f"DUP{index:08d}", "", "", "")
        for index in range(size)
    ]
    sales = [
        ("Duplicate Ltd", f"D-{index:04d}", "Support", 100.0 + index, "2026-10-20")
        for index in range(size)
    ]
    with closing(get_connection()) as connection:
        with connection:
            connection.executemany(
                """
                INSERT INTO clients (id, name, cif, address, contact_person, email)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                clients,
            )
            connection.executemany(
                """
                INSERT INTO sales (client_name, client_id, product_type, price, date)
                VALUES (?, ?, ?, ?, ?)
                """,
                sales,
            )


def _measure_duplicate_merge(
    counter: ReadQueryCounter,
    size: int,
) -> tuple[tuple[int, list[str]], tuple[str, ...]]:
    _seed_duplicate_group(size)
    return counter.measure(merge_clients_by_name)


def test_client_listing_query_count_does_not_scale_with_clients(
    query_counter: ReadQueryCounter,
) -> None:
    (small_rows, small_sql), (large_rows, large_sql) = _measure_at_scales(
        query_counter,
        ClientsController.get_all_clients_with_sales,
    )

    assert len(small_rows) == 3
    assert len(large_rows) == 250
    assert len(small_sql) == len(large_sql) == 1


def test_enriched_leads_use_one_join_query_at_both_scales(
    query_counter: ReadQueryCounter,
) -> None:
    (small_rows, small_sql), (large_rows, large_sql) = _measure_at_scales(
        query_counter,
        get_leads_with_client_info,
    )

    assert len(small_rows) == 3
    assert len(large_rows) == 250
    assert len(small_sql) == len(large_sql) == 1
    assert "LEFT JOIN clients" in large_sql[0]


def test_dashboard_snapshot_query_count_is_constant(
    query_counter: ReadQueryCounter,
) -> None:
    (small_snapshot, small_sql), (large_snapshot, large_sql) = _measure_at_scales(
        query_counter,
        DashboardKPIService.build_snapshot,
    )

    assert small_snapshot.clients_rows == 3
    assert large_snapshot.clients_rows == 250
    assert small_snapshot.total_leads == 3
    assert large_snapshot.total_leads == 250
    assert len(small_sql) == len(large_sql) == 2


def test_duplicate_merge_batches_client_lookup_at_both_scales(
    query_counter: ReadQueryCounter,
) -> None:
    (small_result, small_sql) = _measure_duplicate_merge(query_counter, 2)
    _clear_database()
    (large_result, large_sql) = _measure_duplicate_merge(query_counter, 100)

    assert small_result[0] == 1
    assert large_result[0] == 99
    # Before batching this path issued 3, 11, and 101 SELECTs for groups of
    # 2, 10, and 100 respectively. It must now remain fixed at three reads.
    assert len(small_sql) == len(large_sql) == 3

    with closing(get_connection()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 100
        assert connection.execute(
            "SELECT COUNT(DISTINCT client_id) FROM sales"
        ).fetchone()[0] == 1
