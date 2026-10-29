from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

ROOT = Path(__file__).resolve().parents[2]

_HOVERED_CARD_SCRIPT = textwrap.dedent("""
    import sys
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from techset_leadgen.config import load_settings
    from techset_leadgen.desktop.main_window import MainWindow
    from techset_leadgen.desktop.session import AppContext
    from techset_leadgen.desktop.theme import ThemeManager
    from techset_leadgen.main import create_application
    from tests.qt_helpers import TEST_ADMIN_EMAIL, TEST_PASSWORD, wait_until

    app = create_application(["bug101"])
    manager = ThemeManager(app)
    manager.apply(False)
    context = AppContext(load_settings({}, database_path=sys.argv[1]))
    window = MainWindow(manager, context=context)
    window.resize(1366, 768)
    window.show()
    wait_until(lambda: False, 200)
    setup = window.setup_page  # the first start: create the organization and sign in
    for editor, value in ((setup.organization, "Techset Solutions"), (setup.name, "Test Admin"),
                          (setup.email, TEST_ADMIN_EMAIL), (setup.password, TEST_PASSWORD),
                          (setup.confirm, TEST_PASSWORD)):
        editor.setText(value)
    QTest.mouseClick(setup.create_button, Qt.MouseButton.LeftButton)
    assert wait_until(lambda: context.is_signed_in, 5000), "not signed in"
    wait_until(lambda: False, 300)
    page = window.navigate("dashboard")
    wait_until(lambda: False, 200)
    card = next(iter(page.cards.values()))
    QTest.mouseMove(card, card.rect().center())  # the pointer rests on the card: lift and shadow
    wait_until(lambda: False, 100)
    assert card.graphicsEffect() is not None, "the hover shadow was not shown"
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=card.rect().center())  # opens another area
    wait_until(lambda: False, 200)
    assert window.stack.currentWidget() is not page, "the card did not open its area"
    print("survived", flush=True)
""")


def test_bug101_opening_an_area_from_a_hovered_kpi_card_with_reduced_motion(tmp_path):
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "TSLG_REDUCED_MOTION": "1",
                   "FDT_DATA_DIR": str(tmp_path / "data"), "FDT_LOG_DIR": str(tmp_path / "logs"),
                   "XDG_CONFIG_HOME": str(tmp_path / "config"),
                   "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)])}
    result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", _HOVERED_CARD_SCRIPT,
                             str(tmp_path / "shell.db")], env=environment, cwd=ROOT,
                            capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0 and "survived" in result.stdout, result.stdout + result.stderr[-3000:]


def test_bug107_archive_month_labels_are_english_under_another_system_locale():
    import locale

    from techset_leadgen.analytics.snapshot_builder import _parse_key_and_generate_interval
    from techset_leadgen.domain.analysis_snapshot import TimeGrouping

    previous = locale.setlocale(locale.LC_TIME)
    for name in ("ur_PK.UTF-8", "ur_PK.utf8", "ur_PK", "ar_SA.UTF-8", "de_DE.UTF-8", "fr_FR.UTF-8"):
        try:
            locale.setlocale(locale.LC_TIME, name)
            break
        except locale.Error:
            continue
    else:
        pytest.skip("no non-English LC_TIME locale on this computer")
    try:
        label, _start, _end = _parse_key_and_generate_interval("2026-03", TimeGrouping.MONTH)
    finally:
        locale.setlocale(locale.LC_TIME, previous)
    assert label == "Mar 26"


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()


@pytest.fixture()
def context(tmp_path: Path, qapp):
    from tests.qt_helpers import signed_in_context

    value = signed_in_context(tmp_path / "qa.db")
    yield value
    value.shutdown()
    qapp.processEvents()


def _member(context, role: str = "bdr") -> tuple[str, str]:
    from techset_leadgen.database.models import User
    from techset_leadgen.security.passwords import hash_password
    from tests.qt_helpers import TEST_PASSWORD

    email = f"{role}.member@techset.example"
    context.write("user", lambda db, _actor: db.add(User(email=email, full_name="Bilal Ahmed", role=role,
                                                         password_hash=hash_password(TEST_PASSWORD), is_active=True)))
    return email, TEST_PASSWORD


def test_bug102_audit_log_names_outreach_records_and_offers_their_types(qapp, context):
    from sqlalchemy import select

    from techset_leadgen.database.models import AuditLog, Prospect, User
    from techset_leadgen.desktop.pages.admin_pages import AuditPage, _changes_summary, _record_text, record_names
    from techset_leadgen.services import prospects
    from techset_leadgen.services.schemas import ProspectCreate, parse

    email, _password = _member(context)
    prospect_id = context.write("prospect", lambda db, actor: prospects.create_prospect(db, actor, parse(
        ProspectCreate, {"linkedin_url": "https://www.linkedin.com/in/ayesha-khan-qa/", "full_name": "Ayesha Khan"})).id)

    def shown(db, _actor):
        entry = db.scalar(select(AuditLog).where(AuditLog.entity_type == "prospect", AuditLog.entity_id == prospect_id))
        admin = db.scalar(select(User).where(User.role == "super_admin"))
        member = db.scalar(select(User).where(User.email == email))
        changes = {"prospect_id": prospect_id, "assignee_id": [admin.id, member.id], "status": ["assigned", "cancelled"]}
        fake = AuditLog(action="assignment.reassigned", entity_type="prospect_assignment", entity_id="x", changes=changes)
        names = record_names(db, [entry, fake])
        return (_record_text(entry, names),
                _changes_summary(changes, entity_type="prospect_assignment", names=names, limit=None))

    record, changes = context.run(shown, commit=False)
    assert record == "Prospect: Ayesha Khan"
    assert changes == "prospect: Ayesha Khan; assignee: Test Admin → Bilal Ahmed; status: Assigned → Cancelled"
    page = AuditPage(context)
    offered = {page.entity_filter.itemData(index) for index in range(page.entity_filter.count())}
    assert {"prospect", "prospect_assignment", "assignment_batch", "meeting"} <= offered
    assert Prospect is not None


def test_bug103_only_the_danger_zone_tab_is_marked_red(qapp, context):
    from techset_leadgen.desktop.pages.settings_page import SettingsPage

    page = SettingsPage(context)
    page.refresh()
    assert page.tabs.isTabVisible(page.danger_index) and page.tabs.tabBar().property("danger") is True
    email, password = _member(context)
    context.sign_out()
    context.sign_in(email, password)
    member_page = SettingsPage(context)
    member_page.refresh()
    assert not member_page.tabs.isTabVisible(member_page.danger_index)
    assert member_page.tabs.tabBar().property("danger") is False


def test_bug104_a_failed_sign_in_shows_no_password_rules(qapp, context):
    from techset_leadgen.desktop.auth_pages import PasswordRules, SignInPage

    context.sign_out()
    page = SignInPage(context)
    page.email.setText("admin@techset.example")
    page.password.setText("not-the-password-1")
    assert page.submit() is False
    assert page.error.isVisibleTo(page) or page.error.label.text()
    assert not [rules for rules in page.findChildren(PasswordRules) if rules.isVisibleTo(page)]


def test_bug105_ctrl_number_follows_the_sidebar_the_person_sees(qapp, context):
    from techset_leadgen.desktop.main_window import MainWindow
    from techset_leadgen.desktop.theme import ThemeManager

    email, password = _member(context)
    context.sign_out()
    window = MainWindow(ThemeManager(qapp), context=context)
    window.resize(1366, 768)
    window.show()
    window.sign_in_page.email.setText(email)
    window.sign_in_page.password.setText(password)
    window.sign_in_page.submit()
    qapp.processEvents()
    shown = [key for key, button in window._nav_buttons.items() if button.isVisibleTo(window.sidebar)]
    assert "assignments" not in shown and len(shown) >= 5
    for number in (4, 5):
        window._shortcuts[number - 1].activated.emit()
        qapp.processEvents()
        assert window.stack.currentWidget() is window._pages.get(shown[number - 1]), (number, shown)
    window.close()


def test_bug109_clicking_the_number_of_a_kpi_card_opens_its_area(qapp, context):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from techset_leadgen.desktop.pages.operational_dashboard_page import OperationalDashboardPage

    page = OperationalDashboardPage(context)
    opened: list[str] = []
    page._navigate = lambda destination: opened.append(destination)
    page.resize(1400, 900)
    page.show()
    qapp.processEvents()
    for card in page.cards.values():
        card.clicked.disconnect()
        card.clicked.connect(lambda: opened.append("card"))
        label = card.value_label
        point = label.mapTo(card, label.rect().center())
        target = card.childAt(point) or card
        QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFrom(card, point))
        qapp.processEvents()
        assert opened == ["card"], (card.accessibleName(), type(target).__name__)
        opened.clear()
    page.close()


@pytest.mark.parametrize("pixels", [13, 15, 16])
def test_bug110_the_stretched_name_column_is_not_cut_with_wider_fonts(qapp, pixels):
    from PySide6.QtGui import QFont

    from techset_leadgen.desktop.tables import fit_columns
    from tests.ui.test_tables import _table

    long = "A very long description that would push every later column off screen"
    table = _table([["Globex Corporation", long, "someone@example.com", "Qualified", ""]],
                   ["Name", "Notes", "Email", "Stage", "Actions"], badge_columns=(3,))
    font = QFont(table.font())
    font.setPixelSize(pixels)
    table.setFont(font)
    table.resize(640, 240)
    table.show()
    fit_columns(table, stretch_column=0, fixed_columns={4: 120}, min_widths={0: 150})
    qapp.processEvents()
    header = table.horizontalHeader()
    assert header.sectionSize(0) >= table.sizeHintForColumn(0)
    assert sum(header.sectionSize(column) for column in range(5)) <= table.viewport().width() + 1
    table.close()
    table.deleteLater()

