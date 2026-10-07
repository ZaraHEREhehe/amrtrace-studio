"""Append-only evidence ledger (task I-02).

Typical use, inside a transaction the caller controls:

    create_release(conn, "R2", {...version vector...}, triggered_by_change_id="CHG-0001")
    append_case_state(conn, case_id=..., release_id="R2", state_code=..., explanation={...},
                      verification_status="STATE_CHANGED", ...)
    validate_release(conn, "R2")          # after the equivalence check passes
    publish_release(conn, "R2")
    load_later_release(conn, "R2", {...}, states)   # a whole later release, each state superseding the last
    get_state_as_of(conn, case_id, "R1")  # reconstruct what was believed at R1

There is deliberately no function that updates or deletes a state.
"""

from .errors import (
    DuplicateState,
    EmptyRelease,
    InvalidReleaseTransition,
    LedgerError,
    ReleaseNotDraft,
    ReleaseNotFound,
    UnknownReference,
)
from .releases import (
    ALLOWED_TRANSITIONS,
    block_release,
    create_release,
    fail_release,
    get_release,
    list_releases,
    publish_release,
    validate_release,
)
from .states import (
    VERIFICATION_STATUSES,
    append_case_state,
    get_current_state,
    get_history,
    get_state,
    get_state_as_of,
)
from .load_release import BaselineState, LoadReport, load_baseline_release, load_later_release
from .models import CaseStateRecord, Release
from .review import REVIEW_ACTIONS, ReviewEvent, add_review, get_current_correction, get_latest_review, get_reviews
from .export import export_as_of, export_json, snapshot_hash
from .errors import NoStateToReview, ReleaseNotPublished, ReviewNotAllowed

__all__ = [
    "REVIEW_ACTIONS", "ReviewEvent", "add_review", "get_reviews", "get_latest_review", "get_current_correction", "export_as_of", "export_json", "snapshot_hash", "NoStateToReview", "ReviewNotAllowed", "ReleaseNotPublished",
    "ALLOWED_TRANSITIONS", "VERIFICATION_STATUSES",
    "CaseStateRecord", "Release", "BaselineState", "LoadReport", "load_baseline_release", "load_later_release",
    "LedgerError", "ReleaseNotFound", "ReleaseNotDraft", "InvalidReleaseTransition",
    "EmptyRelease", "DuplicateState", "UnknownReference",
    "create_release", "get_release", "list_releases", "validate_release", "publish_release",
    "block_release", "fail_release",
    "append_case_state", "get_state", "get_history", "get_state_as_of", "get_current_state",
]
