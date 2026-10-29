from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


@dataclass(frozen=True)
class PageRequest:
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    sort: str | None = None
    descending: bool = False

    @classmethod
    def of(cls, page: Any = 1, page_size: Any = DEFAULT_PAGE_SIZE, sort: str | None = None) -> PageRequest:
        def _int(value: Any, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        size = min(max(_int(page_size, DEFAULT_PAGE_SIZE), 1), MAX_PAGE_SIZE)
        number = max(_int(page, 1), 1)
        descending = bool(sort and sort.startswith("-"))
        return cls(page=number, page_size=size, sort=(sort or "").lstrip("-") or None, descending=descending)


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int

    @property
    def pages(self) -> int:
        return max((self.total + self.page_size - 1) // self.page_size, 1)

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def first_index(self) -> int:
        return 0 if self.total == 0 else (self.page - 1) * self.page_size + 1

    @property
    def last_index(self) -> int:
        return min(self.page * self.page_size, self.total)


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_pattern(term: str) -> str:
    return f"%{escape_like(term.strip().lower())}%"


def paginate(
    session: Session,
    statement: Select[Any],
    request: PageRequest,
    sort_columns: dict[str, Any],
    default_sort: str,
    *,
    tiebreaker: Any,
    rows: bool = False,
) -> Page[Any]:
    key = request.sort if request.sort in sort_columns else default_sort.lstrip("-")
    descending = request.descending if request.sort in sort_columns else default_sort.startswith("-")
    column = sort_columns[key]
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    pages = max((total + request.page_size - 1) // request.page_size, 1)
    number = min(request.page, pages)
    ordered = statement.order_by(column.desc() if descending else column.asc(), tiebreaker)
    window = ordered.limit(request.page_size).offset((number - 1) * request.page_size)
    items = list(session.execute(window).all()) if rows else list(session.scalars(window).unique().all())
    return Page(items=items, page=number, page_size=request.page_size, total=total)

