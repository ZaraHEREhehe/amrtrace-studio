# task A-18: reading the two source files, what a publisher's page or release says, and the AMRFinderPlus watcher
from datetime import date

import pytest

from amrtrace.monitor import AmrFinderPlusWatcher, open_snapshot
from amrtrace.monitor.source_check import is_newer_table
from amrtrace.monitor.sources import (
    Edition,
    Release,
    SourceFileError,
    Standard,
    ToolReleases,
    add_fetched_editions,
    database_from_text,
    edition_on_page,
    editions_in,
    load_catalogue,
    load_releases,
    software_from_release,
    write_catalogue,
    write_releases,
)
from tests.monitor_snapshots import MINI_COHORT, make_snapshot

ISOLATES = "curated_v1/isolates_curated.parquet"


def test_the_committed_source_files_are_readable():
    catalogue = load_catalogue()
    assert {s.document for s in catalogue} == {"M100", "VET01S"}
    assert all(s.newest() is not None for s in catalogue)
    assert load_releases().database is not None


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("CLSI_M100_ED33_VET01S_ED7", {"M100": 33, "VET01S": 7}),
        ("CLSI_M100_ED32", {"M100": 32}),
        ("AS_REPORTED", {}),
        (None, {}),
    ],
)
def test_a_table_version_names_the_editions_it_holds(version, expected):
    assert editions_in(version) == expected


@pytest.mark.parametrize(
    ("old", "new", "newer"),
    [
        ("CLSI_M100_ED33", "CLSI_M100_ED36", True),
        ("CLSI_M100_ED33", "CLSI_M100_ED33_VET01S_ED7", True),
        ("CLSI_M100_ED33_VET01S_ED7", "CLSI_M100_ED36_VET01S_ED7", True),
        ("CLSI_M100_ED33_VET01S_ED7", "CLSI_M100_ED36", False),
        ("CLSI_M100_ED33", "CLSI_M100_ED32", False),
        ("CLSI_M100_ED33", "CLSI_M100_ED33", False),
        ("AS_REPORTED", "CLSI_M100_ED33", False),
    ],
)
def test_a_table_is_newer_only_when_it_drops_nothing_and_moves_forward(old, new, newer):
    assert is_newer_table(old, new) is newer


@pytest.mark.parametrize(
    ("html", "document", "edition"),
    [
        ("<td>Print Code M100Ed36</td><td>PDF Code M100Ed36E</td> replaces CLSI M100-Ed35", "M100", 36),
        ("<td>PDF Code VET01SEd7E</td>", "VET01S", 7),
        ("<p>no product code here</p>", "M100", None),
    ],
)
def test_the_edition_is_read_from_the_publishers_product_code(html, document, edition):
    assert edition_on_page(html, document) == edition


def test_ncbi_release_files_are_read():
    assert database_from_text("2026-10-02.1\n") == "2026-10-02.1"
    assert software_from_release('{"tag_name": "amrfinder_v4.2.9"}') == "4.2.9"
    with pytest.raises(SourceFileError):
        database_from_text("<html>not found</html>")
    with pytest.raises(SourceFileError):
        software_from_release('{"tag_name": "nightly"}')


def test_a_fetched_edition_is_added_once_and_the_files_round_trip(tmp_path):
    m100 = Standard("CLSI", "M100", "https://example.org/M100", (Edition(33, "2023"),))
    updated, added = add_fetched_editions([m100], {"M100": 36}, date(2026, 11, 9))
    assert added == ["CLSI M100 Ed36"]
    assert add_fetched_editions(updated, {"M100": 36}, date(2026, 11, 9))[1] == []

    write_catalogue(updated, tmp_path / "catalogue.yaml")
    assert load_catalogue(tmp_path / "catalogue.yaml") == updated
    releases = ToolReleases(Release("4.2.9", "fetched", "2026-11-09"), Release("2026-10-02.1"))
    write_releases(releases, tmp_path / "releases.yaml")
    assert load_releases(tmp_path / "releases.yaml") == releases


def test_a_catalogue_listing_a_document_twice_is_refused(tmp_path):
    path = tmp_path / "catalogue.yaml"
    path.write_text(
        "standards:\n"
        "- {body: CLSI, document: M100, editions: [{edition: 33}]}\n"
        "- {body: CLSI, document: M100, editions: [{edition: 34}]}\n",
        encoding="utf-8",
    )
    with pytest.raises(SourceFileError, match="listed twice"):
        load_catalogue(path)


# the AMRFinderPlus watcher, on two copies of the mini-cohort


def move_software(rows, count, version="4.3.0"):
    return [dict(r, amrfinderplus_version=version) if i < count else r for i, r in enumerate(rows)]


def test_isolates_moved_to_new_software_draft_one_version_change(tmp_path):
    new = open_snapshot(make_snapshot(tmp_path, "AMRTRACE_TEST_V2", {ISOLATES: lambda rows: move_software(rows, 3)}))

    drafts = AmrFinderPlusWatcher().detect(open_snapshot(MINI_COHORT), new)

    assert [(d.change_type, d.old_version, d.new_version) for d in drafts] == [("EVALUATOR_VERSION", "4.2.7", "4.3.0")]
    entity = drafts[0].changed_entities[0]
    assert (entity.node_type, entity.node_id, entity.old_version, entity.new_version) == (
        "amrfinderplus_version", "4.2.7", "4.2.7", "4.3.0"
    )
    assert drafts[0].summary["isolates_moved"] == 3


# a database move changes genotype rows, which the genotype watcher drafts; this watcher only reports it
def test_a_database_move_alone_drafts_no_version_change(tmp_path):
    def rerun(rows):
        return [dict(rows[0], refgene_db_version="2099-01-01.1"), *rows[1:]]

    new = open_snapshot(make_snapshot(tmp_path, "AMRTRACE_TEST_V2", {ISOLATES: rerun}))

    assert AmrFinderPlusWatcher().detect(open_snapshot(MINI_COHORT), new) == []


def test_the_same_software_drafts_nothing(tmp_path):
    new = open_snapshot(make_snapshot(tmp_path, "AMRTRACE_TEST_V2"))

    assert AmrFinderPlusWatcher().detect(open_snapshot(MINI_COHORT), new) == []
