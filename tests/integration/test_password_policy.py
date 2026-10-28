"""The four-rule password policy (``crm.security.passwords``) and where it is enforced."""

from __future__ import annotations

import gzip
import re
from pathlib import Path

import pytest

from techset_leadgen.errors import ValidationFailed
from techset_leadgen.services.schemas import UserInvite, parse
from techset_leadgen.security import passwords
from techset_leadgen.security.passwords import (
    COMMON_PASSWORDS_FILE,
    MAX_LENGTH,
    MIN_LENGTH,
    RULES,
    broken_rules,
    common_passwords,
    comparison_form,
    password_length,
    validate_password,
)
from techset_leadgen.services import auth, users
from techset_leadgen.services.access import Actor

from tests.integration.conftest import PASSWORD

ROOT = Path(__file__).resolve().parents[2]
EMAIL = "ayesha.malik@techset.example"
NAME = "Ayesha Malik"


def broken(password: str, *, email: str | None = EMAIL, name: str | None = NAME) -> list[str]:
    return [rule.key for rule in broken_rules(password, email=email, names=(name,))]


# --- passwords that pass -------------------------------------------------------


@pytest.mark.parametrize("password", [
    "correct horse battery staple",
    "kx7#mqp2",  # exactly the minimum length
    "blue-kettle-42",
    "Password123!",  # a common password with a change is not an exact match
    "9384726a",  # digits with one letter
    "1234-5678",  # digits with a separator
    "ayesha loves rainy mornings",  # contains the first name, but is mostly other words
    "Malik is my favourite cat",
    "ریاضی کی کتاب",  # Urdu letters and spaces
    "café-noir-7",
    "x" * MAX_LENGTH,  # the four rules do not judge repetition
])
def test_passwords_that_follow_the_four_rules_pass(password):
    assert broken(password) == []
    validate_password(password, email=EMAIL, full_name=NAME)  # does not raise


def test_no_character_classes_are_required():
    for password in ("all lower case words", "ALL UPPER CASE WORDS", "nodigitsnosymbols"):
        assert broken(password) == [], password


# --- rule 1: not like the user's email or name ---------------------------------


@pytest.mark.parametrize("password", [
    "ayesha.malik",  # the email's local part
    "AyeshaMalik",  # the name without the space, other case
    "ayeshamalik1",
    "Ayesha2024!",  # the first name plus a few characters
    "techset.example",  # the email's domain
    EMAIL.upper(),  # the email itself
])
def test_passwords_like_the_email_or_name_are_rejected(password):
    assert "similar" in broken(password)
    with pytest.raises(ValidationFailed) as error:
        validate_password(password, email=EMAIL, full_name=NAME)
    assert "too similar to your name or email" in error.value.fields["password"]


@pytest.mark.parametrize(("password", "email", "name"), [
    # Found by the dummy-account run: the user's own words rearranged scored under the
    # similarity threshold, and short names plus a year passed while longer ones did not.
    ("AhmedBilal", "bilal.ahmed@techset.example", "Bilal Ahmed"),  # names swapped
    ("AyeshaAyesha", EMAIL, NAME),  # repeated
    ("kilaMahseyA", EMAIL, NAME),  # reversed
    ("Seán2024", "sean.obrien@techset.example", "Seán O'Brien"),  # a 4-letter name plus a year
    ("José@123", "jose.garcia@techset.example", "José García-Márquez"),
    ("Christopher_Wellington", "chris.mw@example.io", "Christopher Alexander Montgomery-Wellington"),
    ("سارہ2024", "sara.khan@techset.example", "سارہ خان"),  # Urdu name plus a year
    ("مرتضیٰعمران", "imran.urdu@techset.example", "عمران مرتضیٰ"),  # Urdu names swapped
    ("Techset2026!", EMAIL, NAME),  # the email's domain word
])
def test_passwords_made_only_of_the_users_own_words_are_rejected(password, email, name):
    assert "similar" in broken(password, email=email, name=name)


def test_own_words_rule_needs_every_letter_to_be_the_users():
    assert broken("Alibaba99", email="m.ali.khan@gmail.com", name="Muhammad Ali Khan") == []
    assert broken("ayesha loves rainy mornings") == []
    assert broken("Bilal-Ahmed-likes-chai", email="bilal.ahmed@techset.example", name="Bilal Ahmed") == []


def test_similarity_is_not_overly_broad():
    # Short name parts can never reach the threshold against an 8-character password.
    assert broken("liwu-blue-kettle", email="li.wu@example.io", name="Li Wu") == []
    # Without an email or name there is nothing to compare with.
    assert "similar" not in broken("ayesha.malik", email=None, name=None)
    # Similar to someone else's name is fine.
    assert broken("ayeshamalik1", email="bilal@example.io", name="Bilal Ahmed") == []


def test_similarity_ignores_case_and_look_alike_characters():
    assert "similar" in broken("ＡＹＥＳＨＡＭＡＬＩＫ")  # full-width letters fold to plain ones


# --- rule 2: at least 8 characters --------------------------------------------


def test_minimum_length_is_eight():
    assert MIN_LENGTH == 8
    assert "length" in broken("Kx7#mqp")  # 7
    assert "length" not in broken("Kx7#mqp2")  # 8
    assert "length" in broken("")


def test_length_counts_characters_not_code_points():
    composed, decomposed = "é", "é"  # "é" typed two ways
    assert password_length(composed) == password_length(decomposed) == 1
    assert password_length("ریاضی") == 5
    # Seven characters, but ten code points when the accents are combining marks.
    seven = "qvbn" + decomposed * 3
    assert len(seven) == 10 and "length" in broken(seven)
    assert "length" not in broken("qvbn" + composed * 4)


def test_invisible_characters_do_not_count_or_hide_a_common_password():
    for hidden in ("\u200b", "\u200d", "\u00ad", "\u200f", "\ufeff"):  # zero-width, joiner, soft hyphen, RLM, BOM
        assert "common" in broken(f"pass{hidden}word"), repr(hidden)
        assert "length" in broken(f"Kx7#{hidden}mqp"), repr(hidden)  # 7 visible characters


def test_spaces_count_towards_the_length():
    assert "length" not in broken("ab cd ef")


def test_too_long_passwords_are_rejected_before_hashing():
    with pytest.raises(ValidationFailed) as error:
        validate_password("x" * (MAX_LENGTH + 1))
    assert error.value.fields == {"password": f"Use at most {MAX_LENGTH} characters."}


# --- rule 3: not a common password --------------------------------------------


@pytest.mark.parametrize("password", [
    "password", "password123", "Password123", "PASSWORD123", "iloveyou", "qwertyuiop",
    " password ",  # outer spaces do not hide it
    "ｐａｓｓｗｏｒｄ",  # full-width letters
    "𝓅𝒶𝓈𝓈𝓌ℴ𝓇𝒹",  # mathematical script letters
])
def test_common_passwords_are_rejected(password):
    assert "common" in broken(password)
    with pytest.raises(ValidationFailed) as error:
        validate_password(password)
    assert "too common" in error.value.fields["password"]


def test_the_common_password_list_is_local_normalized_and_documented():
    entries = common_passwords()
    assert len(entries) > 90_000
    assert {"password", "password123", "12345678", "iloveyou"} <= entries
    lines = gzip.decompress(COMMON_PASSWORDS_FILE.read_bytes()).decode("utf-8").splitlines()
    assert lines == sorted(set(lines)), "stored sorted and without duplicates"
    assert all(line == comparison_form(line) and line for line in lines), "stored in comparison form"
    notes = (COMMON_PASSWORDS_FILE.parent / "COMMON_PASSWORDS.md").read_text(encoding="utf-8")
    assert f"{len(lines):,} unique entries" in notes, "COMMON_PASSWORDS.md states the current count"


def test_the_windows_build_bundles_the_list():
    spec = (ROOT / "packaging" / "TechsetLeadGen.spec").read_text(encoding="utf-8")
    assert re.search(r'"security" / "common-passwords\.txt\.gz"\), "techset_leadgen/security"', spec)


def test_a_missing_list_fails_loudly_instead_of_accepting_everything(monkeypatch, tmp_path):
    monkeypatch.setattr(passwords, "COMMON_PASSWORDS_FILE", tmp_path / "missing.txt.gz")
    common_passwords.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="common-password list"):
            broken("kx7#mqp2")
    finally:
        monkeypatch.undo()
        common_passwords.cache_clear()


def test_update_script_rebuilds_the_list_reproducibly(tmp_path):
    from scripts.update_common_passwords import build

    source = tmp_path / "list.txt"
    source.write_text("Password\npassword\n  QWERTY  \n\n\x10\x17\nＡＢＣ\n", encoding="utf-8")
    first, second = tmp_path / "a.gz", tmp_path / "b.gz"
    assert build(source, first) == 3
    build(source, second)
    assert first.read_bytes() == second.read_bytes()
    assert gzip.decompress(first.read_bytes()).decode("utf-8") == "abc\npassword\nqwerty\n"


# --- rule 4: not only numbers --------------------------------------------------


@pytest.mark.parametrize("password", [
    "12345678", "987654321",
    "93847261059",  # not on the common list: rejected by this rule alone
    " 93847261059 ",  # outer spaces do not make it more than numbers
    "۹۳۸۴۷۲۶۱۰۵",  # Urdu (Extended Arabic-Indic) digits
    "١٢٣٤٥٦٧٨٩",  # Arabic-Indic digits
    "１２３４５６７８",  # full-width digits
])
def test_numeric_only_passwords_are_rejected(password):
    assert "numeric" in broken(password)
    with pytest.raises(ValidationFailed) as error:
        validate_password(password)
    assert "more than numbers" in error.value.fields["password"]


def test_digits_mixed_with_other_characters_pass_the_numeric_rule():
    for password in ("9384726a", "1234-5678", "2026 10 23 lunch"):
        assert "numeric" not in broken(password), password


# --- messages ---------------------------------------------------------------------


def test_every_broken_rule_is_reported_in_order():
    assert broken("1234567") == ["length", "numeric", "common"]
    with pytest.raises(ValidationFailed) as error:
        validate_password("1234567", field="new_password")
    message = error.value.fields["new_password"]
    for rule in RULES[:3]:
        assert rule.message in message
    assert message.index("at least 8") < message.index("more than numbers") < message.index("too common")
    assert error.value.message == "The password does not meet the requirements."


# --- enforced in every flow that sets a password ------------------------------


def test_first_run_setup_applies_the_policy(db):
    with pytest.raises(ValidationFailed) as error:
        auth.bootstrap_organization(db, organization_name="Techset", admin_email=EMAIL,
                                    admin_name=NAME, password="ayeshamalik1")
    assert "too similar" in error.value.fields["password"]
    user = auth.bootstrap_organization(db, organization_name="Techset", admin_email=EMAIL,
                                       admin_name=NAME, password="ayesha loves rainy mornings")
    assert user.password_hash


@pytest.mark.parametrize("purpose", ["invite", "password_reset"])
def test_activation_and_reset_codes_apply_the_policy(db, settings, acme, purpose):
    admin = acme.actor()
    if purpose == "invite":
        user, code = users.invite_user(db, admin, settings, parse(UserInvite, {
            "email": "bilal.ahmed@example.com", "full_name": "Bilal Ahmed", "role": "bdr"}))
    else:
        user = acme.users["bdr"]
        code, _purpose = users.issue_access_code(db, admin, settings, user.id)
    db.commit()
    for weak, phrase in (("password123", "too common"), ("93847261059", "more than numbers"),
                         ("short", "at least 8"), (user.full_name.replace(" ", ""), "too similar")):
        with pytest.raises(ValidationFailed) as error:
            auth.redeem_code(db, settings, raw_code=code, password=weak)
        assert phrase in error.value.fields["password"], weak
        db.rollback()
    assert auth.redeem_code(db, settings, raw_code=code, password="blue-kettle-42").user.id == user.id


def test_password_change_applies_the_policy(db, settings, acme):
    user = acme.users["bdr"]
    session = auth.authenticate(db, settings, email=user.email, password=PASSWORD).session
    for weak in ("password", "12345678", "kx7#mqp", user.email):
        with pytest.raises(ValidationFailed) as error:
            auth.change_password(db, Actor.for_user(user), current_session_id=session.id,
                                 current_password=PASSWORD, new_password=weak)
        assert set(error.value.fields) == {"new_password"}, weak
    auth.change_password(db, Actor.for_user(user), current_session_id=session.id,
                         current_password=PASSWORD, new_password="blue-kettle-42")
