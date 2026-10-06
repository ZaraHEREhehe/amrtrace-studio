# loader for the frozen V1 files: copies them into the source tables once, after checking their hashes
import argparse
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from amrtrace.ingest.frozen_v1 import (
    AST_FILE,
    GENOTYPE_FILE,
    ISOLATES_FILE,
    MAPPING_FILE,
)
from amrtrace.ledger._tx import atomic

CASE_STATES_FILE = "analysis_v1/final_case_states_v1.parquet"
BATCH_ROWS = 50_000


# how one frozen file maps onto one table
@dataclass(frozen=True)
class TableSpec:
    table: str
    file: str
    # database column names, in the order they are written
    columns: tuple[str, ...]
    # database name to file name, only where the two differ
    renames: dict = field(default_factory=dict)
    # file columns left out on purpose, so a new column in a file is noticed instead of ignored
    dropped: tuple[str, ...] = ()

    def file_columns(self) -> list[str]:
        return [self.renames.get(column, column) for column in self.columns]


ISOLATE = TableSpec(
    table="isolate",
    file=ISOLATES_FILE,
    columns=(
        "target_acc",
        "taxgroup_name",
        "strain",
        "serovar",
        "serotype",
        "creation_date",
        "geo_loc_name",
        "isolation_source",
        "epi_type",
        "erd_group",
        "minsame",
        "mindiff",
        "biosample_acc",
        "asm_acc",
        "number_amr_genes",
        "number_core_amr_genes",
        "number_virulence_genes",
        "number_stress_genes",
        "number_drugs_tested",
        "number_drugs_resistant",
        "number_drugs_intermediate",
        "number_drugs_sensitive",
        "number_drugs_susceptible",
        "ifsac_category",
        "source_type",
        "host",
        "kmer_group_acc",
        "scientific_name",
        "amrfinderplus_version",
        "refgene_db_version",
        "amrfinderplus_analysis_type",
        "amrfinderplus_applied",
        "bioproject_acc",
        "collected_by",
        "collection_date",
        "lat_lon",
        "asm_stats_contig_n50",
        "asm_stats_length_bp",
        "asm_stats_n_contig",
        "librarylayout",
        "platform",
        "run",
        "sra_center",
        "sra_release_date",
        "species_taxid",
        "outbreak",
        "host_disease",
        "asm_level",
        "assembly_method",
        "pfge_primaryenzyme_pattern",
        "pfge_secondaryenzyme_pattern",
        "taxid",
        "wgs_acc_prefix",
        "wgs_master_acc",
        "new_flag",
        "source_checksum",
        "strain_raw",
        "collection_date_raw",
        "geo_loc_name_raw",
        "isolation_source_raw",
        "host_raw",
        "host_disease_raw",
        "erd_group_raw",
        "epi_type_raw",
        "source_type_raw",
        "collection_year",
        "collection_date_precision",
        "isolation_source_key",
        "host_key",
        "geo_loc_name_key",
        "geo_country_raw",
        "geo_subregion_raw",
        "source_snapshot_id",
        "curation_rule_version",
    ),
    renames={
        "ifsac_category": "IFSAC_category",
        "librarylayout": "LibraryLayout",
        "platform": "Platform",
        "run": "Run",
        "pfge_primaryenzyme_pattern": "PFGE_PrimaryEnzyme_pattern",
        "pfge_secondaryenzyme_pattern": "PFGE_SecondaryEnzyme_pattern",
        "new_flag": "new",
        "source_checksum": "checksum",
    },
    # nested columns: they repeat the evidence tables or are unused
    dropped=(
        "isolate_identifiers",
        "AMR_genotypes",
        "AMR_genotypes_core",
        "virulence_genotypes",
        "stress_genotypes",
        "AST_phenotypes",
        "computed_types",
    ),
)

AST_EVIDENCE = TableSpec(
    table="ast_evidence",
    file=AST_FILE,
    columns=(
        "ast_evidence_id",
        "source_row_id",
        "target_acc",
        "antibiotic",
        "antibiotic_raw",
        "antibiotic_normalized",
        "phenotype",
        "phenotype_raw",
        "phenotype_normalized",
        "binary_state_eligible",
        "phenotype_resolvability",
        "measurement_sign",
        "mic",
        "mic_secondary",
        "disk_diffusion",
        "standard",
        "reagent",
        "platform",
        "vendor",
        "source_checksum",
        "source_snapshot_id",
        "curation_rule_version",
    ),
    renames={"source_row_id": "id", "source_checksum": "checksum"},
    # copies of isolate-level facts, plus one column that is empty in every row
    dropped=(
        "biosample_acc",
        "taxgroup_name",
        "scientific_name",
        "epi_type",
        "isolation_source",
        "geo_loc_name",
        "host",
        "collection_date",
        "creation_date",
        "bioproject_acc",
        "disk_diffusion_secondary",
    ),
)

GENOTYPE_EVIDENCE = TableSpec(
    table="genotype_evidence",
    file=GENOTYPE_FILE,
    columns=(
        "genotype_evidence_id",
        "representation_source",
        "target_acc",
        "element_raw",
        "element_symbol_raw",
        "element_name_raw",
        "subtype_raw",
        "subclass_raw",
        "scope_raw",
        "amr_method_raw",
        "summary_method_raw",
        "plus_raw",
        "source_array_offset",
        "amrfinderplus_analysis_type",
        "amrfinderplus_version",
        "refgene_db_version",
        "source_row_signature_sha256",
        "source_snapshot_id",
        "curation_rule_version",
    ),
    # these two live on the isolate table
    dropped=("biosample_acc", "asm_acc"),
)

MAPPING_RULE = TableSpec(
    table="mapping_rule",
    file=MAPPING_FILE,
    columns=(
        "mapping_rule_id",
        "mapping_version",
        "mapping_context",
        "source_reference_id",
        "source_db_version",
        "determinant_identity",
        "source_classification_id",
        "source_type",
        "source_subtype",
        "source_class",
        "source_subclass",
        "source_tables",
        "source_match_types",
        "source_match_fields",
        "source_classifications_json",
        "candidate_antibiotic",
        "mapping_strength",
        "relationship",
        "mapping_reason",
        "ambiguity_policy_id",
        "rule_status",
    ),
)

CASE = TableSpec(
    table="case",
    file=CASE_STATES_FILE,
    columns=("case_id", "target_acc", "antibiotic", "panel_id"),
    # the states themselves are loaded into the ledger as release R1, not here
    dropped=(
        "case_state_id",
        "phenotype_state",
        "phenotype_values",
        "genotype_state",
        "case_state",
        "unresolved_reason",
        "ast_evidence_ids",
        "genotype_evidence_ids_evaluated",
        "genotype_evidence_ids_supporting",
        "mapping_rule_ids_evaluated",
        "mapping_rule_ids_supporting",
        "determinants_evaluated",
        "determinants_supporting",
        "genotype_representation_used",
        "genotype_analysis_valid",
        "amrfinderplus_analysis_type",
        "amrfinderplus_version",
        "refgene_db_version",
        "source_snapshot_id",
        "curation_rule_version",
        "curated_dataset_id",
        "mapping_version",
        "case_rule_version",
    ),
)

# the order respects the links between tables: isolates first, cases last
TABLE_SPECS = (ISOLATE, AST_EVIDENCE, GENOTYPE_EVIDENCE, MAPPING_RULE, CASE)


# what a load did, table by table
@dataclass(frozen=True)
class LoadReport:
    snapshot_id: str
    rows: dict
    already_loaded: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# each manifest line is a hash, then spaces, then a path relative to the data folder
def read_manifest(manifest_path: Path) -> dict:
    expected = {}
    for line in Path(manifest_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, relative_path = line.split(maxsplit=1)
            expected[relative_path.strip()] = digest.lower()
    return expected


# refuses to go on if any file is missing from the manifest or differs from it
def verify_hashes(data_dir: Path, manifest_path: Path) -> None:
    expected = read_manifest(manifest_path)
    problems = []
    for spec in TABLE_SPECS:
        if spec.file not in expected:
            problems.append(f"{spec.file}: not listed in the manifest")
        elif _sha256(Path(data_dir) / spec.file) != expected[spec.file]:
            problems.append(f"{spec.file}: hash differs from the manifest")
    if problems:
        raise ValueError("frozen files failed the hash check: " + "; ".join(problems))


def _file_rows(data_dir: Path, spec: TableSpec) -> int:
    import pyarrow.parquet as pq

    return pq.read_metadata(Path(data_dir) / spec.file).num_rows


# every file column must be either loaded or dropped on purpose
def unmapped_file_columns(data_dir: Path, spec: TableSpec) -> list[str]:
    import pyarrow.parquet as pq

    known = set(spec.file_columns()) | set(spec.dropped)
    return [
        name
        for name in pq.read_schema(Path(data_dir) / spec.file).names
        if name not in known
    ]


def _table_rows(conn, table: str) -> int:
    query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
    return conn.execute(query).fetchone()[0]


# a release-wide value must be the same in every row of the file
def _single_value(data_dir: Path, file: str, column: str) -> str:
    import pyarrow.parquet as pq

    values = set(
        pq.read_table(Path(data_dir) / file, columns=[column])
        .column(column)
        .to_pylist()
    )
    if len(values) != 1:
        raise ValueError(
            f"expected one value for {column} in {file}, found {sorted(map(str, values))}"
        )
    return str(values.pop())


def _copy_table(conn, data_dir: Path, spec: TableSpec) -> None:
    import pyarrow.parquet as pq

    file_columns = spec.file_columns()
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(spec.table),
        sql.SQL(", ").join(sql.Identifier(column) for column in spec.columns),
    )
    parquet = pq.ParquetFile(Path(data_dir) / spec.file)
    with conn.cursor() as cursor, cursor.copy(statement) as copy:
        # read in batches so the largest file never has to sit in memory as Python rows all at once
        for batch in parquet.iter_batches(batch_size=BATCH_ROWS, columns=file_columns):
            for row in batch.to_pylist():
                copy.write_row([row[column] for column in file_columns])


def load_frozen_v1(
    conn, data_dir: Path, manifest_path: Path | None = None
) -> LoadReport:
    data_dir = Path(data_dir)
    if manifest_path is not None:
        verify_hashes(data_dir, manifest_path)

    for spec in TABLE_SPECS:
        extra = unmapped_file_columns(data_dir, spec)
        if extra:
            raise ValueError(
                f"{spec.file} has columns the loader does not know: {extra}"
            )

    expected = {spec.table: _file_rows(data_dir, spec) for spec in TABLE_SPECS}
    snapshot_id = _single_value(data_dir, ISOLATES_FILE, "source_snapshot_id")

    # one unit inside the caller's transaction: either every table is loaded or none is
    with atomic(conn):
        present = {spec.table: _table_rows(conn, spec.table) for spec in TABLE_SPECS}

        # the source tables are loaded once, so a complete earlier load is simply confirmed
        if present == expected:
            return LoadReport(
                snapshot_id=snapshot_id, rows=present, already_loaded=True
            )
        if any(present.values()):
            raise RuntimeError(
                f"source tables are partly loaded: found {present}, expected {expected}"
            )

        conn.execute(
            "INSERT INTO snapshot (snapshot_id, curated_dataset_id) VALUES (%s, %s) "
            "ON CONFLICT (snapshot_id) DO NOTHING",
            (
                snapshot_id,
                _single_value(data_dir, CASE_STATES_FILE, "curated_dataset_id"),
            ),
        )
        for spec in TABLE_SPECS:
            _copy_table(conn, data_dir, spec)

        loaded = {spec.table: _table_rows(conn, spec.table) for spec in TABLE_SPECS}
        if loaded != expected:
            raise RuntimeError(
                f"row counts differ after loading: loaded {loaded}, expected {expected}"
            )

    return LoadReport(snapshot_id=snapshot_id, rows=loaded, already_loaded=False)


# same connection settings as the tests, so one set of variables serves both
def _conninfo(dbname: str) -> str:
    return make_conninfo(
        host=os.environ.get("AMRTRACE_PG_HOST", "localhost"),
        port=os.environ.get("AMRTRACE_PG_PORT", "5432"),
        user=os.environ.get("AMRTRACE_PG_USER", "postgres"),
        password=os.environ.get("AMRTRACE_PG_PASSWORD", "dev"),
        dbname=dbname,
        connect_timeout=5,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load the frozen V1 files into the source tables."
    )
    parser.add_argument("--data-dir", default="data/raw")
    parser.add_argument("--manifest", default="data/manifest/sha256.txt")
    parser.add_argument(
        "--database", default=os.environ.get("AMRTRACE_PG_DATABASE", "amrtrace")
    )
    arguments = parser.parse_args()

    with psycopg.connect(_conninfo(arguments.database)) as conn:
        report = load_frozen_v1(
            conn, Path(arguments.data_dir), Path(arguments.manifest)
        )
        conn.commit()

    print(f"snapshot: {report.snapshot_id}")
    for table, rows in report.rows.items():
        print(f"{table}: {rows} rows")
    print(
        "already loaded, nothing written"
        if report.already_loaded
        else "loaded and committed"
    )


if __name__ == "__main__":
    main()
