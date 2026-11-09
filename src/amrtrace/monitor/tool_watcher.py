# the AMRFinderPlus watcher: notices when NCBI analysed the cohort's isolates with a different software version (A-18)
#
# tool versions are recorded per release (D-05, version level), so a move to new software is drafted as one
# EVALUATOR_VERSION change on the old version node; every case evaluated under it is re-verified, not only the moved
# isolates. A move to a new reference database is not drafted here: it changes the isolate's genotype rows, which the
# genotype watcher drafts row by row, and whether the mapping covers the new database is checked by the source check.

from __future__ import annotations

from collections import Counter, defaultdict

from amrtrace.changes.types import ChangedEntity

from .snapshot import Snapshot
from .watchers import DraftChange

NODE_SOFTWARE = "amrfinderplus_version"
ISOLATE_COLUMNS = ["target_acc", "amrfinderplus_version", "refgene_db_version"]
EXAMPLES = 20


def _by_isolate(snapshot: Snapshot) -> dict[str, dict]:
    return {str(row["target_acc"]): row for row in snapshot.rows("isolates", ISOLATE_COLUMNS)}


class AmrFinderPlusWatcher:
    name = "amrfinderplus"
    change_type = "EVALUATOR_VERSION"

    def detect(self, old: Snapshot, new: Snapshot) -> list[DraftChange]:
        if not (old.has_table("isolates") and new.has_table("isolates")):
            return []
        before, after = _by_isolate(old), _by_isolate(new)
        shared = sorted(set(before) & set(after))

        # isolates kept in both snapshots whose software version moved, grouped by the move
        moves = defaultdict(list)
        for target in shared:
            was, now = before[target].get("amrfinderplus_version"), after[target].get("amrfinderplus_version")
            if was and now and str(was) != str(now):
                moves[(str(was), str(now))].append(target)
        database_moves = Counter(
            (str(before[t].get("refgene_db_version")), str(after[t].get("refgene_db_version")))
            for t in shared
            if before[t].get("refgene_db_version") != after[t].get("refgene_db_version")
        )

        drafts = []
        for (was, now), targets in sorted(moves.items()):
            drafts.append(
                DraftChange(
                    watcher=self.name,
                    change_type=self.change_type,
                    old_version=was,
                    new_version=now,
                    changed_entities=(ChangedEntity(NODE_SOFTWARE, was, was, now, None),),
                    summary={
                        "isolates_moved": len(targets),
                        "isolates_compared": len(shared),
                        "examples": targets[:EXAMPLES],
                        "database_moves": {f"{a} -> {b}": n for (a, b), n in sorted(database_moves.items())},
                        "note": "version level (D-05): every case evaluated under the old version is re-verified",
                    },
                )
            )
        return drafts
