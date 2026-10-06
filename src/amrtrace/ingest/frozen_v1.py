# adapter for the frozen V1 files: turns their rows into the neutral inputs the evaluator expects
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from amrtrace.evaluator.types import CaseInputs, VersionVector

# vocabulary of the frozen files, kept here so the engine never sees it
DETAILED_SOURCE = "MICROBIGGE"
SUMMARY_SOURCE = "ISOLATE_AMR_SUMMARY"
DETAILED_CONTEXT = "SOURCE_CLASSIFICATION"
SUMMARY_CONTEXT = "SUMMARY_SYMBOL"
RESISTANCE_SUBTYPES = frozenset({"AMR", "POINT", "POINT_DISRUPT"})
VALID_ANALYSIS_TYPES = frozenset({"COMBINED", "NUCLEOTIDE"})

# a control character that cannot appear in the data, used to glue key parts together
KEY_SEPARATOR = "\x1f"

# where each frozen table lives under data/raw, and the columns we actually need
ISOLATES_FILE = "curated_v1/isolates_curated.parquet"
AST_FILE = "curated_v1/ast_evidence_curated.parquet"
GENOTYPE_FILE = "curated_v1/genotype_evidence_curated.parquet"
MAPPING_FILE = "mapping_v1/determinant_drug_mapping_v1.parquet"

ISOLATE_COLUMNS = [
    "target_acc",
    "amrfinderplus_applied",
    "amrfinderplus_analysis_type",
    "amrfinderplus_version",
    "refgene_db_version",
    "source_snapshot_id",
    "curation_rule_version",
]
AST_COLUMNS = [
    "ast_evidence_id",
    "target_acc",
    "antibiotic_normalized",
    "phenotype_normalized",
]
GENOTYPE_COLUMNS = [
    "genotype_evidence_id",
    "representation_source",
    "target_acc",
    "element_raw",
    "subtype_raw",
    "subclass_raw",
    "refgene_db_version",
]
MAPPING_COLUMNS = [
    "mapping_rule_id",
    "mapping_version",
    "mapping_context",
    "source_db_version",
    "determinant_identity",
    "source_subtype",
    "source_subclass",
    "source_classifications_json",
    "candidate_antibiotic",
    "mapping_strength",
    "relationship",
]


# the four source tables as plain rows, wherever they were loaded from
@dataclass(frozen=True)
class FrozenTables:
    isolates: list[dict]
    ast: list[dict]
    genotype: list[dict]
    mapping: list[dict]


def read_frozen_tables(data_dir: Path) -> FrozenTables:
    # imported here so the rest of the module works without the parquet reader installed
    import pyarrow.parquet as pq

    def rows(relative_path: str, columns: list[str]) -> list[dict]:
        return pq.read_table(
            Path(data_dir) / relative_path, columns=columns
        ).to_pylist()

    return FrozenTables(
        isolates=rows(ISOLATES_FILE, ISOLATE_COLUMNS),
        ast=rows(AST_FILE, AST_COLUMNS),
        genotype=rows(GENOTYPE_FILE, GENOTYPE_COLUMNS),
        mapping=rows(MAPPING_FILE, MAPPING_COLUMNS),
    )


# same recipe as the V1 builder, so the ids line up with the frozen release
def stable_case_id(target_acc: str, antibiotic: str) -> str:
    text = json.dumps(
        [target_acc, antibiotic],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "CASE_" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# technical clean-up only: underscores, repeated spaces and letter case are ignored
def subclass_link_key(value) -> str:
    if value is None:
        return "<NULL>"
    return " ".join(str(value).replace("_", " ").split()).upper()


def _detailed_key(determinant, db_version, subtype, subclass) -> str:
    return KEY_SEPARATOR.join(
        (
            "D",
            str(determinant),
            str(db_version),
            str(subtype),
            subclass_link_key(subclass),
        )
    )


def _summary_key(determinant, db_version) -> str:
    return KEY_SEPARATOR.join(("S", str(determinant), str(db_version)))


# builds one neutral rule per link key and antibiotic, and notes which database versions exist
def _index_mapping(mapping: list[dict], panel: frozenset) -> tuple[dict, set]:
    rules = {}
    available_versions = set()
    for row in mapping:
        antibiotic = str(row["candidate_antibiotic"])
        if antibiotic not in panel:
            continue
        available_versions.add(str(row["source_db_version"]))

        context = str(row["mapping_context"])
        if context == DETAILED_CONTEXT:
            link_key = _detailed_key(
                row["determinant_identity"],
                row["source_db_version"],
                row["source_subtype"],
                row["source_subclass"],
            )
        elif context == SUMMARY_CONTEXT:
            link_key = _summary_key(
                row["determinant_identity"], row["source_db_version"]
            )
        else:
            continue

        if (link_key, antibiotic) in rules:
            raise ValueError(
                f"mapping link key is not unique for {antibiotic}: {link_key!r}"
            )
        rules[(link_key, antibiotic)] = {
            "mapping_rule_id": str(row["mapping_rule_id"]),
            "link_key": link_key,
            "mapping_context": context,
            "mapping_strength": str(row["mapping_strength"]),
            "relationship": str(row["relationship"]),
            "source_subclass": row["source_subclass"],
            "source_classifications_json": row["source_classifications_json"],
        }
    return rules, available_versions


def _has_identity(row: dict) -> bool:
    return (
        row["target_acc"] is not None
        and row["element_raw"] is not None
        and row["refgene_db_version"] is not None
    )


# picks one genotype representation per isolate, so the same finding is never counted twice
def _authoritative_rows(genotype: list[dict]) -> dict:
    detailed = defaultdict(list)
    for row in genotype:
        if (
            row["representation_source"] != DETAILED_SOURCE
            or row["subtype_raw"] not in RESISTANCE_SUBTYPES
        ):
            continue
        if not _has_identity(row):
            continue
        detailed[str(row["target_acc"])].append(
            {
                "genotype_evidence_id": str(row["genotype_evidence_id"]),
                "determinant": str(row["element_raw"]),
                "evidence_type": DETAILED_SOURCE,
                "link_key": _detailed_key(
                    row["element_raw"],
                    row["refgene_db_version"],
                    row["subtype_raw"],
                    row["subclass_raw"],
                ),
            }
        )

    # the summary is only a fallback for isolates with no detailed resistance evidence
    fallback = defaultdict(list)
    for row in genotype:
        if row["representation_source"] != SUMMARY_SOURCE or not _has_identity(row):
            continue
        target = str(row["target_acc"])
        if target in detailed:
            continue
        fallback[target].append(
            {
                "genotype_evidence_id": str(row["genotype_evidence_id"]),
                "determinant": str(row["element_raw"]),
                "evidence_type": SUMMARY_SOURCE,
                "link_key": _summary_key(row["element_raw"], row["refgene_db_version"]),
            }
        )

    rows_by_target = dict(detailed)
    rows_by_target.update(fallback)
    return rows_by_target


def _is_blank(value) -> bool:
    return value is None or str(value).strip() == ""


# section 3 of the case rules: was the genotype analysis usable at all
def _analysis_valid(isolate: dict, available_versions: set) -> bool:
    applied = isolate["amrfinderplus_applied"]
    applied_ok = (
        applied is True or applied == 1 or str(applied).strip().lower() in {"1", "true"}
    )
    return (
        applied_ok
        and str(isolate["amrfinderplus_analysis_type"]) in VALID_ANALYSIS_TYPES
        and not _is_blank(isolate["amrfinderplus_version"])
        and isolate["refgene_db_version"] is not None
        and str(isolate["refgene_db_version"]) in available_versions
    )


def build_case_inputs(
    tables: FrozenTables, panel: tuple[str, ...], organism: str
) -> Iterator[CaseInputs]:
    panel_set = frozenset(panel)
    panel_order = {antibiotic: index for index, antibiotic in enumerate(panel)}

    isolates = {}
    for row in tables.isolates:
        target = str(row["target_acc"])
        if target in isolates:
            raise ValueError(f"isolate {target} appears more than once")
        isolates[target] = row

    rules, available_versions = _index_mapping(tables.mapping, panel_set)
    rows_by_target = _authoritative_rows(tables.genotype)

    # a case exists only where at least one AST row exists for a panel antibiotic
    ast_groups = defaultdict(list)
    for row in tables.ast:
        antibiotic = str(row["antibiotic_normalized"])
        if antibiotic in panel_set:
            ast_groups[(str(row["target_acc"]), antibiotic)].append(row)

    for target, antibiotic in sorted(
        ast_groups, key=lambda key: (panel_order[key[1]], key[0])
    ):
        isolate = isolates.get(target)
        if isolate is None:
            raise ValueError(f"AST rows exist for {target} but there is no isolate row")

        ast_rows = tuple(
            {
                "ast_evidence_id": str(row["ast_evidence_id"]),
                "phenotype": row["phenotype_normalized"],
            }
            for row in sorted(
                ast_groups[(target, antibiotic)],
                key=lambda row: str(row["ast_evidence_id"]),
            )
        )
        genotype_rows = tuple(
            sorted(
                rows_by_target.get(target, ()),
                key=lambda row: row["genotype_evidence_id"],
            )
        )

        # only the rules this case can actually reach are handed over
        mapping_rules = []
        for link_key in sorted({row["link_key"] for row in genotype_rows}):
            rule = rules.get((link_key, antibiotic))
            if rule is None:
                raise ValueError(
                    f"no mapping rule for {target} / {antibiotic} / {link_key!r}"
                )
            mapping_rules.append(rule)

        yield CaseInputs(
            case_id=stable_case_id(target, antibiotic),
            target_acc=target,
            antibiotic=antibiotic,
            organism=organism,
            refgene_db_version=str(isolate["refgene_db_version"]),
            genotype_analysis_valid=_analysis_valid(isolate, available_versions),
            ast_rows=ast_rows,
            genotype_rows=genotype_rows,
            mapping_rules=tuple(mapping_rules),
            interpretation_rules=(),
        )


# a release-wide value must be the same on every row, otherwise it is not release-wide
def _single_value(rows: list[dict], column: str) -> str:
    values = {str(row[column]) for row in rows}
    if len(values) != 1:
        raise ValueError(f"expected one value for {column}, found {sorted(values)}")
    return values.pop()


def build_version_vector(
    tables: FrozenTables, case_rule_version: str, panel_id: str, evaluator_version: str
) -> VersionVector:
    return VersionVector(
        source_snapshot_id=_single_value(tables.isolates, "source_snapshot_id"),
        curation_rule_version=_single_value(tables.isolates, "curation_rule_version"),
        amrfinderplus_version=_single_value(tables.isolates, "amrfinderplus_version"),
        mapping_version=_single_value(tables.mapping, "mapping_version"),
        interpretation_version=None,
        case_rule_version=case_rule_version,
        panel_id=panel_id,
        evaluator_version=evaluator_version,
    )
