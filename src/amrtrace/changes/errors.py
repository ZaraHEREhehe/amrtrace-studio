"""Errors raised by the change registry. Every one of them means "nothing was written"."""

from __future__ import annotations


class ChangeError(Exception):
    """Base class for all change-registry errors."""


class InvalidChangeEvent(ChangeError):
    """The change event is malformed or refers to things that do not exist. .problems lists every issue found."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        shown = "; ".join(self.problems[:5]) + ("; ..." if len(self.problems) > 5 else "")
        super().__init__(f"invalid change event ({len(self.problems)} problem(s)): {shown}")


class ChangeTypeAlreadyRegistered(ChangeError):
    """The change type (or its differ) is already registered; registrations are never replaced."""


class DuplicateChange(ChangeError):
    """A change event with this id is already registered."""


class ChangeNotFound(ChangeError):
    """No change event with this id."""


class DuplicateVersion(ChangeError):
    """This (node_type, node_id, version) is already registered; versions are immutable."""


class VersionNotFound(ChangeError):
    """No such version node."""
