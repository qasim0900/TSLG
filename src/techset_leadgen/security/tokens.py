"""Opaque random tokens; only their SHA-256 digests are stored.

Tokens carry 256 bits of randomness, so a plain digest cannot be reversed or
guessed, and every desktop computer can verify one without a shared secret.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_match(expected: str, supplied: str | None) -> bool:
    return bool(supplied) and hmac.compare_digest(expected.encode(), (supplied or "").encode())
