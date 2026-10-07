"""Read an interpretation table from a YAML data file and check it. Every problem is reported together.

    interpretation_version: <VERSION_ID>
    standard: <standard name>
    rules:
      - organism: <organism>
        antibiotic: <drug>
        method: MIC
        categories:
          - {label: susceptible, op: "<=", value: 2}
"""

from __future__ import annotations

import numbers
from typing import Any

import yaml

from .intervals import categories_overlap
from .models import LABELS, OPS, Category, InterpretationRule, InterpretationTable, make_rule_key


class InvalidTable(Exception):
    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("invalid interpretation table: " + "; ".join(self.problems[:6]) + ("; ..." if len(self.problems) > 6 else ""))


def _blank(x) -> bool:
    return not isinstance(x, str) or not x.strip()


def parse_table(data: Any) -> InterpretationTable:
    problems: list[str] = []
    if not isinstance(data, dict):
        raise InvalidTable(["the table must be a mapping with interpretation_version, standard and rules"])
    version, standard, raw_rules = data.get("interpretation_version"), data.get("standard"), data.get("rules")
    if _blank(version):
        problems.append("interpretation_version must be a non-empty string")
    if _blank(standard):
        problems.append("standard must be a non-empty string")
    if not isinstance(raw_rules, list) or not raw_rules:
        problems.append("rules must be a non-empty list")
        raise InvalidTable(problems)

    rules, seen = [], set()
    for i, raw in enumerate(raw_rules):
        label = f"rules[{i}]"
        if not isinstance(raw, dict):
            problems.append(f"{label}: must be a mapping")
            continue
        for field in ("organism", "antibiotic", "method"):
            if _blank(raw.get(field)):
                problems.append(f"{label}: {field} must be a non-empty string")
        raw_categories = raw.get("categories")
        if not isinstance(raw_categories, list) or not raw_categories:
            problems.append(f"{label}: categories must be a non-empty list")
            continue
        categories = []
        for j, c in enumerate(raw_categories):
            where = f"{label}.categories[{j}]"
            if not isinstance(c, dict):
                problems.append(f"{where}: must be a mapping")
                continue
            if c.get("label") not in LABELS:
                problems.append(f"{where}: label must be one of {', '.join(LABELS)}")
            if c.get("op") not in OPS:
                problems.append(f"{where}: op must be one of {', '.join(OPS)}")
            value = c.get("value")
            if not isinstance(value, numbers.Real) or isinstance(value, bool):
                problems.append(f"{where}: value must be a number")
            if c.get("label") in LABELS and c.get("op") in OPS and isinstance(value, numbers.Real) and not isinstance(value, bool):
                categories.append(Category(c["label"], c["op"], value))
        if len(categories) == len(raw_categories):
            if categories_overlap(categories):
                problems.append(f"{label}: categories overlap, so one measurement could belong to two of them")
            if not any(_blank(raw.get(f)) for f in ("organism", "antibiotic", "method")) and not _blank(standard):
                key = make_rule_key(standard, raw["organism"], raw["antibiotic"], raw["method"])
                if key in seen:
                    problems.append(f"{label}: duplicate rule for {key}")
                seen.add(key)
                if not _blank(version):
                    rules.append(InterpretationRule(version, standard, raw["organism"], raw["antibiotic"], raw["method"], tuple(categories)))
    if problems:
        raise InvalidTable(problems)
    return InterpretationTable(version, standard, tuple(rules))


def load_table(path: str) -> InterpretationTable:
    with open(path, encoding="utf-8") as handle:
        return parse_table(yaml.safe_load(handle))
