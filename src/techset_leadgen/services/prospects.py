from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from techset_leadgen.domain.outreach import ACTIVE_ASSIGNMENT_STATUSES, OPEN_ASSIGNMENT_STATUSES

from techset_leadgen.database.engine import new_id, utcnow
from techset_leadgen.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from techset_leadgen.database.models import OutreachEvent, Prospect, ProspectAssignment, Task, User
from techset_leadgen.services.schemas import ProspectCreate, ProspectRow, ProspectUpdate
from techset_leadgen.security.permissions import Scope
from techset_leadgen.domain.vocabulary import ASSIGNMENT_STATUSES, OUTREACH_EVENTS, PROSPECT_STATUSES
from techset_leadgen.services import audit
from techset_leadgen.services.access import Actor, get_record, user_names
from techset_leadgen.services.common import check_version
from techset_leadgen.services.normalize import InvalidValue, linkedin_profile
from techset_leadgen.services.pagination import Page, PageRequest, like_pattern, paginate

MAX_IMPORT_ROWS = 5000
_LOOKUP_CHUNK = 500
AUDITED_FIELDS = ("linkedin_url", "full_name", "company", "job_title", "notes")
SORTS = {"name": func.lower(Prospect.full_name), "company": func.lower(Prospect.company),
         "status": Prospect.status, "added": Prospect.created_at, "activity": Prospect.last_activity_at,
         "follow_up": Prospect.next_follow_up_at}
FOLLOW_UP_FILTERS = {"due": "Follow-up due today or overdue", "scheduled": "Has a follow-up",
                     "none": "No follow-up"}


def _given_to(user_id: str) -> Any:
    return exists(select(ProspectAssignment.id).where(ProspectAssignment.prospect_id == Prospect.id,
                                                      ProspectAssignment.assignee_id == user_id,
                                                      ProspectAssignment.status != "planned"))


def visibility(actor: Actor) -> Any:
    scope = actor.require("prospects.view")
    if scope is Scope.ALL:
        return Prospect.id.is_not(None)
    return or_(Prospect.created_by_id == actor.user_id, _given_to(actor.user_id))


def get_prospect(db: Session, actor: Actor, prospect_id: Any) -> Prospect:
    condition = visibility(actor)
    key = str(prospect_id or "").strip()
    prospect = db.scalar(select(Prospect).where(Prospect.id == key, condition)) if key else None
    if prospect is None:
        raise NotFound()
    return prospect


def open_assignment(db: Session, prospect_id: str) -> ProspectAssignment | None:
    return db.scalar(select(ProspectAssignment).where(
        ProspectAssignment.prospect_id == prospect_id,
        ProspectAssignment.status.in_(sorted(OPEN_ASSIGNMENT_STATUSES))))


def works_on(actor: Actor, assignment: ProspectAssignment | None) -> bool:
    return (assignment is not None and assignment.assignee_id == actor.user_id
            and assignment.status in ACTIVE_ASSIGNMENT_STATUSES)


def can_edit(db: Session, actor: Actor, prospect: Prospect) -> bool:
    scope = actor.scope("prospects.edit")
    if scope is Scope.ALL:
        return True
    if scope is Scope.OWN:
        return prospect.created_by_id == actor.user_id or works_on(actor, open_assignment(db, prospect.id))
    return False


def _identity(value: str | None, *, field_name: str = "linkedin_url") -> tuple[str, str]:
    try:
        return linkedin_profile(value)
    except InvalidValue as exc:
        raise ValidationFailed(str(exc), fields={field_name: str(exc)}) from exc


def _existing_by_key(db: Session, key: str, *, exclude: str | None = None) -> Prospect | None:
    statement = select(Prospect).where(Prospect.linkedin_key == key)
    if exclude is not None:
        statement = statement.where(Prospect.id != exclude)
    return db.scalar(statement)


def create_prospect(db: Session, actor: Actor, data: ProspectCreate) -> Prospect:
    actor.require("prospects.create")
    key, url = _identity(data.linkedin_url)
    existing = _existing_by_key(db, key)
    if existing is not None:
        raise Conflict("This LinkedIn profile is already a prospect.",
                       fields={"linkedin_url": "Already added."},
                       details={"duplicate": "prospect", "existing_id": existing.id})
    now = utcnow()
    prospect = Prospect(linkedin_key=key, linkedin_url=url, full_name=data.full_name, company=data.company,
                        job_title=data.job_title, notes=data.notes, source=data.source or "Added by hand",
                        status="new", created_by_id=actor.user_id, created_at=now, updated_at=now)
    db.add(prospect)
    db.flush()
    audit.record(db, actor, "prospect.created", entity_type="prospect", entity_id=prospect.id,
                 changes={"linkedin_url": url, "source": prospect.source})
    return prospect


def update_prospect(db: Session, actor: Actor, prospect_id: Any, data: ProspectUpdate) -> Prospect:
    prospect = get_prospect(db, actor, prospect_id)
    if not can_edit(db, actor, prospect):
        raise PermissionDenied("You can edit only prospects assigned to you.")
    changes = data.model_dump(exclude_unset=True)
    check_version(prospect, changes.pop("version", None))
    if "linkedin_url" in changes:
        if not changes["linkedin_url"]:
            raise ValidationFailed("Enter the LinkedIn profile address.",
                                   fields={"linkedin_url": "This field is required."})
        key, url = _identity(changes.pop("linkedin_url"))
        if key != prospect.linkedin_key:
            other = _existing_by_key(db, key, exclude=prospect.id)
            if other is not None:
                raise Conflict("Another prospect already has this LinkedIn profile.",
                               fields={"linkedin_url": "Already used by another prospect."},
                               details={"duplicate": "prospect", "existing_id": other.id})
            prospect.linkedin_key = key
        changes["linkedin_url"] = url
    before = audit.snapshot(prospect, AUDITED_FIELDS)
    for name, value in changes.items():
        setattr(prospect, name, value)
    delta = audit.diff(before, audit.snapshot(prospect, AUDITED_FIELDS))
    if delta:
        prospect.updated_at = utcnow()
        db.flush()
        audit.record(db, actor, "prospect.updated", entity_type="prospect", entity_id=prospect.id, changes=delta)
    return prospect


@dataclass(frozen=True)
class RowProblem:
    row: int
    value: str
    reason: str


@dataclass(frozen=True)
class CheckedRow:
    row: int
    key: str
    url: str
    full_name: str | None
    company: str | None
    job_title: str | None
    existing_id: str | None = None
    assigned_to: str | None = None


@dataclass(frozen=True)
class ImportPreview:
    new: list[CheckedRow] = field(default_factory=list)
    existing: list[CheckedRow] = field(default_factory=list)
    repeated: list[RowProblem] = field(default_factory=list)
    rejected: list[RowProblem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.new) + len(self.existing) + len(self.repeated) + len(self.rejected)


_URL_TOKEN = re.compile(r"\S*(?:linkedin\.com|lnkd\.in)\S*", re.IGNORECASE)


def rows_from_text(text: str) -> list[ProspectRow]:
    rows: list[ProspectRow] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if "\t" in line:
            cells = [cell.strip() for cell in line.split("\t")]
            url_index = next((index for index, cell in enumerate(cells) if _URL_TOKEN.search(cell)), 0)
            others: list[str | None] = []
            others += [cell for index, cell in enumerate(cells) if index != url_index and cell][:3]
            others += [None] * (3 - len(others))
            rows.append(_row(number, cells[url_index], *others))
            continue
        match = _URL_TOKEN.search(line)
        rows.append(_row(number, match.group(0) if match else line.strip()))
    return rows


_URL_HEADERS = ("linkedin url", "linkedin profile", "linkedin", "profile url", "profile", "url", "linkedin_url",
                "profile link", "link")
_NAME_HEADERS = ("full name", "name", "full_name", "prospect", "contact")
_FIRST_HEADERS = ("first name", "first_name", "firstname")
_LAST_HEADERS = ("last name", "last_name", "lastname", "surname")
_COMPANY_HEADERS = ("company", "company name", "organization", "organisation", "employer", "account")
_TITLE_HEADERS = ("job title", "title", "position", "role", "job_title", "headline")


def rows_from_table(headers: Sequence[str], records: Iterable[dict[str, Any]]) -> list[ProspectRow]:
    def pick(options: Sequence[str]) -> str | None:
        return next((header for header in options if header in headers), None)

    url_column = pick(_URL_HEADERS)
    if url_column is None:
        raise ValidationFailed("The file needs a column with the LinkedIn profile addresses "
                               "(for example “LinkedIn URL”).")
    name, first, last = pick(_NAME_HEADERS), pick(_FIRST_HEADERS), pick(_LAST_HEADERS)
    company, title = pick(_COMPANY_HEADERS), pick(_TITLE_HEADERS)
    rows: list[ProspectRow] = []
    for number, record in enumerate(records, start=2):
        def cell(column: str | None) -> str | None:
            value = record.get(column) if column else None
            return None if value is None else str(value).strip() or None

        url = cell(url_column)
        full_name = cell(name) or " ".join(part for part in (cell(first), cell(last)) if part) or None
        if url is None and full_name is None and cell(company) is None:
            continue
        rows.append(_row(number, url, full_name, cell(company), cell(title)))
    return rows


def _row(number: int, url: str | None, full_name: str | None = None, company: str | None = None,
         job_title: str | None = None) -> ProspectRow:
    def clip(value: str | None) -> str | None:
        return value[:200] if value else value

    return ProspectRow(row=number, linkedin_url=url, full_name=clip(full_name), company=clip(company),
                       job_title=clip(job_title))


def check_rows(db: Session, actor: Actor, rows: Sequence[ProspectRow]) -> ImportPreview:
    actor.require("prospects.create")
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValidationFailed(f"Add at most {MAX_IMPORT_ROWS} profiles at a time.")
    preview = ImportPreview()
    seen: dict[str, int] = {}
    valid: list[CheckedRow] = []
    for row in rows:
        value = (row.linkedin_url or "").strip()
        if not value:
            preview.rejected.append(RowProblem(row.row, "", "No LinkedIn address in this row."))
            continue
        try:
            key, url = linkedin_profile(value)
        except InvalidValue as exc:
            preview.rejected.append(RowProblem(row.row, value, str(exc)))
            continue
        if key in seen:
            preview.repeated.append(RowProblem(row.row, value, f"Same profile as row {seen[key]}."))
            continue
        seen[key] = row.row
        valid.append(CheckedRow(row.row, key, url, row.full_name, row.company, row.job_title))
    found = _lookup(db, [row.key for row in valid])
    for checked in valid:
        match = found.get(checked.key)
        if match is None:
            preview.new.append(checked)
        else:
            preview.existing.append(CheckedRow(checked.row, checked.key, checked.url, checked.full_name,
                                               checked.company, checked.job_title,
                                               existing_id=match[0], assigned_to=match[1]))
    return preview


def _lookup(db: Session, keys: Sequence[str]) -> dict[str, tuple[str, str | None]]:
    found: dict[str, tuple[str, str | None]] = {}
    for start in range(0, len(keys), _LOOKUP_CHUNK):
        chunk = list(keys[start:start + _LOOKUP_CHUNK])
        statement = (select(Prospect.linkedin_key, Prospect.id, User.full_name)
                     .outerjoin(ProspectAssignment, and_(ProspectAssignment.prospect_id == Prospect.id,
                                                         ProspectAssignment.status.in_(
                                                             sorted(OPEN_ASSIGNMENT_STATUSES))))
                     .outerjoin(User, User.id == ProspectAssignment.assignee_id)
                     .where(Prospect.linkedin_key.in_(chunk)))
        for key, prospect_id, assignee in db.execute(statement):
            found[key] = (prospect_id, assignee)
    return found


@dataclass(frozen=True)
class ImportResult:
    created: list[str]
    existing: list[str]
    preview: ImportPreview

    @property
    def prospect_ids(self) -> list[str]:
        order = {row.key: row.row for row in (*self.preview.new, *self.preview.existing)}
        by_key = dict(zip((row.key for row in self.preview.new), self.created, strict=True))
        by_key.update({row.key: row.existing_id or "" for row in self.preview.existing})
        return [by_key[key] for key in sorted(by_key, key=order.__getitem__)]


def import_rows(db: Session, actor: Actor, rows: Sequence[ProspectRow], *, source: str) -> ImportResult:
    preview = check_rows(db, actor, rows)
    now = utcnow()
    new_rows = [Prospect(id=new_id(), linkedin_key=row.key, linkedin_url=row.url, full_name=row.full_name,
                         company=row.company, job_title=row.job_title, source=source[:120], status="new",
                         created_by_id=actor.user_id, created_at=now, updated_at=now) for row in preview.new]
    db.add_all(new_rows)
    db.flush()
    created = [prospect.id for prospect in new_rows]
    if created:
        audit.record(db, actor, "prospect.imported", entity_type="prospect", changes={
            "source": source[:120], "added": len(created), "already_prospects": len(preview.existing),
            "repeated_rows": len(preview.repeated), "rejected_rows": len(preview.rejected)})
    return ImportResult(created, [row.existing_id or "" for row in preview.existing], preview)


@dataclass(frozen=True)
class ProspectListRow:
    prospect: Prospect
    assignment_status: str | None
    assignee_id: str | None
    assignee_name: str | None


def list_prospects(db: Session, actor: Actor, *, page: PageRequest, q: str | None = None,
                   status: str | None = None, assignee: str | None = None, follow_up: str | None = None,
                   now: datetime | None = None) -> Page[ProspectListRow]:
    current = aliased(ProspectAssignment)
    statement = (select(Prospect, current.status, current.assignee_id, User.full_name)
                 .outerjoin(current, and_(current.prospect_id == Prospect.id,
                                          current.status.in_(sorted(OPEN_ASSIGNMENT_STATUSES))))
                 .outerjoin(User, User.id == current.assignee_id)
                 .where(visibility(actor)))
    if q and q.strip():
        pattern = like_pattern(q)
        statement = statement.where(or_(func.lower(Prospect.full_name).like(pattern, escape="\\"),
                                        func.lower(Prospect.company).like(pattern, escape="\\"),
                                        func.lower(Prospect.job_title).like(pattern, escape="\\"),
                                        Prospect.linkedin_key.like(pattern, escape="\\")))
    if status:
        statement = statement.where(Prospect.status == status)
    if assignee == "me":
        statement = statement.where(current.assignee_id == actor.user_id)
    elif assignee == "none":
        statement = statement.where(current.id.is_(None))
    elif assignee:
        statement = statement.where(current.assignee_id == assignee)
    moment = now or utcnow()
    if follow_up == "due":
        statement = statement.where(Prospect.next_follow_up_at.is_not(None),
                                    Prospect.next_follow_up_at < _end_of_day(actor.timezone, moment))
    elif follow_up == "scheduled":
        statement = statement.where(Prospect.next_follow_up_at.is_not(None))
    elif follow_up == "none":
        statement = statement.where(Prospect.next_follow_up_at.is_(None))
    page_ = paginate(db, cast(Any, statement), page, SORTS, "-added", tiebreaker=Prospect.id, rows=True)
    items = [ProspectListRow(prospect, state, assignee_id, name) for prospect, state, assignee_id, name in page_.items]
    return Page(items, page_.page, page_.page_size, page_.total)


def _end_of_day(timezone: str, now: datetime) -> datetime:
    from techset_leadgen.services.tasks import local_day_bounds

    return local_day_bounds(timezone, now)[1]


@dataclass(frozen=True)
class HistoryEntry:
    kind: str
    occurred_at: datetime
    title: str
    detail: str | None
    actor_name: str | None


def assignments_for(db: Session, actor: Actor, prospect: Prospect) -> list[ProspectAssignment]:
    from sqlalchemy.orm import joinedload

    get_prospect(db, actor, prospect.id)
    return list(db.scalars(select(ProspectAssignment).where(ProspectAssignment.prospect_id == prospect.id)
                           .options(joinedload(ProspectAssignment.assignee), joinedload(ProspectAssignment.batch))
                           .order_by(ProspectAssignment.assigned_at.desc(), ProspectAssignment.id)))


def events_for(db: Session, actor: Actor, prospect: Prospect, *, limit: int = 200) -> list[OutreachEvent]:
    get_prospect(db, actor, prospect.id)
    return list(db.scalars(select(OutreachEvent).where(OutreachEvent.prospect_id == prospect.id)
                           .order_by(OutreachEvent.occurred_at.desc(), OutreachEvent.created_at.desc())
                           .limit(limit)))


def history(db: Session, actor: Actor, prospect: Prospect, *, limit: int = 200) -> list[HistoryEntry]:
    names = user_names(db)
    entries = [HistoryEntry("event", event.occurred_at, OUTREACH_EVENTS.get(event.event_type, event.event_type),
                            event.note, names.get(event.recorded_by_id or ""))
               for event in events_for(db, actor, prospect, limit=limit)]
    for assignment in assignments_for(db, actor, prospect)[:limit]:
        assignee = names.get(assignment.assignee_id, "someone")
        title = f"Assigned to {assignee}" if assignment.previous_assignment_id is None \
            else f"Reassigned to {assignee}"
        if assignment.status == "planned":
            title = f"Planned for {assignee} (draft batch)"
        entries.append(HistoryEntry("assignment", assignment.assigned_at, title,
                                    assignment.batch.name if assignment.batch else None,
                                    names.get(assignment.assigned_by_id or "")))
        if assignment.closed_at is not None and assignment.status != "reassigned":
            entries.append(HistoryEntry("assignment", assignment.closed_at,
                                        f"Assignment {ASSIGNMENT_STATUSES[assignment.status].lower()}",
                                        assignment.close_reason, names.get(assignment.closed_by_id or "")))
    for task in db.scalars(select(Task).where(Task.prospect_id == prospect.id, Task.kind == "follow_up")
                           .order_by(Task.created_at.desc()).limit(limit)):
        entries.append(HistoryEntry("follow_up", task.created_at, "Follow-up scheduled", task.description,
                                    names.get(task.created_by_id or "")))
        if task.status == "done" and task.completed_at is not None:
            entries.append(HistoryEntry("follow_up", task.completed_at, "Follow-up done", task.outcome,
                                        names.get(task.assigned_to_id or "")))
    entries.sort(key=lambda item: item.occurred_at, reverse=True)
    return entries[:limit]


def status_label(status: str) -> str:
    return PROSPECT_STATUSES.get(status, status)


__all__ = ["CheckedRow", "HistoryEntry", "ImportPreview", "ImportResult", "ProspectListRow", "RowProblem",
           "can_edit", "check_rows", "create_prospect", "get_prospect", "get_record", "history", "import_rows",
           "list_prospects", "open_assignment", "rows_from_table", "rows_from_text", "update_prospect",
           "visibility", "works_on"]

