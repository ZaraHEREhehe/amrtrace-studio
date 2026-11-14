"""Z-22: read-only release/report/run identity validation."""
import pytest

from amrtrace.api.release_identity import (
    ComparisonIdentityMismatch,
    validate_persisted_comparison,
)


def example():
    return {
        "report_id": 5,
        "change_id": "C2",
        "selective_run_id": "S2",
        "exhaustive_run_id": "E2",
        "release_id": "R2",
        "passed": True,
        "report": {
            "change_id": "C2",
            "selective_run_id": "S2",
            "exhaustive_run_id": "E2",
            "release_id": "R2",
            "passed": True,
        },
        "selective_release_id": "R2",
        "selective_change_id": "C2",
        "selective_mode": "SELECTIVE",
        "selective_status": "COMPLETE",
        "exhaustive_release_id": "R2",
        "exhaustive_change_id": "C2",
        "exhaustive_mode": "EXHAUSTIVE",
        "exhaustive_status": "COMPLETE",
    }


def test_correct_report_bound_to_release_and_both_runs():
    assert validate_persisted_comparison("R2", "C2", example()) == {
        "report_id": 5,
        "selective_run_id": "S2",
        "exhaustive_run_id": "E2",
        "comparison_passed": True,
    }


def test_baseline_without_report_is_not_a_fake_pass():
    assert validate_persisted_comparison("R1", None, None) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("release_id", "R1"),
        ("change_id", "C1"),
        ("selective_release_id", "R1"),
        ("exhaustive_release_id", "R3"),
        ("selective_change_id", "C1"),
        ("exhaustive_mode", "SELECTIVE"),
        ("selective_status", "FAILED"),
        ("passed", False),
        ("selective_run_id", "OTHER"),
    ],
)
def test_rejects_mismatch_in_persisted_comparison_or_run(field, value):
    row = example()
    row[field] = value
    with pytest.raises(ComparisonIdentityMismatch):
        validate_persisted_comparison("R2", "C2", row)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("release_id", "R1"),
        ("selective_run_id", "WRONG"),
        ("exhaustive_run_id", "WRONG"),
        ("passed", False),
    ],
)
def test_rejects_mismatch_in_json_body(field, value):
    row = example()
    row["report"][field] = value
    with pytest.raises(ComparisonIdentityMismatch):
        validate_persisted_comparison("R2", "C2", row)


def test_rejects_missing_report_body():
    row = example()
    row["report"] = None
    with pytest.raises(ComparisonIdentityMismatch):
        validate_persisted_comparison("R2", "C2", row)

