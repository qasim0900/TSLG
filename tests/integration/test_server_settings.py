from __future__ import annotations

import pytest

from techset_leadgen.config import ConfigurationError, load_settings, settings_for_url

SECRET = "s3cret-pass"
URL = f"postgresql://tslg_app:{SECRET}@office-server:5432/techset_leadgen?sslmode=require"


def test_the_environment_selects_the_team_database(tmp_path, monkeypatch):
    from techset_leadgen.database import local_db

    monkeypatch.setattr(local_db, "DB_PATH", tmp_path / "sales.db")
    settings = load_settings({"TSLG_DATABASE_URL": URL})
    assert settings.is_server
    assert settings.database_url.startswith("postgresql+psycopg://tslg_app:")
    assert settings.display_database == "Team database techset_leadgen on office-server:5432"
    assert SECRET not in settings.display_database
    assert not load_settings({}).is_server


def test_database_ini_in_the_data_folder_selects_the_team_database(tmp_path, monkeypatch):
    from techset_leadgen.database import local_db

    monkeypatch.setattr(local_db, "DB_PATH", tmp_path / "sales.db")
    (tmp_path / "database.ini").write_text(f"[database]\nurl = {URL}\n", encoding="utf-8")
    assert load_settings({}).is_server
    assert not load_settings({"TSLG_DATABASE_URL": URL}, database_path=tmp_path / "other.db").is_server


@pytest.mark.parametrize("bad", [f"mysql://root:{SECRET}@db/x", f"postgresql://u:{SECRET}@/nodatabase",
                                 f"not a url {SECRET}"])
def test_invalid_addresses_are_refused_without_repeating_them(tmp_path, monkeypatch, bad):
    from techset_leadgen.database import local_db

    monkeypatch.setattr(local_db, "DB_PATH", tmp_path / "sales.db")
    with pytest.raises(ConfigurationError) as caught:
        load_settings({"TSLG_DATABASE_URL": bad})
    assert SECRET not in str(caught.value) and caught.value.__cause__ is None


def test_an_unreachable_server_is_reported_without_the_password():
    pytest.importorskip("PySide6.QtCore")
    from techset_leadgen.desktop.session import AppContext, ConnectionProblem

    context = AppContext(settings_for_url(f"postgresql://tslg_app:{SECRET}@127.0.0.1:1/techset_leadgen"))
    with pytest.raises(ConnectionProblem) as caught:
        context.open()
    assert caught.value.message == "The team database server cannot be reached."
    assert SECRET not in caught.value.details and SECRET not in caught.value.message

