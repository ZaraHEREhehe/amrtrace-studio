"""
AMRTraceStudio Curated Dataset v1 builder.

M5.4 implementation of CURATION_RULES_V1.

Reads immutable AMRTRACE_RAW_V1 and creates:
    data/curated_v1/isolates_curated.parquet
    data/curated_v1/ast_evidence_curated.parquet
    data/curated_v1/genotype_evidence_curated.parquet

Also creates:
    manifests/curated_v1.json

This script NEVER modifies Raw Snapshot v1.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import subprocess
import sys
from datetime import date, datetime, time, timezone
from importlib.metadata import version
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = ROOT / "data" / "raw_snapshot_v1"
OUTPUT_DIR = ROOT / "data" / "curated_v1"

RAW_MANIFEST_PATH = (
    ROOT / "manifests" / "raw_snapshot_v1.json"
)

CURATED_MANIFEST_PATH = (
    ROOT / "manifests" / "curated_v1.json"
)

RULES_PATH = (
    ROOT / "docs" / "curation" / "M5_3_CURATION_RULES_V1.md"
)

ISOLATES_PATH = (
    RAW_DIR / "isolates_ast_cohort.parquet"
)

AST_PATH = (
    RAW_DIR / "ast_raw.parquet"
)

GENOTYPE_PATH = (
    RAW_DIR / "genotype_raw.parquet"
)

SUMMARY_PATH = (
    RAW_DIR / "genotype_summary_raw.parquet"
)

OUTPUTS = {
    "isolates":
        OUTPUT_DIR / "isolates_curated.parquet",

    "ast":
        OUTPUT_DIR / "ast_evidence_curated.parquet",

    "genotype":
        OUTPUT_DIR / "genotype_evidence_curated.parquet",
}

SNAPSHOT_ID = "AMRTRACE_RAW_V1"
RULE_VERSION = "CURATION_RULES_V1"


PHENOTYPE_MAP = {
    "susceptible": "S",
    "resistant": "R",
    "intermediate": "I",
    "susceptible-dose dependent": "SDD",
    "nonsusceptible": "NS",
    "not defined": "NOT_DEFINED",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def canonicalize(value):

    if value is None:
        return None

    if isinstance(
        value,
        (datetime, date, time),
    ):
        return value.isoformat()

    if isinstance(value, bytes):
        return {
            "__bytes_hex__": value.hex()
        }

    if isinstance(value, float):

        if math.isnan(value):
            return "__NaN__"

        if math.isinf(value):
            return (
                "__Infinity__"
                if value > 0
                else "__NegativeInfinity__"
            )

        return value

    if isinstance(value, dict):
        return {
            str(key): canonicalize(value[key])
            for key in sorted(
                value,
                key=lambda item: str(item),
            )
        }

    if isinstance(value, (list, tuple)):
        return [
            canonicalize(item)
            for item in value
        ]

    if isinstance(
        value,
        (str, int, bool),
    ):
        return value

    return str(value)


def canonical_json(value) -> str:
    return json.dumps(
        canonicalize(value),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def sha256_value(value) -> str:
    return hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def git_commit() -> str:

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    return result.stdout.strip()


def git_is_clean() -> bool:

    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    return result.stdout.strip() == ""


def normalized_text(value):

    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.lower()


def date_parts(value):

    if value is None:
        return (
            None,
            "MISSING",
        )

    if isinstance(
        value,
        (datetime, date),
    ):
        text = value.isoformat()
    else:
        text = str(value).strip()

    if not text:
        return (
            None,
            "MISSING",
        )

    if re.fullmatch(
        r"\d{4}-\d{2}-\d{2}",
        text,
    ):
        return (
            int(text[:4]),
            "FULL_DATE",
        )

    if re.fullmatch(
        r"\d{4}-\d{2}",
        text,
    ):
        return (
            int(text[:4]),
            "YEAR_MONTH",
        )

    if re.fullmatch(
        r"\d{4}",
        text,
    ):
        return (
            int(text),
            "YEAR",
        )

    return (
        None,
        "OTHER",
    )


def split_geography(value):

    if value is None:
        return (
            None,
            None,
        )

    text = str(value).strip()

    if not text:
        return (
            None,
            None,
        )

    if ":" not in text:
        return (
            text,
            None,
        )

    country, subregion = text.split(
        ":",
        1,
    )

    country = country.strip() or None
    subregion = subregion.strip() or None

    return (
        country,
        subregion,
    )


def column_values(
    table: pa.Table,
    column: str,
):

    if column not in table.column_names:
        return [
            None
        ] * table.num_rows

    return table[column].to_pylist()


def append_column(
    table: pa.Table,
    name: str,
    values,
    data_type=None,
) -> pa.Table:

    check(
        name not in table.column_names,
        f"Column already exists: {name}",
    )

    if isinstance(
        values,
        pa.ChunkedArray,
    ):
        array = values

    elif data_type is not None:
        array = pa.array(
            values,
            type=data_type,
        )

    else:
        array = pa.array(values)

    return table.append_column(
        name,
        array,
    )


def verify_raw_snapshot() -> dict:

    print("Verifying frozen Raw Snapshot v1...")

    check(
        RAW_MANIFEST_PATH.exists(),
        "Raw Snapshot manifest is missing.",
    )

    manifest = json.loads(
        RAW_MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )

    check(
        manifest.get("snapshot_id")
        == SNAPSHOT_ID,
        (
            "Expected source snapshot "
            "AMRTRACE_RAW_V1."
        ),
    )

    check(
        manifest.get("status")
        == "FROZEN",
        (
            "Raw Snapshot v1 must be "
            "FROZEN."
        ),
    )

    for output in manifest["outputs"]:

        relative = Path(
            output["output_file"]
        )

        path = ROOT / relative

        check(
            path.exists(),
            f"Missing raw file: {path}",
        )

        actual_hash = sha256_file(path)

        check(
            actual_hash
            == output["file_sha256"],
            (
                "Frozen raw file hash changed: "
                f"{path.name}"
            ),
        )

        print(
            f"[OK] {path.name} "
            "matches frozen SHA-256"
        )

    print(
        "[OK] Raw Snapshot v1 integrity verified."
    )

    return manifest


def verify_rules() -> None:

    check(
        RULES_PATH.exists(),
        "CURATION_RULES_V1 document missing.",
    )

    content = RULES_PATH.read_text(
        encoding="utf-8"
    )

    check(
        "APPROVED_FOR_IMPLEMENTATION"
        in content,
        (
            "CURATION_RULES_V1 is not "
            "approved for implementation."
        ),
    )

    print(
        "[OK] CURATION_RULES_V1 "
        "approved for implementation."
    )


def ensure_safe_output() -> None:

    if CURATED_MANIFEST_PATH.exists():
        raise RuntimeError(
            "Curated v1 manifest already exists. "
            "Refusing to overwrite it."
        )

    if OUTPUT_DIR.exists():

        existing = list(
            OUTPUT_DIR.iterdir()
        )

        if existing:

            names = ", ".join(
                path.name
                for path in existing
            )

            raise RuntimeError(
                "data/curated_v1 is not empty. "
                f"Existing files: {names}"
            )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    CURATED_MANIFEST_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


def write_parquet(
    table: pa.Table,
    path: Path,
) -> None:

    temporary = Path(
        str(path) + ".tmp"
    )

    if temporary.exists():
        temporary.unlink()

    pq.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=True,
    )

    temporary.replace(path)


def build_isolates() -> tuple[pa.Table, dict]:

    print()
    print("=" * 72)
    print("Building isolates_curated.parquet")
    print("=" * 72)

    table = pq.read_table(
        ISOLATES_PATH
    )

    check(
        "target_acc"
        in table.column_names,
        "target_acc missing from isolate source.",
    )

    targets = column_values(
        table,
        "target_acc",
    )

    check(
        len(set(targets))
        == table.num_rows,
        (
            "Isolate source does not have "
            "one row per target_acc."
        ),
    )

    raw_copy_fields = {
        "strain":
            "strain_raw",

        "collection_date":
            "collection_date_raw",

        "geo_loc_name":
            "geo_loc_name_raw",

        "isolation_source":
            "isolation_source_raw",

        "host":
            "host_raw",

        "host_disease":
            "host_disease_raw",

        "erd_group":
            "erd_group_raw",

        "epi_type":
            "epi_type_raw",

        "source_type":
            "source_type_raw",
    }

    for source, destination in (
        raw_copy_fields.items()
    ):

        if source in table.column_names:

            table = append_column(
                table,
                destination,
                table[source],
            )

    collection_dates = column_values(
        table,
        "collection_date",
    )

    years = []
    precisions = []

    for value in collection_dates:

        year, precision = date_parts(
            value
        )

        years.append(year)
        precisions.append(precision)

    table = append_column(
        table,
        "collection_year",
        years,
        pa.int16(),
    )

    table = append_column(
        table,
        "collection_date_precision",
        precisions,
        pa.string(),
    )

    isolation_sources = column_values(
        table,
        "isolation_source",
    )

    hosts = column_values(
        table,
        "host",
    )

    geography = column_values(
        table,
        "geo_loc_name",
    )

    table = append_column(
        table,
        "isolation_source_key",
        [
            normalized_text(value)
            for value
            in isolation_sources
        ],
        pa.string(),
    )

    table = append_column(
        table,
        "host_key",
        [
            normalized_text(value)
            for value
            in hosts
        ],
        pa.string(),
    )

    table = append_column(
        table,
        "geo_loc_name_key",
        [
            normalized_text(value)
            for value
            in geography
        ],
        pa.string(),
    )

    geo_country = []
    geo_subregion = []

    for value in geography:

        country, subregion = (
            split_geography(value)
        )

        geo_country.append(country)
        geo_subregion.append(subregion)

    table = append_column(
        table,
        "geo_country_raw",
        geo_country,
        pa.string(),
    )

    table = append_column(
        table,
        "geo_subregion_raw",
        geo_subregion,
        pa.string(),
    )

    table = append_column(
        table,
        "source_snapshot_id",
        [
            SNAPSHOT_ID
        ] * table.num_rows,
        pa.string(),
    )

    table = append_column(
        table,
        "curation_rule_version",
        [
            RULE_VERSION
        ] * table.num_rows,
        pa.string(),
    )

    print(
        f"Rows: {table.num_rows:,}"
    )

    print(
        f"Unique target_acc: "
        f"{len(set(targets)):,}"
    )

    return table, {
        "row_count":
            table.num_rows,

        "unique_target_count":
            len(set(targets)),
    }


def build_ast() -> tuple[pa.Table, dict]:

    print()
    print("=" * 72)
    print("Building ast_evidence_curated.parquet")
    print("=" * 72)

    table = pq.read_table(
        AST_PATH
    )

    required = {
        "target_acc",
        "antibiotic",
        "phenotype",
        "id",
        "checksum",
    }

    check(
        required.issubset(
            table.column_names
        ),
        "AST identity fields are missing.",
    )

    targets = column_values(
        table,
        "target_acc",
    )

    antibiotics = column_values(
        table,
        "antibiotic",
    )

    phenotypes = column_values(
        table,
        "phenotype",
    )

    source_ids = column_values(
        table,
        "id",
    )

    checksums = column_values(
        table,
        "checksum",
    )

    ast_ids = []

    normalized_phenotypes = []
    binary_eligible = []
    resolvability = []

    unknown_values = {}

    for (
        target,
        antibiotic,
        phenotype,
        source_id,
        checksum,
    ) in zip(
        targets,
        antibiotics,
        phenotypes,
        source_ids,
        checksums,
    ):

        digest = sha256_value(
            [
                SNAPSHOT_ID,
                target,
                antibiotic,
                source_id,
                checksum,
            ]
        )

        ast_ids.append(
            f"ASTV1_{digest}"
        )

        normalized = (
            PHENOTYPE_MAP.get(
                phenotype,
                "UNKNOWN",
            )
        )

        normalized_phenotypes.append(
            normalized
        )

        eligible = normalized in {
            "S",
            "R",
        }

        binary_eligible.append(
            eligible
        )

        resolvability.append(
            (
                "BINARY_ELIGIBLE"
                if eligible
                else "NON_BINARY"
            )
        )

        if normalized == "UNKNOWN":

            key = str(phenotype)

            unknown_values[key] = (
                unknown_values.get(
                    key,
                    0,
                )
                + 1
            )

    check(
        len(ast_ids)
        == len(set(ast_ids)),
        (
            "AST_EVIDENCE_ID_V1 "
            "produced duplicate IDs."
        ),
    )

    table = append_column(
        table,
        "ast_evidence_id",
        ast_ids,
        pa.string(),
    )

    table = append_column(
        table,
        "antibiotic_raw",
        table["antibiotic"],
    )

    table = append_column(
        table,
        "antibiotic_normalized",
        antibiotics,
        pa.string(),
    )

    table = append_column(
        table,
        "phenotype_raw",
        table["phenotype"],
    )

    table = append_column(
        table,
        "phenotype_normalized",
        normalized_phenotypes,
        pa.string(),
    )

    table = append_column(
        table,
        "binary_state_eligible",
        binary_eligible,
        pa.bool_(),
    )

    table = append_column(
        table,
        "phenotype_resolvability",
        resolvability,
        pa.string(),
    )

    table = append_column(
        table,
        "source_snapshot_id",
        [
            SNAPSHOT_ID
        ] * table.num_rows,
        pa.string(),
    )

    table = append_column(
        table,
        "curation_rule_version",
        [
            RULE_VERSION
        ] * table.num_rows,
        pa.string(),
    )

    if unknown_values:

        print(
            "[WARNING] Unexpected phenotype "
            "values were mapped to UNKNOWN:"
        )

        for value, count in (
            unknown_values.items()
        ):

            print(
                f"  {value}: {count}"
            )

    print(
        f"Rows: {table.num_rows:,}"
    )

    print(
        f"Unique AST evidence IDs: "
        f"{len(set(ast_ids)):,}"
    )

    return table, {
        "row_count":
            table.num_rows,

        "unique_evidence_ids":
            len(set(ast_ids)),

        "unique_target_count":
            len(set(targets)),

        "unknown_phenotype_rows":
            sum(
                unknown_values.values()
            ),

        "unknown_phenotype_values":
            unknown_values,
    }


def build_isolate_metadata_map(
    isolates: pa.Table,
) -> dict:

    target_values = column_values(
        isolates,
        "target_acc",
    )

    biosamples = column_values(
        isolates,
        "biosample_acc",
    )

    assemblies = column_values(
        isolates,
        "asm_acc",
    )

    analysis_types = column_values(
        isolates,
        "amrfinderplus_analysis_type",
    )

    tool_versions = column_values(
        isolates,
        "amrfinderplus_version",
    )

    database_versions = column_values(
        isolates,
        "refgene_db_version",
    )

    result = {}

    for values in zip(
        target_values,
        biosamples,
        assemblies,
        analysis_types,
        tool_versions,
        database_versions,
    ):

        (
            target,
            biosample,
            assembly,
            analysis_type,
            tool_version,
            database_version,
        ) = values

        result[target] = {
            "biosample_acc":
                biosample,

            "asm_acc":
                assembly,

            "amrfinderplus_analysis_type":
                analysis_type,

            "amrfinderplus_version":
                tool_version,

            "refgene_db_version":
                database_version,
        }

    return result


def build_genotype(
    isolates: pa.Table,
) -> tuple[pa.Table, dict]:

    print()
    print("=" * 72)
    print(
        "Building genotype_evidence_curated.parquet"
    )
    print("=" * 72)

    metadata = build_isolate_metadata_map(
        isolates
    )

    micro = pq.ParquetFile(
        GENOTYPE_PATH
    )

    summary = pq.ParquetFile(
        SUMMARY_PATH
    )

    output = {
        "genotype_evidence_id": [],
        "representation_source": [],
        "target_acc": [],
        "biosample_acc": [],
        "asm_acc": [],
        "element_raw": [],
        "element_symbol_raw": [],
        "element_name_raw": [],
        "subtype_raw": [],
        "subclass_raw": [],
        "scope_raw": [],
        "amr_method_raw": [],
        "summary_method_raw": [],
        "plus_raw": [],
        "source_array_offset": [],
        "amrfinderplus_analysis_type": [],
        "amrfinderplus_version": [],
        "refgene_db_version": [],
        "source_row_signature_sha256": [],
        "source_snapshot_id": [],
        "curation_rule_version": [],
    }

    print(
        "Processing detailed MicroBIGG-E rows..."
    )

    micro_count = 0

    for batch in micro.iter_batches(
        batch_size=10_000
    ):

        for row in batch.to_pylist():

            signature = sha256_value(
                row
            )

            evidence_id = (
                f"GMV1_{signature}"
            )

            target = row.get(
                "target_acc"
            )

            meta = metadata.get(
                target,
                {},
            )

            element_symbol = row.get(
                "element_symbol"
            )

            output[
                "genotype_evidence_id"
            ].append(
                evidence_id
            )

            output[
                "representation_source"
            ].append(
                "MICROBIGGE"
            )

            output[
                "target_acc"
            ].append(
                target
            )

            output[
                "biosample_acc"
            ].append(
                row.get(
                    "biosample_acc"
                )
                or
                meta.get(
                    "biosample_acc"
                )
            )

            output[
                "asm_acc"
            ].append(
                row.get(
                    "asm_acc"
                )
                or
                meta.get(
                    "asm_acc"
                )
            )

            output[
                "element_raw"
            ].append(
                element_symbol
            )

            output[
                "element_symbol_raw"
            ].append(
                element_symbol
            )

            output[
                "element_name_raw"
            ].append(
                row.get(
                    "element_name"
                )
            )

            output[
                "subtype_raw"
            ].append(
                row.get(
                    "subtype"
                )
            )

            output[
                "subclass_raw"
            ].append(
                row.get(
                    "subclass"
                )
            )

            output[
                "scope_raw"
            ].append(
                row.get(
                    "scope"
                )
            )

            output[
                "amr_method_raw"
            ].append(
                row.get(
                    "amr_method"
                )
            )

            output[
                "summary_method_raw"
            ].append(
                None
            )

            output[
                "plus_raw"
            ].append(
                None
            )

            output[
                "source_array_offset"
            ].append(
                None
            )

            output[
                "amrfinderplus_analysis_type"
            ].append(
                meta.get(
                    "amrfinderplus_analysis_type"
                )
            )

            output[
                "amrfinderplus_version"
            ].append(
                meta.get(
                    "amrfinderplus_version"
                )
            )

            output[
                "refgene_db_version"
            ].append(
                meta.get(
                    "refgene_db_version"
                )
            )

            output[
                "source_row_signature_sha256"
            ].append(
                signature
            )

            output[
                "source_snapshot_id"
            ].append(
                SNAPSHOT_ID
            )

            output[
                "curation_rule_version"
            ].append(
                RULE_VERSION
            )

            micro_count += 1

        print(
            f"  Processed "
            f"{micro_count:,} detailed rows",
            end="\r",
        )

    print()

    print(
        "Processing isolate-level "
        "genotype-summary rows..."
    )

    summary_count = 0

    for batch in summary.iter_batches(
        batch_size=10_000
    ):

        for row in batch.to_pylist():

            target = row.get(
                "target_acc"
            )

            offset = row.get(
                "source_array_offset"
            )

            evidence_id = (
                "GSV1_"
                + sha256_value(
                    [
                        SNAPSHOT_ID,
                        target,
                        offset,
                    ]
                )
            )

            signature = sha256_value(
                row
            )

            meta = metadata.get(
                target,
                {},
            )

            element = row.get(
                "element"
            )

            output[
                "genotype_evidence_id"
            ].append(
                evidence_id
            )

            output[
                "representation_source"
            ].append(
                "ISOLATE_AMR_SUMMARY"
            )

            output[
                "target_acc"
            ].append(
                target
            )

            output[
                "biosample_acc"
            ].append(
                row.get(
                    "biosample_acc"
                )
                or
                meta.get(
                    "biosample_acc"
                )
            )

            output[
                "asm_acc"
            ].append(
                row.get(
                    "asm_acc"
                )
                or
                meta.get(
                    "asm_acc"
                )
            )

            output[
                "element_raw"
            ].append(
                element
            )

            output[
                "element_symbol_raw"
            ].append(
                None
            )

            output[
                "element_name_raw"
            ].append(
                None
            )

            output[
                "subtype_raw"
            ].append(
                None
            )

            output[
                "subclass_raw"
            ].append(
                None
            )

            output[
                "scope_raw"
            ].append(
                None
            )

            output[
                "amr_method_raw"
            ].append(
                None
            )

            output[
                "summary_method_raw"
            ].append(
                row.get(
                    "method"
                )
            )

            output[
                "plus_raw"
            ].append(
                row.get(
                    "plus"
                )
            )

            output[
                "source_array_offset"
            ].append(
                offset
            )

            output[
                "amrfinderplus_analysis_type"
            ].append(
                row.get(
                    "amrfinderplus_analysis_type"
                )
                or
                meta.get(
                    "amrfinderplus_analysis_type"
                )
            )

            output[
                "amrfinderplus_version"
            ].append(
                row.get(
                    "amrfinderplus_version"
                )
                or
                meta.get(
                    "amrfinderplus_version"
                )
            )

            output[
                "refgene_db_version"
            ].append(
                row.get(
                    "refgene_db_version"
                )
                or
                meta.get(
                    "refgene_db_version"
                )
            )

            output[
                "source_row_signature_sha256"
            ].append(
                signature
            )

            output[
                "source_snapshot_id"
            ].append(
                SNAPSHOT_ID
            )

            output[
                "curation_rule_version"
            ].append(
                RULE_VERSION
            )

            summary_count += 1

        print(
            f"  Processed "
            f"{summary_count:,} summary rows",
            end="\r",
        )

    print()

    evidence_ids = output[
        "genotype_evidence_id"
    ]

    check(
        len(evidence_ids)
        == len(set(evidence_ids)),
        (
            "GENOTYPE_EVIDENCE_ID_V1 "
            "produced duplicate IDs."
        ),
    )

    table = pa.table(
        {
            "genotype_evidence_id":
                pa.array(
                    output[
                        "genotype_evidence_id"
                    ],
                    type=pa.string(),
                ),

            "representation_source":
                pa.array(
                    output[
                        "representation_source"
                    ],
                    type=pa.string(),
                ),

            "target_acc":
                pa.array(
                    output[
                        "target_acc"
                    ],
                    type=pa.string(),
                ),

            "biosample_acc":
                pa.array(
                    output[
                        "biosample_acc"
                    ],
                    type=pa.string(),
                ),

            "asm_acc":
                pa.array(
                    output[
                        "asm_acc"
                    ],
                    type=pa.string(),
                ),

            "element_raw":
                pa.array(
                    output[
                        "element_raw"
                    ],
                    type=pa.string(),
                ),

            "element_symbol_raw":
                pa.array(
                    output[
                        "element_symbol_raw"
                    ],
                    type=pa.string(),
                ),

            "element_name_raw":
                pa.array(
                    output[
                        "element_name_raw"
                    ],
                    type=pa.string(),
                ),

            "subtype_raw":
                pa.array(
                    output[
                        "subtype_raw"
                    ],
                    type=pa.string(),
                ),

            "subclass_raw":
                pa.array(
                    output[
                        "subclass_raw"
                    ],
                    type=pa.string(),
                ),

            "scope_raw":
                pa.array(
                    output[
                        "scope_raw"
                    ],
                    type=pa.string(),
                ),

            "amr_method_raw":
                pa.array(
                    output[
                        "amr_method_raw"
                    ],
                    type=pa.string(),
                ),

            "summary_method_raw":
                pa.array(
                    output[
                        "summary_method_raw"
                    ],
                    type=pa.string(),
                ),

            "plus_raw":
                pa.array(
                    output[
                        "plus_raw"
                    ],
                    type=pa.bool_(),
                ),

            "source_array_offset":
                pa.array(
                    output[
                        "source_array_offset"
                    ],
                    type=pa.int64(),
                ),

            "amrfinderplus_analysis_type":
                pa.array(
                    output[
                        "amrfinderplus_analysis_type"
                    ],
                    type=pa.string(),
                ),

            "amrfinderplus_version":
                pa.array(
                    output[
                        "amrfinderplus_version"
                    ],
                    type=pa.string(),
                ),

            "refgene_db_version":
                pa.array(
                    output[
                        "refgene_db_version"
                    ],
                    type=pa.string(),
                ),

            "source_row_signature_sha256":
                pa.array(
                    output[
                        "source_row_signature_sha256"
                    ],
                    type=pa.string(),
                ),

            "source_snapshot_id":
                pa.array(
                    output[
                        "source_snapshot_id"
                    ],
                    type=pa.string(),
                ),

            "curation_rule_version":
                pa.array(
                    output[
                        "curation_rule_version"
                    ],
                    type=pa.string(),
                ),
        }
    )

    targets = {
        value
        for value
        in output["target_acc"]
        if value is not None
    }

    print(
        f"Combined genotype evidence rows: "
        f"{table.num_rows:,}"
    )

    print(
        f"  MICROBIGGE: "
        f"{micro_count:,}"
    )

    print(
        f"  ISOLATE_AMR_SUMMARY: "
        f"{summary_count:,}"
    )

    print(
        f"Unique genotype evidence IDs: "
        f"{len(set(evidence_ids)):,}"
    )

    print(
        f"Unique targets represented: "
        f"{len(targets):,}"
    )

    return table, {
        "row_count":
            table.num_rows,

        "unique_evidence_ids":
            len(set(evidence_ids)),

        "unique_target_count":
            len(targets),

        "representation_counts": {
            "MICROBIGGE":
                micro_count,

            "ISOLATE_AMR_SUMMARY":
                summary_count,
        },
    }


def output_record(
    path: Path,
    table: pa.Table,
    extra: dict,
) -> dict:

    return {
        "output_file":
            str(
                path.relative_to(ROOT)
            ),

        "row_count":
            table.num_rows,

        "file_size_bytes":
            path.stat().st_size,

        "file_sha256":
            sha256_file(path),

        **extra,
    }


def main() -> None:

    print("=" * 72)
    print(
        "AMRTraceStudio "
        "Curated Dataset v1 builder"
    )
    print("=" * 72)

    raw_manifest = (
        verify_raw_snapshot()
    )

    verify_rules()

    check(
        git_is_clean(),
        (
            "Git working tree is not clean. "
            "Commit the builder before "
            "creating Curated Dataset v1."
        ),
    )

    ensure_safe_output()

    build_commit = git_commit()

    build_started = utc_now()

    print(
        f"[OK] Build Git commit: "
        f"{build_commit}"
    )

    print()

    isolates_table = None
    ast_table = None
    genotype_table = None

    created_files = []

    try:

        isolates_table, isolate_info = (
            build_isolates()
        )

        write_parquet(
            isolates_table,
            OUTPUTS["isolates"],
        )

        created_files.append(
            OUTPUTS["isolates"]
        )

        print(
            f"[DONE] "
            f"{OUTPUTS['isolates'].name}"
        )

        ast_table, ast_info = (
            build_ast()
        )

        write_parquet(
            ast_table,
            OUTPUTS["ast"],
        )

        created_files.append(
            OUTPUTS["ast"]
        )

        print(
            f"[DONE] "
            f"{OUTPUTS['ast'].name}"
        )

        genotype_table, genotype_info = (
            build_genotype(
                isolates_table
            )
        )

        write_parquet(
            genotype_table,
            OUTPUTS["genotype"],
        )

        created_files.append(
            OUTPUTS["genotype"]
        )

        print(
            f"[DONE] "
            f"{OUTPUTS['genotype'].name}"
        )

        build_completed = utc_now()

        manifest = {
            "dataset_id":
                "AMRTRACE_CURATED_V1",

            "status":
                "BUILT_NOT_VALIDATED",

            "source_snapshot_id":
                SNAPSHOT_ID,

            "source_snapshot_manifest_sha256":
                sha256_file(
                    RAW_MANIFEST_PATH
                ),

            "source_extraction_git_commit":
                raw_manifest.get(
                    "git_commit"
                ),

            "curation_rule_version":
                RULE_VERSION,

            "curation_rules_file":
                str(
                    RULES_PATH.relative_to(
                        ROOT
                    )
                ),

            "curation_rules_sha256":
                sha256_file(
                    RULES_PATH
                ),

            "builder_script":
                (
                    "scripts/"
                    "build_curated_dataset_v1.py"
                ),

            "build_git_commit":
                build_commit,

            "build_started_utc":
                build_started,

            "build_completed_utc":
                build_completed,

            "environment": {
                "python_version":
                    platform.python_version(),

                "pyarrow_version":
                    version("pyarrow"),
            },

            "policies": [
                "JOIN_POLICY_V1",
                "PHENOTYPE_NORMALIZATION_V1",
                "AST_EVIDENCE_POLICY_V1",
                "AST_EVIDENCE_ID_V1",
                "ANTIBIOTIC_NAME_POLICY_V1",
                "AST_MEASUREMENT_PRESERVATION_V1",
                "AST_STANDARD_POLICY_V1",
                "DATE_DERIVATION_V1",
                "TEXT_NORMALIZATION_V1",
                "ISOLATION_SOURCE_POLICY_V1",
                "GEOGRAPHY_POLICY_V1",
                "HOST_POLICY_V1",
                "SOURCE_METADATA_POLICY_V1",
                "STRAIN_POLICY_V1",
                "ERD_GROUP_POLICY_V1",
                "BIOPROJECT_POLICY_V1",
                "AMRFINDER_VERSION_PROVENANCE_V1",
                "GENOTYPE_SOURCE_POLICY_V1",
                "GENOTYPE_SUBTYPE_PRESERVATION_V1",
                "GENOTYPE_SUBCLASS_POLICY_V1",
                "GENOTYPE_RECONCILIATION_POLICY_V1",
                "GENOTYPE_EVIDENCE_ID_V1",
                "MISSINGNESS_POLICY_V1",
                "CURATION_PROVENANCE_V1",
            ],

            "outputs": [
                output_record(
                    OUTPUTS["isolates"],
                    isolates_table,
                    isolate_info,
                ),

                output_record(
                    OUTPUTS["ast"],
                    ast_table,
                    ast_info,
                ),

                output_record(
                    OUTPUTS["genotype"],
                    genotype_table,
                    genotype_info,
                ),
            ],

            "four_question_record": {
                "what_source_gave":
                    (
                        "Frozen NCBI-derived "
                        "Raw Snapshot v1 evidence."
                    ),

                "what_changed":
                    (
                        "Added deterministic evidence "
                        "IDs, conservative normalized "
                        "fields, date-derived fields, "
                        "and provenance metadata."
                    ),

                "why":
                    (
                        "To create stable, auditable "
                        "research evidence tables while "
                        "preserving raw values."
                    ),

                "which_version":
                    (
                        "AMRTRACE_RAW_V1 + "
                        "CURATION_RULES_V1 + "
                        "build_curated_dataset_v1.py"
                    ),
            },

            "excluded_operations": [
                (
                    "No determinant-to-antibiotic "
                    "mapping"
                ),
                (
                    "No final antibiotic-panel "
                    "selection"
                ),
                (
                    "No genotype-phenotype "
                    "concordance classification"
                ),
                (
                    "No AST majority voting"
                ),
                (
                    "No genotype representation "
                    "deduplication"
                ),
            ],
        }

        CURATED_MANIFEST_PATH.write_text(
            json.dumps(
                manifest,
                indent=2,
            ),
            encoding="utf-8",
        )

        print()
        print("=" * 72)
        print(
            "CURATED DATASET V1 BUILD COMPLETE"
        )
        print("=" * 72)

        print(
            f"Isolates: "
            f"{isolates_table.num_rows:,}"
        )

        print(
            f"AST evidence: "
            f"{ast_table.num_rows:,}"
        )

        print(
            f"Genotype evidence: "
            f"{genotype_table.num_rows:,}"
        )

        print()

        print(
            f"Manifest: "
            f"{CURATED_MANIFEST_PATH}"
        )

        print()

        print(
            "Status: BUILT_NOT_VALIDATED"
        )

        print(
            "Curated Dataset v1 must pass "
            "M5.5 validation before freezing."
        )

        print()

        print(
            "Raw Snapshot v1 was not modified."
        )

    except Exception:

        print()
        print(
            "Curated Dataset v1 build failed."
        )

        for path in created_files:

            if path.exists():
                path.unlink()

        if OUTPUT_DIR.exists():

            for path in OUTPUT_DIR.glob(
                "*.tmp"
            ):
                path.unlink()

        if CURATED_MANIFEST_PATH.exists():
            CURATED_MANIFEST_PATH.unlink()

        raise


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:

        print(
            "\nCancelled by user."
        )

        sys.exit(130)

    except Exception as exc:

        print()
        print(
            f"BUILD FAILED: {exc}"
        )

        sys.exit(1)