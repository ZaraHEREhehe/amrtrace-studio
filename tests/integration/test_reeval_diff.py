"""I-13: before/after data for one case.

Uses the I-10 world (five cases, a fake evaluator whose rules are written out in TABLE):
  C4   R under T1, S under T2          -> state changes
  CLE4 UNRESOLVED (censored) -> S      -> state and uncertainty change
  CGE4 R under both                    -> selected, re-evaluated, same conclusion (re-verified)
  C2   S under both                    -> not selected, keeps its R1 row
"""

import dataclasses
import json

import pytest

from amrtrace.changes import register_version
from amrtrace.evaluator.types import DependencyRecord
from amrtrace.ledger import ReleaseNotFound
from amrtrace.reeval import CaseNotFound, case_diff
from tests.integration import test_reeval_compare as compare_world
from tests.integration.test_reeval_compare import V2, evaluate, make_world, select, selective, tweak

EXTRA = DependencyRecord("positive_support", "derived_from", "mapping_rule", "X", "V1", None)   # same as an existing record


def twice(result):
    return dataclasses.replace(result, dependency_records=result.dependency_records + (EXTRA,))


@pytest.fixture
def world(conn):
    for node in ("T1", "T2"):
        register_version(conn, "interpretation_rule", "RK", node)
    make_world(conn)
    return conn


@pytest.fixture
def published(world):
    select(world)
    selective(world, publish=True)
    return world


def changes(diff):
    return [(f.field, f.before, f.after) for f in diff.state_changes]


def test_a_changed_case_lists_exactly_the_fields_that_changed(published):
    diff = case_diff(published, "C4")
    assert diff.outcome == "STATE_CHANGED"
    assert changes(diff) == [("state_code", "CONCORDANT_RESISTANT", "CONCORDANT_SUSCEPTIBLE"),
                             ("phenotype_state", "P-CONCORDANT_RESISTANT", "P-CONCORDANT_SUSCEPTIBLE")]
    assert (diff.before.release_id, diff.after.release_id) == ("R1", "R2")
    assert diff.explanation_changed
    assert diff.before.explanation["state"] == "CONCORDANT_RESISTANT"
    assert diff.after.explanation["state"] == "CONCORDANT_SUSCEPTIBLE"
    assert diff.triggered_by_change_id == "CHG-I"


def test_uncertainty_is_part_of_the_conclusion(published):
    diff = case_diff(published, "CLE4")
    assert diff.outcome == "STATE_CHANGED"
    assert ("uncertainty_reason", "CENSORED", None) in changes(diff)


def test_versions_that_differ_are_named(published):
    diff = case_diff(published, "C4")
    assert [(v.name, v.before, v.after) for v in diff.version_changes] == [("interpretation_version", "T1", "T2")]


def test_dependency_records_split_into_removed_added_and_unchanged(published):
    diff = case_diff(published, "C4")
    assert [(r.node_type, r.node_id, r.node_version) for r in diff.dependencies_removed] == [("interpretation_rule", "RK", "T1")]
    assert [(r.node_type, r.node_id, r.node_version) for r in diff.dependencies_added] == [("interpretation_rule", "RK", "T2")]
    assert diff.dependencies_unchanged == 2          # the provenance record and the positive support are the same


def test_a_duplicated_record_still_shows_as_added(world):
    # the multiset matters: a record present twice on one side and once on the other is a difference
    select(world)
    selective(world, evaluator=tweak(evaluate, "C4", twice), publish=True)
    diff = case_diff(world, "C4")
    assert [(r.node_type, r.node_id) for r in diff.dependencies_added].count(("mapping_rule", "X")) == 1
    assert diff.dependencies_unchanged == 2


def test_a_duplicated_record_that_is_gone_shows_as_removed(conn):
    for node in ("T1", "T2"):
        register_version(conn, "interpretation_rule", "RK", node)
    make_world(conn, evaluator=tweak(evaluate, "C4", twice))
    select(conn)
    selective(conn, publish=True)
    diff = case_diff(conn, "C4")
    assert [(r.node_type, r.node_id) for r in diff.dependencies_removed].count(("mapping_rule", "X")) == 1


def test_a_record_duplicated_on_both_sides_counts_every_copy_as_unchanged(conn):
    for node in ("T1", "T2"):
        register_version(conn, "interpretation_rule", "RK", node)
    both = tweak(evaluate, "C4", twice)
    make_world(conn, evaluator=both)
    select(conn)
    selective(conn, evaluator=both, publish=True)
    assert case_diff(conn, "C4").dependencies_unchanged == 3        # the provenance record plus two copies


def test_only_versions_that_differ_are_listed(conn, monkeypatch):
    # both release vectors carry a "panel" key with the same value: it must not appear as a change
    real_load, real_reevaluate = compare_world.load_baseline_release, compare_world.reevaluate
    monkeypatch.setattr(compare_world, "load_baseline_release",
                        lambda conn, rid, vector, states: real_load(conn, rid, {**vector, "panel": "P"}, states))
    monkeypatch.setattr(compare_world, "reevaluate",
                        lambda conn, cid, rid, vector, *a, **k: real_reevaluate(conn, cid, rid, {**vector, "panel": "P"}, *a, **k))
    for node in ("T1", "T2"):
        register_version(conn, "interpretation_rule", "RK", node)
    make_world(conn)
    select(conn)
    selective(conn, publish=True)
    assert [v.name for v in case_diff(conn, "C4").version_changes] == ["interpretation_version"]


def test_the_same_state_on_both_sides_is_not_triggered_by_a_change(published):
    diff = case_diff(published, "C4", before_release="R2", after_release="R2")
    assert diff.outcome == "UNCHANGED"
    assert diff.triggered_by_change_id is None
    assert diff.after.refgene_db_version == "DB1"


def test_a_new_evaluator_version_is_a_version_change(world):
    select(world)
    selective(world, versions=dataclasses.replace(V2, evaluator_version="EV2"), publish=True)
    diff = case_diff(world, "C4")
    assert ("evaluator_version", "EV1", "EV2") in [(v.name, v.before, v.after) for v in diff.version_changes]


def test_a_selected_case_with_the_same_conclusion_is_reported_as_re_verified(published):
    diff = case_diff(published, "CGE4")
    assert diff.outcome == "RE_VERIFIED_UNCHANGED"
    assert diff.state_changes == ()
    assert not diff.explanation_changed
    assert diff.after.verification_status == "RE_VERIFIED_UNCHANGED"
    assert diff.after.state_id != diff.before.state_id         # it has a new ledger entry
    assert diff.before.input_hash == diff.after.input_hash == "iCGE4"
    assert [(v.name, v.before, v.after) for v in diff.version_changes] == [("interpretation_version", "T1", "T2")]


def test_a_case_nothing_touched_has_one_row_and_nothing_changed(published):
    diff = case_diff(published, "C2", before_release="R1", after_release="R2")
    assert diff.outcome == "UNCHANGED"
    assert diff.before.state_id == diff.after.state_id
    assert diff.version_changes == () and diff.dependencies_removed == () and diff.dependencies_added == ()
    assert diff.dependencies_unchanged == 3
    assert diff.triggered_by_change_id is None


def test_with_only_one_published_state_there_is_nothing_to_compare(published):
    diff = case_diff(published, "C2")
    assert diff.outcome == "FIRST_STATE"
    assert diff.before is None and diff.after.release_id == "R1"
    assert diff.dependencies_unchanged == 0 and len(diff.dependencies_added) == 3


def test_a_draft_release_is_invisible(world):
    select(world)
    selective(world, publish=False)                           # R2 stays DRAFT
    diff = case_diff(world, "C4")
    assert diff.outcome == "FIRST_STATE" and diff.after.release_id == "R1"


def test_releases_can_be_named_and_agree_with_the_default(published):
    assert case_diff(published, "C4", before_release="R1", after_release="R2") == case_diff(published, "C4")
    reverse = case_diff(published, "C4", before_release="R2", after_release="R1")
    assert reverse.outcome == "STATE_CHANGED"
    assert changes(reverse)[0] == ("state_code", "CONCORDANT_SUSCEPTIBLE", "CONCORDANT_RESISTANT")


def test_a_case_with_no_published_state(published):
    published.execute("INSERT INTO isolate (target_acc) VALUES ('PDT_NEW')")
    published.execute('INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
                      ("CNEW", "PDT_NEW", "gentamicin", "P"))
    diff = case_diff(published, "CNEW")
    assert (diff.outcome, diff.before, diff.after) == ("NO_STATE", None, None)
    assert diff.version_changes == () and diff.dependencies_added == ()


def test_unknown_case_and_unknown_release_are_errors(published):
    with pytest.raises(CaseNotFound):
        case_diff(published, "NOPE")
    with pytest.raises(ReleaseNotFound):
        case_diff(published, "C4", after_release="R99")


def test_the_dict_form_is_plain_json(published):
    data = case_diff(published, "C4").as_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["outcome"] == "STATE_CHANGED"
    assert data["state_changes"][0] == {"field": "state_code", "before": "CONCORDANT_RESISTANT", "after": "CONCORDANT_SUSCEPTIBLE"}
    assert data["after"]["release_id"] == "R2"


def test_reading_a_diff_writes_nothing(published):
    tables = ("case_state", "dependency", "release", "review_event", "reeval_run")
    before = [published.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables]
    for case in ("C4", "CGE4", "C2", "CLE4", "C8"):
        case_diff(published, case)
    assert [published.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables] == before
