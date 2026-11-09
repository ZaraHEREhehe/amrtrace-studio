# "check now": compares an old and a new snapshot folder and stores what the watchers find as pending drafts
#
#   python -m amrtrace.monitor.check --old data/raw --old-manifest data/manifest/sha256.txt --new <new snapshot folder>
#
# add --dry-run to print the drafts without storing anything

from __future__ import annotations

import argparse
import os
import sys

import psycopg
from psycopg.conninfo import make_conninfo

from . import default_watchers, detect_changes, open_snapshot, run_check
from .snapshot import SnapshotError


def _conninfo() -> str:
    return make_conninfo(
        host=os.environ.get("AMRTRACE_PG_HOST", "localhost"),
        port=os.environ.get("AMRTRACE_PG_PORT", "5432"),
        user=os.environ.get("AMRTRACE_PG_USER", "postgres"),
        password=os.environ.get("AMRTRACE_PG_PASSWORD", "dev"),
        dbname=os.environ.get("AMRTRACE_PG_DBNAME", "amrtrace"),
        connect_timeout=5,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare two source snapshots and draft the changes between them.")
    parser.add_argument("--old", required=True, help="folder of the snapshot the current release was built from")
    parser.add_argument("--old-manifest", help="manifest of the old snapshot, if it is not <old>/sha256.txt")
    parser.add_argument("--new", required=True, help="folder of the newer snapshot")
    parser.add_argument("--new-manifest", help="manifest of the new snapshot, if it is not <new>/sha256.txt")
    parser.add_argument("--dry-run", action="store_true", help="print the drafts without storing them")
    args = parser.parse_args(argv)

    try:
        old = open_snapshot(args.old, args.old_manifest)
        new = open_snapshot(args.new, args.new_manifest)
        registry = default_watchers()
        print(f"comparing {old.snapshot_id} -> {new.snapshot_id} with watchers: {', '.join(registry.names())}")

        if args.dry_run:
            drafts = detect_changes(registry, old, new)
            for draft in drafts:
                print(f"  {draft.watcher}: {draft.change_type}, {len(draft.changed_entities)} entities, {draft.summary}")
            print(f"{len(drafts)} draft(s) found; nothing stored (dry run)")
            return 0

        with psycopg.connect(_conninfo()) as conn:
            result = run_check(conn, registry, old, new)
            conn.commit()
    except (SnapshotError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        print("nothing was drafted", file=sys.stderr)
        return 1

    for draft_id in result.created:
        print(f"  new draft     {draft_id}")
    for draft_id in result.already_drafted:
        print(f"  already found {draft_id}")
    print(f"{len(result.created)} new draft(s), {len(result.already_drafted)} already drafted; apply or dismiss them")
    return 0


if __name__ == "__main__":
    sys.exit(main())
