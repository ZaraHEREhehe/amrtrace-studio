# materializer tests against a real database: what is stored, and that a second run changes nothing
from dataclasses import replace

import psycopg
import pytest
from psycopg import pq

from amrtrace.deps.materialize import materialize
from amrtrace.evaluator import (
    CaseInputs,
    DependencyRecord,
    VersionVector,
    evaluate,
    register_genotype_policy,
)
from amrtrace.evaluator import constants as c

pytestmark = pytest.mark.integration

RULE_VERSION = "TEST_RULES_DEPS"
RELEASE = "R_TEST"


# a tiny stand-in rule set, so these tests do not depend on any real drug rules
def _toy_policy(antibiotic, items):
    decisive = [item for item in items if item.get("toy") == "decisive"]
    if decisive:
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(decisive)
    return c.GENOTYPE_NO_MAPPED_SUPPORT, ()


register_genotype_policy(RULE_VERSION, _toy_policy)

VERSIONS = VersionVector(
    source_snapshot_id="SNAP_X",
    curation_rule_version="CURATION_X",
    amrfinderplus_version="9.9.9",
    mapping_version="MAPPING_X",
    interpretation_version=None,
    case_rule_version=RULE_VERSION,
    panel_id="PANEL_X",
    evaluator_version="0.1.0",
)


def make_inputs(case_id, determinants=("detA", "detB")):
    genotype_rows = tuple(
        {
            "genotype_evidence_id": f"GEN_{case_id}_{name}",
            "determinant": name,
            "link_key": f"KEY_{name}",
            "evidence_type": "DETAILED",
        }
        for name in determinants
    )
    mapping_rules = tuple(
        {
            "mapping_rule_id": f"RULE_{name}",
            "link_key": f"KEY_{name}",
            "toy": "decisive" if name == "detA" else "none",
        }
        for name in determinants
    )
    return CaseInputs(
        case_id=case_id,
        target_acc="PDT_" + case_id,
        antibiotic="drugzol",
        organism="Testus organismus",
        refgene_db_version="2000-01-01.1",
        genotype_analysis_valid=True,
        ast_rows=({"ast_evidence_id": f"AST_{case_id}", "phenotype": "R"},),
        genotype_rows=genotype_rows,
        mapping_rules=mapping_rules,
        interpretation_rules=(),
    )


def evaluated(*case_ids):
    return [
        (inputs, evaluate(inputs, VERSIONS))
        for inputs in (make_inputs(case_id) for case_id in case_ids)
    ]


def add_release(conn, release_id=RELEASE, status="DRAFT"):
    conn.execute(
        "INSERT INTO release (release_id, version_vector, status) VALUES (%s, '{}'::jsonb, %s)",
        (release_id, status),
    )


def count(conn, table, release_id=RELEASE):
    return conn.execute(
        f"SELECT count(*) FROM {table} WHERE release_id = %s", (release_id,)
    ).fetchone()[0]


def test_every_dependency_record_is_stored(conn, seed_cases):
    seed_cases("CASE_A")
    add_release(conn)
    ((inputs, result),) = evaluated("CASE_A")

    summary = materialize(conn, RELEASE, [(inputs, result)], VERSIONS)

    stored = conn.execute(
        "SELECT dep_type, edge_type, node_type, node_id, node_version FROM dependency "
        "WHERE case_id = %s AND release_id = %s",
        ("CASE_A", RELEASE),
    ).fetchall()
    expected = [
        (r.dep_type, r.edge_type, r.node_type, r.node_id, r.node_version)
        for r in result.dependency_records
    ]
    assert sorted(stored, key=str) == sorted(expected, key=str)
    # one lab result, two evidence rows, one supporting, two rules, one supporting, seven versions
    assert summary.dependency_rows == len(expected) == 14
    assert summary.cases_written == 1 and summary.cases_skipped == 0


def test_applicability_is_stored_per_determinant_and_antibiotic(conn, seed_cases):
    seed_cases("CASE_A")
    add_release(conn)

    summary = materialize(conn, RELEASE, evaluated("CASE_A"), VERSIONS)

    stored = conn.execute(
        "SELECT determinant_identity, candidate_antibiotic, organism, evidence_type, rule_set_version "
        "FROM applicability WHERE case_id = %s ORDER BY determinant_identity",
        ("CASE_A",),
    ).fetchall()
    assert stored == [
        ("detA", "drugzol", "Testus organismus", "DETAILED", "MAPPING_X"),
        ("detB", "drugzol", "Testus organismus", "DETAILED", "MAPPING_X"),
    ]
    assert summary.applicability_rows == 2


def test_a_second_run_changes_nothing(conn, seed_cases):
    seed_cases("CASE_A", "CASE_B")
    add_release(conn)
    first = materialize(conn, RELEASE, evaluated("CASE_A", "CASE_B"), VERSIONS)
    before = (count(conn, "dependency"), count(conn, "applicability"))

    second = materialize(conn, RELEASE, evaluated("CASE_A", "CASE_B"), VERSIONS)

    assert (count(conn, "dependency"), count(conn, "applicability")) == before
    assert first.cases_written == 2
    assert second == replace(
        second,
        cases_written=0,
        cases_skipped=2,
        dependency_rows=0,
        applicability_rows=0,
    )


def test_new_cases_are_added_while_finished_ones_are_left_alone(conn, seed_cases):
    seed_cases("CASE_A", "CASE_B")
    add_release(conn)
    materialize(conn, RELEASE, evaluated("CASE_A"), VERSIONS)

    summary = materialize(conn, RELEASE, evaluated("CASE_A", "CASE_B"), VERSIONS)

    assert summary.cases_written == 1 and summary.cases_skipped == 1
    assert count(conn, "dependency") == 28


def test_the_same_case_given_twice_is_written_once(conn, seed_cases):
    seed_cases("CASE_A")
    add_release(conn)

    summary = materialize(conn, RELEASE, evaluated("CASE_A", "CASE_A"), VERSIONS)

    assert summary.cases_written == 1
    assert count(conn, "dependency") == 14


def test_each_release_keeps_its_own_rows(conn, seed_cases):
    seed_cases("CASE_A")
    add_release(conn, "R_ONE")
    add_release(conn, "R_TWO")
    materialize(conn, "R_ONE", evaluated("CASE_A"), VERSIONS)

    summary = materialize(conn, "R_TWO", evaluated("CASE_A"), VERSIONS)

    assert summary.cases_written == 1
    assert (
        count(conn, "dependency", "R_ONE") == count(conn, "dependency", "R_TWO") == 14
    )


def test_node_context_is_stored_as_json(conn, seed_cases):
    seed_cases("CASE_A")
    add_release(conn)
    ((inputs, result),) = evaluated("CASE_A")
    extra = DependencyRecord(
        dep_type="interpretation_rule",
        edge_type="evaluated_against",
        node_type="interpretation_rule",
        node_id="RULE_KEY_X",
        node_version="TABLE_X",
        node_context={"mic": 4.0, "sign": "=="},
    )
    result = replace(result, dependency_records=result.dependency_records + (extra,))

    materialize(conn, RELEASE, [(inputs, result)], VERSIONS)

    stored = conn.execute(
        "SELECT node_context FROM dependency WHERE node_id = %s", ("RULE_KEY_X",)
    ).fetchone()[0]
    assert stored == {"mic": 4.0, "sign": "=="}
    assert (
        conn.execute(
            "SELECT count(*) FROM dependency WHERE node_context IS NULL"
        ).fetchone()[0]
        == 14
    )


def test_a_published_release_still_accepts_its_dependency_rows(conn, seed_cases):
    seed_cases("CASE_A")
    add_release(conn, status="PUBLISHED")

    assert materialize(conn, RELEASE, evaluated("CASE_A"), VERSIONS).cases_written == 1


def test_an_unknown_release_is_refused(conn, seed_cases):
    seed_cases("CASE_A")
    with pytest.raises(LookupError, match="does not exist"):
        materialize(conn, "R_MISSING", evaluated("CASE_A"), VERSIONS)


def test_an_unknown_case_writes_nothing_at_all(conn, seed_cases):
    seed_cases("CASE_A")
    add_release(conn)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        materialize(conn, RELEASE, evaluated("CASE_A", "CASE_NOT_SEEDED"), VERSIONS)

    # the good case in the same batch is undone too, and the connection stays usable
    assert count(conn, "dependency") == 0
    assert count(conn, "applicability") == 0


def test_nothing_is_committed_for_the_caller(conn, seed_cases):
    seed_cases("CASE_A")
    add_release(conn)

    materialize(conn, RELEASE, evaluated("CASE_A"), VERSIONS)

    assert conn.info.transaction_status == pq.TransactionStatus.INTRANS
    conn.rollback()
    assert conn.execute("SELECT count(*) FROM dependency").fetchone()[0] == 0


def test_an_empty_batch_is_fine(conn, seed_cases):
    add_release(conn)
    summary = materialize(conn, RELEASE, [], VERSIONS)
    assert (
        summary.cases_written,
        summary.dependency_rows,
        summary.applicability_rows,
    ) == (0, 0, 0)
