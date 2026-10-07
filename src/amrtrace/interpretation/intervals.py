"""Interval arithmetic for interpretation rules. Generic and pure.

A category is an interval of measured values; a measurement (exact or censored) is an interval too.
  - touched_categories: which categories a measurement could belong to (ADR-002 amendment 1)
  - differing_regions: where two versions of a rule give different answers (used by the table differ)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .models import Category, InterpretationRule

INF = math.inf


@dataclass(frozen=True)
class Interval:
    lo: float
    hi: float
    lo_closed: bool
    hi_closed: bool

    def contains(self, x: float) -> bool:
        above = x > self.lo or (self.lo_closed and x == self.lo)
        below = x < self.hi or (self.hi_closed and x == self.hi)
        return above and below

    def intersects(self, other: "Interval") -> bool:
        lo, lo_closed = max((self.lo, self.lo_closed), (other.lo, other.lo_closed), key=lambda t: (t[0], not t[1]))
        hi, hi_closed = min((self.hi, self.hi_closed), (other.hi, other.hi_closed), key=lambda t: (t[0], not t[1]))
        if lo < hi:
            return True
        return lo == hi and lo_closed and hi_closed


def interval_from_comparison(op: str, value: float) -> Interval:
    if op == "<=":
        return Interval(-INF, value, False, True)
    if op == "<":
        return Interval(-INF, value, False, False)
    if op == "==":
        return Interval(value, value, True, True)
    if op == ">=":
        return Interval(value, INF, True, False)
    if op == ">":
        return Interval(value, INF, False, False)
    raise ValueError(f"unknown comparison {op!r}")


def category_interval(category: Category) -> Interval:
    return interval_from_comparison(category.op, category.value)


def measurement_interval(value: float, sign: Optional[str]) -> Interval:
    """The values a measurement allows: '==' x is exactly x, '<=' x is up to x, and so on."""
    return interval_from_comparison(sign or "==", value)


def touched_categories(rule: InterpretationRule, value: float, sign: Optional[str]) -> list[str]:
    """Labels of every category the measurement could fall in, in the order the rule lists them."""
    measured = measurement_interval(value, sign)
    return [c.label for c in rule.categories if category_interval(c).intersects(measured)]


def label_at(rule: InterpretationRule, x: float) -> Optional[str]:
    """The category label at one exact value, or None if the value falls in a gap."""
    for category in rule.categories:
        if category_interval(category).contains(x):
            return category.label
    return None


def categories_overlap(categories) -> bool:
    intervals = [category_interval(c) for c in categories]
    return any(intervals[i].intersects(intervals[j]) for i in range(len(intervals)) for j in range(i + 1, len(intervals)))


def differing_regions(old: InterpretationRule, new: InterpretationRule) -> Optional[list[list[float]]]:
    """Closed [low, high] intervals covering every value that is classified differently by the two rules.

    Open ends are widened to closed ones, so the answer may include a boundary value that did not change: it never
    misses one that did (over-selecting is the safe direction, plan rule 6). Returns None when a difference
    reaches infinity, because that cannot be written as a finite interval: callers then treat the whole rule as changed.
    """
    points = sorted({c.value for rule in (old, new) for c in rule.categories})
    if not points:
        return []
    probes: list[tuple[float, tuple[float, float]]] = []     # (a value in the region, (low, high) of the region)
    probes.append((points[0] - 1, (-INF, points[0])))
    for i, p in enumerate(points):
        probes.append((p, (p, p)))
        upper = points[i + 1] if i + 1 < len(points) else INF
        probes.append((p + 1 if upper == INF else (p + upper) / 2, (p, upper)))
    differing = [span for x, span in probes if label_at(old, x) != label_at(new, x)]
    if any(math.isinf(lo) or math.isinf(hi) for lo, hi in differing):
        return None
    merged: list[list[float]] = []
    for lo, hi in sorted(differing):
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return merged
