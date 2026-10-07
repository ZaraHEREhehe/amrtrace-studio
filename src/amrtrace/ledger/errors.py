"""Errors raised by the ledger. Every one of them means "nothing was written"."""


class LedgerError(Exception):
    """Base class for all ledger errors."""


class ReleaseNotFound(LedgerError):
    """The release id does not exist."""


class ReleaseNotDraft(LedgerError):
    """States can only be added to a DRAFT release; published releases are immutable."""


class InvalidReleaseTransition(LedgerError):
    """The requested release status change is not allowed (see ALLOWED_TRANSITIONS)."""


class EmptyRelease(LedgerError):
    """A release with no states cannot be validated or published."""


class DuplicateState(LedgerError):
    """The release already holds a state for this case (one state per case per release)."""


class UnknownReference(LedgerError):
    """The case, the superseded state, or the triggering change event does not exist."""


class NoStateToReview(LedgerError):
    """The case has no state in a published release, so there is nothing to review."""


class ReviewNotAllowed(LedgerError):
    """The state cannot be reviewed: wrong case, not published, or no longer the case's current state."""


class ReleaseNotPublished(LedgerError):
    """Only a published release can be exported."""
