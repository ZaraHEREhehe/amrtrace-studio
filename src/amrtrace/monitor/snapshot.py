# a source snapshot is a folder of curated tables plus a sha256 manifest, checked before anything is read (task A-13)

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from amrtrace.ingest.frozen_v1 import AST_FILE, GENOTYPE_FILE, ISOLATES_FILE, MAPPING_FILE

# the tables a watcher can ask for, and where they live when snapshot.json does not say otherwise
DEFAULT_FILES = {
    "isolates": ISOLATES_FILE,
    "ast": AST_FILE,
    "genotype": GENOTYPE_FILE,
    "mapping": MAPPING_FILE,
}
MANIFEST_NAME = "sha256.txt"
DESCRIPTION_NAME = "snapshot.json"


# raised when a snapshot cannot be trusted or read, so nothing gets drafted from it
class SnapshotError(Exception):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# reads "<hash>  <relative path>" lines, the format data/manifest/sha256.txt and the fixtures already use
def read_manifest(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise SnapshotError(f"manifest {path} does not exist")
    entries: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise SnapshotError(f"manifest {path}, line {number}: expected '<sha256>  <path>'")
        entries[parts[1].strip().replace("\\", "/")] = parts[0].lower()
    if not entries:
        raise SnapshotError(f"manifest {path} lists no files")
    return entries


# a verified snapshot folder; tables are read only when a watcher asks, and only the columns it needs
@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    folder: Path
    files: Mapping[str, str]
    created_at: datetime | None = None
    _cache: dict = field(default_factory=dict, compare=False, repr=False)

    def has_table(self, name: str) -> bool:
        return name in self.files and (self.folder / self.files[name]).is_file()

    def rows(self, name: str, columns: list[str] | None = None) -> list[dict[str, Any]]:
        key = (name, tuple(columns) if columns else None)
        if key not in self._cache:
            if not self.has_table(name):
                raise SnapshotError(f"snapshot {self.snapshot_id!r} has no {name} table")
            # imported here so the rest of the package works without the parquet reader installed
            import pyarrow.parquet as pq

            path = self.folder / self.files[name]
            available = set(pq.read_schema(path).names)
            wanted = [c for c in columns if c in available] if columns else None
            self._cache[key] = pq.read_table(path, columns=wanted).to_pylist()
        return self._cache[key]


# a snapshot without snapshot.json takes its id from the source_snapshot_id its rows were stored under
def _id_from_rows(folder: Path, files: Mapping[str, str]) -> str:
    import pyarrow.parquet as pq

    path = folder / files["isolates"]
    if not path.is_file() or "source_snapshot_id" not in pq.read_schema(path).names:
        raise SnapshotError(f"{folder}: no {DESCRIPTION_NAME} and no source_snapshot_id to name the snapshot")
    ids = {row["source_snapshot_id"] for row in pq.read_table(path, columns=["source_snapshot_id"]).to_pylist()}
    ids.discard(None)
    if len(ids) != 1:
        raise SnapshotError(f"{folder}: rows name {len(ids)} source snapshots, expected exactly one")
    return str(ids.pop())


# opens a snapshot folder only after every manifest entry matches; any mismatch raises SnapshotError
def open_snapshot(folder: str | Path, manifest: str | Path | None = None) -> Snapshot:
    folder = Path(folder)
    if not folder.is_dir():
        raise SnapshotError(f"snapshot folder {folder} does not exist")

    description: dict[str, Any] = {}
    if (folder / DESCRIPTION_NAME).is_file():
        try:
            description = json.loads((folder / DESCRIPTION_NAME).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SnapshotError(f"{folder / DESCRIPTION_NAME} is not valid JSON: {exc}") from exc
    files = {**DEFAULT_FILES, **(description.get("files") or {})}

    # every listed file must exist and match, and every table we may read must be listed
    entries = read_manifest(Path(manifest) if manifest else folder / MANIFEST_NAME)
    problems = []
    for relative, expected in sorted(entries.items()):
        path = folder / relative
        if not path.is_file():
            problems.append(f"{relative}: listed in the manifest but missing")
        elif _sha256(path) != expected:
            problems.append(f"{relative}: SHA-256 does not match the manifest")
    for name, relative in sorted(files.items()):
        if (folder / relative).is_file() and relative not in entries:
            problems.append(f"{relative}: the {name} table is not listed in the manifest")
    if problems:
        raise SnapshotError(f"snapshot {folder} failed its manifest check: " + "; ".join(problems))

    created = description.get("created_at")
    try:
        created_at = datetime.fromisoformat(created) if created else None
    except ValueError as exc:
        raise SnapshotError(f"{folder / DESCRIPTION_NAME}: created_at {created!r} is not an ISO date") from exc

    snapshot_id = description.get("snapshot_id") or _id_from_rows(folder, files)
    return Snapshot(snapshot_id=str(snapshot_id), folder=folder, files=files, created_at=created_at)
