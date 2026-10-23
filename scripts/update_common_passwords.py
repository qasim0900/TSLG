"""Rebuild ``crm/security/common-passwords.txt.gz`` from a downloaded password list.

The list ships with the application, so passwords are checked on the user's
computer and never sent to an online service. To refresh it (see
``crm/security/COMMON_PASSWORDS.md``)::

    curl -fsSL -o ncsc.txt https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt
    poetry run python scripts/update_common_passwords.py ncsc.txt

Each entry is stored exactly as the policy compares passwords (NFKC-normalized,
case-folded, outer spaces removed), deduplicated and sorted. Blank entries and
entries with control characters are dropped. The output is byte-for-byte
reproducible for the same input, so a refresh shows up as a real diff.
"""

from __future__ import annotations

import argparse
import gzip
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crm.security.passwords import COMMON_PASSWORDS_FILE, comparison_form  # noqa: E402


def build(source: Path, target: Path = COMMON_PASSWORDS_FILE) -> int:
    entries: set[str] = set()
    for line in source.read_text(encoding="utf-8").splitlines():
        if any(unicodedata.category(character) == "Cc" for character in line):
            continue
        entry = comparison_form(line)
        if entry:
            entries.add(entry)
    data = "".join(f"{entry}\n" for entry in sorted(entries)).encode("utf-8")
    with target.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as packed:
        packed.write(data)
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="downloaded list, one password per line (UTF-8)")
    args = parser.parse_args()
    count = build(args.source)
    print(f"Wrote {count} passwords to {COMMON_PASSWORDS_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
