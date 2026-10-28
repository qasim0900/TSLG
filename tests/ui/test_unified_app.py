"""The consolidated application: one window, one sidebar, one set of records.

These tests drive the real main window and its dialogs (through ``ModalPilot``)
against pytest's sandboxed database, then check what was stored, so each covers
screen -> business service -> database. They also pin the consolidation itself:
there is no separate CRM area, and leads and clients exist once.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel
from sqlalchemy import select, update

from techset_leadgen.database.local_db import get_connection, init_db
from techset_leadgen.config import load_settings
from techset_leadgen.database.models import AuditLog, Contact, Lead, Task, User, UserSession
from techset_leadgen.errors import PermissionDenied
from techset_leadgen.services.schemas import BulkAssignment, parse
from techset_leadgen.security.passwords import broken_rules, hash_password
from techset_leadgen.services import leads as lead_service
from techset_leadgen.desktop.forms import FieldSpec, FormDialog
from techset_leadgen.desktop.main_window import SECTIONS, MainWindow
from techset_leadgen.desktop.pages import ClientsPage, DashboardPage, LeadsPage
from techset_leadgen.desktop.pages.admin_pages import AuditPage, CodeDialog, UsersPage
from techset_leadgen.desktop.pages.clients_page import ClientDetailDialog
from techset_leadgen.desktop.pages.tasks_page import TasksPage
from techset_leadgen.desktop.search_dialog import SearchDialog
from techset_leadgen.desktop.session import AppContext, ConnectionProblem
from techset_leadgen.desktop.theme import ThemeManager
from techset_leadgen.desktop.widgets import PasswordRules
from techset_leadgen.desktop.workflows import LeadDialog
from techset_leadgen.main import create_application
from tests.qt_helpers import TEST_PASSWORD, ModalPilot, click_button, sign_in_window

ALL_SECTIONS = [section.key for section in SECTIONS]


@pytest.fixture(scope="module")
def qapp(tmp_path_factory):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      str(tmp_path_factory.mktemp("qt-settings")))
    app = QApplication.instance() or create_application(["unified-app-tests"])
    ThemeManager(app).apply(False)
    yield app
    app.processEvents()


def _clear_records() -> None:
    init_db()
    with closing(get_connection()) as connection, connection:
        for table in ("tasks", "activities", "contacts", "lead_status_history", "funnel_events", "leads", "sales",
                      "marketing_spend", "import_metadata", "clients", "auth_attempts", "user_sessions"):
            try:
                connection.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed whitelist
            except sqlite3.OperationalError:
                pass  # first test: the account tables do not exist until the window migrates
    from techset_leadgen.analytics.models.client_manager import invalidate_clients_cache

    invalidate_clients_cache()


@pytest.fixture()
def window(qapp):
    _clear_records()
    manager = ThemeManager(qapp)
    shell = MainWindow(manager)
    shell.resize(1360, 880)
    shell.show()
    qapp.processEvents()
    yield shell
    shell.close()
    shell.deleteLater()
    qapp.processEvents()


def _visible_sections(shell: MainWindow) -> list[str]:
    return [key for key, button in shell._nav_buttons.items() if button.isVisibleTo(shell.sidebar)]


def _add_user(shell: MainWindow, role: str) -> str:
    email = f"{role}.{uuid.uuid4().hex[:6]}@techset.example"
    with shell.context._sessions()() as db:
        db.add(User(email=email, full_name=f"{role.replace('_', ' ').title()} User", role=role,
                    password_hash=hash_password(TEST_PASSWORD), is_active=True))
        db.commit()
    return email


def _sign_in_as(shell: MainWindow, email: str) -> None:
    if shell.context.is_signed_in:
        shell.context.sign_out()
    page = shell.sign_in_page
    page.email.setText(email)
    page.password.setText(TEST_PASSWORD)
    assert page.submit(), page.error.text()


def _query(shell: MainWindow, statement):
    with shell.context._sessions()() as db:
        return list(db.execute(statement).scalars())


def _seed_imported_records() -> None:
    """Rows as the existing importers write them: one client with sales, two leads."""
    with closing(get_connection()) as connection, connection:
        connection.execute("INSERT INTO clients (id, name, cif, address, contact_person, email) "
                           "VALUES ('C-1', 'Acme Corp', 'B12345678', 'Main St 1', 'Ann Lee', 'ann@acme.example')")
        connection.execute("INSERT INTO sales (client_name, client_id, product_type, price, date) "
                           "VALUES ('Acme Corp', 'C-1', 'Web', 1200, '2026-09-01')")
        connection.execute("INSERT INTO leads (id, external_id, created_at, source, status, client_id) "
                           "VALUES ('EXT-1', 'EXT-1', '2026-09-02', 'google_ads', 'new', 'C-1')")
        connection.execute("INSERT INTO leads (id, external_id, created_at, source, status) "
                           "VALUES ('EXT-2', 'EXT-2', '2026-09-03', 'meta_ads', 'contacted')")


# --- one application ------------------------------------------------------------------


def test_one_sidebar_with_no_duplicate_areas(window, qapp):
    assert window.root_stack.currentWidget() is window.auth_stack  # nothing before sign-in
    sign_in_window(window)
    labels = [button.text() for button in window._nav_buttons.values()]
    assert labels == ["Dashboard", "My Work", "Notifications", "Daily Assignments", "Meetings", "Prospects", "Follow-ups",
                      "Tasks", "Team performance", "Users & roles", "Audit log", "Settings",
                      "Sales overview", "Sales", "Leads", "Clients"]
    assert "CRM" not in labels and len(set(labels)) == len(labels)
    assert _visible_sections(window) == ALL_SECTIONS
    for key in ALL_SECTIONS:
        assert window.navigate(key) is window.stack.currentWidget()
        qapp.processEvents()
        assert window._nav_buttons[key].isChecked()


ARCHIVE = ["sales_overview", "sales", "leads", "clients"]
MEMBER = ["dashboard", "my_work", "notifications", "meetings", "prospects", "followups", "tasks", "settings"]


@pytest.mark.parametrize(("role", "sections"), [
    ("sales_manager", ["dashboard", "my_work", "notifications", "assignments", "meetings", "prospects", "followups", "tasks",
                       "team", "users", "settings", *ARCHIVE]),
    ("lead_researcher", MEMBER),
    ("bdr", MEMBER),
    ("account_executive", MEMBER),
    ("marketing", ["dashboard", "notifications", "meetings", "tasks", "settings", *ARCHIVE]),
    ("read_only", ["dashboard", "notifications", "prospects", "followups", "tasks", "team", "settings", *ARCHIVE]),
])
def test_each_role_sees_its_areas_and_actions(window, qapp, role, sections):
    sign_in_window(window)
    _sign_in_as(window, _add_user(window, role))
    assert _visible_sections(window) == sections
    if "leads" not in sections:  # the retired analytics are not reachable, not even by shortcut
        assert window.navigate("leads") is None and window.navigate("clients") is None
        return
    leads = window.navigate("leads")
    assert isinstance(leads, LeadsPage)
    can = window.context.can
    # isHidden, not isVisibleTo: the spend button sits on a tab that is not showing.
    assert leads.new_lead_button.isHidden() is not can("leads.create")
    assert leads.assign_button.isHidden() is not can("leads.assign")
    assert leads.manage_spend_button.isHidden() is not can("marketing.manage")
    clients = window.navigate("clients")
    assert isinstance(clients, ClientsPage)
    assert clients.add_button.isHidden() is not can("clients.create")
    assert clients.merge_button.isHidden() is not can("clients.merge")
    assert window.navigate("audit") is None  # not reachable by shortcut either


def test_import_needs_the_import_permission(window, qapp):
    sign_in_window(window)
    _sign_in_as(window, _add_user(window, "bdr"))
    with ModalPilot() as pilot:
        window._request_import()
    assert [item.text for item in pilot.message_boxes] == ["Your role cannot import data."]


# --- leads: the existing page, with the workflow ---------------------------------------


def test_leads_page_runs_the_whole_lead_workflow_on_imported_leads(window, qapp):
    _seed_imported_records()
    sign_in_window(window)
    page = window.navigate("leads")
    assert isinstance(page, LeadsPage)
    page.refresh()
    assert sorted(lead["id"] for lead in page.active_leads) == ["EXT-1", "EXT-2"]
    assert page.funnel_stats["total"] == 2  # the analytics read the same rows

    def qualify(dialog):
        dialog.set_value("status", "qualified")
        dialog.save_button.click()  # no reason: refused, dialog stays open
        reasons.append(dialog.field_error("reason"))
        dialog.set_value("reason", "Budget confirmed on call")
        dialog.save_button.click()

    reasons: list[str] = []
    with ModalPilot(qualify):
        assert page.change_stage("EXT-1") is True
    assert reasons == ["A reason is required for this stage."]
    lead = _query(window, select(Lead).where(Lead.id == "EXT-1"))[0]
    assert (lead.status, lead.qualification_reason) == ("qualified", "Budget confirmed on call")
    assert page.funnel_stats["meetings"] == 1  # Qualified counts as past the meeting stage

    due = (datetime.now(UTC) + timedelta(days=2)).replace(second=0, microsecond=0)

    def follow_up_and_close(dialog):
        assert isinstance(dialog, LeadDialog)
        assert dialog.task_button.isEnabled() and dialog.stage_button.isEnabled()
        dialog.add_follow_up()  # the task form opens on top and is answered by fill_task
        dialog.accept()

    def fill_task(dialog):
        assert isinstance(dialog, FormDialog)
        dialog.set_value("due_at", due)
        dialog.save_button.click()

    with ModalPilot(follow_up_and_close, fill_task):
        assert page.open_lead("EXT-1") is True  # something changed while it was open
    task = _query(window, select(Task))[0]
    assert (task.lead_id, task.client_id, task.due_at) == ("EXT-1", "C-1", due)
    assert _query(window, select(Lead.next_follow_up_at).where(Lead.id == "EXT-1")) == [due]

    def new_lead(dialog):
        dialog.set_value("title", "Website redesign")
        dialog.set_value("client_id", "C-1")
        dialog.save_button.click()

    with ModalPilot(new_lead, click_button("Add anyway")) as pilot:
        assert page.new_lead() is True
    assert [item.text for item in pilot.message_boxes] == ["This client already has an open lead"]
    manual = _query(window, select(Lead).where(Lead.title == "Website redesign"))[0]
    assert manual.id.startswith("L_") and manual.owner_id == window.context.actor.user_id
    page.owner_combo.setCurrentIndex(page.owner_combo.findData("me"))
    assert [lead["id"] for lead in page.active_leads] == [manual.id]
    actions = set(_query(window, select(AuditLog.action)))
    assert {"lead.status_changed", "task.created", "lead.created"} <= actions


def test_assigning_selected_leads_and_role_limits_on_the_leads_page(window, qapp):
    _seed_imported_records()
    sign_in_window(window)
    rep = _add_user(window, "bdr")
    rep_id = _query(window, select(User.id).where(User.email == rep))[0]
    page = window.navigate("leads")
    page.refresh()
    page.leads_table.selectAll()

    def choose_rep(dialog):
        dialog.set_value("owner_id", rep_id)
        dialog.save_button.click()

    with ModalPilot(choose_rep):
        assert page.assign_selected() is True
    assert set(_query(window, select(Lead.owner_id))) == {rep_id}

    _sign_in_as(window, rep)
    assert window.navigate("leads") is None  # retired from a rep's navigation (it is the archive now)
    page = LeadsPage(context=window.context)  # opened anyway, the page still applies the rep's limits
    page.refresh()
    assert not page.assign_button.isVisibleTo(page)
    with ModalPilot(lambda dialog: dialog.reject()) as pilot:  # their own lead: the stage dialog opens
        page.change_stage("EXT-2")
    assert [item.kind for item in pilot.seen] == ["FormDialog"]
    # The screen hides what a role may not do; the service refuses it regardless.
    with pytest.raises(PermissionDenied):
        window.context.run(lambda db, actor: lead_service.bulk_assign(
            db, actor, parse(BulkAssignment, {"lead_ids": ["EXT-1"], "owner_id": None})))
    with pytest.raises(PermissionDenied):  # a rep cannot take a lead away from its owner
        window.context.run(lambda db, actor: lead_service.assign(db, actor, "EXT-1", None))


# --- clients: the existing page, with people, activity, and tasks ----------------------


def test_client_profile_manages_contacts_activity_and_tasks(window, qapp):
    _seed_imported_records()
    sign_in_window(window)
    page = window.navigate("clients")
    assert isinstance(page, ClientsPage)

    def edit_account(dialog):
        dialog.industry_edit.setText("Logistics")
        dialog.website_edit.setText("https://www.acme.example")
        dialog.buttons.button(dialog.buttons.StandardButton.Save).click()

    with ModalPilot(edit_account):
        assert page.edit_client("C-1") is True
    with closing(get_connection()) as connection:
        assert connection.execute("SELECT industry, primary_domain, cif FROM clients WHERE id='C-1'").fetchone() == (
            "Logistics", "acme.example", "B12345678")

    def use_profile(dialog):
        assert isinstance(dialog, ClientDetailDialog)
        assert dialog.tabs.tabText(dialog.tabs.indexOf(dialog.leads_tab)) == "Leads (1)"
        dialog.add_contact()
        dialog.log_activity()
        steps.append(dialog.tabs.tabText(dialog.tabs.indexOf(dialog.contacts_tab)))
        steps.append(dialog.tabs.tabText(dialog.tabs.indexOf(dialog.activity_tab)))
        dialog.reject()

    def add_contact(dialog):
        dialog.set_value("first_name", "Bob")
        dialog.set_value("last_name", "Stone")
        dialog.set_value("email", "Bob.Stone@Acme.example")
        dialog.save_button.click()

    def add_activity(dialog):
        dialog.set_value("subject", "Quarterly review call")
        dialog.save_button.click()

    steps: list[str] = []
    with ModalPilot(use_profile, add_contact, add_activity):
        page.show_client_profile("C-1")
    assert steps == ["Contacts (1)", "Activity (1)"]
    assert _query(window, select(Contact.email)) == ["bob.stone@acme.example"]

    with ModalPilot(click_button("Delete client")):
        assert page.delete_client("C-1") is True
    assert _query(window, select(Contact)) == []
    assert _query(window, select(Lead.client_id).where(Lead.id == "EXT-1")) == [None]


# --- users, sessions, search, dashboard -------------------------------------------------


def test_invited_user_activates_with_a_code_and_sees_only_their_role(window, qapp):
    sign_in_window(window)
    users_page = window.navigate("users")
    assert isinstance(users_page, UsersPage)
    captured: dict[str, str] = {}

    def invite(dialog):
        dialog.set_value("full_name", "Bilal Ahmed")
        dialog.set_value("email", f"bilal.{uuid.uuid4().hex[:6]}@techset.example")
        dialog.set_value("role", "bdr")
        dialog.save_button.click()

    def keep_code(dialog):
        assert isinstance(dialog, CodeDialog)
        captured["code"] = dialog.code_field.text()
        dialog.accept()

    with ModalPilot(invite, keep_code):
        users_page.create_record()
    window.context.sign_out()
    window.sign_in_page.code_requested.emit()
    page = window.code_page

    def shown_marks() -> int:
        return sum(1 for label in page.findChildren(QLabel, "requiredMark") if label.isVisibleTo(page))

    # Until the code is accepted only its own field shows: no stray "*" from the hidden fields.
    assert shown_marks() == 1
    assert not page.field_block("password").isVisibleTo(page)
    page.code.setText(captured["code"])
    assert page.check_code()
    assert shown_marks() == 3 and page.field_block("password").isVisibleTo(page)
    checklist = page.field_block("password").findChild(PasswordRules)
    assert checklist is not None and not checklist.met("BilalAhmed1")  # like the invitee's name
    for weak, phrase in (("password123", "too common"), ("BilalAhmed1", "too similar")):
        page.password.setText(weak)
        page.confirm.setText(weak)
        assert page.submit() is False
        assert phrase in page.error.text(), page.error.text()
    window.code_page.password.setText(TEST_PASSWORD)
    window.code_page.confirm.setText(TEST_PASSWORD)
    assert window.code_page.submit(), window.code_page.error.text()
    assert window.context.actor.role == "bdr"
    assert "users" not in _visible_sections(window) and "audit" not in _visible_sections(window)
    window.context.sign_out()
    window.code_page.prepare()
    window.code_page.code.setText(captured["code"])
    assert window.code_page.check_code() is False  # single use


def test_password_checklists_use_the_service_rules(qapp):
    """The live checklist and the services can never disagree about a password."""
    email, name = "ayesha.malik@techset.example", "Ayesha Malik"
    checklist = PasswordRules(email=email, name=name)
    for password in ("", "short", "12345678", "93847261059", "password123", "AyeshaMalik1", "blue-kettle-42",
                     "correct horse battery staple"):
        expected = bool(password) and not broken_rules(password, email=email, names=(name,))
        assert checklist.met(password) is expected, password
    # The change-password form passes the signed-in account to its checklist.
    dialog = FormDialog(None, title="Password", heading="Change your password", submit=lambda _dialog: None,
                        fields=[FieldSpec("new_password", "New password", "password", rules=True,
                                          rules_owner=(email, name))])
    form_checklist = dialog.findChild(PasswordRules)
    assert form_checklist is not None and not form_checklist.met("AyeshaMalik1")
    dialog.deleteLater()


def test_a_session_ended_elsewhere_returns_to_sign_in_and_drops_pages(window, qapp):
    sign_in_window(window)
    window.navigate("clients")
    with window.context._sessions()() as db:
        db.execute(update(UserSession).values(revoked_at=datetime.now(UTC)))
        db.commit()
    window.check_session()
    assert window.root_stack.currentWidget() is window.auth_stack
    assert window.auth_stack.currentWidget() is window.sign_in_page
    assert "signed out" in window.sign_in_page.notice.text()
    assert window._pages == {}


def test_search_opens_leads_and_client_profiles_and_dashboard_shows_my_work(window, qapp):
    _seed_imported_records()
    sign_in_window(window)
    dashboard = window.navigate("sales_overview")
    assert isinstance(dashboard, DashboardPage)
    dashboard.refresh()
    assert dashboard.work_card.isVisibleTo(dashboard)
    assert dashboard._work_buttons["unassigned"].text() == "1 new leads unassigned"
    window.search_field.setText("acme")

    def pick_lead(dialog):
        assert isinstance(dialog, SearchDialog)
        kinds = [dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())]
        assert kinds == ["Client", "Lead"]
        dialog.open_row(1)

    with ModalPilot(pick_lead, lambda dialog: dialog.reject()) as pilot:
        window.run_search()
    assert [item.kind for item in pilot.seen] == ["SearchDialog", "LeadDialog"]
    assert isinstance(window.stack.currentWidget(), LeadsPage)


def test_tasks_and_audit_pages_show_the_same_records(window, qapp):
    sign_in_window(window)
    tasks_page = window.navigate("tasks")
    assert isinstance(tasks_page, TasksPage)

    def fill(dialog):
        dialog.set_value("title", "Prepare proposal")
        dialog.set_value("due_at", datetime.now(UTC) - timedelta(hours=1))
        dialog.save_button.click()

    with ModalPilot(fill):
        tasks_page.create_record()
    task_id = _query(window, select(Task.id))[0]
    assert window.task_badge.text().startswith("1 overdue")  # an hour ago may also be "due today"
    tasks_page.show_record(task_id)
    tasks_page.set_status("done")
    assert _query(window, select(Task.status)) == ["done"]
    audit = window.navigate("audit")
    assert isinstance(audit, AuditPage)
    audit.refresh()
    actions = {audit.records.table.item(row, 2).text() for row in range(audit.records.table.rowCount())}
    assert {"Task added", "Task status changed", "Signed in"} <= actions
    records = {audit.records.table.item(row, 3).text() for row in range(audit.records.table.rowCount())}
    assert "Task: Prepare proposal" in records  # names, not IDs
    audit.search.setText("status changed")
    audit.records.reload(page=1)
    actions = {audit.records.table.item(row, 2).text() for row in range(audit.records.table.rowCount())}
    assert actions == {"Task status changed"}


# --- upgrading an existing installation -----------------------------------------------


def test_an_existing_database_is_backed_up_then_upgraded_and_old_accounts_carry_over(qapp, tmp_path):
    database = tmp_path / "sales.db"
    with closing(sqlite3.connect(database)) as connection:  # an installation from before accounts existed
        from techset_leadgen.database.local_db import create_base_tables

        create_base_tables(connection.cursor())
        connection.execute("INSERT INTO clients VALUES ('C-1', 'Acme', '-', NULL, NULL, NULL)")
        connection.commit()
    previous = tmp_path / "crm.db"  # the separate database of the earlier build
    with closing(sqlite3.connect(previous)) as old:
        old.execute("CREATE TABLE organizations (name TEXT, created_at TEXT)")
        old.execute("CREATE TABLE users (email TEXT, full_name TEXT, password_hash TEXT, role TEXT, "
                    "is_active INTEGER, timezone TEXT)")
        old.execute("INSERT INTO organizations VALUES ('Techset Solutions', '2026-10-21')")
        old.execute("INSERT INTO users VALUES ('owner@techset.example', 'Owner', ?, 'super_admin', 1, "
                    "'Asia/Karachi')", (hash_password(TEST_PASSWORD),))
        old.commit()
    context = AppContext(load_settings({}, database_path=database), previous_accounts=previous)
    context.open()
    assert context.last_backup is not None and context.last_backup.is_file()
    with closing(sqlite3.connect(context.last_backup)) as backup:
        assert backup.execute("SELECT name FROM clients").fetchall() == [("Acme",)]
    assert context.has_users() and context.organization_name() == "Techset Solutions"
    context.sign_in("owner@techset.example", TEST_PASSWORD)  # the existing password still works
    assert context.actor.role == "super_admin"
    context.shutdown()
    shutil.rmtree(tmp_path / "backups", ignore_errors=True)
    assert Path(previous).is_file()  # left untouched


def test_an_earlier_crm_file_with_business_records_is_refused_not_ignored(qapp, tmp_path):
    database = tmp_path / "sales.db"
    previous = tmp_path / "crm.db"
    with closing(sqlite3.connect(previous)) as old:
        old.execute("CREATE TABLE organizations (name TEXT, created_at TEXT)")
        old.execute("CREATE TABLE users (email TEXT, full_name TEXT, password_hash TEXT, role TEXT, "
                    "is_active INTEGER, timezone TEXT)")
        old.execute("CREATE TABLE companies (id TEXT)")
        old.execute("INSERT INTO users VALUES ('owner@techset.example', 'Owner', 'x', 'super_admin', 1, 'UTC')")
        old.execute("INSERT INTO companies VALUES ('a'), ('b')")
        old.commit()
    context = AppContext(load_settings({}, database_path=database), previous_accounts=previous)
    with pytest.raises(ConnectionProblem) as problem:
        context.open()
    assert "2 companies" in problem.value.details and not context.is_open
    with closing(sqlite3.connect(database)) as check:
        assert check.execute("SELECT COUNT(*) FROM users").fetchone() == (0,)  # nothing half-imported


def test_a_standalone_crm_file_selected_as_the_database_is_refused(qapp, tmp_path):
    """The earlier standalone crm.db is also stamped revision 0001; its layout gives it away."""
    impostor = tmp_path / "sales.db"
    with closing(sqlite3.connect(impostor)) as old:
        old.execute("CREATE TABLE alembic_version (version_num TEXT)")
        old.execute("INSERT INTO alembic_version VALUES ('0001')")
        old.execute("CREATE TABLE organizations (id TEXT, name TEXT)")
        old.execute("CREATE TABLE companies (id TEXT, organization_id TEXT, name TEXT)")
        old.commit()
    context = AppContext(load_settings({}, database_path=impostor))
    with pytest.raises(ConnectionProblem) as problem:
        context.open()
    assert "standalone CRM database" in problem.value.details and not problem.value.retry
    with closing(sqlite3.connect(impostor)) as check:  # untouched
        assert check.execute("SELECT name FROM sqlite_master WHERE name = 'clients'").fetchall() == []
