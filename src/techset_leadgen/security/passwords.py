"""Password hashing with Argon2id (argon2-cffi) and the password policy.

The policy is four rules, all checked on this computer (a password is never sent
anywhere to be checked):

1. **Length** - at least :data:`MIN_LENGTH` characters, counted after Unicode NFC
   normalization so "é" is one character however it was typed; invisible formatting
   characters (zero-width spaces, joiners, direction marks) do not count.
2. **Not only numbers** - a password made only of digits (``12345678``, or digits
   from any script) is rejected; digits mixed with other characters are fine.
3. **Not common** - the password is looked up, case-insensitively, in a local
   list of about 98,000 passwords seen most often in breaches
   (``common-passwords.txt.gz``; see ``COMMON_PASSWORDS.md`` for its source and how
   to refresh it).
4. **Not like the user's email or name** - the password is compared with the email
   address, its parts, the full name and its parts; it is rejected when it is
   nearly the same as one of them, or when its letters are only those words in any
   order, repeated or reversed (see :func:`_too_similar` and :func:`_only_own_words`).

No character classes (upper case, digits, symbols) are required. :data:`MAX_LENGTH`
is not a strength rule: it bounds the cost of hashing hostile input.
"""

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
MAX_LENGTH = 128  # bounds hashing cost for hostile input
MAX_SIMILARITY = 0.7  # SequenceMatcher ratio at or above which a password is "too similar"
COMMON_PASSWORDS_FILE = Path(__file__).with_name("common-passwords.txt.gz")

_hasher = PasswordHasher()  # library defaults follow RFC 9106 recommendations
# Verified when an account does not exist so response time does not reveal it.
_DUMMY_HASH = _hasher.hash("timing-equalisation-placeholder")
_SEPARATORS = re.compile(r"[\W_]+")


@dataclass(frozen=True)
class PasswordRule:
    key: str
    label: str  # the live checklist's wording
    message: str  # shown when a password breaks the rule


RULES = (
    PasswordRule("length", f"At least {MIN_LENGTH} characters", f"Use at least {MIN_LENGTH} characters."),
    PasswordRule("numeric", "Not only numbers", "Use more than numbers: add letters, spaces, or symbols."),
    PasswordRule("common", "Not a common password",
                 "This password is too common and easy to guess. Choose a less predictable one."),
    PasswordRule("similar", "Not like your name or email",
                 "This password is too similar to your name or email address."),
)


def _visible(text: str) -> str:
    """``text`` without invisible formatting characters (Unicode category Cf).

    Zero-width spaces and joiners, soft hyphens and direction marks change nothing on
    screen, so "pass\u200bword" is still the common password "password".
    """
    return "".join(character for character in text if unicodedata.category(character) != "Cf")


def comparison_form(text: str) -> str:
    """``text`` as passwords are compared: NFKC-normalized, invisible characters removed,
    case-folded, outer spaces removed.

    NFKC folds look-alike forms (full-width letters and digits, ligatures) into their
    plain equivalents, so "ＰＡＳＳＷＯＲＤ" is the common password "password". Only the
    comparison uses this form: the password is hashed exactly as typed.
    """
    return _visible(unicodedata.normalize("NFKC", text)).casefold().strip()


def password_length(password: str) -> int:
    """Characters in ``password``: a composed and a decomposed "é" count alike (NFC), and
    invisible formatting characters do not count."""
    return len(_visible(unicodedata.normalize("NFC", password)))


@cache
def common_passwords() -> frozenset[str]:
    """The local list of common passwords, already in :func:`comparison_form`."""
    try:
        with gzip.open(COMMON_PASSWORDS_FILE, "rt", encoding="utf-8") as handle:
            return frozenset(line.rstrip("\n") for line in handle if line.strip())
    except OSError as exc:  # missing from a build: refuse to guess rather than accept everything
        raise RuntimeError(f"The common-password list is missing or unreadable: {COMMON_PASSWORDS_FILE}") from exc


def _attribute_values(email: str | None, names: Iterable[str | None]) -> list[str]:
    """The email, its local part, the names, each of their parts, and each without separators."""
    values: list[str] = []
    for raw in (email, *(email or "").partition("@")[::2], *names):
        value = comparison_form(raw or "")
        if not value:
            continue
        values += [value, _SEPARATORS.sub("", value), *_SEPARATORS.split(value)]
    return list(dict.fromkeys(value for value in values if value))


def _too_similar(password: str, values: Iterable[str]) -> bool:
    """Whether ``password`` is nearly the same text as one of ``values``.

    Uses difflib's ratio (2 × matching characters / total characters): 1.0 for the
    same text, and :data:`MAX_SIMILARITY` (0.7) for, say, "ayesha123" against
    "ayesha". Because the ratio counts both lengths, a short part such as "ali" can
    never reach it against an 8-character password, and a long passphrase that only
    contains a name ("ayesha's garden is in bloom") passes: only passwords that are
    mostly the name or email are rejected.
    """
    candidate = comparison_form(password)
    if not candidate:
        return False
    return any(SequenceMatcher(None, candidate, value, autojunk=False).ratio() >= MAX_SIMILARITY
               for value in values)


def _letters(text: str) -> str:
    return "".join(character for character in text if character.isalpha())


def _only_own_words(password: str, values: Iterable[str]) -> bool:
    """Whether the password's letters are nothing but the user's own words.

    The words are the name's and the email's parts. Digits and symbols are ignored, and
    the words may come in any order, repeat, or be reversed: "AhmedBilal", "AyeshaAyesha",
    "Seán2024", and "kilaMahseyA" are all just the user's name. A password with any
    other letters ("ayesha loves rainy mornings") is left to :func:`_too_similar`.
    """
    letters = _letters(comparison_form(password))
    words = {_letters(value) for value in values} - {""}
    if not letters or not words:
        return False
    longest = max(map(len, words))

    def made_of_words(text: str) -> bool:
        # reachable[i]: text[:i] splits into words (the classic word-break check).
        reachable = [True] + [False] * len(text)
        for end in range(1, len(text) + 1):
            reachable[end] = any(reachable[start] and text[start:end] in words
                                 for start in range(max(0, end - longest), end))
        return reachable[-1]

    return made_of_words(letters) or made_of_words(letters[::-1])


def broken_rules(password: str, *, email: str | None = None,
                 names: Iterable[str | None] = ()) -> list[PasswordRule]:
    """The rules ``password`` breaks, in :data:`RULES` order (empty when it passes all four)."""
    compared = comparison_form(password)
    attributes = _attribute_values(email, names)
    checks = {
        "length": password_length(password) < MIN_LENGTH,
        # Outer spaces are ignored here and below, so padding cannot slip past the rule.
        "numeric": compared.isdigit(),
        "common": compared in common_passwords(),
        "similar": _too_similar(password, attributes) or _only_own_words(password, attributes),
    }
    return [rule for rule in RULES if checks[rule.key]]


def validate_password(password: str, *, email: str | None = None, full_name: str | None = None,
                      field: str = "password") -> None:
    """Raise :class:`ValidationFailed` naming every rule ``password`` breaks."""
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
