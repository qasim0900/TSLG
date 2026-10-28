"""Sign-in, rate limiting, desktop sessions, activation codes, and password changes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from techset_leadgen.errors import DomainError, PermissionDenied, ValidationFailed
from techset_leadgen.database.models import AuditLog, AuthAttempt, User, UserSession, UserToken
from techset_leadgen.services.schemas import UserAdminUpdate, UserInvite, parse
from techset_leadgen.services import auth, users
from techset_leadgen.services.access import Actor

from tests.integration.conftest import PASSWORD


def _sign_in(db, settings, user, password=PASSWORD):
    return auth.authenticate(db, settings, email=user.email, password=password, client_host="pc-1", client_app="test")


def test_sign_in_normalizes_email_and_records_attempt_and_audit(db, settings, acme):
    user = acme.users["bdr"]
    signed_in = auth.authenticate(db, settings, email=f"  {user.email.upper()} ", password=PASSWORD)
    assert signed_in.user.id == user.id
    assert db.scalar(select(UserSession.id).where(UserSession.user_id == user.id)) == signed_in.session.id
    assert signed_in.session.token_hash != signed_in.raw_token  # only the digest is stored
    assert db.scalar(select(AuthAttempt.succeeded).where(AuthAttempt.email == user.email)) is True
    assert db.scalar(select(AuditLog.action).where(AuditLog.entity_id == str(user.id))) == "auth.login"


@pytest.mark.parametrize("case", ["wrong_password", "unknown_email", "inactive", "no_password_yet"])
def test_failed_sign_in_gives_one_generic_message(db, settings, world, acme, case):
    email, password = acme.users["bdr"].email, PASSWORD
    if case == "wrong_password":
        password = "not the password at all"
    elif case == "unknown_email":
        email = "nobody@example.com"
    elif case == "inactive":
        email = world.user(acme.organization, "bdr", active=False).email
    else:
        email = world.user(acme.organization, "bdr", password=False).email
    db.commit()
    with pytest.raises(auth.InvalidCredentials) as error:
        auth.authenticate(db, settings, email=email, password=password)
    assert error.value.message == "Incorrect email or password."
    assert db.scalar(select(AuthAttempt.succeeded).where(AuthAttempt.email == email)) is False


def test_repeated_failures_lock_the_account_for_the_window(db, settings, acme):
    user = acme.users["bdr"]
    for _ in range(settings.login_max_failures):
        with pytest.raises(auth.InvalidCredentials):
            auth.authenticate(db, settings, email=user.email, password="wrong password!!")
    with pytest.raises(DomainError) as error:  # even the right password is refused now
        auth.authenticate(db, settings, email=user.email, password=PASSWORD)
    assert error.value.code == "rate_limited"
    # Attempts older than the window no longer count.
    for attempt in db.scalars(select(AuthAttempt)):
        attempt.created_at -= timedelta(minutes=settings.login_window_minutes + 1)
    db.commit()
    assert _sign_in(db, settings, user).user.id == user.id


def test_passwords_are_argon2_hashed_never_plain(db, acme):
    stored = db.scalar(select(User.password_hash).where(User.id == acme.users["bdr"].id))
    assert stored.startswith("$argon2id$") and PASSWORD not in stored


def test_session_check_detects_revocation_deactivation_idle_and_expiry(db, settings, acme):
    user = acme.users["bdr"]
    first = _sign_in(db, settings, user)
    assert auth.check_session(db, settings, session_id=first.session.id, raw_token=first.raw_token)
    with pytest.raises(auth.SessionEnded):  # a stolen session id alone is useless
        auth.check_session(db, settings, session_id=first.session.id, raw_token="x" * 43)

    first.session.last_seen_at -= timedelta(minutes=settings.session_idle_minutes + 1)
    db.commit()
    with pytest.raises(auth.SessionEnded, match="inactivity"):
        auth.check_session(db, settings, session_id=first.session.id, raw_token=first.raw_token)

    second = _sign_in(db, settings, user)
    second.session.expires_at = second.session.created_at - timedelta(seconds=1)
    db.commit()
    with pytest.raises(auth.SessionEnded, match="at most"):
        auth.check_session(db, settings, session_id=second.session.id, raw_token=second.raw_token)

    third = _sign_in(db, settings, user)
    users.update_user(db, acme.actor(), user.id, parse(UserAdminUpdate, {"is_active": False}))
    db.commit()
    with pytest.raises(auth.SessionEnded):
        auth.check_session(db, settings, session_id=third.session.id, raw_token=third.raw_token)


def test_check_without_touch_lets_server_side_idle_limit_apply(db, settings, acme):
    signed_in = _sign_in(db, settings, acme.users["bdr"])
    before = signed_in.session.last_seen_at - timedelta(minutes=5)
    signed_in.session.last_seen_at = before
    db.commit()
    auth.check_session(db, settings, session_id=signed_in.session.id, raw_token=signed_in.raw_token, touch=False)
    assert db.get(UserSession, signed_in.session.id).last_seen_at == before
    auth.check_session(db, settings, session_id=signed_in.session.id, raw_token=signed_in.raw_token, touch=True)
    assert db.get(UserSession, signed_in.session.id).last_seen_at > before


def test_role_change_ends_sessions_even_within_the_same_unit_of_work(db, settings, acme):
    """Regression: a cached session row hid the revocation (found by smoke test, 2026-10-21)."""
    user = acme.users["bdr"]
    signed_in = _sign_in(db, settings, user)
    users.update_user(db, acme.actor(), user.id, parse(UserAdminUpdate, {"role": "account_executive"}))
    db.commit()
    with pytest.raises(auth.SessionEnded, match="signed out"):
        auth.check_session(db, settings, session_id=signed_in.session.id, raw_token=signed_in.raw_token)


def test_sign_out_and_password_change_end_sessions(db, settings, acme):
    user = acme.users["bdr"]
    current, other = _sign_in(db, settings, user), _sign_in(db, settings, user)
    actor = Actor.for_user(user)
    with pytest.raises(ValidationFailed) as error:
        auth.change_password(db, actor, current_session_id=current.session.id,
                             current_password="wrong guess here", new_password="a brand new passphrase")
    assert error.value.fields == {"current_password": "Your current password is incorrect."}
    ended = auth.change_password(db, actor, current_session_id=current.session.id,
                                 current_password=PASSWORD, new_password="a brand new passphrase")
    db.commit()
    assert ended == 1
    with pytest.raises(auth.SessionEnded):
        auth.check_session(db, settings, session_id=other.session.id, raw_token=other.raw_token)
    auth.check_session(db, settings, session_id=current.session.id, raw_token=current.raw_token)
    auth.sign_out(db, actor, current.session.id)
    db.commit()
    with pytest.raises(auth.SessionEnded):
        auth.check_session(db, settings, session_id=current.session.id, raw_token=current.raw_token)
    assert _sign_in(db, settings, user, "a brand new passphrase").user.id == user.id


@pytest.mark.parametrize(
    ("password", "message"),
    [("short", "at least 8"), ("password123", "too common"), ("93847261059", "more than numbers")],
)
def test_password_policy(db, settings, acme, password, message):
    with pytest.raises(ValidationFailed) as error:
        auth.change_password(db, Actor.for_user(acme.users["bdr"]), current_session_id=_sign_in(
            db, settings, acme.users["bdr"]).session.id, current_password=PASSWORD, new_password=password)
    assert message in error.value.fields["new_password"]


def test_invitation_code_is_single_use_hashed_and_signs_in(db, settings, acme):
    admin = acme.actor()
    invited, code = users.invite_user(db, admin, settings, parse(UserInvite, {
        "email": "New.Person@Example.com", "full_name": "New Person", "role": "bdr"}))
    db.commit()
    assert invited.email == "new.person@example.com" and invited.password_hash is None
    assert code not in {token.token_hash for token in db.scalars(select(UserToken))}
    assert auth.code_owner(db, code) == (invited, "invite")
    with pytest.raises(ValidationFailed):  # the policy still applies
        auth.redeem_code(db, settings, raw_code=code, password="weak")
    db.rollback()
    signed_in = auth.redeem_code(db, settings, raw_code=f"  {code} ", password="a perfectly fine passphrase")
    assert signed_in.user.id == invited.id
    with pytest.raises(auth.InvalidCode):
        auth.redeem_code(db, settings, raw_code=code, password="a perfectly fine passphrase")


def test_codes_expire_are_replaced_and_reject_garbage(db, settings, acme):
    admin, user = acme.actor(), acme.users["bdr"]
    old_code, purpose = users.issue_access_code(db, admin, settings, user.id)
    new_code, _ = users.issue_access_code(db, admin, settings, user.id)
    db.commit()
    assert purpose == "password_reset"
    with pytest.raises(auth.InvalidCode):  # issuing a new code invalidates the old one
        auth.code_owner(db, old_code)
    token = db.scalar(select(UserToken).where(UserToken.used_at.is_(None)))
    token.expires_at -= timedelta(hours=settings.token_ttl_hours + 1)
    db.commit()
    with pytest.raises(auth.InvalidCode):
        auth.code_owner(db, new_code)
    for garbage in ("", "short", "x' OR '1'='1' --padding-padding", "a" * 500):
        with pytest.raises(auth.InvalidCode):
            auth.code_owner(db, garbage)


def test_reset_code_ends_existing_sessions(db, settings, acme):
    user = acme.users["bdr"]
    old = _sign_in(db, settings, user)
    code, _ = users.issue_access_code(db, acme.actor(), settings, user.id)
    db.commit()
    auth.redeem_code(db, settings, raw_code=code, password="the replacement passphrase")
    with pytest.raises(auth.SessionEnded):
        auth.check_session(db, settings, session_id=old.session.id, raw_token=old.raw_token)


def test_only_super_admin_can_invite_or_issue_codes(db, settings, acme):
    for role in ("sales_manager", "bdr", "read_only"):
        with pytest.raises(PermissionDenied):
            users.invite_user(db, acme.actor(role), settings, parse(UserInvite, {
                "email": f"x.{role}@example.com", "full_name": "X", "role": "super_admin"}))
        with pytest.raises(PermissionDenied):
            users.issue_access_code(db, acme.actor(role), settings, acme.users["bdr"].id)


def test_admins_cannot_lock_themselves_out_or_remove_the_last_admin(db, settings, acme):
    admin = acme.actor()
    with pytest.raises(PermissionDenied):
        users.update_user(db, admin, admin.user_id, parse(UserAdminUpdate, {"role": "bdr"}))
    with pytest.raises(PermissionDenied):
        users.update_user(db, admin, admin.user_id, parse(UserAdminUpdate, {"is_active": False}))
    manager = acme.users["sales_manager"]
    with pytest.raises(PermissionDenied):  # privilege escalation through the service is refused
        users.update_user(db, Actor.for_user(manager), manager.id, parse(UserAdminUpdate, {"role": "super_admin"}))


def test_first_run_bootstrap_validates_and_creates_one_admin(db):
    assert not auth.has_users(db)
    with pytest.raises(ValidationFailed) as error:
        auth.bootstrap_organization(db, organization_name=" ", admin_email="bad", admin_name="", password=PASSWORD)
    assert set(error.value.fields) == {"organization_name", "admin_email", "admin_name"}
    admin = auth.bootstrap_organization(db, organization_name="Techset Solutions", admin_email="Owner@Example.com",
                                        admin_name="Owner", password=PASSWORD)
    db.commit()
    assert (admin.role, admin.email) == ("super_admin", "owner@example.com")
    assert auth.has_users(db)
