# shared builders so each test only states what it cares about
import pytest

from amrtrace.evaluator import CaseInputs, VersionVector, register_genotype_policy
from amrtrace.evaluator import constants as c

# an invented rule version keeps these tests independent of any real rule set
TEST_RULE_VERSION = "TEST_RULES_X"


# a tiny stand-in policy driven by a flag on each item
def _toy_policy(antibiotic, items):
    decisive = [item for item in items if item.get("toy") == "decisive"]
    if decisive:
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(decisive)
    contextual = [item for item in items if item.get("toy") == "contextual"]
    if contextual:
        return c.GENOTYPE_CONTEXTUAL_SUPPORT, tuple(contextual)
    return c.GENOTYPE_NO_MAPPED_SUPPORT, ()


register_genotype_policy(TEST_RULE_VERSION, _toy_policy)


@pytest.fixture
def versions():
    return VersionVector(
        source_snapshot_id="SNAP_X",
        curation_rule_version="CURATION_X",
        amrfinderplus_version="9.9.9",
        mapping_version="MAPPING_X",
        interpretation_version=None,
        case_rule_version=TEST_RULE_VERSION,
        panel_id="PANEL_X",
        evaluator_version="0.1.0",
    )


@pytest.fixture
def make_inputs():
    def _make(phenotypes=("S",), toys=(), valid=True, ast_ids=None):
        if ast_ids is None:
            ast_ids = [f"AST_{i}" for i in range(len(phenotypes))]
        ast_rows = tuple(
            {"ast_evidence_id": ast_id, "phenotype": phenotype}
            for ast_id, phenotype in zip(ast_ids, phenotypes)
        )
        genotype_rows = tuple(
            {
                "genotype_evidence_id": f"GEN_{i}",
                "determinant": f"detX{i}",
                "link_key": f"KEY_{i}",
            }
            for i in range(len(toys))
        )
        mapping_rules = tuple(
            {"mapping_rule_id": f"RULE_{i}", "link_key": f"KEY_{i}", "toy": toy}
            for i, toy in enumerate(toys)
        )
        return CaseInputs(
            case_id="CASE_abc",
            target_acc="ISO_1",
            antibiotic="drugzol",
            organism="Testus organismus",
            refgene_db_version="2000-01-01.1",
            genotype_analysis_valid=valid,
            ast_rows=ast_rows,
            genotype_rows=genotype_rows,
            mapping_rules=mapping_rules,
            interpretation_rules=(),
        )

    return _make
