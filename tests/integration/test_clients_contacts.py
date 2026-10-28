"""Clients (the one client record shared with sales analytics) and their contacts."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from techset_leadgen.errors import Conflict, PermissionDenied, ValidationFailed
from techset_leadgen.database.models import AuditLog, Client, Contact, Lead, Task
from techset_leadgen.services.schemas import ClientCreate, ClientUpdate, ContactCreate, ContactUpdate, parse
from techset_leadgen.services import clients, contacts


def _create(db, actor, **values):
    return clients.create_client(db, actor, parse(ClientCreate, values))


def test_new_clients_follow_the_original_format_and_duplicate_rules(db, world, acme):
    admin = acme.actor()
    acme_client = world.client(admin, "Café Müller", cif="b-123.456 7", email="hola@cafe.example",
                               website_url="https://www.cafe.example/menu")
    assert acme_client.id.startswith("M_") and len(acme_client.id) == 8  # the original manual-client IDs
    assert (acme_client.cif, acme_client.primary_domain, acme_client.account_status) == (
        "B-123.456 7".upper(), "cafe.example", "prospect")
    with pytest.raises(ValidationFailed) as error:
        _create(db, admin, name="X", cif="12", email="nope", contact_person="J")
    assert error.value.fields == {
        "name": "The name must have at least 2 characters.",
        "cif": "The tax ID (CIF/NIF) must have 7 to 12 letters or digits.",
        "email": "Enter a valid email address.",
        "contact_person": "The contact name must have at least 2 characters.",
    }
    with pytest.raises(Conflict, match="already exists"):  # Unicode case folding, as the original rule
        _create(db, admin, name="CAFÉ MÜLLER")
    with pytest.raises(Conflict, match="tax ID"):
        _create(db, admin, name="Another café", cif=acme_client.cif)
    with pytest.raises(Conflict, match="domain"):
        _create(db, admin, name="Cafe Online", website_url="cafe.example")


def test_the_database_refuses_duplicate_domains_even_if_the_service_is_bypassed(db, world, acme):
    world.client(acme.actor(), "Globex", primary_domain="globex.example")
    db.add(Client(id="M_RAW001", name="Other", cif="", primary_domain="globex.example"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_edit_scope_follows_roles_and_ownership(db, world, acme):
    bdr_client = world.client(acme.actor("bdr"), "Mine Ltd")
    manager_client = world.client(acme.actor("sales_manager"), "Theirs Ltd")
    change = parse(ClientUpdate, {"industry": "Retail"})
    clients.update_client(db, acme.actor("bdr"), bdr_client.id, change)
    with pytest.raises(PermissionDenied):
        clients.update_client(db, acme.actor("bdr"), manager_client.id, change)
    clients.update_client(db, acme.actor("lead_researcher"), manager_client.id, change)  # researchers edit all
    for role in ("marketing", "read_only"):
        with pytest.raises(PermissionDenied):
            clients.update_client(db, acme.actor(role), bdr_client.id, change)
    with pytest.raises(PermissionDenied):  # front-line users cannot hand clients to others
        clients.update_client(db, acme.actor("bdr"), bdr_client.id,
                              parse(ClientUpdate, {"owner_id": acme.users["account_executive"].id}))
    db.rollback()
    world.imported_client("C-FREE", "Unowned Ltd")
    with pytest.raises(PermissionDenied):  # read-only users cannot take clients
        clients.assign_client(db, acme.actor("read_only"), "C-FREE", acme.users["read_only"].id)
    clients.assign_client(db, acme.actor("bdr"), "C-FREE", acme.users["bdr"].id)  # a rep may take one
    db.rollback()
    extras = clients.extras(db, acme.actor("bdr"))
    assert (extras[bdr_client.id].editable, extras[manager_client.id].editable) == (True, False)


def test_imported_and_sales_only_clients_can_be_edited_in_place(db, world, acme, settings):
    world.imported_client("C-77", "Imported Co", sales=2)
    clients.update_client(db, acme.actor(), "C-77", parse(ClientUpdate, {"industry": "Logistics", "cif": "B7654321"}))
    db.commit()
    assert db.get(Client, "C-77").industry == "Logistics"
    db.rollback()  # end this session's read transaction (it holds SQLite's write lock)
    # An identity known only from older sales rows (no client row) gets its row on first edit.
    with closing(sqlite3.connect(settings.database_path)) as raw:  # foreign keys off, as in older files
        raw.execute("INSERT INTO sales (client_name, client_id, product_type, price, date) "
                    "VALUES ('Orphan Ltd', 'C-OLD', 'Web', 50, '2025-01-01')")
        raw.commit()
    clients.update_client(db, acme.actor(), "C-OLD", parse(ClientUpdate, {"country": "ES"}))
    db.commit()
    assert (db.get(Client, "C-OLD").name, db.get(Client, "C-OLD").country) == ("Orphan Ltd", "ES")


def test_deleting_a_client_removes_its_sales_people_and_tasks_and_unlinks_leads(db, world, acme):
    admin = acme.actor()
    world.imported_client("C-9", "Nine Ltd", sales=3)
    world.contact(admin, db.get(Client, "C-9"), "Ann", email="ann@nine.example")
    lead_id = world.imported_lead("L-9", client_id="C-9")
    world.task(admin, "Call Nine", client_id="C-9")
    with pytest.raises(PermissionDenied):
        clients.delete_client(db, acme.actor("bdr"), "C-9")
    name, sales = clients.delete_client(db, admin, "C-9")
    db.commit()
    assert (name, sales) == ("Nine Ltd", 3)
    assert db.scalar(select(func.count()).select_from(Contact)) == 0
    assert db.scalar(select(func.count()).select_from(Task)) == 0
    assert db.scalar(text("SELECT COUNT(*) FROM sales")) == 0
    assert db.get(Lead, lead_id).client_id is None
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "client.deleted"))
    assert entry.changes == {"name": "Nine Ltd", "sales_deleted": 3, "leads_unlinked": 1}


def test_stale_copies_are_refused(db, world, acme, session_factory):
    actor = acme.actor()
    client_id = world.client(actor, "Acme").id
    clients.update_client(db, actor, client_id, parse(ClientUpdate, {"industry": "Retail", "version": 1}))
    db.commit()
    with pytest.raises(Conflict, match="changed by someone else"):
        clients.update_client(db, actor, client_id, parse(ClientUpdate, {"industry": "Old copy", "version": 1}))
    db.rollback()
    with session_factory() as first, session_factory() as second:
        stale = second.get(Client, client_id)
        second.commit()  # the desktop keeps the loaded copy between units of work
        fresh = first.get(Client, client_id)
        fresh.industry = "First"
        first.commit()
        stale.industry = "Second"
        with pytest.raises(StaleDataError):
            second.commit()


def test_client_changes_are_audited_field_by_field(db, world, acme):
    actor = acme.actor()
    client = world.client(actor, "Initech", industry="Software")
    clients.update_client(db, actor, client.id, parse(ClientUpdate, {"industry": "Finance", "city": "Austin"}))
    db.commit()
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "client.updated"))
    assert entry.changes == {"industry": ["Software", "Finance"], "city": [None, "Austin"]}
    assert entry.actor_user_id == actor.user_id and entry.client_host == "test-pc"


def test_contacts_belong_to_a_client_and_follow_its_permissions(db, world, acme):
    bdr = acme.actor("bdr")
    mine = world.client(bdr, "Mine Ltd")
    theirs = world.client(acme.actor(), "Theirs Ltd")
    ann = world.contact(bdr, mine, "Ann", last_name="Lee", email="Ann.Lee@Mine.example", phone="+44 20 7946 0000")
    assert (ann.full_name, ann.email) == ("Ann Lee", "ann.lee@mine.example")
    with pytest.raises(PermissionDenied):
        contacts.create_contact(db, bdr, parse(ContactCreate, {"client_id": theirs.id, "first_name": "Bob"}))
    with pytest.raises(Conflict, match="already uses this email"):
        contacts.create_contact(db, acme.actor(), parse(ContactCreate, {
            "client_id": theirs.id, "first_name": "Copy", "email": "ann.lee@mine.example"}))
    with pytest.raises(ValidationFailed, match="reason"):
        contacts.update_contact(db, bdr, ann.id, parse(ContactUpdate, {"do_not_contact": True}))
    contacts.update_contact(db, bdr, ann.id, parse(ContactUpdate, {"do_not_contact": True,
                                                                  "suppression_reason": "Asked by phone",
                                                                  "phone": "+44 20 7946 1111"}))
    db.commit()
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "contact.updated"))
    assert entry.changes["phone"] == ["[changed]"]  # the audit trail never stores contact details
    assert contacts.delete_contact(db, bdr, ann.id) == "Ann Lee"
