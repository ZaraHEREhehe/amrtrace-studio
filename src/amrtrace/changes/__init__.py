"""Change registry (task I-05): change types and their differs, version nodes, and typed change events.

    registry   which change types exist, and which have a differ        (generic, never edited for a new type)
    versions   register_version / get_version / list_versions            (versions are immutable)
    events     register_change_event / get_change_event / list_change_events
    validation validate_change_event: shape, existence of named versions, version ordering

Nothing is activated without a typed, validated event. The application service that turns an event into an
impact set is a later task (I-08).
"""

from .builtin import BUILTIN_CHANGE_TYPES, register_builtin_types
from .errors import (
    ChangeError,
    ChangeNotFound,
    ChangeTypeAlreadyRegistered,
    DuplicateChange,
    DuplicateVersion,
    InvalidChangeEvent,
    VersionNotFound,
)
from .events import get_change_event, list_change_events, register_change_event
from .registry import ChangeTypeRegistry, default_registry, register_change_type, register_differ
from .types import ChangeDiffer, ChangedEntity, ChangeEvent, ChangeEventRecord, VersionNode
from .validation import validate_against_database, validate_change_event, validate_shape
from .versions import get_version, list_versions, register_version, version_exists

register_builtin_types(default_registry)

__all__ = [
    "BUILTIN_CHANGE_TYPES", "register_builtin_types",
    "ChangeError", "InvalidChangeEvent", "ChangeTypeAlreadyRegistered", "DuplicateChange", "ChangeNotFound",
    "DuplicateVersion", "VersionNotFound",
    "ChangeTypeRegistry", "default_registry", "register_change_type", "register_differ",
    "ChangeDiffer", "ChangedEntity", "ChangeEvent", "ChangeEventRecord", "VersionNode",
    "validate_shape", "validate_against_database", "validate_change_event",
    "register_version", "get_version", "version_exists", "list_versions",
    "register_change_event", "get_change_event", "list_change_events",
]
