# task A-13: snapshots are checked before use, and each watcher drafts exactly the changes between two snapshots

from __future__ import annotations

import json

import pytest

from amrtrace.changes.registry import default_registry
from amrtrace.changes.types import ChangeEvent
from amrtrace.changes.validation import validate_shape
from amrtrace.monitor import (
    DraftChange,
    DraftError,
    MappingWatcher,
    SnapshotError,
    WatcherRegistry,
    ast_watcher,
    default_watchers,
    detect_changes,
    genotype_watcher,
    open_snapshot,
)
from tests.monitor_snapshots import (
    AST,
    GENOTYPE,
    MAPPING,
    MINI_COHORT,
    first_used_genotype_row,
    flip_phenotype,
    make_snapshot,
    read_rows,
    write_rows,
)

OLD_ID = "AMRTRACE_RAW_V1"
NEW_ID = "AMRTRACE_TEST_V2"


@pytest.fixture
def old():
    return open_snapshot(MINI_COHORT)


def new_snapshot(tmp_path, edits=None, snapshot_id=NEW_ID):
    return open_snapshot(make_snapshot(tmp_path, snapshot_id, edits))


def only(drafts, change_type):
    found = [d for d in drafts if d.change_type == change_type]
    assert len(found) == 1, [d.change_type for d in drafts]
    return found[0]


# snapshots


def test_the_mini_cohort_opens_and_takes_its_id_from_its_rows(old):
    assert old.snapshot_id == OLD_ID
    assert old.has_table("ast") and old.has_table("mapping")


def test_a_snapshot_whose_file_differs_from_its_manifest_is_refused(tmp_path):
    folder = make_snapshot(tmp_path, NEW_ID)
    rows = read_rows(folder, AST)
    write_rows(folder, AST, [flip_phenotype(rows[0]), *rows[1:]])

    with pytest.raises(SnapshotError, match="SHA-256 does not match"):
        open_snapshot(folder)


def test_a_snapshot_missing_a_listed_file_is_refused(tmp_path):
    folder = make_snapshot(tmp_path, NEW_ID)
    (folder / MAPPING).unlink()

    with pytest.raises(SnapshotError, match="missing"):
        open_snapshot(folder)


def test_a_table_left_out_of_the_manifest_is_refused(tmp_path):
    folder = make_snapshot(tmp_path, NEW_ID)
    manifest = folder / "sha256.txt"
    manifest.write_text(
        "".join(line + "\n" for line in manifest.read_text().splitlines() if "mapping_v1" not in line)
    )

    with pytest.raises(SnapshotError, match="not listed in the manifest"):
        open_snapshot(folder)


def test_a_broken_snapshot_description_is_refused(tmp_path):
    folder = make_snapshot(tmp_path, NEW_ID)
    (folder / "snapshot.json").write_text("{not json")

    with pytest.raises(SnapshotError, match="not valid JSON"):
        open_snapshot(folder)


# the registry


def test_the_default_watchers_run_in_a_fixed_order():
    assert default_watchers().names() == ["ast_evidence", "genotype_evidence", "mapping"]


def test_a_watcher_name_can_only_be_registered_once():
    registry = WatcherRegistry()
    registry.register(MappingWatcher())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(MappingWatcher())


def test_something_that_is_not_a_watcher_is_refused():
    with pytest.raises(TypeError, match="needs a name"):
        WatcherRegistry().register(object())


# nothing changed


def test_two_snapshots_with_the_same_content_give_no_drafts(old, tmp_path):
    assert detect_changes(default_watchers(), old, new_snapshot(tmp_path)) == []


def test_a_snapshot_cannot_be_compared_with_itself(old):
    with pytest.raises(DraftError, match="two different snapshots"):
        detect_changes(default_watchers(), old, old)


# AST rows


def test_a_corrected_ast_row_is_one_edited_entity_named_by_its_old_id(old, tmp_path):
    first = read_rows(MINI_COHORT, AST)[0]
    new = new_snapshot(tmp_path, {AST: lambda rows: [flip_phenotype(rows[0]), *rows[1:]]})

    draft = only(ast_watcher().detect(old, new), "AST_CORRECTED")

    assert [(e.node_type, e.node_id, e.old_version, e.new_version) for e in draft.changed_entities] == [
        ("ast_evidence", first["ast_evidence_id"], OLD_ID, NEW_ID)
    ]
    assert draft.summary["rows_edited"] == 1
    assert draft.summary["fields_changed"] == {"phenotype_normalized": 1}


def test_a_field_the_evaluator_never_reads_is_not_a_correction(old, tmp_path):
    new = new_snapshot(tmp_path, {AST: lambda rows: [dict(r, creation_date="2030-01-01") for r in rows]})

    assert ast_watcher().detect(old, new) == []


# V1 AST ids include the snapshot id; a later snapshot re-ids every row, and that alone must not look like a change
def test_new_ast_ids_for_the_same_rows_are_not_a_change(old, tmp_path):
    new = new_snapshot(tmp_path, {AST: lambda rows: [dict(r, ast_evidence_id="ASTV2_" + r["id"]) for r in rows]})

    assert ast_watcher().detect(old, new) == []


def test_an_edited_row_under_a_new_id_is_still_named_by_the_id_the_graph_holds(old, tmp_path):
    first = read_rows(MINI_COHORT, AST)[0]
    new = new_snapshot(
        tmp_path,
        {AST: lambda rows: [dict(flip_phenotype(rows[0]), ast_evidence_id="ASTV2_X"), *rows[1:]]},
    )

    draft = only(ast_watcher().detect(old, new), "AST_CORRECTED")

    assert [e.node_id for e in draft.changed_entities] == [first["ast_evidence_id"]]
    assert draft.summary["examples_edited"][0]["new_id"] == "ASTV2_X"


def test_added_and_removed_ast_rows_have_one_open_version_each(old, tmp_path):
    rows = read_rows(MINI_COHORT, AST)
    added = dict(rows[0], id="999_NEW", ast_evidence_id="ASTV2_NEW")
    new = new_snapshot(tmp_path, {AST: lambda r: [*r[1:], added]})

    draft = only(ast_watcher().detect(old, new), "AST_CORRECTED")

    found = {(e.node_id, e.old_version, e.new_version) for e in draft.changed_entities}
    assert found == {(rows[0]["ast_evidence_id"], OLD_ID, None), ("ASTV2_NEW", None, NEW_ID)}


# genotype rows


def test_a_removed_detailed_genotype_row_is_drafted(old, tmp_path):
    removed = first_used_genotype_row(read_rows(MINI_COHORT, GENOTYPE))
    new = new_snapshot(
        tmp_path,
        {GENOTYPE: lambda rows: [r for r in rows if r["genotype_evidence_id"] != removed["genotype_evidence_id"]]},
    )

    draft = only(genotype_watcher().detect(old, new), "GENOTYPE_CHANGED")

    assert [(e.node_id, e.old_version, e.new_version) for e in draft.changed_entities] == [
        (removed["genotype_evidence_id"], OLD_ID, None)
    ]


# summary row ids include the snapshot id too, so they are matched by what they say
def test_new_summary_ids_for_the_same_rows_are_not_a_change(old, tmp_path):
    def reid(rows):
        return [
            dict(r, genotype_evidence_id="GSV2_" + r["genotype_evidence_id"][5:])
            if r["representation_source"] == "ISOLATE_AMR_SUMMARY"
            else r
            for r in rows
        ]

    assert genotype_watcher().detect(old, new_snapshot(tmp_path, {GENOTYPE: reid})) == []


# the mapping


def retire_first_rule(rows):
    return [dict(r, mapping_version="DETERMINANT_DRUG_MAPPING_V2") for r in rows[1:]]


def test_a_retired_mapping_rule_is_drafted_as_mapping_retired(old, tmp_path):
    first = read_rows(MINI_COHORT, MAPPING)[0]
    new = new_snapshot(tmp_path, {MAPPING: retire_first_rule})

    draft = only(MappingWatcher().detect(old, new), "MAPPING_RETIRED")

    assert draft.old_version == "DETERMINANT_DRUG_MAPPING_V1"
    assert draft.new_version == "DETERMINANT_DRUG_MAPPING_V2"
    assert [(e.node_id, e.new_version) for e in draft.changed_entities] == [(first["mapping_rule_id"], None)]


def test_a_new_mapping_version_with_the_same_rules_is_not_a_change(old, tmp_path):
    new = new_snapshot(tmp_path, {MAPPING: lambda rows: [dict(r, mapping_version="M_V2") for r in rows]})

    assert MappingWatcher().detect(old, new) == []


def test_changed_rules_under_the_same_mapping_version_are_refused(old, tmp_path):
    new = new_snapshot(tmp_path, {MAPPING: lambda rows: rows[1:]})

    with pytest.raises(SnapshotError, match="needs a new version"):
        MappingWatcher().detect(old, new)


# every draft


def drop_first_used_genotype_row(rows):
    removed = first_used_genotype_row(rows)["genotype_evidence_id"]
    return [r for r in rows if r["genotype_evidence_id"] != removed]


# one corrected AST row, one removed genotype row and one retired mapping rule
def all_changes():
    return {
        AST: lambda rows: [flip_phenotype(rows[0]), *rows[1:]],
        GENOTYPE: drop_first_used_genotype_row,
        MAPPING: retire_first_rule,
    }


def test_every_draft_is_a_change_event_the_registry_accepts(old, tmp_path):
    drafts = detect_changes(default_watchers(), old, new_snapshot(tmp_path, all_changes()))

    assert sorted(d.change_type for d in drafts) == ["AST_CORRECTED", "GENOTYPE_CHANGED", "MAPPING_RETIRED"]
    for draft in drafts:
        event = ChangeEvent(
            change_id="CHG-CHECK",
            type=draft.change_type,
            old_version=draft.old_version,
            new_version=draft.new_version,
            changed_entities=draft.changed_entities,
            initiator="test",
        )
        assert validate_shape(event, default_registry) == [], draft.change_type


def test_the_same_finding_always_gets_the_same_draft_id(old, tmp_path):
    new = new_snapshot(tmp_path, all_changes())
    first = [d.draft_id(OLD_ID, NEW_ID) for d in detect_changes(default_watchers(), old, new)]
    again = [d.draft_id(OLD_ID, NEW_ID) for d in detect_changes(default_watchers(), old, new)]

    assert first == again
    assert len(set(first)) == 3


def test_a_draft_summary_can_be_stored_as_json(old, tmp_path):
    for draft in detect_changes(default_watchers(), old, new_snapshot(tmp_path, all_changes())):
        assert isinstance(draft, DraftChange)
        json.dumps(dict(draft.summary))
