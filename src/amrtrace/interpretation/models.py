"""Interpretation tables as plain objects (plan section 5.5). Generic: nothing here names a drug, standard or edition.

A table is a set of rules. A rule says: for this (standard, organism, antibiotic, method), a measured value falls in
the susceptible, intermediate or resistant category according to these comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

LABELS = ("susceptible", "intermediate", "resistant")
OPS = ("<=", "<", "==", ">=", ">")


def _norm(text: str) -> str:
    return " ".join(str(text).split()).lower()


def make_rule_key(standard: str, organism: str, antibiotic: str, method: str) -> str:
    """Canonical key of a rule: the four matching fields, trimmed and lower-cased, joined with '|'."""
    return "|".join(_norm(x) for x in (standard, organism, antibiotic, method))


@dataclass(frozen=True)
class Category:
    label: str          # susceptible | intermediate | resistant
    op: str             # <= < == >= >
    value: float

    def to_dict(self) -> dict:
        return {"label": self.label, "op": self.op, "value": self.value}


@dataclass(frozen=True)
class InterpretationRule:
    interpretation_version: str
    standard: str
    organism: str
    antibiotic: str
    method: str
    categories: tuple[Category, ...]

    @property
    def rule_key(self) -> str:
        return make_rule_key(self.standard, self.organism, self.antibiotic, self.method)

    def to_dict(self) -> dict:
        """The shape handed to the evaluator in CaseInputs.interpretation_rules (and stored in the database)."""
        return {
            "rule_key": self.rule_key,
            "interpretation_version": self.interpretation_version,
            "standard": self.standard,
            "organism": self.organism,
            "antibiotic": self.antibiotic,
            "method": self.method,
            "categories": [c.to_dict() for c in self.categories],
        }


@dataclass(frozen=True)
class InterpretationTable:
    interpretation_version: str
    standard: str
    rules: tuple[InterpretationRule, ...]

    def by_key(self) -> dict[str, InterpretationRule]:
        return {r.rule_key: r for r in self.rules}


def find_rules(
    rules: Iterable[InterpretationRule],
    *,
    standard: Optional[str],
    organism: str,
    antibiotic: str,
    method: str = "MIC",
) -> list[InterpretationRule]:
    """Rules that apply to a case: all four fields match (case and spacing ignored). A case with no standard
    matches nothing, so a table never touches a result that does not say which standard it used."""
    if not standard:
        return []
    wanted = make_rule_key(standard, organism, antibiotic, method)
    return sorted((r for r in rules if r.rule_key == wanted), key=lambda r: r.interpretation_version)


def rules_as_dicts(rules: Iterable[InterpretationRule]) -> tuple[dict, ...]:
    return tuple(r.to_dict() for r in rules)


def rule_from_dict(data: dict[str, Any]) -> InterpretationRule:
    return InterpretationRule(
        interpretation_version=data["interpretation_version"],
        standard=data["standard"],
        organism=data["organism"],
        antibiotic=data["antibiotic"],
        method=data["method"],
        categories=tuple(Category(c["label"], c["op"], c["value"]) for c in data["categories"]),
    )
