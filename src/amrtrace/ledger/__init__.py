"""Append-only evidence ledger (task I-02).

Typical use, inside a transaction the caller controls:

    create_release(conn, "R2", {...version vector...}, triggered_by_change_id="CHG-0001")
    append_case_state(conn, case_id=..., release_id="R2", state_code=..., explanation={...},
                      verification_status="STATE_CHANGED", ...)
    validate_release(conn, "R2")
    publish_release(conn, "R2", verification_level="SELECTIVE")   # or EXHAUSTIVE after a passing comparison (I-27)
    load_later_release(conn, "R2", {...}, states)   # a whole later release, each state superseding the last
    get_state_as_of(conn, case_id, "R1")  # reconstruct what was believed at R1

There is deliberately no function that updates or deletes a state.
"""

from .errors import (
    DuplicateState,
    EmptyRelease,
    InvalidReleaseTransition,
    LedgerError,
    PublicationRefused,
    ReleaseNotDraft,
    ReleaseNotFound,
    UnknownReference,
)
from .publication import (
    LEVEL_EXHAUSTIVE,
    LEVEL_SELECTIVE,
    VERIFICATION_LEVELS,
    FailedAudit,
    ReleaseVerification,
    check_publication,
    failed_audits,
    release_binding,
    release_verification,
    verification_label,
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
from .verification import (
    REVIEW_STATUSES,
    ReviewQueueItem,
    ReviewQueuePage,
    ReviewStatus,
    get_review_status,
    list_review_queue,
    review_status_for,
)

__all__ = [
    "REVIEW_ACTIONS", "ReviewEvent", "add_review", "get_reviews", "get_latest_review", "get_current_correction", "export_as_of", "export_json", "snapshot_hash", "NoStateToReview", "ReviewNotAllowed", "ReleaseNotPublished",
    "ALLOWED_TRANSITIONS", "VERIFICATION_STATUSES",
    "CaseStateRecord", "Release", "BaselineState", "LoadReport", "load_baseline_release", "load_later_release",
    "LedgerError", "ReleaseNotFound", "ReleaseNotDraft", "InvalidReleaseTransition",
    "EmptyRelease", "DuplicateState", "UnknownReference", "PublicationRefused", "check_publication", "release_binding",
    "LEVEL_SELECTIVE", "LEVEL_EXHAUSTIVE", "VERIFICATION_LEVELS", "ReleaseVerification", "FailedAudit",
    "release_verification", "failed_audits", "verification_label",
    "create_release", "get_release", "list_releases", "validate_release", "publish_release",
    "block_release", "fail_release",
    "append_case_state", "get_state", "get_history", "get_state_as_of", "get_current_state",
    "REVIEW_STATUSES", "ReviewStatus", "ReviewQueueItem", "ReviewQueuePage",
    "review_status_for", "get_review_status", "list_review_queue",
]
