# the source check (A-18): compares what the publishers have released with what AMRTrace holds, and turns each
# difference into an alert for a person or, once a person has entered a new breakpoint table, into a draft
#
#   standards:      an edition newer than the table in force with no stored table      -> alert NEW_STANDARD_EDITION
#                   a stored table newer than the table in force                      -> draft INTERPRETATION_VERSION
#   AMRFinderPlus:  NCBI's newest database has no mapping rules                       -> alert DATABASE_NOT_IN_MAPPING
#                   NCBI's newest software is newer than the release's                -> alert NEWER_SOFTWARE
#                   a snapshot's isolates use a database with no mapping rules        -> alert SNAPSHOT_DATABASE_NOT_IN_MAPPING

from __future__ import annotations

import re
from dataclasses import dataclass

from amrtrace.changes.differs.interpretation import InterpretationTableDiffer
from amrtrace.interpretation.db import list_table_versions, load_table_from_db

from .alerts import Alert
from .snapshot import Snapshot
from .sources import Standard, ToolReleases, editions_in
from .watchers import DraftChange

SOURCE_STANDARDS = "standards"
SOURCE_AMRFINDERPLUS = "amrfinderplus"
NEW_STANDARD_EDITION = "NEW_STANDARD_EDITION"
DATABASE_NOT_IN_MAPPING = "DATABASE_NOT_IN_MAPPING"
NEWER_SOFTWARE = "NEWER_SOFTWARE"
SNAPSHOT_DATABASE_NOT_IN_MAPPING = "SNAPSHOT_DATABASE_NOT_IN_MAPPING"
INTERPRETATION_CHANGE = "INTERPRETATION_VERSION"


@dataclass(frozen=True)
class TableDraft:
    old_table: str
    new_table: str
    draft: DraftChange


@dataclass(frozen=True)
class SourceFindings:
    alerts: tuple[Alert, ...]
    table_drafts: tuple[TableDraft, ...]


# the versions the newest published release was built with; empty before any release exists
def versions_in_force(conn) -> dict:
    row = conn.execute(
        "SELECT version_vector FROM release WHERE status = 'PUBLISHED' ORDER BY release_seq DESC LIMIT 1"
    ).fetchone()
    return dict(row[0]) if row and row[0] else {}


# true when table b holds every standard table a holds, none older, and is newer in at least one way
def is_newer_table(a: str, b: str) -> bool:
    held_a, held_b = editions_in(a), editions_in(b)
    if not held_a or not set(held_a) <= set(held_b):
        return False
    if any(held_b[d] < held_a[d] for d in held_a):
        return False
    return any(held_b[d] > held_a[d] for d in held_a) or set(held_b) > set(held_a)


def check_standards(conn, catalogue: list[Standard]) -> SourceFindings:
    in_force = versions_in_force(conn).get("interpretation_version")
    held = editions_in(in_force)
    stored = list_table_versions(conn)
    alerts = []
    for standard in catalogue:
        newest = standard.newest()
        if newest is None or newest.edition <= held.get(standard.document, 0):
            continue
        # once a person has entered a table holding the edition, the alert has done its job; the draft takes over
        holders = [t for t in stored if editions_in(t).get(standard.document, 0) >= newest.edition]
        if holders:
            continue
        current = held.get(standard.document)
        now = f"the table in force ({in_force}) holds Ed{current}" if current else f"no table in force holds {standard.document}"
        alerts.append(
            Alert(
                source=SOURCE_STANDARDS,
                kind=NEW_STANDARD_EDITION,
                subject=f"{standard.label} Ed{newest.edition}",
                message=(
                    f"{standard.label} Ed{newest.edition} is published and {now}. Enter its breakpoints as a new table "
                    "in data/interpretation/ and store it; the next source check then drafts the change."
                ),
                details={
                    "document": standard.document,
                    "edition": newest.edition,
                    "published": newest.published,
                    "page": standard.page,
                    "table_in_force": in_force,
                    "edition_in_force": current,
                    "editions_skipped": [e.edition for e in standard.editions if (current or 0) < e.edition < newest.edition],
                },
            )
        )

    drafts = []
    if in_force:
        differ = InterpretationTableDiffer()
        old_table = None
        for candidate in sorted(t for t in stored if t != in_force and is_newer_table(in_force, t)):
            # a change someone already registered by hand is not drafted a second time
            if conn.execute(
                "SELECT 1 FROM change_event WHERE type = %s AND old_version = %s AND new_version = %s",
                (INTERPRETATION_CHANGE, in_force, candidate),
            ).fetchone():
                continue
            old_table = old_table or load_table_from_db(conn, in_force)
            entities = differ.diff(old_table, load_table_from_db(conn, candidate))
            if not entities:
                continue
            counts = {
                "rules_added": sum(1 for e in entities if e.old_version is None),
                "rules_removed": sum(1 for e in entities if e.new_version is None),
            }
            counts["rules_changed"] = len(entities) - counts["rules_added"] - counts["rules_removed"]
            draft = DraftChange(
                watcher=SOURCE_STANDARDS,
                change_type=INTERPRETATION_CHANGE,
                old_version=in_force,
                new_version=candidate,
                changed_entities=tuple(entities),
                summary={**counts, "editions_before": editions_in(in_force), "editions_after": editions_in(candidate)},
            )
            drafts.append(TableDraft(in_force, candidate, draft))
    return SourceFindings(tuple(alerts), tuple(drafts))


def _mapped_databases(conn) -> set[str]:
    return {row[0] for row in conn.execute("SELECT DISTINCT source_db_version FROM mapping_rule").fetchall()}


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"[0-9]+", version))


def check_amrfinderplus(conn, releases: ToolReleases, snapshot: Snapshot | None = None) -> SourceFindings:
    mapped = _mapped_databases(conn)
    alerts = []
    database = releases.database
    if database is not None and database.version not in mapped:
        alerts.append(
            Alert(
                source=SOURCE_AMRFINDERPLUS,
                kind=DATABASE_NOT_IN_MAPPING,
                subject=f"AMRFinderPlus database {database.version}",
                message=(
                    f"NCBI has published AMRFinderPlus database {database.version}, and the mapping has no rules for it. "
                    "Isolates NCBI re-runs with it cannot be evaluated until a mapping covering it is added."
                ),
                details={"database": database.version, "mapped_databases": sorted(mapped), "source": database.source,
                         "checked_on": database.checked_on},
            )
        )

    software = releases.software
    used = versions_in_force(conn).get("amrfinderplus_version")
    if software is not None and used and _version_key(software.version) > _version_key(str(used)):
        alerts.append(
            Alert(
                source=SOURCE_AMRFINDERPLUS,
                kind=NEWER_SOFTWARE,
                subject=f"AMRFinderPlus {software.version}",
                message=(
                    f"NCBI has released AMRFinderPlus {software.version}; the release in force was built from results of "
                    f"{used}. Nothing changes until NCBI re-runs the isolates; the next snapshot check drafts that move."
                ),
                details={"software": software.version, "software_in_force": used, "source": software.source,
                         "checked_on": software.checked_on},
            )
        )

    if snapshot is not None and snapshot.has_table("isolates"):
        unmapped: dict[str, int] = {}
        for row in snapshot.rows("isolates", ["target_acc", "refgene_db_version"]):
            version = row.get("refgene_db_version")
            if version and str(version) not in mapped:
                unmapped[str(version)] = unmapped.get(str(version), 0) + 1
        for version, isolates in sorted(unmapped.items()):
            alerts.append(
                Alert(
                    source=SOURCE_AMRFINDERPLUS,
                    kind=SNAPSHOT_DATABASE_NOT_IN_MAPPING,
                    subject=f"AMRFinderPlus database {version} in {snapshot.snapshot_id}",
                    message=(
                        f"{isolates} isolates in {snapshot.snapshot_id} were analysed with database {version}, which the "
                        "mapping has no rules for; their cases cannot be evaluated on this snapshot until it is covered."
                    ),
                    details={"database": version, "isolates": isolates, "snapshot_id": snapshot.snapshot_id,
                             "mapped_databases": sorted(mapped)},
                )
            )
    return SourceFindings(tuple(alerts), ())


def check_sources(conn, catalogue: list[Standard], releases: ToolReleases, snapshot: Snapshot | None = None) -> SourceFindings:
    standards = check_standards(conn, catalogue)
    tools = check_amrfinderplus(conn, releases, snapshot)
    return SourceFindings(standards.alerts + tools.alerts, standards.table_drafts + tools.table_drafts)


def _fetch(catalogue_path, releases_path, catalogue: list[Standard], releases: ToolReleases):
    # imported here so the check itself never needs the network
    from datetime import datetime, timezone

    from .sources import (
        DATABASE_URL,
        SOFTWARE_URL,
        Release,
        SourceFileError,
        add_fetched_editions,
        database_from_text,
        edition_on_page,
        fetch_text,
        software_from_release,
        write_catalogue,
        write_releases,
    )

    today = datetime.now(timezone.utc).date()
    found = {}
    for standard in catalogue:
        if not standard.page:
            continue
        try:
            number = edition_on_page(fetch_text(standard.page), standard.document)
        except (OSError, ValueError) as exc:  # one unreachable page must not stop the others
            print(f"  could not read {standard.page}: {exc}")
            continue
        print(f"  {standard.label}: the publisher's page shows Ed{number}" if number else f"  {standard.label}: no edition found on {standard.page}")
        if number:
            found[standard.document] = number
    catalogue, added = add_fetched_editions(catalogue, found, today)
    if added:
        write_catalogue(catalogue, catalogue_path)
        print(f"  added to the catalogue: {', '.join(added)} (review and commit {catalogue_path})")

    software, database = releases.software, releases.database
    for label, url, read in (("database", DATABASE_URL, database_from_text), ("software", SOFTWARE_URL, software_from_release)):
        try:
            version = read(fetch_text(url))
        except (OSError, ValueError, SourceFileError) as exc:
            print(f"  could not read the AMRFinderPlus {label} release: {exc}")
            continue
        print(f"  AMRFinderPlus {label}: NCBI's newest is {version}")
        fetched = Release(version, url, today.isoformat())
        if label == "database":
            database = fetched
        else:
            software = fetched
    updated = ToolReleases(software, database)
    if updated != releases:
        write_releases(updated, releases_path)
        print(f"  updated {releases_path} (review and commit it)")
    return catalogue, updated


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    from pathlib import Path

    import psycopg

    from .alerts import record_alerts
    from .check import _conninfo
    from .drafts import store_drafts
    from .snapshot import SnapshotError, open_snapshot
    from .sources import (
        CATALOGUE_FILE,
        RELEASES_FILE,
        SourceFileError,
        load_catalogue,
        load_releases,
    )

    parser = argparse.ArgumentParser(description="Check the breakpoint standards and AMRFinderPlus releases.")
    parser.add_argument("--fetch", action="store_true", help="first update the two source files from the publishers")
    parser.add_argument("--snapshot", help="also check that this snapshot's database versions are covered by the mapping")
    parser.add_argument("--snapshot-manifest", help="manifest of that snapshot, if it is not <snapshot>/sha256.txt")
    parser.add_argument("--catalogue", default=str(CATALOGUE_FILE))
    parser.add_argument("--releases", default=str(RELEASES_FILE))
    parser.add_argument("--dry-run", action="store_true", help="print what was found without storing it")
    args = parser.parse_args(argv)

    try:
        catalogue = load_catalogue(Path(args.catalogue))
        releases = load_releases(Path(args.releases))
        if args.fetch:
            print("fetching the publishers' latest releases:")
            catalogue, releases = _fetch(Path(args.catalogue), Path(args.releases), catalogue, releases)
        snapshot = open_snapshot(args.snapshot, args.snapshot_manifest) if args.snapshot else None
        with psycopg.connect(_conninfo()) as conn:
            findings = check_sources(conn, catalogue, releases, snapshot)
            for alert in findings.alerts:
                print(f"  alert  {alert.kind}: {alert.subject}\n         {alert.message}")
            for item in findings.table_drafts:
                summary = {k: item.draft.summary[k] for k in ("rules_added", "rules_removed", "rules_changed")}
                print(f"  draft  {item.draft.change_type}: {item.old_table} -> {item.new_table} {summary}")
            if args.dry_run:
                print(f"{len(findings.alerts)} alert(s), {len(findings.table_drafts)} draft(s) found; nothing stored (dry run)")
                return 0
            created, existing = record_alerts(conn, list(findings.alerts))
            drafted = [store_drafts(conn, [d.draft], d.old_table, d.new_table) for d in findings.table_drafts]
            conn.commit()
    except (SourceFileError, SnapshotError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        print("nothing was stored", file=sys.stderr)
        return 1

    new_drafts = sum(len(r.created) for r in drafted)
    print(f"{len(created)} new alert(s), {len(existing)} already raised; "
          f"{new_drafts} new draft(s), {len(drafted) - new_drafts} already drafted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
