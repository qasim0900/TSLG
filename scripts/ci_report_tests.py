from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_SHOWN = 10


def _escape(text: str, *, property_value: bool = False) -> str:
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if property_value else text


def main(report: str) -> int:
    path = Path(report)
    if not path.is_file():
        print(f"::error title=No test report::pytest did not write {report} (it may have crashed).")
        return 1
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    failures: list[tuple[str, str]] = []
    for case in cases:
        for kind in ("failure", "error"):
            node = case.find(kind)
            if node is not None:
                name = f"{case.get('classname', '')}::{case.get('name', '')}"
                detail = f"{node.get('message') or ''}\n{node.text or ''}".strip()
                failures.append((name, detail))
    for name, detail in failures[:_SHOWN]:
        print(f"::error title={_escape(name, property_value=True)}::{_escape(detail[-3000:])}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = [f"## Tests on Windows: {len(cases) - len(failures)} passed, {len(failures)} failed", ""]
        for name, detail in failures:
            lines += [f"### `{name}`", "```", detail[-6000:], "```", ""]
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
    print(f"{len(cases)} tests, {len(failures)} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "test-results.xml"))

