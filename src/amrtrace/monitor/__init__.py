# the change detection engine: watchers compare two snapshots and draft typed changes for a person to apply (A-13)

from __future__ import annotations

from .alerts import (
    ACKNOWLEDGED,
    OPEN,
    Alert,
    AlertAlreadyAcknowledged,
    AlertError,
    AlertNotFound,
    StoredAlert,
    acknowledge_alert,
    get_alert,
    list_alerts,
    record_alerts,
)
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
    store_drafts,
)
from .evidence_watcher import EvidenceWatcher, ast_watcher, genotype_watcher
from .mapping_watcher import MappingWatcher
from .snapshot import Snapshot, SnapshotError, open_snapshot
from .tool_watcher import AmrFinderPlusWatcher
from .watchers import DraftChange, Watcher, WatcherRegistry


# the watchers shipped with the project; a new source of change is one more line here
def default_watchers() -> WatcherRegistry:
    registry = WatcherRegistry()
    for watcher in (ast_watcher(), genotype_watcher(), MappingWatcher(), AmrFinderPlusWatcher()):
        registry.register(watcher)
    return registry


__all__ = [
    "ACKNOWLEDGED",
    "APPLIED",
    "DISMISSED",
    "OPEN",
    "PENDING",
    "Alert",
    "AlertAlreadyAcknowledged",
    "AlertError",
    "AlertNotFound",
    "AmrFinderPlusWatcher",
    "CheckResult",
    "DraftAlreadyDecided",
    "DraftChange",
    "DraftError",
    "DraftNotFound",
    "EvidenceWatcher",
    "MappingWatcher",
    "Snapshot",
    "SnapshotError",
    "StoredAlert",
    "StoredDraft",
    "Watcher",
    "WatcherRegistry",
    "acknowledge_alert",
    "apply_draft",
    "ast_watcher",
    "default_watchers",
    "detect_changes",
    "dismiss_draft",
    "genotype_watcher",
    "get_alert",
    "get_draft",
    "list_alerts",
    "list_drafts",
    "open_snapshot",
    "record_alerts",
    "run_check",
    "store_drafts",
]
