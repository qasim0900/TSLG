from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from techset_leadgen.config import Settings, load_settings
from techset_leadgen.database import migrations_util
from techset_leadgen.database.engine import create_db_engine, create_session_factory, utcnow
from techset_leadgen.database.models import (
    AssignmentBatch, AuditLog, AuthAttempt, Notification, Organization, OutreachEvent, Prospect,
    ProspectAssignment, Task, User, UserSession, UserToken,
)
from techset_leadgen.domain.outreach import balance_plan
from techset_leadgen.services import assignments, auth, notifications, outreach, prospects, tasks, users
from techset_leadgen.services.access import Actor
from techset_leadgen.services.schemas import (
    BatchCreate, OutreachRecord, Reassignment, TaskCreate, UserInvite, parse,
)

DEMO_DOMAIN = "demo.techset.example"
DEMO_PASSWORD = "Demo-Kettle-2026"
DEMO_SOURCE = "Demo data"
MANAGER = ("Ayesha Malik", "ayesha.malik", "sales_manager")
MEMBERS = [
    ("Bilal Ahmed", "bilal.ahmed", "bdr"),
    ("Sana Iqbal", "sana.iqbal", "bdr"),
    ("Usman Tariq", "usman.tariq", "account_executive"),
    ("Hira Shah", "hira.shah", "lead_researcher"),
    ("Zain Abbas", "zain.abbas", "bdr"),
]
VIEWER = ("Nadia Hussain", "nadia.hussain", "read_only")
FIRST = ["Ali", "Fatima", "Omar", "Zara", "Hamza", "Amna", "Saad", "Mahnoor", "Asad", "Iqra", "Daniyal", "Rabia",
         "Junaid", "Sadia", "Waqas", "Noor", "Emma", "James", "Sophie", "Ahmed", "Layla", "Yusuf", "Hassan", "Ayla"]
LAST = ["Khan", "Siddiqui", "Chaudhry", "Butt", "Mirza", "Sheikh", "Baig", "Hashmi", "Raza", "Akhtar", "Smith",
        "Taylor", "Al Mansoori", "Haddad", "Qureshi", "Farooq"]
COMPANIES = ["Tandoor House", "Kite Learning", "Orchid Skincare", "Harbor Logistics", "Margalla Realty",
             "Saffron Kitchen", "Indus Textiles", "Crescent Clinics", "Bluewater Travel", "Nimbus Software",
             "Ravi Motors", "Pearl Jewellers", "Greenfield Organics", "Apex Fitness", "Sapphire Hotels",
             "Northstar Consulting", "Chenab Builders", "Silverline Electronics", "Desert Rose Events",
             "Mehran Pharma", "Falcon Security", "Brightpath Academy", "Monsoon Media", "Zenith Insurance",
             "Gulf Freight", "Thames Legal", "Hunza Water", "Shalimar Interiors"]
TITLES = ["Founder", "CEO", "Managing Director", "Head of Marketing", "Marketing Manager", "Head of Growth",
          "Operations Manager", "Brand Manager", "Chief Technology Officer", "Sales Director"]
STORIES: list[tuple[int, list[str]]] = [
    (10, ["connection_sent"]),
    (8, ["connection_sent", "connection_accepted"]),
    (8, ["connection_sent", "connection_accepted", "message_sent"]),
    (7, ["connection_sent", "connection_accepted", "message_sent", "reply_received"]),
    (9, ["connection_sent", "connection_accepted", "message_sent", "reply_received", "follow_up_requested"]),
    (4, ["connection_sent", "connection_accepted", "message_sent", "reply_received", "meeting_requested"]),
    (4, ["connection_sent", "connection_accepted", "message_sent", "not_interested"]),
    (2, ["wrong_profile"]),
]
NOTES = {
    "message_sent": ["Sent the short intro about our SEO work.", "Shared the case study for their industry."],
    "reply_received": ["Interested, asked about pricing.", "Said they are busy this month.",
                       "Asked for examples of similar clients."],
    "follow_up_requested": ["Asked to be contacted again next week.", "Contact again after their board meeting."],
    "meeting_requested": ["Agreed to a 20-minute call.", "Wants a call with their marketing lead."],
    "not_interested": ["Already has an agency.", "No budget this year."],
    "wrong_profile": ["Left the company; profile out of date."],
}
GENERAL_TASKS = [
    ("Research 50 fintech founders in Karachi", "Add them as prospects with company and title.", "high", 2, False),
    ("Clean duplicate company names in prospects", "Same company written two ways; agree one spelling.",
     "medium", -1, False),
    ("Prepare the weekly outreach report", "Use Team performance → Export CSV for Monday to Friday.", "urgent",
     0, False),
    ("Review last week's rejected import rows", "Find the right profile addresses where possible.", "low", -3,
     True),
    ("Update the LinkedIn message templates", "Shorter intro; mention the new case study.", "medium", 5, False),
    ("Shortlist hospitality companies in Dubai", "Hotels and event companies, 30 names.", "medium", 3, False),
]

rng = random.Random(20261027)


def demo_email(local: str) -> str:
    return f"{local}@{DEMO_DOMAIN}"


def business_timezone(db: Session) -> str:
    organization = db.get(Organization, 1)
    return organization.timezone if organization is not None and organization.timezone else "UTC"


def working_days_before(day: date, count: int) -> list[date]:
    days: list[date] = []
    while len(days) < count:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            days.append(day)
    return sorted(days)


def next_working_day(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def acting_as(db: Session, user_id: str) -> Actor:
    user = db.get(User, user_id)
    assert user is not None
    return Actor.for_user(user)


def prepare(settings: Settings) -> sessionmaker[Session]:
    engine = create_db_engine(settings)
    with engine.connect() as connection:
        state = migrations_util.schema_state(connection)
    if state.newer_than_app:
        raise SystemExit("This database is newer than this copy of the app; nothing was changed.")
    if not state.ready:
        if settings.is_server:
            raise SystemExit("Run `python -m techset_leadgen --upgrade-database` first; nothing was changed.")
        migrations_util.upgrade(settings.database_url)
    with engine.connect() as connection:
        problems = migrations_util.layout_problems(connection)
    if problems:
        raise SystemExit("This is not a database this app can use: " + "; ".join(problems))
    return create_session_factory(engine)


def seed(settings: Settings, say: Callable[[str], None] = print) -> dict[str, int]:
    rng.seed(20261027)
    factory = prepare(settings)
    with factory() as db:
        if db.scalar(select(User.id).where(User.email.like(f"%@{DEMO_DOMAIN}"))) is not None:
            raise SystemExit("Demo data is already in this database (remove it first with --remove).")
        admin = db.scalar(select(User).where(User.role == "super_admin", User.is_active.is_(True))
                          .order_by(User.created_at))
        if admin is None and auth.has_users(db):
            raise SystemExit("This database has accounts but no active Super Admin; nothing was changed.")
        if admin is None:
            admin = auth.bootstrap_organization(db, organization_name="Techset Solutions (demo)",
                                                admin_email=demo_email("admin"), admin_name="Demo Admin",
                                                password=DEMO_PASSWORD)
            db.commit()
        admin_id = admin.id
        zone = ZoneInfo(business_timezone(db))

    now = utcnow()
    today = now.astimezone(zone).date()

    def at(day: date, hour: int, minute: int = 0) -> datetime:
        moment = datetime.combine(day, time(hour, minute), zone).astimezone(UTC)
        return min(moment, now - timedelta(minutes=5))

    people: dict[str, str] = {}
    with factory() as db:
        inviter = acting_as(db, admin_id)
        for name, local, role in [MANAGER, *MEMBERS, VIEWER]:
            user, code = users.invite_user(db, inviter, settings, parse(UserInvite, {
                "email": demo_email(local), "full_name": name, "role": role}))
            db.commit()
            auth.redeem_code(db, settings, raw_code=code, password=DEMO_PASSWORD)
            auth.revoke_sessions(db, user.id)
            user.timezone = zone.key
            db.commit()
            people[local] = user.id
    say(f"Team: {len(people)} demo accounts (password {DEMO_PASSWORD})")

    with factory() as db:
        manager = acting_as(db, people[MANAGER[1]])
        researcher = acting_as(db, people["hira.shah"])

        lines = []
        for number in range(150):
            first, last = rng.choice(FIRST), rng.choice(LAST)
            slug = f"{first}-{last}".lower().replace(" ", "-") + f"-{rng.randrange(16 ** 6):06x}"
            lines.append("\t".join((f"https://www.linkedin.com/in/{slug}/", f"{first} {last}",
                                    rng.choice(COMPANIES), rng.choice(TITLES))))
        lines += ["https://lnkd.in/abc123", lines[0]]
        result = prospects.import_rows(db, researcher, prospects.rows_from_text("\n".join(lines)),
                                       source=DEMO_SOURCE)
        db.commit()
        prospect_ids = list(result.created)
        rng.shuffle(prospect_ids)
        say(f"Prospects: {len(prospect_ids)} added "
            f"({len(result.preview.rejected)} rejected, {len(result.preview.repeated)} repeated rows)")

        past_days = working_days_before(today, 5)
        member_ids = [people[local] for _name, local, _role in MEMBERS]
        plan_days = [(day, 16, False) for day in past_days] + [(today, 18, False),
                                                                (next_working_day(today), 12, True)]
        queue = list(prospect_ids)
        counts = {"batches": 0, "assignments": 0, "events": 0, "follow_ups": 0, "completed": 0}
        for work_day, size, draft in plan_days:
            chosen, queue = queue[:size], queue[size:]
            open_work = {member.user_id: member.open_assignments
                         for member in assignments.assignable_members(db, manager) if member.user_id in member_ids}
            batch = assignments.create_batch(db, manager, parse(BatchCreate, {
                "name": f"Daily batch {work_day:%a %d %b}", "work_date": work_day, "draft": draft,
                "plan": [{"prospect_id": p, "assignee_id": u} for p, u in balance_plan(chosen, open_work)]}))
            db.flush()
            assigned_at = at(min(work_day, today), 9, 30) if not draft else now - timedelta(minutes=30)
            batch.created_at = assigned_at
            if not draft:
                batch.activated_at = assigned_at
            for row in assignments.assignments_for_batch(db, manager, batch.id):
                row.assigned_at = row.created_at = assigned_at
                row.prospect.created_at = row.prospect.updated_at = assigned_at - timedelta(hours=20)
            db.commit()
            counts["batches"] += 1
            counts["assignments"] += size
            if not draft:
                worked = _work_batch(db, batch.id, work_day, today, at, manager, zone, now)
                for key, value in worked.items():
                    counts[key] += value

        open_today = [row for row in assignments.list_assignments(db, manager, page=_page(), view="team").items
                      if row.due_on == today]
        by_member: dict[str, list[ProspectAssignment]] = {}
        for row in open_today:
            by_member.setdefault(row.assignee_id, []).append(row)
        source = people["zain.abbas"]
        if len(by_member.get(source, [])) < 2 and by_member:
            source = max(by_member, key=lambda user_id: len(by_member[user_id]))
        target = people["sana.iqbal"] if source != people["sana.iqbal"] else people["bilal.ahmed"]
        for row in by_member.get(source, [])[:2]:
            assignments.reassign(db, manager, row.id, parse(Reassignment, {
                "assignee_id": target, "reason": "On leave today."}))
        earlier = sorted((row for row in assignments.list_assignments(db, manager, page=_page(), view="team").items
                          if row.due_on is not None and row.due_on < today), key=lambda row: row.due_on)
        for row in earlier[:1]:
            assignments.cancel_assignment(db, manager, row.id, reason="Same company as another profile.")
        db.commit()

        for index, (title, details, priority, due_in, done) in enumerate(GENERAL_TASKS):
            owner = member_ids[index % len(member_ids)]
            due_day = today + timedelta(days=due_in)
            task = tasks.create_task(db, manager, parse(TaskCreate, {
                "title": title, "description": details, "priority": priority, "assigned_to_id": owner,
                "due_at": datetime.combine(due_day, time(17, 0), zone).isoformat()}))
            task.created_at = at(today - timedelta(days=4), 10)
            db.commit()
            if done:
                tasks.set_status(db, acting_as(db, owner), task.id, "done")
                task.completed_at = at(today - timedelta(days=1), 15)
                db.commit()
        notifications.mark_read(db, acting_as(db, people["bilal.ahmed"]))
        db.commit()
    counts["tasks"] = len(GENERAL_TASKS)
    say("Added: " + ", ".join(f"{value} {key.replace('_', ' ')}" for key, value in counts.items()))
    return counts


def _page():
    from techset_leadgen.services.pagination import MAX_PAGE_SIZE, PageRequest

    return PageRequest(page_size=MAX_PAGE_SIZE)


def _work_batch(db: Session, batch_id: str, work_day: date, today: date, at: Callable[..., datetime],
                manager: Actor, zone: ZoneInfo, now: datetime) -> dict[str, int]:
    counts = {"events": 0, "follow_ups": 0, "completed": 0}
    weights = [weight for weight, _story in STORIES]
    latest = now - timedelta(minutes=2)
    for row in assignments.assignments_for_batch(db, manager, batch_id):
        if work_day == today and rng.random() < 0.45:
            continue
        member = acting_as(db, row.assignee_id)
        story = rng.choices([story for _weight, story in STORIES], weights=weights)[0]
        if work_day == today:
            story = story[:2]
        moment = max(row.assigned_at, min(at(work_day, 10, rng.randrange(60)), latest))
        follow_up_moment: datetime | None = None
        for step, event in enumerate(story):
            if step:
                moment = min(moment + timedelta(hours=rng.randint(1, 20)), latest)
            values: dict[str, object] = {"prospect_id": row.prospect_id, "event_type": event}
            if event in NOTES:
                values["note"] = rng.choice(NOTES[event])
            if event == "follow_up_requested":
                target = today + timedelta(days=rng.choice((-2, -1, 0, 0, 1, 2, 4, 6)))
                due = datetime.combine(target, time(rng.choice((10, 11, 15, 16))), zone).astimezone(UTC)
                if due <= moment:
                    due = moment + timedelta(hours=rng.randint(20, 60))
                values["follow_up_at"] = due.isoformat()
                follow_up_moment = moment
            outreach.record_event(db, member, parse(OutreachRecord, values), now=moment)
            counts["events"] += 1
        if follow_up_moment is not None:
            follow_up = db.scalar(select(Task).where(Task.kind == "follow_up", Task.status == "open",
                                                     Task.prospect_id == row.prospect_id))
            if follow_up is not None:
                follow_up.created_at = follow_up_moment
                counts["follow_ups"] += 1
                if follow_up.due_at is not None and follow_up.due_at < at(today, 0) and rng.random() < 0.3:
                    tasks.complete_follow_up(db, member, follow_up.id, outcome="Spoke again; still interested.")
                    follow_up.completed_at = min(follow_up.due_at + timedelta(hours=1), latest)
        if story[-1] in {"meeting_requested", "not_interested", "wrong_profile"} or (
                work_day != today and story[-1] == "reply_received" and rng.random() < 0.5):
            assignments.complete_assignment(db, member, row.id, reason="Outreach finished.")
            row.closed_at = min(moment + timedelta(minutes=10), latest)
            counts["completed"] += 1
        db.commit()
    return counts


def remove(settings: Settings, say: Callable[[str], None] = print) -> dict[str, int]:
    factory = prepare(settings)
    with factory() as db:
        demo_users = select(User.id).where(User.email.like(f"%@{DEMO_DOMAIN}"))
        demo_prospects = select(Prospect.id).where(Prospect.source == DEMO_SOURCE)
        demo_assignments = select(ProspectAssignment.id).where(ProspectAssignment.prospect_id.in_(demo_prospects))
        demo_tasks = select(Task.id).where(or_(Task.prospect_id.in_(demo_prospects),
                                               Task.created_by_id.in_(demo_users)))
        still_assigned = db.scalar(select(func.count()).select_from(ProspectAssignment).where(
            ProspectAssignment.assignee_id.in_(demo_users), ProspectAssignment.prospect_id.not_in(demo_prospects)))
        if still_assigned:
            raise SystemExit(f"{still_assigned} of your own prospects are assigned to demo accounts; reassign them "
                             "first. Nothing was removed.")
        removed: dict[str, int] = {}
        steps = [
            ("notifications", delete(Notification).where(or_(
                Notification.recipient_id.in_(demo_users),
                (Notification.entity_type == "prospect_assignment") & Notification.entity_id.in_(demo_assignments),
                (Notification.entity_type == "task") & Notification.entity_id.in_(demo_tasks)))),
            ("tasks", delete(Task).where(Task.id.in_(demo_tasks))),
            ("outreach events", delete(OutreachEvent).where(OutreachEvent.prospect_id.in_(demo_prospects))),
            ("assignments", delete(ProspectAssignment).where(ProspectAssignment.prospect_id.in_(demo_prospects))),
            ("batches", delete(AssignmentBatch).where(
                AssignmentBatch.created_by_id.in_(demo_users),
                ~select(ProspectAssignment.id).where(ProspectAssignment.batch_id == AssignmentBatch.id).exists())),
            ("prospects", delete(Prospect).where(Prospect.source == DEMO_SOURCE)),
            ("audit entries", delete(AuditLog).where(AuditLog.actor_user_id.in_(demo_users))),
            ("sessions", delete(UserSession).where(UserSession.user_id.in_(demo_users))),
            ("codes", delete(UserToken).where(UserToken.user_id.in_(demo_users))),
            ("sign-in attempts", delete(AuthAttempt).where(AuthAttempt.email.like(f"%@{DEMO_DOMAIN}"))),
            ("accounts", delete(User).where(User.email.like(f"%@{DEMO_DOMAIN}"))),
        ]
        for name, statement in steps:
            result = db.execute(statement.execution_options(synchronize_session=False))
            removed[name] = int(getattr(result, "rowcount", 0) or 0)
        db.commit()
    say("Removed: " + ", ".join(f"{count} {name}" for name, count in removed.items() if count))
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Add (or remove) LinkedIn-outreach demo data.")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--remove", action="store_true", help="delete the demo data instead of adding it")
    options = parser.parse_args()
    settings = load_settings()
    action = "Remove the demo data from" if options.remove else "Add demo data to"
    print(f"{action}: {settings.display_database}")
    if not options.yes and input("Continue? [y/N] ").strip().lower() != "y":
        print("Nothing was changed.")
        return 1
    if options.remove:
        remove(settings)
    else:
        seed(settings)
        print(f"Sign in as {demo_email(MANAGER[1])} (manager) or {demo_email('bilal.ahmed')} (team member) "
              f"with the password {DEMO_PASSWORD}. Remove it all with --remove.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

