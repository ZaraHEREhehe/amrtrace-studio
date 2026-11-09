# the change detection engine: watchers compare two snapshots and draft typed changes for a person to apply (A-13)

from __future__ import annotations

from .drafts import (
    APPLIED,
    DISMISSED,
    PENDING,
    CheckResult,
    DraftAlreadyDecided,
    DraftError,
    DraftNotFound,
    StoredDraft,
    apply_draft,
    detect_changes,
    dismiss_draft,
    get_draft,
    list_drafts,
    run_check,
)
from .evidence_watcher import EvidenceWatcher, ast_watcher, genotype_watcher
from .mapping_watcher import MappingWatcher
from .snapshot import Snapshot, SnapshotError, open_snapshot
from .watchers import DraftChange, Watcher, WatcherRegistry


# the watchers shipped with the project; a new source of change is one more line here
def default_watchers() -> WatcherRegistry:
    registry = WatcherRegistry()
    for watcher in (ast_watcher(), genotype_watcher(), MappingWatcher()):
        registry.register(watcher)
    return registry


__all__ = [
    "APPLIED",
    "DISMISSED",
    "PENDING",
    "CheckResult",
    "DraftAlreadyDecided",
    "DraftChange",
    "DraftError",
    "DraftNotFound",
    "EvidenceWatcher",
    "MappingWatcher",
    "Snapshot",
    "SnapshotError",
    "StoredDraft",
    "Watcher",
    "WatcherRegistry",
    "apply_draft",
    "ast_watcher",
    "default_watchers",
    "detect_changes",
    "dismiss_draft",
    "genotype_watcher",
    "get_draft",
    "list_drafts",
    "open_snapshot",
    "run_check",
]
