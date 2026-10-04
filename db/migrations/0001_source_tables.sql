-- 0001: source tables loaded from the frozen V1 files (ADR-003 section 3).
-- Loaded once by the ingest step (Z-03) and never changed afterwards.
--
-- Naming rules (ADR-003 section 2): frozen column names are kept. Exceptions, all applied by the ingest adapter:
--   * every table's "checksum" column is loaded as source_checksum
--   * isolate: IFSAC_category, LibraryLayout, Platform, Run, PFGE_PrimaryEnzyme_pattern and
--     PFGE_SecondaryEnzyme_pattern are lowercased (mixed-case names would need quoting in every query);
--     "new" is loaded as new_flag
--   * ast_evidence: "id" is loaded as source_row_id
--
-- ASCII only, so every runner (psql, docker exec, CI) reads it the same way.

CREATE TABLE snapshot (
    snapshot_id        text PRIMARY KEY,                 -- AMRTRACE_RAW_V1
    curated_dataset_id text,                             -- AMRTRACE_CURATED_V1
    raw_manifest       jsonb NOT NULL DEFAULT '{}'::jsonb,
    curated_manifest   jsonb NOT NULL DEFAULT '{}'::jsonb,
    loaded_at          timestamptz NOT NULL DEFAULT now()
);

-- Lookup of the 8 antibiotic names that appear in the frozen files (5 in the panel, 3 outside it).
-- The long TMP-SMX name is canonical (ADR-003 section 3).
CREATE TABLE antibiotic (
    antibiotic text PRIMARY KEY,
    in_panel   boolean NOT NULL
);

INSERT INTO antibiotic (antibiotic, in_panel) VALUES
    ('ceftriaxone', true),
    ('ciprofloxacin', true),
    ('gentamicin', true),
    ('meropenem', true),
    ('trimethoprim-sulfamethoxazole', true),
    ('cefepime', false),
    ('ceftazidime', false),
    ('imipenem', false);

-- isolates_curated.parquet: 10,584 rows. Scalar columns only (the 7 nested columns are not loaded).
CREATE TABLE isolate (
    target_acc                   text PRIMARY KEY,
    taxgroup_name                text,
    strain                       text,
    serovar                      text,
    serotype                     text,
    creation_date                timestamptz,
    geo_loc_name                 text,
    isolation_source             text,
    epi_type                     text,
    erd_group                    text,
    minsame                      bigint,
    mindiff                      bigint,
    biosample_acc                text,
    asm_acc                      text,                   -- nullable (215 isolates), never a key
    number_amr_genes             bigint,
    number_core_amr_genes        bigint,
    number_virulence_genes       bigint,
    number_stress_genes          bigint,
    number_drugs_tested          bigint,
    number_drugs_resistant       bigint,
    number_drugs_intermediate    bigint,
    number_drugs_sensitive       bigint,
    number_drugs_susceptible     bigint,
    ifsac_category               text,
    source_type                  text,
    host                         text,
    kmer_group_acc               text,
    scientific_name              text,
    amrfinderplus_version        text,
    refgene_db_version           text,
    amrfinderplus_analysis_type  text,
    amrfinderplus_applied        bigint,
    bioproject_acc               text,
    collected_by                 text,
    collection_date              text,                   -- mixed precision (full date, year-month, year): keep as text
    lat_lon                      text,
    asm_stats_contig_n50         bigint,
    asm_stats_length_bp          bigint,
    asm_stats_n_contig           bigint,
    librarylayout                text,
    platform                     text,
    run                          text,
    sra_center                   text,
    sra_release_date             timestamptz,
    species_taxid                bigint,
    outbreak                     text,
    host_disease                 text,
    asm_level                    text,
    assembly_method              text,
    pfge_primaryenzyme_pattern   text,
    pfge_secondaryenzyme_pattern text,
    taxid                        bigint,
    wgs_acc_prefix               text,
    wgs_master_acc               text,
    new_flag                     bigint,
    source_checksum              text,
    strain_raw                   text,
    collection_date_raw          text,
    geo_loc_name_raw             text,
    isolation_source_raw         text,
    host_raw                     text,
    host_disease_raw             text,
    erd_group_raw                text,
    epi_type_raw                 text,
    source_type_raw              text,
    collection_year              smallint,
    collection_date_precision    text,
    isolation_source_key         text,
    host_key                     text,
    geo_loc_name_key             text,
    geo_country_raw              text,
    geo_subregion_raw            text,
    source_snapshot_id           text REFERENCES snapshot (snapshot_id),
    curation_rule_version        text
);

-- ast_evidence_curated.parquet: 57,228 rows. Isolate-level duplicate columns and the all-null
-- disk_diffusion_secondary are not loaded (ADR-003 section 3).
CREATE TABLE ast_evidence (
    ast_evidence_id         text PRIMARY KEY,
    source_row_id           text NOT NULL UNIQUE,        -- frozen column "id"
    target_acc              text NOT NULL REFERENCES isolate (target_acc),
    antibiotic              text NOT NULL REFERENCES antibiotic (antibiotic),
    antibiotic_raw          text,
    antibiotic_normalized   text,
    phenotype               text,
    phenotype_raw           text,
    phenotype_normalized    text,
    binary_state_eligible   boolean,
    phenotype_resolvability text,
    measurement_sign        text,                        -- '==', '<', '<=', '>', '>='
    mic                     double precision,
    mic_secondary           double precision,
    disk_diffusion          double precision,
    standard                text,                        -- CLSI / EUCAST / SFM / null
    reagent                 text,
    platform                text,
    vendor                  text,
    source_checksum         text,
    source_snapshot_id      text REFERENCES snapshot (snapshot_id),
    curation_rule_version   text
);
CREATE INDEX ast_evidence_target_antibiotic_idx ON ast_evidence (target_acc, antibiotic);

-- genotype_evidence_curated.parquet: 413,116 rows. biosample_acc and asm_acc live on isolate.
-- No element_class column exists in the frozen file; representation_source is the evidence type.
CREATE TABLE genotype_evidence (
    genotype_evidence_id        text PRIMARY KEY,
    representation_source       text NOT NULL,           -- MICROBIGGE | ISOLATE_AMR_SUMMARY
    target_acc                  text NOT NULL REFERENCES isolate (target_acc),
    element_raw                 text,
    element_symbol_raw          text,
    element_name_raw            text,
    subtype_raw                 text,
    subclass_raw                text,
    scope_raw                   text,
    amr_method_raw              text,
    summary_method_raw          text,
    plus_raw                    boolean,
    source_array_offset         bigint,
    amrfinderplus_analysis_type text,
    amrfinderplus_version       text,
    refgene_db_version          text,
    source_row_signature_sha256 text NOT NULL UNIQUE,
    source_snapshot_id          text REFERENCES snapshot (snapshot_id),
    curation_rule_version       text
);
CREATE INDEX genotype_evidence_target_idx ON genotype_evidence (target_acc);

-- determinant_drug_mapping_v1.parquet: 43,536 rows, all 21 columns. Includes the explicit UNMAPPED rows
-- (39,693): they carry applicability. There is no organism column (constant, held in version metadata).
-- source_classifications_json stays text: UNMAPPED and SUMMARY_SYMBOL rows may hold empty strings.
CREATE TABLE mapping_rule (
    mapping_rule_id              text PRIMARY KEY,
    mapping_version              text NOT NULL,
    mapping_context              text,
    source_reference_id          text,
    source_db_version            text NOT NULL,          -- AMRFinderPlus database version (3 values)
    determinant_identity         text NOT NULL,
    source_classification_id     text,
    source_type                  text,
    source_subtype               text,
    source_class                 text,
    source_subclass              text,
    source_tables                text,
    source_match_types           text,
    source_match_fields          text,
    source_classifications_json  text,
    candidate_antibiotic         text NOT NULL REFERENCES antibiotic (antibiotic),
    mapping_strength             text,
    relationship                 text,
    mapping_reason               text,
    ambiguity_policy_id          text,
    rule_status                  text NOT NULL
);
CREATE INDEX mapping_rule_pair_idx ON mapping_rule (determinant_identity, candidate_antibiotic);
CREATE INDEX mapping_rule_db_version_idx ON mapping_rule (source_db_version);

-- final_case_states_v1.parquet: identity of the 41,858 cases. Case grain is (target_acc, antibiotic);
-- case_id is an opaque hash and is never parsed. The R1 state rows live in case_state (migration 0002).
CREATE TABLE "case" (
    case_id    text PRIMARY KEY,
    target_acc text NOT NULL REFERENCES isolate (target_acc),
    antibiotic text NOT NULL REFERENCES antibiotic (antibiotic),
    panel_id   text NOT NULL,
    UNIQUE (target_acc, antibiotic)
);
