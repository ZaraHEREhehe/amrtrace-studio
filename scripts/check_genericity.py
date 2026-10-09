#!/usr/bin/env python3
"""Fail when project-specific names leak into generic engine packages."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PROTECTED_PACKAGES = (
    "evaluator",
    "deps",
    "ledger",
    "changes",
    "reeval",
)


def load_denylist(path: Path) -> tuple[str, ...]:
    # utf-8-sig also handles the BOM written by Windows PowerShell.
    lines = path.read_text(encoding="utf-8-sig").splitlines()

    terms = []
    seen = set()

    for line_number, raw in enumerate(lines, start=1):
        term = raw.strip()

        if not term or term.startswith("#"):
            continue

        key = term.casefold()

        if key in seen:
            raise ValueError(
                f"{path}:{line_number}: duplicate term {term!r}"
            )

        seen.add(key)
        terms.append(term)

    if not terms:
        raise ValueError(f"{path}: denylist is empty")

    return tuple(terms)


def pattern_for(term: str) -> re.Pattern[str]:
    # Prevent short terms such as C7 from matching inside C70 or ABC7X.
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def source_files(source_root: Path) -> tuple[Path, ...]:
    files = []

    for package in PROTECTED_PACKAGES:
        package_root = source_root / package

        if not package_root.is_dir():
            continue

        files.extend(
            path
            for path in package_root.rglob("*.py")
            if "__pycache__" not in path.parts
        )

    return tuple(sorted(files))


def scan(source_root: Path, terms: tuple[str, ...]) -> list[str]:
    violations = []
    patterns = [(term, pattern_for(term)) for term in terms]

    for path in source_files(source_root):
        lines = path.read_text(encoding="utf-8").splitlines()

        try:
            display_path = path.relative_to(source_root.parent)
        except ValueError:
            display_path = path

        for line_number, line in enumerate(lines, start=1):
            for term, pattern in patterns:
                for match in pattern.finditer(line):
                    violations.append(
                        f"{display_path.as_posix()}:{line_number}:"
                        f"{match.start() + 1}: forbidden term {term!r}"
                    )

    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=repo_root / "src" / "amrtrace",
    )
    parser.add_argument(
        "--denylist",
        type=Path,
        default=repo_root / "scripts" / "genericity_denylist.txt",
    )
    args = parser.parse_args()

    try:
        terms = load_denylist(args.denylist)
        files = source_files(args.source_root)

        if not files:
            raise ValueError(
                f"No protected Python files found under {args.source_root}"
            )

        violations = scan(args.source_root, terms)

    except (OSError, ValueError) as exc:
        print(f"GENERICITY GUARD ERROR: {exc}", file=sys.stderr)
        return 2

    if violations:
        print(
            f"GENERICITY GUARD FAILED: {len(violations)} violation(s)",
            file=sys.stderr,
        )

        for violation in violations:
            print(violation, file=sys.stderr)

        return 1

    print(
        "Genericity guard passed: "
        f"{len(files)} protected Python files checked "
        f"against {len(terms)} denylist terms."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
