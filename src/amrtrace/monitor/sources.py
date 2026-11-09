# the two small source files the A-18 watchers read, and the optional fetch that keeps them up to date
#
# data/sources/standards_catalogue.yaml: the published editions of each breakpoint standard (a person adds a line
#   when an edition is announced, or --fetch adds the edition the publisher's page shows)
# data/sources/amrfinderplus_releases.yaml: the latest AMRFinderPlus software and database NCBI has published
#
# both are committed, so a check can always be replayed; fetching only updates them, a person reviews the change

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOGUE_FILE = REPO_ROOT / "data" / "sources" / "standards_catalogue.yaml"
RELEASES_FILE = REPO_ROOT / "data" / "sources" / "amrfinderplus_releases.yaml"

# where NCBI publishes the newest database and software release; read only when a person asks for --fetch
DATABASE_URL = "https://ftp.ncbi.nlm.nih.gov/pathogen/Antimicrobial_resistance/AMRFinderPlus/database/latest/version.txt"
SOFTWARE_URL = "https://api.github.com/repos/ncbi/amr/releases/latest"
USER_AGENT = "AMRTrace-Studio source check"

# an edition inside a table version name, for example CLSI_M100_ED33_VET01S_ED7 holds M100 Ed33 and VET01S Ed7
_EDITION_IN_VERSION = re.compile(r"(?:^|_)([A-Z][A-Z0-9]*)_ED([0-9]+)(?=_|$)")
_DATABASE_VERSION = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+$")
_SOFTWARE_VERSION = re.compile(r"([0-9]+\.[0-9]+(?:\.[0-9]+)?)")


class SourceFileError(Exception):
    pass


@dataclass(frozen=True)
class Edition:
    edition: int
    published: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class Standard:
    body: str
    document: str
    page: str | None
    editions: tuple[Edition, ...] = field(default_factory=tuple)

    @property
    def label(self) -> str:
        return f"{self.body} {self.document}"

    def newest(self) -> Edition | None:
        return max(self.editions, key=lambda e: e.edition) if self.editions else None


@dataclass(frozen=True)
class Release:
    version: str
    source: str | None = None
    checked_on: str | None = None


@dataclass(frozen=True)
class ToolReleases:
    software: Release | None
    database: Release | None


def editions_in(version: str | None) -> dict[str, int]:
    return {document: int(number) for document, number in _EDITION_IN_VERSION.findall(version or "")}


def _text(value) -> str | None:
    return None if value is None else str(value)


def load_catalogue(path: Path = CATALOGUE_FILE) -> list[Standard]:
    try:
        content = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SourceFileError(f"cannot read the standards catalogue {path}: {exc}") from exc
    standards = []
    for entry in content.get("standards") or []:
        try:
            editions = tuple(
                Edition(int(item["edition"]), _text(item.get("published")), _text(item.get("source")))
                for item in entry.get("editions") or []
            )
            standards.append(Standard(str(entry["body"]), str(entry["document"]), _text(entry.get("page")), editions))
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceFileError(f"{path}: every standard needs body, document and numbered editions ({exc})") from exc
    documents = [s.document for s in standards]
    if len(documents) != len(set(documents)):
        raise SourceFileError(f"{path}: a document is listed twice")
    return standards


def _release(entry) -> Release | None:
    if not entry or not entry.get("version"):
        return None
    return Release(str(entry["version"]), _text(entry.get("source")), _text(entry.get("checked_on")))


def load_releases(path: Path = RELEASES_FILE) -> ToolReleases:
    try:
        content = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SourceFileError(f"cannot read the AMRFinderPlus release file {path}: {exc}") from exc
    releases = ToolReleases(_release(content.get("software")), _release(content.get("database")))
    if releases.database is not None and not _DATABASE_VERSION.match(releases.database.version):
        raise SourceFileError(f"{path}: database version {releases.database.version!r} is not like 2026-08-07.1")
    return releases


# the edition a publisher's product page names, for example the code M100Ed36 or VET01SEd7E
def edition_on_page(html: str, document: str) -> int | None:
    found = [int(n) for n in re.findall(rf"\b{re.escape(document)}[\s-]?Ed([0-9]+)", html, flags=re.IGNORECASE)]
    return max(found) if found else None


def database_from_text(text: str) -> str:
    version = text.strip()
    if not _DATABASE_VERSION.match(version):
        raise SourceFileError(f"NCBI's version file did not hold a database version: {version[:40]!r}")
    return version


def software_from_release(text: str) -> str:
    try:
        tag = str(json.loads(text).get("tag_name", ""))
    except (ValueError, AttributeError) as exc:
        raise SourceFileError("the release information was not JSON") from exc
    match = _SOFTWARE_VERSION.search(tag)
    if not match:
        raise SourceFileError(f"no version number in the release tag {tag!r}")
    return match.group(1)


def fetch_text(url: str, timeout: float = 20.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


# adds the edition a page shows when the catalogue does not list it yet; returns the updated standards and what was added
def add_fetched_editions(standards: list[Standard], found: dict[str, int], today: date) -> tuple[list[Standard], list[str]]:
    updated, added = [], []
    for standard in standards:
        number = found.get(standard.document)
        if number is not None and number not in {e.edition for e in standard.editions}:
            edition = Edition(number, None, f"fetched from {standard.page} on {today.isoformat()}")
            standard = replace(standard, editions=tuple(sorted((*standard.editions, edition), key=lambda e: e.edition)))
            added.append(f"{standard.label} Ed{number}")
        updated.append(standard)
    return updated, added


CATALOGUE_HEADER = """\
# Published editions of the breakpoint standards AMRTrace reads (task A-18, D-25).
# A person adds an edition when the publisher announces it; `python -m amrtrace.monitor.sources --fetch` adds the
# edition the publisher's page shows. The tables themselves are licensed and are entered by hand
# (data/interpretation/); the check raises an alert while an edition newer than the table in force has no table.
"""

RELEASES_HEADER = """\
# The newest AMRFinderPlus software and reference database NCBI has published (task A-18, D-25).
# `python -m amrtrace.monitor.sources --fetch` updates it from NCBI; review and commit the change. The check raises an
# alert when the database is not covered by the mapping, or the software is newer than the one the release used.
"""


def write_catalogue(standards: list[Standard], path: Path = CATALOGUE_FILE) -> None:
    def edition(e: Edition) -> dict:
        return {k: v for k, v in (("edition", e.edition), ("published", e.published), ("source", e.source)) if v is not None}

    content = {
        "standards": [
            {"body": s.body, "document": s.document, "page": s.page, "editions": [edition(e) for e in s.editions]}
            for s in standards
        ]
    }
    Path(path).write_text(CATALOGUE_HEADER + yaml.safe_dump(content, sort_keys=False, width=120), encoding="utf-8")


def write_releases(releases: ToolReleases, path: Path = RELEASES_FILE) -> None:
    def release(r: Release | None):
        return None if r is None else {k: v for k, v in vars(r).items() if v is not None}

    content = {"software": release(releases.software), "database": release(releases.database)}
    Path(path).write_text(RELEASES_HEADER + yaml.safe_dump(content, sort_keys=False, width=120), encoding="utf-8")
