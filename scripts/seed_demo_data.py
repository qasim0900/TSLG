"""Fill the local database with demo data for the Archive (sales, leads, clients analytics).

For the LinkedIn-outreach workflow (on the team database or a local file) use
``scripts/seed_outreach_demo.py`` instead.

    poetry run python scripts/seed_demo_data.py         # asks before changing anything
    poetry run python scripts/seed_demo_data.py --yes   # no question

It uses the database the app opens (``data/sales.db``, or ``FDT_DATA_DIR``). A new or
empty database is prepared the way the app prepares it on start, and gets a demo
organization whose Super Admin is ``admin@demo.techset.example``; otherwise the demo
records are added by the first existing Super Admin.

* The database is backed up first, to ``data/backups/sales-before-demo-data-<time>.db``;
  copy that file back over ``data/sales.db`` (with the app closed) to remove the demo data.
* Records go in through the app's own importer and services, so they pass the same
  validation and permissions as the screens and appear in the audit log, as changes made
  by the first Super Admin.
* Demo people use ``@demo.techset.example`` addresses; the script refuses to run twice.

Everything is random but reproducible (a fixed seed), with dates relative to today.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import tempfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select  # noqa: E402

from techset_leadgen.database.local_db import init_db  # noqa: E402
from techset_leadgen.analytics.importer import import_csv_to_db, import_leads_to_db, import_marketing_spend_to_db  # noqa: E402
from techset_leadgen.database import migrations_util  # noqa: E402
from techset_leadgen.config import load_settings  # noqa: E402
from techset_leadgen.database.engine import create_db_engine, create_session_factory  # noqa: E402
from techset_leadgen.database.models import Client, Lead, User  # noqa: E402
from techset_leadgen.services.schemas import (  # noqa: E402
    ActivityCreate, BulkAssignment, ClientCreate, ClientUpdate, ContactCreate, LeadCreate, LeadTransition,
    TaskCreate, UserAdminUpdate, UserInvite, parse,
)
from techset_leadgen.services import activities, auth, clients, contacts, leads, maintenance, tasks, users  # noqa: E402
from techset_leadgen.services.access import Actor  # noqa: E402
from techset_leadgen.desktop.session import system_timezone  # noqa: E402

DEMO_DOMAIN = "demo.techset.example"
DEMO_PASSWORD = "Demo-Kettle-2026"  # passes the password policy; shared by every demo account
rng = random.Random(20261023)
today = date.today()

TEAM = [  # name, local part, role
    ("Ayesha Malik", "ayesha.malik", "sales_manager"),
    ("Bilal Ahmed", "bilal.ahmed", "bdr"),
    ("Sana Iqbal", "sana.iqbal", "bdr"),
    ("Usman Tariq", "usman.tariq", "account_executive"),
    ("Hira Shah", "hira.shah", "lead_researcher"),
    ("Kamran Javed", "kamran.javed", "marketing"),
    ("Nadia Hussain", "nadia.hussain", "read_only"),
]
PENDING = [("Zain Abbas", "zain.abbas", "bdr"), ("Maryam Rizvi", "maryam.rizvi", "account_executive")]
FORMER = ("Faisal Qureshi", "faisal.qureshi", "bdr")  # deactivated

COMPANIES = [  # name, industry, city, country, size
    ("Tandoor House", "Restaurants", "Lahore", "PK", "11-50"),
    ("Kite Learning", "Education", "Karachi", "PK", "51-200"),
    ("Orchid Skincare", "Beauty & cosmetics", "Islamabad", "PK", "11-50"),
    ("Harbor Logistics", "Logistics", "Karachi", "PK", "201-500"),
    ("Margalla Realty", "Real estate", "Islamabad", "PK", "11-50"),
    ("Saffron Kitchen", "Restaurants", "Dubai", "AE", "11-50"),
    ("Indus Textiles", "Manufacturing", "Faisalabad", "PK", "501-1000"),
    ("Crescent Clinics", "Healthcare", "Lahore", "PK", "51-200"),
    ("Bluewater Travel", "Travel", "Dubai", "AE", "11-50"),
    ("Nimbus Software", "Software", "London", "GB", "51-200"),
    ("Ravi Motors", "Automotive", "Lahore", "PK", "201-500"),
    ("Pearl Jewellers", "Retail", "Karachi", "PK", "11-50"),
    ("Greenfield Organics", "Food & beverage", "Multan", "PK", "11-50"),
    ("Apex Fitness", "Fitness", "Islamabad", "PK", "1-10"),
    ("Sapphire Hotels", "Hospitality", "Murree", "PK", "201-500"),
    ("Northstar Consulting", "Consulting", "Manchester", "GB", "11-50"),
    ("Chenab Builders", "Construction", "Sialkot", "PK", "51-200"),
    ("Lotus Bakery", "Food & beverage", "Lahore", "PK", "1-10"),
    ("Silverline Electronics", "Retail", "Karachi", "PK", "51-200"),
    ("Desert Rose Events", "Events", "Abu Dhabi", "AE", "11-50"),
    ("Mehran Pharma", "Healthcare", "Hyderabad", "PK", "501-1000"),
    ("Cedar Furniture", "Retail", "Peshawar", "PK", "11-50"),
    ("Falcon Security", "Security services", "Rawalpindi", "PK", "201-500"),
    ("Oasis Dental", "Healthcare", "Dubai", "AE", "1-10"),
    ("Brightpath Academy", "Education", "Lahore", "PK", "51-200"),
    ("Urban Threads", "Fashion", "Karachi", "PK", "11-50"),
    ("Monsoon Media", "Media", "Islamabad", "PK", "11-50"),
    ("Zenith Insurance", "Financial services", "Karachi", "PK", "1001-5000"),
]
PROSPECTS = [
    ("Karakoram Adventures", "Travel", "Gilgit", "PK", "1-10"),
    ("Swat Valley Honey", "Food & beverage", "Mingora", "PK", "1-10"),
    ("Thames Legal", "Legal services", "London", "GB", "11-50"),
    ("Gulf Freight", "Logistics", "Sharjah", "AE", "51-200"),
    ("Hunza Water", "Food & beverage", "Karimabad", "PK", "11-50"),
    ("Shalimar Interiors", "Design", "Lahore", "PK", "1-10"),
]
PRODUCTS = [  # product, typical price (EUR)
    ("SEO retainer", 1200), ("Custom website build", 3200), ("Social media management", 900),
    ("Google Ads management", 950), ("Shopify store setup", 1400), ("WordPress site", 700),
    ("Brand identity package", 1800), ("Email marketing", 450), ("Content writing", 350),
    ("Mobile app MVP", 6500),
]
SOURCES = ["Google Ads", "Meta Ads", "LinkedIn Ads", "TikTok Ads"]
FIRST_NAMES = ["Ali", "Fatima", "Omar", "Zara", "Hamza", "Amna", "Saad", "Mahnoor", "Asad", "Iqra", "Daniyal",
               "Rabia", "Junaid", "Sadia", "Waqas", "Noor", "Emma", "James", "Sophie", "Ahmed", "Layla", "Yusuf"]
LAST_NAMES = ["Khan", "Siddiqui", "Chaudhry", "Butt", "Mirza", "Sheikh", "Baig", "Hashmi", "Raza", "Akhtar",
              "Smith", "Taylor", "Al Mansoori", "Haddad"]
JOB_TITLES = ["Owner", "Managing Director", "Marketing Manager", "Operations Manager", "CEO", "Head of Growth",
              "Office Manager", "Brand Manager"]


def slug(name: str) -> str:
    return "".join(character for character in name.lower() if character.isalnum())


def aware(day: date, hour: int, timezone: str) -> str:
    return datetime.combine(day, time(hour, rng.choice((0, 15, 30, 45))), ZoneInfo(timezone)).isoformat()


def write_csv(rows: list[dict], name: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix="tslg-demo-")) / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def acting_as(db, user_id: str) -> Actor:
    user = db.get(User, user_id)
    assert user is not None
    return Actor.for_user(user)


def checked(result: tuple, what: str) -> None:
    if not result or not result[0]:
        raise SystemExit(f"The {what} import failed: {result}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill the app database with demo data.")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    settings = load_settings()
    if settings.is_server:
        raise SystemExit("These are demo records for the Archive (sales, leads, clients), which uses the local "
                         "file only. For the team database use scripts/seed_outreach_demo.py. Nothing was changed.")
    database = settings.database_path
    init_db()
    engine = create_db_engine(settings)
    with engine.connect() as connection:
        state = migrations_util.schema_state(connection)
    if state.newer_than_app:
        raise SystemExit("This database is newer than this copy of the app; nothing was changed.")
    if not state.ready:  # as the app does on start: back up (skipped for a new file), then upgrade
        maintenance.backup_before_migration(database, state.current, state.head)
        migrations_util.upgrade(settings.database_url)
    with engine.connect() as connection:
        problems = migrations_util.layout_problems(connection)
    if problems:
        raise SystemExit("This file is not a database this app can use: " + "; ".join(problems))
    factory = create_session_factory(engine)

    with factory() as db:
        if db.scalar(select(User.id).where(User.email.like(f"%@{DEMO_DOMAIN}"))) is not None:
            raise SystemExit("Demo data is already in this database; nothing was changed.")
        admin = db.scalar(select(User).where(User.role == "super_admin", User.is_active.is_(True))
                          .order_by(User.created_at))
        if admin is None and auth.has_users(db):
            raise SystemExit("This database has accounts but no active Super Admin; nothing was changed.")
        admin_email = admin.email if admin is not None else f"admin@{DEMO_DOMAIN}"

    print(f"Database: {database}\nDemo records are added as changes by {admin_email}"
          + (" (a new demo Super Admin)." if admin is None else "."))
    if not args.yes and input("Back it up and add demo data? [y/N] ").strip().lower() != "y":
        raise SystemExit("Nothing was changed.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = maintenance.copy_database(database, database.parent / "backups" / f"{database.stem}-before-demo-data-{stamp}.db")
    print(f"Backup: {backup}")
    zone = system_timezone()  # "today", "overdue" and due times follow this computer's clock

    with factory() as db:
        if admin is None:
            founder = auth.bootstrap_organization(db, organization_name="Techset Solutions (demo)",
                                                  admin_email=admin_email, admin_name="Demo Admin",
                                                  password=DEMO_PASSWORD)
            founder.timezone = zone
            db.commit()
            admin_id = founder.id
        else:
            admin_id = admin.id

    # ---------------------------------------------------------------- people
    people: dict[str, str] = {}  # local part -> user id
    codes: list[tuple[str, str, str]] = []
    with factory() as db:
        actor = acting_as(db, admin_id)
        timezone = actor.timezone
        for name, local, role in [*TEAM, FORMER]:
            user, code = users.invite_user(db, actor, settings, parse(UserInvite, {
                "email": f"{local}@{DEMO_DOMAIN}", "full_name": name, "role": role}))
            db.commit()
            auth.redeem_code(db, settings, raw_code=code, password=DEMO_PASSWORD)  # the password policy applies
            auth.revoke_sessions(db, user.id)
            user.timezone = zone
            db.commit()
            people[local] = user.id
        users.update_user(db, actor, people[FORMER[1]], UserAdminUpdate(is_active=False))
        for name, local, role in PENDING:
            _user, code = users.invite_user(db, actor, settings, parse(UserInvite, {
                "email": f"{local}@{DEMO_DOMAIN}", "full_name": name, "role": role}))
            codes.append((name, "activation", code))
        reset_code, _purpose = users.issue_access_code(db, actor, settings, people["sana.iqbal"])
        codes.append(("Sana Iqbal", "password reset", reset_code))
        db.commit()
    sellers = [people[local] for local in ("bilal.ahmed", "sana.iqbal", "usman.tariq", "ayesha.malik")] + [admin_id]

    # ---------------------------------------------------------------- sales (the importer, like Import data)
    client_ids = {name: f"C-{index:04d}" for index, (name, *_rest) in enumerate(COMPANIES, start=1)}
    weights = [rng.uniform(0.4, 2.5) for _ in COMPANIES]
    sales_rows = []
    for offset in range(0, 425):  # about 14 months, busier recently
        day = today - timedelta(days=offset)
        for _ in range(rng.choices((0, 1, 2, 3), weights=(4, 5, 2, 1 + (offset < 120)))[0]):
            (company, *_rest), = rng.choices(COMPANIES, weights=weights)
            product, price = rng.choice(PRODUCTS)
            sales_rows.append({"client_name": company, "client_id": client_ids[company], "product_type": product,
                               "price": f"{price * rng.uniform(0.8, 1.25):.2f}", "date": day.isoformat()})
    checked(import_csv_to_db(str(write_csv(sales_rows, "demo-sales.csv"))), "sales")

    spend_rows = [{"source": source, "amount": f"{rng.uniform(150, 1400):.2f}",
                   "date": (today.replace(day=1) - timedelta(days=31 * months)).replace(day=rng.randint(1, 26)).isoformat()}
                  for months in range(12) for source in SOURCES]
    checked(import_marketing_spend_to_db(str(write_csv(spend_rows, "demo-spend.csv"))), "marketing spend")

    stages = ["new"] * 30 + ["contacted"] * 28 + ["meeting"] * 18 + ["qualified"] * 8 + ["nurture"] * 6 \
        + ["converted"] * 12 + ["lost"] * 14
    lead_rows = []
    for index, status in enumerate(stages):
        created = today - timedelta(days=rng.randint(0, 150))
        meeting = ""
        if status in ("meeting", "qualified", "converted"):
            meeting = (created + timedelta(days=rng.randint(2, 20))).isoformat()
        if status == "meeting" and index % 3 == 0:  # some meetings still ahead
            meeting = (today + timedelta(days=rng.randint(1, 14))).isoformat()
        linked = client_ids[rng.choice(COMPANIES)[0]] if status == "converted" else ""
        lead_rows.append({"external_id": f"DEMO-{3000 + index}", "created_at": created.isoformat(),
                          "source": rng.choice(SOURCES), "status": status, "meeting_date": meeting,
                          "client_id": linked})
    checked(import_leads_to_db(str(write_csv(lead_rows, "demo-leads.csv"))), "leads")

    # ---------------------------------------------------------------- clients, contacts, leads, activity, tasks
    with factory() as db:
        actor = acting_as(db, admin_id)
        for name, industry, city, country, size in COMPANIES:
            client = db.get(Client, client_ids[name])
            if client is None:
                continue
            domain = f"{slug(name)}.example"
            clients.update_client(db, actor, client.id, parse(ClientUpdate, {
                "industry": industry, "city": city, "country": country, "employee_range": size,
                "account_status": rng.choices(["active", "former"], weights=(6, 1))[0],
                "website_url": f"https://www.{domain}", "primary_domain": domain,
                "owner_id": rng.choice(sellers), "address": f"{rng.randint(2, 180)} Main Boulevard, {city}",
                "notes": rng.choice(["Prefers WhatsApp for quick questions.", "Invoice in EUR, net 30.",
                                     "Renewal discussion due next quarter.", ""]) or None}))
        prospect_ids = []
        for name, industry, city, country, size in PROSPECTS:
            domain = f"{slug(name)}.example"
            client = clients.create_client(db, actor, parse(ClientCreate, {
                "name": name, "industry": industry, "city": city, "country": country, "employee_range": size,
                "account_status": "prospect", "website_url": f"https://www.{domain}", "primary_domain": domain,
                "owner_id": rng.choice(sellers)}))
            prospect_ids.append(client.id)
        db.commit()

        contact_ids: dict[str, list[str]] = {}
        used_emails: set[str] = set()
        for client in db.scalars(select(Client)).all():
            domain = client.primary_domain or f"{slug(client.name)}.example"
            for number in range(rng.randint(1, 3)):
                first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
                email = f"{first.lower()}.{slug(last)}@{domain}"
                if email in used_emails:
                    continue
                used_emails.add(email)
                blocked = number == 2 and rng.random() < 0.3
                contact = contacts.create_contact(db, actor, parse(ContactCreate, {
                    "client_id": client.id, "first_name": first, "last_name": last,
                    "job_title": rng.choice(JOB_TITLES), "email": email,
                    "phone": f"+92 3{rng.randint(0, 4)}{rng.randint(0, 9)} {rng.randint(1000000, 9999999)}",
                    "do_not_contact": blocked, "suppression_reason": "Asked not to be contacted" if blocked else None}))
                contact_ids.setdefault(client.id, []).append(contact.id)
        db.commit()

        # Leads worked in the app: titles, owners, priorities, stage changes with reasons.
        worked = []
        prospect_names = {client_id: name for client_id, (name, *_rest) in zip(prospect_ids, PROSPECTS)}
        for index, client_id in enumerate(prospect_ids * 2):
            lead = leads.create_lead(db, actor, parse(LeadCreate, {
                "title": f"{prospect_names[client_id]}: {rng.choice(PRODUCTS)[0]}", "source": rng.choice(SOURCES),
                "client_id": client_id, "owner_id": rng.choice(sellers), "allow_duplicate": index >= len(prospect_ids),
                "priority": rng.choice(["low", "medium", "medium", "high", "urgent"]),
                "created_on": (today - timedelta(days=rng.randint(0, 40))).isoformat(),
                "notes": "Found through the website contact form."}))
            worked.append(lead.id)
        plan = [("contacted",), ("contacted", "meeting"), ("contacted", "meeting", "qualified"),
                ("contacted", "lost"), ("nurture",), ("contacted", "meeting")]
        for lead_id, steps in zip(worked, plan * 2):
            for step in steps:
                reason = {"qualified": "Budget approved, decision this month.",
                          "lost": "Went with a cheaper local agency."}.get(step)
                ahead = (today + timedelta(days=rng.randint(1, 10))).isoformat() if step == "meeting" else None
                leads.transition(db, actor, lead_id, parse(LeadTransition, {"status": step, "reason": reason}),
                                 meeting_date=ahead)
        imported_open = db.scalars(select(Lead.id).where(Lead.id.like("DEMO-%"), Lead.status != "new")).all()
        for owner in sellers:
            batch = [lead_id for lead_id in imported_open if rng.random() < 1 / len(sellers)]
            if batch:
                leads.bulk_assign(db, actor, parse(BulkAssignment, {"lead_ids": batch, "owner_id": owner}))
        new_imported = db.scalars(select(Lead.id).where(Lead.id.like("DEMO-%"), Lead.status == "new")).all()
        leads.bulk_assign(db, actor, parse(BulkAssignment, {"lead_ids": new_imported[:12], "owner_id": admin_id}))
        db.commit()  # the other new leads stay unassigned ("new leads unassigned" on the Dashboard)

        all_leads = db.scalars(select(Lead.id)).all()
        subjects = {"call": ["Intro call", "Follow-up call", "Pricing questions"],
                    "email": ["Sent proposal", "Shared case studies", "Sent invoice"],
                    "meeting": ["Discovery meeting", "Strategy workshop", "Quarterly review"],
                    "note": ["Prefers mornings", "Decision maker is the owner", "Competitor also pitching"]}
        for _ in range(90):
            kind = rng.choice(list(subjects))
            on_lead = rng.random() < 0.55
            client_id = rng.choice(list(contact_ids))
            activities.create_activity(db, actor, parse(ActivityCreate, {
                "activity_type": kind, "subject": rng.choice(subjects[kind]),
                "body": "Logged from the demo data.",
                "occurred_at": aware(today - timedelta(days=rng.randint(0, 60)), rng.randint(9, 18), timezone),
                **({"lead_id": rng.choice(all_leads)} if on_lead else
                   {"client_id": client_id, "contact_id": rng.choice(contact_ids[client_id])})}))
        db.commit()

        titles = ["Call back about the proposal", "Send revised quote", "Prepare meeting agenda",
                  "Check payment status", "Share onboarding checklist", "Follow up on WhatsApp",
                  "Book a demo", "Update contact details", "Confirm meeting time", "Send case study"]
        task_ids = []
        for index in range(48):
            due = today + timedelta(days=rng.choice((-9, -5, -2, -1, 0, 0, 0, 1, 2, 3, 5, 8, 14)))
            link = {"lead_id": rng.choice(worked + list(all_leads[:30]))} if index % 2 else \
                {"client_id": rng.choice(list(contact_ids))}
            task = tasks.create_task(db, actor, parse(TaskCreate, {
                "title": f"{rng.choice(titles)} #{index + 1}", "priority": rng.choice(["low", "medium", "high", "urgent"]),
                "assigned_to_id": admin_id if index % 3 == 0 else rng.choice(sellers),
                "due_at": aware(due, rng.randint(9, 17), timezone),
                "description": "Demo task." if index % 4 else None, **link}))
            task_ids.append(task.id)
        for task_id in task_ids[::5]:
            tasks.set_status(db, actor, task_id, "done")
        for task_id in task_ids[2::11]:
            tasks.set_status(db, actor, task_id, "cancelled")
        db.commit()

        counts = {model.__tablename__: len(db.scalars(select(model.id)).all()) for model in (Client, Lead, User)}

    print(f"\nAdded: {len(sales_rows)} sales, {len(spend_rows)} marketing-spend records, "
          f"{counts['leads']} leads, {counts['clients']} clients, 90 activities, 48 tasks, "
          f"{len(TEAM) + len(PENDING) + 1} demo people.")
    print(f"\nDemo accounts (password for all: {DEMO_PASSWORD}):")
    if admin is None:
        print(f"  {admin_email:40} {'super_admin':18} Demo Admin")
    for name, local, role in TEAM:
        print(f"  {local + '@' + DEMO_DOMAIN:40} {role:18} {name}")
    print(f"  {FORMER[1] + '@' + DEMO_DOMAIN:40} {'(deactivated)':18} {FORMER[0]}")
    print("\nOne-time codes (Sign in > I have an activation or password-reset code):")
    for name, purpose, code in codes:
        print(f"  {code}   {purpose} for {name}")
    print(f"\nTo remove the demo data: close the app and copy {backup.name} back over {database.name}.")


if __name__ == "__main__":
    main()
