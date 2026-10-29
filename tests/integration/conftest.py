from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from techset_leadgen.database import migrations_util
from techset_leadgen.config import Settings, load_settings
from techset_leadgen.database.engine import create_db_engine, create_session_factory
from techset_leadgen.database.models import Organization, User
from techset_leadgen.services.schemas import ActivityCreate, ClientCreate, ContactCreate, LeadCreate, TaskCreate, parse
from techset_leadgen.security.passwords import hash_password
from techset_leadgen.services import activities, clients, contacts, leads, tasks
from techset_leadgen.services.access import Actor

PASSWORD = "correct horse battery staple"
ROLES = ("super_admin", "sales_manager", "lead_researcher", "bdr", "account_executive", "marketing", "read_only")


@pytest.fixture(scope="session")
def password_hash() -> str:
    return hash_password(PASSWORD)


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("db-template") / "template.db"
    migrations_util.upgrade(f"sqlite:///{path}")
    return path


@pytest.fixture()
def settings(tmp_path: Path, migrated_template: Path) -> Settings:
    database = tmp_path / "sales.db"
    shutil.copy(migrated_template, database)
    return load_settings({}, database_path=database)


@pytest.fixture()
def session_factory(settings: Settings) -> Iterator[sessionmaker[Session]]:
    engine = create_db_engine(settings)
    yield create_session_factory(engine)
    engine.dispose()


@pytest.fixture()
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@dataclass
class Team:
    organization: Organization
    users: dict[str, User]

    def actor(self, role: str = "super_admin") -> Actor:
        return Actor.for_user(self.users[role], client_host="test-pc")


class World:
    def __init__(self, db: Session, password_hash: str) -> None:
        self.db = db
        self.password_hash = password_hash

    def team(self, name: str = "Techset Solutions") -> Team:
        organization = self.db.get(Organization, 1) or Organization(id=1, name=name)
        self.db.add(organization)
        users = {role: self.user(organization, role) for role in ROLES}
        self.db.commit()
        return Team(organization, users)

    def user(self, organization: Organization | None, role: str, *, email: str | None = None,
             active: bool = True, password: bool = True) -> User:
        user = User(
            email=email or f"{role}.{uuid.uuid4().hex[:8]}@example.com",
            full_name=f"{role.replace('_', ' ').title()} {uuid.uuid4().hex[:4]}",
            password_hash=self.password_hash if password else None,
            role=role,
            is_active=active,
        )
        self.db.add(user)
        self.db.flush()
        return user

    def client(self, actor: Actor, name: str = "Acme Inc.", **values: Any):
        client = clients.create_client(self.db, actor, parse(ClientCreate, {"name": name, **values}))
        self.db.commit()
        return client

    def contact(self, actor: Actor, client, first_name: str = "Jane", **values: Any):
        contact = contacts.create_contact(self.db, actor, parse(ContactCreate, {
            "client_id": client.id, "first_name": first_name, **values}))
        self.db.commit()
        return contact

    def lead(self, actor: Actor, title: str = "Portal rebuild", client=None, **values: Any):
        data = {"title": title, "source": "manual_import", **values}
        if client is not None:
            data["client_id"] = client.id
        lead = leads.create_lead(self.db, actor, parse(LeadCreate, data))
        self.db.commit()
        return lead

    def imported_lead(self, lead_id: str, *, source: str = "meta_ads", status: str = "new",
                      created_at: str = "2026-09-01", client_id: str | None = None,
                      meeting_date: str | None = None) -> str:
        self.db.execute(text(
            "INSERT INTO leads (id, external_id, created_at, source, status, meeting_date, client_id) "
            "VALUES (:id, :id, :created_at, :source, :status, :meeting_date, :client_id)"
        ), {"id": lead_id, "created_at": created_at, "source": source, "status": status,
            "meeting_date": meeting_date, "client_id": client_id})
        self.db.commit()
        return lead_id

    def imported_client(self, client_id: str, name: str, *, sales: int = 0) -> str:
        self.db.execute(text("INSERT INTO clients (id, name, cif, address, contact_person, email) "
                             "VALUES (:id, :name, '-', NULL, NULL, NULL)"), {"id": client_id, "name": name})
        for number in range(sales):
            self.db.execute(text("INSERT INTO sales (client_name, client_id, product_type, price, date) "
                                 "VALUES (:name, :id, 'Web', 100, :date)"),
                            {"name": name, "id": client_id, "date": f"2026-01-{number + 1:02d}"})
        self.db.commit()
        return client_id

    def task(self, actor: Actor, title: str = "Follow up", **values: Any):
        task = tasks.create_task(self.db, actor, parse(TaskCreate, {"title": title, **values}))
        self.db.commit()
        return task

    def activity(self, actor: Actor, **values: Any):
        activity = activities.create_activity(self.db, actor, parse(ActivityCreate, {
            "activity_type": "call", "subject": "Intro call", **values}))
        self.db.commit()
        return activity


@pytest.fixture()
def world(db: Session, password_hash: str) -> World:
    return World(db, password_hash)


@pytest.fixture()
def acme(world: World) -> Team:
    return world.team()

