# the evidence in force (I-20): what an overlay of evidence changes does to the frozen rows, without a database

import pytest

from amrtrace.ingest.evidence_in_force import EvidenceNotInForce, EvidenceOverlay, evidence_changes
from amrtrace.ingest.frozen_v1 import FrozenTables


def ast(row_id, target, phenotype="S"):
    return {"ast_evidence_id": row_id, "target_acc": target, "antibiotic_normalized": "drugzol",
            "phenotype_normalized": phenotype}


def genotype(row_id, target):
    return {"genotype_evidence_id": row_id, "target_acc": target, "representation_source": "DETAILED"}


def tables(*targets):
    return FrozenTables(
        isolates=[{"target_acc": t} for t in targets],
        ast=[ast("A1", "T1"), ast("A2", "T2")],
        genotype=[genotype("G1", "T1"), genotype("G2", "T2")],
        mapping=[],
    )


def overlay(removed_ast=(), added_ast=(), removed_genotype=(), added_genotype=()):
    return EvidenceOverlay(
        change_ids=("CHG",),
        removed={"ast_evidence": frozenset(removed_ast), "genotype_evidence": frozenset(removed_genotype)},
        added={"ast_evidence": tuple(added_ast), "genotype_evidence": tuple(added_genotype)},
    )


def ids(rows, column):
    return sorted(r[column] for r in rows)


def test_an_edit_replaces_the_row_and_leaves_every_other_row_untouched():
    base = tables("T1", "T2")
    result = overlay(removed_ast={"A1"}, added_ast=[ast("A1_V2", "T1", "R")]).apply(base)
    assert ids(result.ast, "ast_evidence_id") == ["A1_V2", "A2"]
    assert next(r for r in result.ast if r["ast_evidence_id"] == "A2") is base.ast[1]
    assert result.genotype == base.genotype


def test_a_removed_row_that_is_not_in_force_is_refused():
    with pytest.raises(EvidenceNotInForce, match="A9"):
        overlay(removed_ast={"A9"}).apply(tables("T1", "T2"))


def test_an_added_row_already_in_force_is_refused():
    with pytest.raises(EvidenceNotInForce, match="G2"):
        overlay(added_genotype=[genotype("G2", "T2")]).apply(tables("T1", "T2"))


def test_a_partial_batch_skips_rows_of_other_isolates():
    # the API reads one batch of isolates at a time: T2's rows are not in it
    batch = FrozenTables(isolates=[{"target_acc": "T1"}], ast=[ast("A1", "T1")], genotype=[genotype("G1", "T1")],
                         mapping=[])
    result = overlay(removed_ast={"A2"}, added_ast=[ast("A2_V2", "T2")],
                     added_genotype=[genotype("G3", "T1")]).apply(batch, partial=True)
    assert ids(result.ast, "ast_evidence_id") == ["A1"]
    assert ids(result.genotype, "genotype_evidence_id") == ["G1", "G3"]


def test_an_empty_overlay_returns_the_same_tables():
    base = tables("T1")
    assert EvidenceOverlay((), {}, {}).apply(base) is base


def test_a_release_vector_lists_its_evidence_changes_oldest_first():
    assert evidence_changes(None) == []
    assert evidence_changes({"source_snapshot_id": "S1"}) == []
    assert evidence_changes({"evidence_changes": ["C1", "C2"]}) == ["C1", "C2"]
