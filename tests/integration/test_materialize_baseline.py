# baseline graph tests: a tiny cohort is evaluated, checked against the ledger and stored
import pytest
from psycopg.types.json import Jsonb

import amrtrace.ingest.materialize_baseline as materialize_module
import amrtrace.policies  # noqa: F401
from amrtrace.deps.materialize import MaterializeSummary
from amrtrace.evaluator import evaluate
from amrtrace.ingest.frozen_v1 import (
    FrozenTables,
    build_case_inputs,
    build_version_vector,
)
from amrtrace.ingest.materialize_baseline import materialize_baseline

pytestmark = pytest.mark.integration

RELEASE = "R_BASE"
PANEL = ("gentamicin",)
ORGANISM = "Testus organismus"
DB = "2000-01-01.1"
VECTOR = {
    "source_snapshot_id": "SNAP_X",
    "curation_rule_version": "CURATION_X",
    "mapping_version": "MAPPING_X",
    "case_rule_version": "CASE_RULES_V1",
    "panel_id": "PANEL_X",
    "evaluator_version": "0.1.0",
    "interpretation_version": None,
    # extra keys in the stored vector are allowed
    "refgene_db_versions": [DB],
}


def isolate(target):
    return {
        "target_acc": target,
        "amrfinderplus_applied": 1,
        "amrfinderplus_analysis_type": "COMBINED",
        "amrfinderplus_version": "9.9.9",
        "refgene_db_version": DB,
        "source_snapshot_id": "SNAP_X",
        "curation_rule_version": "CURATION_X",
    }


def mapping(rule_id, element, strength, relationship):
    return {
        "mapping_rule_id": rule_id,
        "mapping_version": "MAPPING_X",
        "mapping_context": "SOURCE_CLASSIFICATION",
        "source_db_version": DB,
        "determinant_identity": element,
        "source_subtype": "AMR",
        "source_subclass": "CLASS ONE",
        "source_classifications_json": "",
        "candidate_antibiotic": "gentamicin",
        "mapping_strength": strength,
        "relationship": relationship,
    }


# two isolates: one resistant with decisive support, one susceptible with only an unmapped gene
@pytest.fixture
def tables():
    def genotype(gen_id, target, element):
        return {
            "genotype_evidence_id": gen_id,
            "representation_source": "MICROBIGGE",
            "target_acc": target,
            "element_raw": element,
            "subtype_raw": "AMR",
            "subclass_raw": "CLASS_ONE",
            "refgene_db_version": DB,
        }

    def ast(ast_id, target, phenotype):
        return {
            "ast_evidence_id": ast_id,
            "target_acc": target,
            "antibiotic_normalized": "gentamicin",
            "phenotype_normalized": phenotype,
        }

    return FrozenTables(
        isolates=[isolate("ISO_1"), isolate("ISO_2")],
        ast=[ast("AST_1", "ISO_1", "R"), ast("AST_2", "ISO_2", "S")],
        genotype=[
            genotype("GEN_1", "ISO_1", "geneR"),
            genotype("GEN_2", "ISO_2", "geneU"),
        ],
        mapping=[
            mapping("RULE_R", "geneR", "DIRECT_DRUG_SUPPORT", "SUPPORTS_RESISTANCE"),
            mapping("RULE_U", "geneU", "NO_CANDIDATE_MAPPING", "UNMAPPED"),
        ],
    )


# fills the database the way the cohort loader and the baseline loader would, leaving the release a draft
def store_draft(conn, tables):
    versions = build_version_vector(tables, "CASE_RULES_V1", "PANEL_X", "0.1.0")
    conn.execute(
        "INSERT INTO release (release_id, version_vector, status) VALUES (%s, %s, 'DRAFT')",
        (RELEASE, Jsonb(VECTOR)),
    )
    states = {}
    for inputs in build_case_inputs(tables, PANEL, ORGANISM):
        result = evaluate(inputs, versions)
        conn.execute(
            "INSERT INTO isolate (target_acc) VALUES (%s)", (inputs.target_acc,)
        )
        conn.execute(
            'INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
            (inputs.case_id, inputs.target_acc, inputs.antibiotic, "PANEL_X"),
        )
        conn.execute(
            "INSERT INTO case_state (case_id, release_id, state_code, phenotype_state, genotype_state, "
            "uncertainty_reason, explanation, verification_status) VALUES (%s, %s, %s, %s, %s, %s, '{}', 'EVALUATED')",
            (
                inputs.case_id,
                RELEASE,
                result.state_code,
                result.phenotype_state,
                result.genotype_state,
                result.uncertainty_reason,
            ),
        )
        states[inputs.target_acc] = (inputs.case_id, result.state_code)
    return states


# a release that was published before task A-17, the way existing databases hold R1
@pytest.fixture
def baseline(conn, tables):
    states = store_draft(conn, tables)
    conn.execute(
        "UPDATE release SET status = 'PUBLISHED' WHERE release_id = %s", (RELEASE,)
    )
    return states


# a release stored the way the baseline loader stores it now: a draft waiting for its graph
@pytest.fixture
def draft(conn, tables):
    return store_draft(conn, tables)


def release_status(conn):
    return conn.execute(
        "SELECT status FROM release WHERE release_id = %s", (RELEASE,)
    ).fetchone()[0]


def published_releases(conn):
    return conn.execute(
        "SELECT count(*) FROM release WHERE status = 'PUBLISHED'"
    ).fetchone()[0]


def stored_rows(conn):
    return conn.execute(
        "SELECT count(*) FROM dependency WHERE release_id = %s", (RELEASE,)
    ).fetchone()[0]


def test_the_graph_is_stored_when_the_evaluator_agrees_with_the_ledger(
    conn, tables, baseline
):
    assert baseline["ISO_1"][1] == "CONCORDANT_RESISTANT"
    assert baseline["ISO_2"][1] == "CONCORDANT_SUSCEPTIBLE"

    report = materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)

    assert report.cases_checked == 2
    assert report.summary.cases_written == 2
    # resistant case: 1 lab result, 1 evidence, 1 supporting, 1 rule, 1 supporting, 7 versions = 12
    # susceptible case: the same without the two supporting edges = 10
    assert report.summary.dependency_rows == stored_rows(conn) == 22
    assert report.summary.applicability_rows == 2


def test_a_second_run_checks_again_and_writes_nothing(conn, tables, baseline):
    materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)

    report = materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)

    assert report.cases_checked == 2
    assert report.summary.cases_written == 0 and report.summary.cases_skipped == 2
    assert stored_rows(conn) == 22


def test_a_state_that_differs_from_the_ledger_stops_the_run_and_stores_nothing(
    conn, tables, baseline
):
    tables.ast[1]["phenotype_normalized"] = "R"

    with pytest.raises(ValueError, match="the ledger holds"):
        materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)
    assert stored_rows(conn) == 0


def test_a_ledger_case_missing_from_the_files_stops_the_run_and_stores_nothing(
    conn, tables, baseline
):
    del tables.ast[1]

    with pytest.raises(ValueError, match="were not built"):
        materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)
    assert stored_rows(conn) == 0


def test_a_case_built_from_the_files_but_absent_from_the_release_stops_the_run(
    conn, tables, baseline
):
    tables.isolates.append(isolate("ISO_3"))
    tables.ast.append(
        {
            "ast_evidence_id": "AST_3",
            "target_acc": "ISO_3",
            "antibiotic_normalized": "gentamicin",
            "phenotype_normalized": "S",
        }
    )

    with pytest.raises(ValueError, match="is not in release"):
        materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)
    assert stored_rows(conn) == 0


def test_versions_that_differ_from_the_release_stop_the_run(conn, tables, baseline):
    for row in tables.mapping:
        row["mapping_version"] = "MAPPING_NEWER"

    with pytest.raises(ValueError, match="mapping_version differs"):
        materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)
    assert stored_rows(conn) == 0


def test_an_unknown_release_is_refused(conn, tables):
    with pytest.raises(LookupError, match="does not exist"):
        materialize_baseline(conn, tables, "R_MISSING", PANEL, ORGANISM)


def test_a_release_without_states_is_refused(conn, tables):
    conn.execute(
        "INSERT INTO release (release_id, version_vector, status) VALUES (%s, %s, 'DRAFT')",
        ("R_EMPTY", Jsonb(VECTOR)),
    )
    with pytest.raises(LookupError, match="no states"):
        materialize_baseline(conn, tables, "R_EMPTY", PANEL, ORGANISM)


# task A-17: a baseline is published only once its graph is stored and checked


def test_a_draft_baseline_is_published_once_its_graph_is_stored(conn, tables, draft):
    report = materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)

    assert report.status == "PUBLISHED"
    assert release_status(conn) == "PUBLISHED"
    assert stored_rows(conn) == 22


def test_a_draft_baseline_can_be_left_unpublished_on_request(conn, tables, draft):
    report = materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM, publish=False)

    assert report.status == "DRAFT"
    assert stored_rows(conn) == 22


def test_an_already_published_baseline_is_left_as_it_is(conn, tables, baseline):
    report = materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)

    assert report.status == "PUBLISHED"
    assert stored_rows(conn) == 22


def test_a_graph_step_that_fails_leaves_the_draft_unpublished_and_empty(
    conn, tables, draft, monkeypatch
):
    real_materialize = materialize_module.materialize

    # the rows are written and then the step breaks, as a crash half way through would
    def breaks_after_writing(*args, **kwargs):
        real_materialize(*args, **kwargs)
        raise RuntimeError("graph step failed")

    monkeypatch.setattr(materialize_module, "materialize", breaks_after_writing)

    with pytest.raises(RuntimeError, match="graph step failed"):
        materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)

    assert release_status(conn) == "DRAFT"
    assert stored_rows(conn) == 0
    assert published_releases(conn) == 0


# A-19 (SRF09): the interruption is followed by a retry; the release is published only by the run that stores the graph
def test_an_interrupted_graph_step_can_be_retried_and_only_the_retry_publishes(
    conn, tables, draft, monkeypatch
):
    real_materialize = materialize_module.materialize

    def breaks_after_writing(*args, **kwargs):
        real_materialize(*args, **kwargs)
        raise RuntimeError("graph step failed")

    monkeypatch.setattr(materialize_module, "materialize", breaks_after_writing)
    with pytest.raises(RuntimeError, match="graph step failed"):
        materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)
    assert (release_status(conn), stored_rows(conn), published_releases(conn)) == ("DRAFT", 0, 0)

    monkeypatch.setattr(materialize_module, "materialize", real_materialize)
    report = materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)
    assert report.status == "PUBLISHED"
    assert (release_status(conn), stored_rows(conn)) == ("PUBLISHED", 22)


def test_a_graph_missing_cases_is_refused_and_the_draft_stays_unpublished(
    conn, tables, draft, monkeypatch
):
    # a broken graph step that reports success but stores nothing
    def stores_nothing(conn, release_id, evaluations, versions):
        for _ in evaluations:
            pass
        return MaterializeSummary(
            cases_written=0, cases_skipped=0, dependency_rows=0, applicability_rows=0
        )

    monkeypatch.setattr(materialize_module, "materialize", stores_nothing)

    with pytest.raises(ValueError, match="have no dependency rows"):
        materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)

    assert release_status(conn) == "DRAFT"
    assert published_releases(conn) == 0


def test_a_state_mismatch_leaves_the_draft_unpublished(conn, tables, draft):
    tables.ast[1]["phenotype_normalized"] = "R"

    with pytest.raises(ValueError, match="the ledger holds"):
        materialize_baseline(conn, tables, RELEASE, PANEL, ORGANISM)

    assert release_status(conn) == "DRAFT"
    assert stored_rows(conn) == 0
