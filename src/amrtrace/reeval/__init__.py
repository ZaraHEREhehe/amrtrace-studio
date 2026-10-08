"""Selective re-evaluation (task I-09, engine.py) and the exhaustive comparator (task I-10, compare.py)."""

from .compare import (
    AlreadyCompared,
    AxisResult,
    ComparisonFailed,
    EquivalenceReport,
    GateError,
    Mismatch,
    NoSelectiveRun,
    compare_with_exhaustive,
    gate_release,
    stored_report,
)
from .engine import (
    AlreadyReevaluated,
    CorrectionNotice,
    InputsMismatch,
    NoImpactSet,
    ReevalReport,
    ReevaluationError,
    ReevaluationFailed,
    reevaluate,
)

__all__ = [
    "AlreadyCompared", "AlreadyReevaluated", "AxisResult", "ComparisonFailed", "CorrectionNotice",
    "EquivalenceReport", "GateError", "InputsMismatch", "Mismatch", "NoImpactSet", "NoSelectiveRun", "ReevalReport",
    "ReevaluationError", "ReevaluationFailed", "compare_with_exhaustive", "gate_release", "reevaluate",
    "stored_report",
]
