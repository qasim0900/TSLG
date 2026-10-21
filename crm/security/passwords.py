"""Password hashing with Argon2id (argon2-cffi) and the password policy."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..errors import ValidationFailed

MIN_LENGTH = 12
MAX_LENGTH = 128  # bounds hashing cost for hostile input

_hasher = PasswordHasher()  # library defaults follow RFC 9106 recommendations
# Verified when an account does not exist so response time does not reveal it.
_DUMMY_HASH = _hasher.hash("timing-equalisation-placeholder")


def validate_password(password: str, *, email: str | None = None, field: str = "password") -> None:
    problem: str | None = None
    if len(password) < MIN_LENGTH:
        problem = f"Use at least {MIN_LENGTH} characters."
    elif len(password) > MAX_LENGTH:
        problem = f"Use at most {MAX_LENGTH} characters."
    elif password.strip() != password:
        problem = "Remove spaces from the start and end."
    elif len(set(password)) < 5:
        problem = "Use a less repetitive password."
    elif email and password.casefold() in {email.casefold(), email.split("@")[0].casefold()}:
        problem = "Do not use your email address as the password."
    if problem:
        raise ValidationFailed("The password does not meet the requirements.", fields={field: problem})


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if len(password) > MAX_LENGTH:
        return False
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
