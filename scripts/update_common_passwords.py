from __future__ import annotations

import argparse
import gzip
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from techset_leadgen.security.passwords import COMMON_PASSWORDS_FILE, comparison_form


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
    parser = argparse.ArgumentParser(description='Rebuild ``crm/security/common-passwords.txt.gz`` from a downloaded password list.')
    parser.add_argument("source", type=Path, help="downloaded list, one password per line (UTF-8)")
    args = parser.parse_args()
    count = build(args.source)
    print(f"Wrote {count} passwords to {COMMON_PASSWORDS_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

