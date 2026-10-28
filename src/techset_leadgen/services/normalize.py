"""Normalization and validation of identity fields used for duplicate detection.

Nothing here performs network access: URLs and domains are parsed, never fetched.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from urllib.parse import quote, unquote, urlsplit
from zoneinfo import available_timezones

_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TLD = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")
_EMAIL_LOCAL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}$")
_PHONE = re.compile(r"^\+?[0-9 ().-]{5,40}$")
_SPACES = re.compile(r"\s+")
# "javascript:alert(1)" or "mailto:x@y.io"; a digit after the colon is a port ("example.com:8080").
_OTHER_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:(?!\d)", re.IGNORECASE)
# Dotted initialisms such as "S.L." or "S.A.R.L." are compared without their dots.
_INITIALISM_DOT = re.compile(r"\b([a-z])\.(?=[a-z]\b)")
_LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "plc", "corp", "corporation", "co", "company",
    "gmbh", "ag", "kg", "sa", "sas", "sarl", "sl", "slu", "bv", "nv", "pvt", "private", "pte", "pty", "srl",
    "oy", "ab", "llp", "lp",
}
_TIMEZONES = frozenset(available_timezones())


class InvalidValue(ValueError):
    """A value that cannot be normalized; the message is safe to show to users."""


def clean_text(value: str | None, *, max_length: int | None = None) -> str | None:
    """Trim, collapse internal whitespace runs in single-line text, and map blanks to None."""
    if value is None:
        return None
    cleaned = _SPACES.sub(" ", value).strip()
    if not cleaned:
        return None
    if max_length is not None and len(cleaned) > max_length:
        raise InvalidValue(f"Use at most {max_length} characters.")
    return cleaned


def clean_multiline(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = value.replace("\r\n", "\n").strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise InvalidValue(f"Use at most {max_length} characters.")
    return cleaned


def normalize_hostname(value: str) -> str:
    host = value.strip().lower().rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidValue("Enter a valid domain, such as example.com.") from exc
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise InvalidValue("Use a domain name, not an IP address.")
    labels = host.split(".")
    if (
        len(host) > 253
        or len(labels) < 2
        or not all(_LABEL.match(label) for label in labels)
        or not _TLD.match(labels[-1])
    ):
        raise InvalidValue("Enter a valid domain, such as example.com.")
    return host


def normalize_domain(value: str | None) -> str | None:
    """``https://www.Example.com/about`` -> ``example.com``."""
    if value is None or not value.strip():
        return None
    raw = value.strip()
    if "://" not in raw:
        raw = "http://" + raw
    try:
        host = urlsplit(raw).hostname or ""
    except ValueError as exc:
        raise InvalidValue("Enter a valid domain, such as example.com.") from exc
    host = normalize_hostname(host)
    if host.startswith("www.") and host.count(".") >= 2:
        host = host[4:]
    return host


def normalize_url(value: str | None, *, max_length: int = 500) -> str | None:
    """Accept only absolute http(s) URLs with a valid host (blocks ``javascript:`` and friends)."""
    if value is None or not value.strip():
        return None
    raw = value.strip()
    if "://" not in raw:
        if _OTHER_SCHEME.match(raw):
            raise InvalidValue("Enter a web address starting with http:// or https://.")
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        host = parts.hostname
    except ValueError as exc:
        raise InvalidValue("Enter a valid web address.") from exc
    if parts.scheme.lower() not in {"http", "https"} or not host:
        raise InvalidValue("Enter a web address starting with http:// or https://.")
    if parts.username or parts.password:
        raise InvalidValue("Web addresses must not contain credentials.")
    normalize_hostname(host)
    if len(raw) > max_length:
        raise InvalidValue(f"Use at most {max_length} characters.")
    return raw


def normalize_linkedin_url(value: str | None) -> str | None:
    url = normalize_url(value, max_length=300)
    if url is None:
        return None
    host = (urlsplit(url).hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        raise InvalidValue("Enter a linkedin.com profile address.")
    return url


_PROFILE_SLUG = re.compile(r"^[\w-]{2,100}$")
_PROFILE_NOT_PERSON = {
    "company": "This is a company page, not a person's profile.",
    "school": "This is a school page, not a person's profile.",
    "showcase": "This is a showcase page, not a person's profile.",
    "groups": "This is a group, not a person's profile.",
    "jobs": "This is a job posting, not a person's profile.",
    "posts": "This is a post, not a person's profile.",
    "feed": "This is a post, not a person's profile.",
    "sales": "Sales Navigator links cannot be matched to a profile. Open the person's public profile and copy "
             "that address (linkedin.com/in/…).",
    "talent": "Recruiter links cannot be matched to a profile. Copy the public profile address (linkedin.com/in/…).",
}


def linkedin_profile(value: str | None) -> tuple[str, str]:
    """``(key, url)`` identifying one LinkedIn member profile.

    Policy: the identity is the first path segment after ``/in/`` (or the five
    segments of an old ``/pub/`` address), compared case-insensitively. The
    subdomain (``www``, ``uk``, ``m``), scheme, query string, fragment, and any
    deeper path (``/details/experience``, ``/recent-activity``, a locale such as
    ``/en``) are presentation only and dropped. Query parameters never identify a
    member on these addresses (they are tracking or locale hints). Short links
    (``lnkd.in``) and Sales Navigator/Recruiter IDs cannot be resolved offline and
    are rejected with an explanation rather than guessed at.

    ``key`` (``in/jane-doe-1a2b``) is unique per prospect; ``url`` is the
    canonical ``https://www.linkedin.com/...`` address to open.
    """
    raw = (value or "").strip().strip("<>\"'").strip()
    if not raw:
        raise InvalidValue("Enter a LinkedIn profile address.")
    if len(raw) > 500:
        raise InvalidValue("This address is too long to be a LinkedIn profile.")
    if "://" not in raw:
        if _OTHER_SCHEME.match(raw):
            raise InvalidValue("Enter a LinkedIn profile address, such as linkedin.com/in/jane-doe.")
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise InvalidValue("Enter a valid LinkedIn profile address.") from exc
    if parts.scheme.lower() not in {"http", "https"} or parts.username or parts.password:
        raise InvalidValue("Enter a LinkedIn profile address, such as linkedin.com/in/jane-doe.")
    if host == "lnkd.in":
        raise InvalidValue("Short links (lnkd.in) cannot be checked. Open the link and copy the profile address.")
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        raise InvalidValue("This is not a linkedin.com address.")
    segments = [unquote(segment) for segment in parts.path.split("/") if segment]
    kind = segments[0].lower() if segments else ""
    if kind in _PROFILE_NOT_PERSON:
        raise InvalidValue(_PROFILE_NOT_PERSON[kind])
    if kind == "in" and len(segments) >= 2:
        identity = [segments[1]]
    elif kind == "pub" and len(segments) >= 5:
        identity = segments[1:5]
    else:
        raise InvalidValue("This is not a profile address. Profile addresses look like linkedin.com/in/jane-doe.")
    identity = [unicodedata.normalize("NFC", part).lower() for part in identity]
    if not all(_PROFILE_SLUG.match(part) for part in identity):
        raise InvalidValue("The profile name in this address contains characters LinkedIn does not use.")
    path = "/".join([kind, *identity])
    return path, "https://www.linkedin.com/" + quote(path, safe="/-_") + "/"


def normalize_email(value: str | None) -> str | None:
    """Lower-case and validate a business email address. Dots and plus tags are kept."""
    if value is None or not value.strip():
        return None
    raw = value.strip()
    if len(raw) > 254 or raw.count("@") != 1:
        raise InvalidValue("Enter a valid email address.")
    local, _, domain = raw.rpartition("@")
    if not _EMAIL_LOCAL.match(local) or local.startswith(".") or local.endswith(".") or ".." in local:
        raise InvalidValue("Enter a valid email address.")
    try:
        domain = normalize_hostname(domain)
    except InvalidValue as exc:
        raise InvalidValue("Enter a valid email address.") from exc
    return f"{local.lower()}@{domain}"


def email_lookup_key(value: str) -> str:
    """Best-effort key for lookups of user-typed emails that are not validated (e.g. sign-in)."""
    return value.strip().lower()[:254]


def normalize_company_name(name: str) -> str:
    """Comparison key for possible-duplicate hints. Never used as a unique identifier."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").casefold()
    text = _INITIALISM_DOT.sub(r"\1", text)
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)[:200] or name.strip().casefold()[:200]


def normalize_phone(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    raw = _SPACES.sub(" ", value.strip())
    if not _PHONE.match(raw) or sum(ch.isdigit() for ch in raw) < 5:
        raise InvalidValue("Enter a valid phone number.")
    return raw


def normalize_timezone(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    if value.strip() not in _TIMEZONES:
        raise InvalidValue("Choose a time zone from the list, such as Europe/London.")
    return value.strip()


def normalize_tags(values: list[str] | str | None, *, max_items: int = 20, max_length: int = 40) -> list[str]:
    if values is None:
        return []
    items = values.split(",") if isinstance(values, str) else values
    seen: dict[str, str] = {}
    for item in items:
        tag = clean_text(item, max_length=max_length)
        if tag and tag.casefold() not in seen:
            seen[tag.casefold()] = tag
    if len(seen) > max_items:
        raise InvalidValue(f"Use at most {max_items} entries.")
    return list(seen.values())


def is_valid_timezone(value: str) -> bool:
    return value in _TIMEZONES


def all_timezones() -> list[str]:
    return sorted(_TIMEZONES)
