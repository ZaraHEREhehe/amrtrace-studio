"""Record, in every fixture, the commit it was written on top of (task I-07, decision D-10).

Run this once, just before committing the fixtures:   python tests/oracle/stamp_fixtures.py
It replaces STAMP_ME with the current HEAD. A file cannot contain the hash of the commit that adds it, so the stamp
names the commit before it; git history then shows the fixtures were committed before any run of the selector.
    --check   only report fixtures that are not stamped (exit code 1 if any)
"""

import pathlib
import re
import subprocess
import sys

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
PLACEHOLDER = re.compile(r"^(authored_on_base_commit:\s*)STAMP_ME\b", re.M)
STAMPED = re.compile(r"^authored_on_base_commit:\s*[0-9a-f]{40}\b", re.M)


def main(argv) -> int:
    paths = sorted(FIXTURES.glob("*.yaml"))
    if "--check" in argv:
        unstamped = [p.name for p in paths if not STAMPED.search(p.read_text(encoding="utf-8"))]
        print("unstamped:", ", ".join(unstamped) if unstamped else "none")
        return 1 if unstamped else 0
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    changed = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        new = PLACEHOLDER.sub(lambda m: m.group(1) + head, text)
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed += 1
    print(f"stamped {changed} of {len(paths)} fixtures with {head}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
