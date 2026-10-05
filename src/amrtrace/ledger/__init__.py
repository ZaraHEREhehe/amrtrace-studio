"""Append-only evidence ledger (task I-02).

Typical use, inside a transaction the caller controls:

    create_release(conn, "R2", {...version vector...}, triggered_by_change_id="CHG-0001")
    append_case_state(conn, case_id=..., release_id="R2", state_code=..., explanation={...},
                      verification_status="STATE_CHANGED", ...)
    validate_release(conn, "R2")          # after the equivalence check passes
    publish_release(conn, "R2")
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
from .models import CaseStateRecord, Release

__all__ = [
    "ALLOWED_TRANSITIONS", "VERIFICATION_STATUSES",
    "CaseStateRecord", "Release",
    "LedgerError", "ReleaseNotFound", "ReleaseNotDraft", "InvalidReleaseTransition",
    "EmptyRelease", "DuplicateState", "UnknownReference",
    "create_release", "get_release", "list_releases", "validate_release", "publish_release",
    "block_release", "fail_release",
    "append_case_state", "get_state", "get_history", "get_state_as_of", "get_current_state",
]
