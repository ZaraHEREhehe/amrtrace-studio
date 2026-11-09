# watches the determinant-to-drug mapping between two snapshots and drafts a MAPPING_ADDED or MAPPING_RETIRED change

from __future__ import annotations

from dataclasses import dataclass

from amrtrace.changes.differs.mapping import MappingAddedDiffer, MappingRetiredDiffer, parse_mapping_set
from amrtrace.ingest.frozen_v1 import MAPPING_COLUMNS

from .snapshot import Snapshot, SnapshotError
from .watchers import DraftChange

EXAMPLES = 20


# a snapshot holds one mapping version, the same rule the loader uses
def mapping_version(snapshot: Snapshot) -> str:
    versions = {row["mapping_version"] for row in snapshot.rows("mapping", MAPPING_COLUMNS)}
    versions.discard(None)
    if len(versions) != 1:
        raise SnapshotError(
            f"snapshot {snapshot.snapshot_id!r}: the mapping names {len(versions)} versions, expected exactly one"
        )
    return str(versions.pop())


@dataclass(frozen=True)
class MappingWatcher:
    name: str = "mapping"

    def detect(self, old: Snapshot, new: Snapshot) -> list[DraftChange]:
        if not (old.has_table("mapping") and new.has_table("mapping")):
            return []
        old_version, new_version = mapping_version(old), mapping_version(new)
        old_set = parse_mapping_set(old_version, old.rows("mapping", MAPPING_COLUMNS))
        new_set = parse_mapping_set(new_version, new.rows("mapping", MAPPING_COLUMNS))
        comparison = MappingAddedDiffer().compare(old_set, new_set)
        if not (comparison.added or comparison.retired or comparison.edited):
            return []
        # the same mapping version with different rules would make the change impossible to tell apart later
        if old_version == new_version:
            raise SnapshotError(
                f"the mapping rules changed but both snapshots call the mapping {old_version!r}; "
                "a changed mapping needs a new version"
            )

        # the entities are always the full difference; the type only names what most of the change is
        only_retired = comparison.retired and not (comparison.added or comparison.edited)
        differ = MappingRetiredDiffer() if only_retired else MappingAddedDiffer()
        summary = {
            "rules_added": len(comparison.added),
            "rules_retired": len(comparison.retired),
            "rules_edited": len(comparison.edited),
            "newly_linked_pairs": [list(p) for p in comparison.newly_linked_pairs[:EXAMPLES]],
            "unlinked_pairs": [list(p) for p in comparison.unlinked_pairs[:EXAMPLES]],
            "newly_linked_pair_count": len(comparison.newly_linked_pairs),
            "unlinked_pair_count": len(comparison.unlinked_pairs),
        }
        return [
            DraftChange(
                watcher=self.name,
                change_type=differ.change_type,
                old_version=old_version,
                new_version=new_version,
                changed_entities=tuple(comparison.entities()),
                summary=summary,
            )
        ]
