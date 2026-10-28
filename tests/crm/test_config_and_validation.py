"""Configuration loading, input normalization, and schema validation."""

from __future__ import annotations


import pytest

from crm.config import ConfigurationError, load_settings
from crm.errors import ValidationFailed
from crm.schemas import ClientCreate, ContactCreate, LeadCreate, LeadTransition, parse
from crm.services import normalize as norm

# --- configuration -------------------------------------------------------------


def test_the_application_database_is_the_analytics_file(monkeypatch, tmp_path):
    import core.db

    monkeypatch.setattr(core.db, "DB_PATH", tmp_path / "sales.db")
    settings = load_settings({})
    assert settings.database_path == (tmp_path / "sales.db").resolve()
    assert settings.database_url == f"sqlite:///{(tmp_path / 'sales.db').resolve().as_posix()}"
    assert settings.display_database.startswith("Local file on this computer")


def test_session_limits_can_be_tuned_and_are_validated(tmp_path):
    settings = load_settings({"TSLG_SESSION_IDLE_MINUTES": "45", "TSLG_LOGIN_MAX_FAILURES": "3"},
                             database_path=tmp_path / "x.db")
    assert (settings.session_idle_minutes, settings.login_max_failures) == (45, 3)
    with pytest.raises(ConfigurationError, match="at least 1"):
        load_settings({"TSLG_SESSION_IDLE_MINUTES": "0"}, database_path=tmp_path / "x.db")
    with pytest.raises(ConfigurationError, match="whole number"):
        load_settings({"TSLG_LOGIN_MAX_FAILURES": "five"}, database_path=tmp_path / "x.db")


# --- normalization -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.Example.com/about?x=1", "example.com"),
        ("EXAMPLE.com.", "example.com"),
        ("http://shop.example.co.uk:8080", "shop.example.co.uk"),
        ("www.io", "www.io"),  # a bare www.<tld> is a real two-label domain
        ("münchen.de", "xn--mnchen-3ya.de"),
        ("", None),
    ],
)
def test_domains_are_normalized_for_duplicate_detection(raw, expected):
    assert norm.normalize_domain(raw) == expected


@pytest.mark.parametrize("raw", ["localhost", "192.168.1.10", "exa mple.com", "-bad-.com", "example.c0m"])
def test_invalid_domains_are_rejected(raw):
    with pytest.raises(norm.InvalidValue):
        norm.normalize_domain(raw)


def test_urls_only_allow_http_and_https_without_credentials():
    assert norm.normalize_url("acme.io/contact") == "https://acme.io/contact"
    for bad in ("javascript:alert(1)", "ftp://acme.io", "https://user:pw@acme.io", "https://"):
        with pytest.raises(norm.InvalidValue):
            norm.normalize_url(bad)
    with pytest.raises(norm.InvalidValue, match="linkedin.com"):
        norm.normalize_linkedin_url("https://evil.example/in/jane")


def test_emails_are_lower_cased_but_not_rewritten():
    assert norm.normalize_email(" Jane.Doe+crm@ACME.io ") == "jane.doe+crm@acme.io"
    for bad in ("jane", "jane@", "@acme.io", "jane..doe@acme.io", "jane@acme", "a@b@c.io"):
        with pytest.raises(norm.InvalidValue):
            norm.normalize_email(bad)


def test_company_name_key_ignores_case_accents_punctuation_and_legal_suffixes():
    assert norm.normalize_company_name("Café Müller S.L.") == norm.normalize_company_name("cafe muller sl")
    assert norm.normalize_company_name("Acme, Inc.") == "acme"
    assert norm.normalize_company_name("Inc") == "inc"  # never empties the key


def test_tags_phone_and_timezone():
    assert norm.normalize_tags("SaaS, saas , fintech,,") == ["SaaS", "fintech"]
    assert norm.normalize_phone("+44 (20) 7946-0000") == "+44 (20) 7946-0000"
    with pytest.raises(norm.InvalidValue):
        norm.normalize_phone("call me")
    assert norm.normalize_timezone("Asia/Karachi") == "Asia/Karachi"
    with pytest.raises(norm.InvalidValue):
        norm.normalize_timezone("Mars/Olympus")


# --- schemas -------------------------------------------------------------------


def test_schemas_reject_server_owned_fields_mass_assignment():
    with pytest.raises(ValidationFailed) as error:
        parse(LeadCreate, {"title": "x", "source": "manual_import", "status": "qualified", "owner": "x",
                           "qualification_reason": "self-approved", "id": "L_ADMIN"})
    assert error.value.fields == {
        "status": "This field cannot be set.",
        "owner": "This field cannot be set.",
        "qualification_reason": "This field cannot be set.",
        "id": "This field cannot be set.",
    }


def test_schema_errors_are_per_field_and_user_facing():
    with pytest.raises(ValidationFailed) as error:
        parse(ClientCreate, {"name": "  ", "website_url": "javascript:alert(1)", "employee_range": "huge",
                             "account_status": "vip"})
    assert error.value.fields == {
        "name": "This field is required.",
        "website_url": "Enter a web address starting with http:// or https://.",
        "employee_range": "Choose one of the listed options.",
        "account_status": "Choose one of the listed options.",
    }
    with pytest.raises(ValidationFailed) as error:
        parse(ContactCreate, {"client_id": "C1", "first_name": "Jane", "email": "not-an-email"})
    assert error.value.fields == {"email": "Enter a valid email address."}
    with pytest.raises(ValidationFailed) as error:
        parse(LeadTransition, {"status": "won"})
    assert error.value.fields == {"status": "Choose one of the listed options."}
    with pytest.raises(ValidationFailed) as error:
        parse(LeadCreate, {"title": "x", "source": "manual_import", "meeting_date": "31/12/2026"})
    assert error.value.fields == {"meeting_date": "Enter a date as YYYY-MM-DD."}


def test_lead_stage_names_from_imports_map_to_codes_or_are_refused():
    from domain.lead_stages import normalize_lead_status

    assert [normalize_lead_status(value) for value in ("Client", " contacted ", None, "Qualified", "Lost")] == [
        "converted", "contacted", "new", "qualified", "lost"]
    with pytest.raises(ValueError, match="Unknown lead stage"):
        normalize_lead_status("maybe later")
