from __future__ import annotations

import gzip
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from techset_leadgen.errors import ValidationFailed

MIN_LENGTH = 8
MAX_LENGTH = 128
MAX_SIMILARITY = 0.7
COMMON_PASSWORDS_FILE = Path(__file__).with_name("common-passwords.txt.gz")

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("timing-equalisation-placeholder")
_SEPARATORS = re.compile(r"[\W_]+")


@dataclass(frozen=True)
class PasswordRule:
    key: str
    label: str
    message: str


RULES = (
    PasswordRule("length", f"At least {MIN_LENGTH} characters", f"Use at least {MIN_LENGTH} characters."),
    PasswordRule("numeric", "Not only numbers", "Use more than numbers: add letters, spaces, or symbols."),
    PasswordRule("common", "Not a common password",
                 "This password is too common and easy to guess. Choose a less predictable one."),
    PasswordRule("similar", "Not like your name or email",
                 "This password is too similar to your name or email address."),
)


def _visible(text: str) -> str:
    return "".join(character for character in text if unicodedata.category(character) != "Cf")


def comparison_form(text: str) -> str:
    return _visible(unicodedata.normalize("NFKC", text)).casefold().strip()


def password_length(password: str) -> int:
    return len(_visible(unicodedata.normalize("NFC", password)))


@cache
def common_passwords() -> frozenset[str]:
    try:
        with gzip.open(COMMON_PASSWORDS_FILE, "rt", encoding="utf-8") as handle:
            return frozenset(line.rstrip("\n") for line in handle if line.strip())
    except OSError as exc:
        raise RuntimeError(f"The common-password list is missing or unreadable: {COMMON_PASSWORDS_FILE}") from exc


def _attribute_values(email: str | None, names: Iterable[str | None]) -> list[str]:
    values: list[str] = []
    for raw in (email, *(email or "").partition("@")[::2], *names):
        value = comparison_form(raw or "")
        if not value:
            continue
        values += [value, _SEPARATORS.sub("", value), *_SEPARATORS.split(value)]
    return list(dict.fromkeys(value for value in values if value))


def _too_similar(password: str, values: Iterable[str]) -> bool:
    candidate = comparison_form(password)
    if not candidate:
        return False
    return any(SequenceMatcher(None, candidate, value, autojunk=False).ratio() >= MAX_SIMILARITY
               for value in values)


def _letters(text: str) -> str:
    return "".join(character for character in text if character.isalpha())


def _only_own_words(password: str, values: Iterable[str]) -> bool:
    letters = _letters(comparison_form(password))
    words = {_letters(value) for value in values} - {""}
    if not letters or not words:
        return False
    longest = max(map(len, words))

    def made_of_words(text: str) -> bool:
        reachable = [True] + [False] * len(text)
        for end in range(1, len(text) + 1):
            reachable[end] = any(reachable[start] and text[start:end] in words
                                 for start in range(max(0, end - longest), end))
        return reachable[-1]

    return made_of_words(letters) or made_of_words(letters[::-1])


def broken_rules(password: str, *, email: str | None = None,
                 names: Iterable[str | None] = ()) -> list[PasswordRule]:
    compared = comparison_form(password)
    attributes = _attribute_values(email, names)
    checks = {
        "length": password_length(password) < MIN_LENGTH,
        "numeric": compared.isdigit(),
        "common": compared in common_passwords(),
        "similar": _too_similar(password, attributes) or _only_own_words(password, attributes),
    }
    return [rule for rule in RULES if checks[rule.key]]


def validate_password(password: str, *, email: str | None = None, full_name: str | None = None,
                      field: str = "password") -> None:
    if len(password) > MAX_LENGTH:
        raise ValidationFailed("The password does not meet the requirements.",
                               fields={field: f"Use at most {MAX_LENGTH} characters."})
    broken = broken_rules(password, email=email, names=(full_name,))
    if broken:
        raise ValidationFailed("The password does not meet the requirements.",
                               fields={field: " ".join(rule.message for rule in broken)})


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

