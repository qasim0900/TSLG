"""Administrator recovery command: ``TechsetLeadGen --issue-reset-code EMAIL``.

For when nobody who can manage users is able to sign in (for example the only
Super Admin forgot their password). It prints a one-time password-reset code
for that account; the person enters it on the sign-in screen under "I have an
activation or password-reset code". Anyone who can run this already has the
database file, so it grants nothing beyond that access; it is still audited.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select

from .config import load_settings
from .db import create_db_engine, create_session_factory
from .models import User
from .services import audit, auth
from .services.normalize import email_lookup_key

COMMANDS = {"--issue-reset-code": "Print a one-time password-reset code for the given email address."}


def issue_reset_code(email: str, say: Callable[[str], None]) -> int:
    settings = load_settings()
    engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as db:
            user = db.scalar(select(User).where(User.email == email_lookup_key(email)))
            if user is None or not user.is_active:
                say(f"No active account uses {email!r} in {settings.database_path}.")
                return 1
            purpose = "invite" if user.password_hash is None else "password_reset"
            code = auth.issue_token(db, settings, user, purpose)
            audit.record(db, None, f"user.{purpose}_code_issued", entity_type="user", entity_id=user.id,
                         changes={"via": "command line"})
            db.commit()
    finally:
        engine.dispose()
    say(f"One-time code for {user.full_name} ({user.email}), valid for {settings.token_ttl_hours} hours:")
    say(code)
    say("Enter it on the sign-in screen under “I have an activation or password-reset code”.")
    return 0
