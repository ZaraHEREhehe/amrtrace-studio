"""Check persisted comparison-to-release identity for read-only release views."""
from __future__ import annotations

from collections.abc import Mapping


class ComparisonIdentityMismatch(ValueError):
    """A persisted report, its release, or its runs disagree."""


def validate_persisted_comparison(
    release_id: str, change_id: str | None, row: Mapping | None,
) -> dict | None:
    """Return validated report metadata; missing historical reports remain explicit."""
    if row is None:
        return None

    raw = row.get("report")
    if not isinstance(raw, dict):
        raise ComparisonIdentityMismatch("Stored comparison body is missing or malformed")

    expected = {
        "release_id": release_id,
        "change_id": row.get("change_id"),
        "selective_run_id": row.get("selective_run_id"),
        "exhaustive_run_id": row.get("exhaustive_run_id"),
    }
    if any(raw.get(key) != value for key, value in expected.items()):
        raise ComparisonIdentityMismatch(
            "Stored comparison body does not match the persisted release and runs"
        )
    if row.get("release_id") != release_id or (
        change_id is not None and row.get("change_id") != change_id
    ):
        raise ComparisonIdentityMismatch(
            "Stored comparison belongs to a different release or change"
        )
    if not row.get("selective_run_id") or not row.get("exhaustive_run_id"):
        raise ComparisonIdentityMismatch("Stored comparison has incomplete run references")

    for prefix, mode in (("selective", "SELECTIVE"), ("exhaustive", "EXHAUSTIVE")):
        if (
            row.get(f"{prefix}_release_id") != release_id
            or row.get(f"{prefix}_change_id") != row.get("change_id")
            or row.get(f"{prefix}_mode") != mode
            or row.get(f"{prefix}_status") != "COMPLETE"
        ):
            raise ComparisonIdentityMismatch(
                f"Stored {prefix} run belongs to another release or change"
            )

    if type(row.get("passed")) is not bool or raw.get("passed") is not row.get("passed"):
        raise ComparisonIdentityMismatch(
            "Stored comparison pass flag does not match its report"
        )

    return {
        "report_id": row["report_id"],
        "selective_run_id": row["selective_run_id"],
        "exhaustive_run_id": row["exhaustive_run_id"],
        "comparison_passed": row["passed"],
    }

