# Data facts

<!-- BEGIN GENERATED: scripts/regen_data_facts.py -->
## Generated facts

Do not edit this block by hand; rerun `scripts/regen_data_facts.py`. Text outside the markers is kept.

- data folder scanned: `data`
- python 3.12.10, pandas 3.0.5, pyarrow 25.0.1

### File inventory

| file | size (MB) | rows | columns | sha256 (first 16) |
| --- | --- | --- | --- | --- |
| data/raw/analysis_v1/final_case_states_v1.parquet | 38.9 | 41,858 | 27 | bccfa970be376b2c |
| data/raw/curated_v1/ast_evidence_curated.parquet | 3.3 | 57,228 | 33 | dda9567ad91865fa |
| data/raw/curated_v1/genotype_evidence_curated.parquet | 27.8 | 413,116 | 21 | ea4bbf14ce1a321e |
| data/raw/curated_v1/isolates_curated.parquet | 1.3 | 10,584 | 81 | 438c3834d3c5f15b |
| data/raw/mapping_v1/determinant_drug_mapping_v1.parquet | 1.6 | 43,536 | 21 | 5b91c1c47b13e678 |

### Regenerated counts and checks

37 passed, 0 failed, 0 skipped. Expected values come from the M10/M11 handbook and the earlier AST conflict check.

| check | expected | actual | status |
| --- | --- | --- | --- |
| data/raw/analysis_v1/final_case_states_v1.parquet: row count | 41858 | 41858 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: sha256 | bccfa970be376b2cb0cab600345451a70906f133a65f9f698e4aea7239cdf886 | bccfa970be376b2cb0cab600345451a70906f133a65f9f698e4aea7239cdf886 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: rows in CONCORDANT_SUSCEPTIBLE | 26532 | 26532 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: rows in UNRESOLVED | 8389 | 8389 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: rows in CONCORDANT_RESISTANT | 5223 | 5223 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: rows in DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S | 1288 | 1288 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: rows in DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE | 426 | 426 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: duplicated case_id values | 0 | 0 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: total cases for ceftriaxone | 7220 | 7220 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: ceftriaxone genotype-positive/phenotype-S | 702 | 702 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: ceftriaxone phenotype-R/no mapped genotype | 50 | 50 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: ceftriaxone unresolved | 91 | 91 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: total cases for ciprofloxacin | 8787 | 8787 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: ciprofloxacin genotype-positive/phenotype-S | 229 | 229 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: ciprofloxacin phenotype-R/no mapped genotype | 34 | 34 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: ciprofloxacin unresolved | 2436 | 2436 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: total cases for gentamicin | 9715 | 9715 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: gentamicin genotype-positive/phenotype-S | 94 | 94 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: gentamicin phenotype-R/no mapped genotype | 177 | 177 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: gentamicin unresolved | 2149 | 2149 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: total cases for meropenem | 7105 | 7105 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: meropenem genotype-positive/phenotype-S | 118 | 118 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: meropenem phenotype-R/no mapped genotype | 121 | 121 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: meropenem unresolved | 698 | 698 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: total cases for tmp-smx | 9031 | 9031 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: tmp-smx genotype-positive/phenotype-S | 145 | 145 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: tmp-smx phenotype-R/no mapped genotype | 44 | 44 | PASS |
| data/raw/analysis_v1/final_case_states_v1.parquet: tmp-smx unresolved | 3015 | 3015 | PASS |
| data/raw/curated_v1/ast_evidence_curated.parquet: row count | 57228 | 57228 | PASS |
| data/raw/curated_v1/ast_evidence_curated.parquet: isolate+antibiotic groups with more than one AST test | 21 | 21 | PASS |
| data/raw/curated_v1/ast_evidence_curated.parquet: groups whose tests disagree on phenotype | 3 | 3 | PASS |
| data/raw/curated_v1/ast_evidence_curated.parquet: AST rows with a non-null mic | 56675 | 56675 | PASS |
| data/raw/curated_v1/genotype_evidence_curated.parquet: row count | 413116 | 413116 | PASS |
| data/raw/curated_v1/genotype_evidence_curated.parquet: rows with representation_source MICROBIGGE | 325265 | 325265 | PASS |
| data/raw/curated_v1/genotype_evidence_curated.parquet: rows with representation_source ISOLATE_AMR_SUMMARY | 87851 | 87851 | PASS |
| data/raw/curated_v1/isolates_curated.parquet: row count | 10584 | 10584 | PASS |
| data/raw/mapping_v1/determinant_drug_mapping_v1.parquet: row count | 43536 | 43536 | PASS |

### OD-1 mismatch list

The plan says the frozen files win. Value 1 and value 2 are the two competing sets of numbers quoted in OD-1.

| metric | OD-1 value 1 | OD-1 value 2 | frozen files | verdict |
| --- | --- | --- | --- | --- |
| ceftriaxone total cases | 7,220 | - | 7,220 | files match value 1 |
| ciprofloxacin total cases | 8,787 | 8,885 | 8,787 | files match value 1 |
| gentamicin total cases | 9,715 | 9,106 | 9,715 | files match value 1 |
| meropenem total cases | 7,105 | 7,346 | 7,105 | files match value 1 |
| TMP-SMX total cases | 9,031 | 9,301 | 9,031 | files match value 1 |
| genotype-positive/phenotype-S (all drugs) | 1,288 | 1,463 | 1,288 | files match value 1 |
| unresolved cases | 8,389 | 16.25% overall | 8,389 (20.04%) | files match value 1 |

### Draft schema (plan section 5.3) against the real columns

'check' means a similar name exists and a human should confirm it. This is the input for the schema ADR.

#### draft table `isolate` (from `isolates_curated`)

| draft column | status | real column(s) |
| --- | --- | --- |
| isolate_target_acc | check | target_acc, wgs_master_acc, bioproject_acc |
| biosample_acc | exact | biosample_acc |
| scientific_name | exact | scientific_name |
| host | exact | host |
| geo_loc_name | exact | geo_loc_name |
| collection_date | exact | collection_date |
| isolation_source | exact | isolation_source |
| snapshot_id | check | source_snapshot_id |

Real columns with no draft counterpart: `taxgroup_name`, `strain`, `isolate_identifiers`, `serovar`, `serotype`, `creation_date`, `epi_type`, `erd_group`, `minsame`, `mindiff`, `asm_acc`, `AMR_genotypes`, `number_amr_genes`, `AMR_genotypes_core`, `number_core_amr_genes`, `virulence_genotypes`, `number_virulence_genes`, `stress_genotypes`, `number_stress_genes`, `AST_phenotypes`, `number_drugs_tested`, `number_drugs_resistant`, `number_drugs_intermediate`, `number_drugs_sensitive`, `number_drugs_susceptible`, `computed_types`, `IFSAC_category`, `source_type`, `kmer_group_acc`, `amrfinderplus_version`, `refgene_db_version`, `amrfinderplus_analysis_type`, `amrfinderplus_applied`, `collected_by`, `lat_lon`, `asm_stats_contig_n50`, `asm_stats_length_bp`, `asm_stats_n_contig`, `LibraryLayout`, `Platform`, `Run`, `sra_center`, `sra_release_date`, `species_taxid`, `outbreak`, `host_disease`, `asm_level`, `assembly_method`, `PFGE_PrimaryEnzyme_pattern`, `PFGE_SecondaryEnzyme_pattern`, `taxid`, `wgs_acc_prefix`, `new`, `checksum`, `strain_raw`, `collection_date_raw`, `geo_loc_name_raw`, `isolation_source_raw`, `host_raw`, `host_disease_raw`, `erd_group_raw`, `epi_type_raw`, `source_type_raw`, `collection_year`, `collection_date_precision`, `isolation_source_key`, `host_key`, `geo_loc_name_key`, `geo_country_raw`, `geo_subregion_raw`, `curation_rule_version`

#### draft table `ast_evidence` (from `ast_evidence_curated`)

| draft column | status | real column(s) |
| --- | --- | --- |
| ast_evidence_id | exact | ast_evidence_id |
| isolate_target_acc | check | target_acc, bioproject_acc |
| antibiotic | exact | antibiotic |
| phenotype | exact | phenotype |
| measurement_sign | exact | measurement_sign |
| mic | exact | mic |
| disk_diffusion | exact | disk_diffusion |
| testing_standard | check | standard |
| snapshot_id | check | source_snapshot_id |

Real columns with no draft counterpart: `id`, `biosample_acc`, `taxgroup_name`, `scientific_name`, `epi_type`, `isolation_source`, `geo_loc_name`, `mic_secondary`, `disk_diffusion_secondary`, `reagent`, `platform`, `vendor`, `host`, `collection_date`, `creation_date`, `checksum`, `antibiotic_raw`, `antibiotic_normalized`, `phenotype_raw`, `phenotype_normalized`, `binary_state_eligible`, `phenotype_resolvability`, `curation_rule_version`

#### draft table `genotype_evidence` (from `genotype_evidence_curated`)

| draft column | status | real column(s) |
| --- | --- | --- |
| genotype_evidence_id | exact | genotype_evidence_id |
| isolate_target_acc | check | target_acc |
| element_symbol | check | element_symbol_raw, element_raw, element_name_raw |
| element_class | check | element_raw, element_name_raw, element_symbol_raw |
| element_subclass | check | element_symbol_raw, element_raw, subclass_raw |
| evidence_type | no match | - |
| amrfinderplus_version | exact | amrfinderplus_version |
| refgene_db_version | exact | refgene_db_version |
| snapshot_id | check | source_snapshot_id |

Real columns with no draft counterpart: `representation_source`, `biosample_acc`, `asm_acc`, `subtype_raw`, `scope_raw`, `amr_method_raw`, `summary_method_raw`, `plus_raw`, `source_array_offset`, `amrfinderplus_analysis_type`, `source_row_signature_sha256`, `curation_rule_version`

#### draft table `mapping_rule` (from `determinant_drug_mapping_v1`)

| draft column | status | real column(s) |
| --- | --- | --- |
| mapping_rule_id | exact | mapping_rule_id |
| mapping_version | exact | mapping_version |
| determinant | check | determinant_identity |
| antibiotic | check | candidate_antibiotic |
| organism | no match | - |
| relation | check | relationship |
| status | check | rule_status |

Real columns with no draft counterpart: `mapping_context`, `source_reference_id`, `source_db_version`, `source_classification_id`, `source_type`, `source_subtype`, `source_class`, `source_subclass`, `source_tables`, `source_match_types`, `source_match_fields`, `source_classifications_json`, `mapping_strength`, `mapping_reason`, `ambiguity_policy_id`

#### draft table `case` (from `final_case_states_v1`)

| draft column | status | real column(s) |
| --- | --- | --- |
| case_id | exact | case_id |
| isolate_target_acc | check | target_acc |
| antibiotic | exact | antibiotic |
| panel_version | check | case_rule_version, mapping_version, amrfinderplus_version |

Real columns with no draft counterpart: `case_state_id`, `phenotype_state`, `phenotype_values`, `genotype_state`, `case_state`, `unresolved_reason`, `ast_evidence_ids`, `genotype_evidence_ids_evaluated`, `genotype_evidence_ids_supporting`, `mapping_rule_ids_evaluated`, `mapping_rule_ids_supporting`, `determinants_evaluated`, `determinants_supporting`, `genotype_representation_used`, `genotype_analysis_valid`, `amrfinderplus_analysis_type`, `refgene_db_version`, `source_snapshot_id`, `curation_rule_version`, `curated_dataset_id`, `panel_id`

### Antibiotic name vocabularies

Use this to decide the antibiotic lookup table and to catch naming mismatches between tables.

| file | column | values |
| --- | --- | --- |
| data/raw/analysis_v1/final_case_states_v1.parquet | antibiotic | ceftriaxone, ciprofloxacin, gentamicin, meropenem, trimethoprim-sulfamethoxazole |
| data/raw/curated_v1/ast_evidence_curated.parquet | antibiotic | cefepime, ceftazidime, ceftriaxone, ciprofloxacin, gentamicin, imipenem, meropenem, trimethoprim-sulfamethoxazole |
| data/raw/curated_v1/ast_evidence_curated.parquet | antibiotic_normalized | cefepime, ceftazidime, ceftriaxone, ciprofloxacin, gentamicin, imipenem, meropenem, trimethoprim-sulfamethoxazole |

### Cross-table key overlap

Shows which columns can act as foreign keys. A child value missing from the parent means orphans during migration.

| column | child file | parent file | child distinct | parent distinct | % of child values found in parent |
| --- | --- | --- | --- | --- | --- |
| antibiotic | data/raw/analysis_v1/final_case_states_v1.parquet | data/raw/curated_v1/ast_evidence_curated.parquet | 5 | 8 | 100.0% |
| antibiotic | data/raw/curated_v1/ast_evidence_curated.parquet | data/raw/analysis_v1/final_case_states_v1.parquet | 8 | 5 | 62.5% |
| asm_acc | data/raw/curated_v1/genotype_evidence_curated.parquet | data/raw/curated_v1/isolates_curated.parquet | 10369 | 10369 | 100.0% |
| asm_acc | data/raw/curated_v1/isolates_curated.parquet | data/raw/curated_v1/genotype_evidence_curated.parquet | 10369 | 10369 | 100.0% |
| bioproject_acc | data/raw/curated_v1/ast_evidence_curated.parquet | data/raw/curated_v1/isolates_curated.parquet | 74 | 74 | 100.0% |
| bioproject_acc | data/raw/curated_v1/isolates_curated.parquet | data/raw/curated_v1/ast_evidence_curated.parquet | 74 | 74 | 100.0% |
| biosample_acc | data/raw/curated_v1/ast_evidence_curated.parquet | data/raw/curated_v1/genotype_evidence_curated.parquet | 10584 | 10584 | 100.0% |
| biosample_acc | data/raw/curated_v1/ast_evidence_curated.parquet | data/raw/curated_v1/isolates_curated.parquet | 10584 | 10584 | 100.0% |
| biosample_acc | data/raw/curated_v1/genotype_evidence_curated.parquet | data/raw/curated_v1/ast_evidence_curated.parquet | 10584 | 10584 | 100.0% |
| biosample_acc | data/raw/curated_v1/genotype_evidence_curated.parquet | data/raw/curated_v1/isolates_curated.parquet | 10584 | 10584 | 100.0% |
| biosample_acc | data/raw/curated_v1/isolates_curated.parquet | data/raw/curated_v1/ast_evidence_curated.parquet | 10584 | 10584 | 100.0% |
| biosample_acc | data/raw/curated_v1/isolates_curated.parquet | data/raw/curated_v1/genotype_evidence_curated.parquet | 10584 | 10584 | 100.0% |
| target_acc | data/raw/analysis_v1/final_case_states_v1.parquet | data/raw/curated_v1/ast_evidence_curated.parquet | 10396 | 10584 | 100.0% |
| target_acc | data/raw/analysis_v1/final_case_states_v1.parquet | data/raw/curated_v1/genotype_evidence_curated.parquet | 10396 | 10584 | 100.0% |
| target_acc | data/raw/analysis_v1/final_case_states_v1.parquet | data/raw/curated_v1/isolates_curated.parquet | 10396 | 10584 | 100.0% |
| target_acc | data/raw/curated_v1/ast_evidence_curated.parquet | data/raw/analysis_v1/final_case_states_v1.parquet | 10584 | 10396 | 98.2% |
| target_acc | data/raw/curated_v1/ast_evidence_curated.parquet | data/raw/curated_v1/genotype_evidence_curated.parquet | 10584 | 10584 | 100.0% |
| target_acc | data/raw/curated_v1/ast_evidence_curated.parquet | data/raw/curated_v1/isolates_curated.parquet | 10584 | 10584 | 100.0% |
| target_acc | data/raw/curated_v1/genotype_evidence_curated.parquet | data/raw/analysis_v1/final_case_states_v1.parquet | 10584 | 10396 | 98.2% |
| target_acc | data/raw/curated_v1/genotype_evidence_curated.parquet | data/raw/curated_v1/ast_evidence_curated.parquet | 10584 | 10584 | 100.0% |
| target_acc | data/raw/curated_v1/genotype_evidence_curated.parquet | data/raw/curated_v1/isolates_curated.parquet | 10584 | 10584 | 100.0% |
| target_acc | data/raw/curated_v1/isolates_curated.parquet | data/raw/analysis_v1/final_case_states_v1.parquet | 10584 | 10396 | 98.2% |
| target_acc | data/raw/curated_v1/isolates_curated.parquet | data/raw/curated_v1/ast_evidence_curated.parquet | 10584 | 10584 | 100.0% |
| target_acc | data/raw/curated_v1/isolates_curated.parquet | data/raw/curated_v1/genotype_evidence_curated.parquet | 10584 | 10584 | 100.0% |

### List columns (possible dependency edges)

Total items is the number of rows you get by exploding a list column into a child table. In the case table the id lists look like the already-realised dependency edges; confirm what evaluated and supporting mean with the author of the case rules.

| file | column | rows with items | total items | distinct items | max per row |
| --- | --- | --- | --- | --- | --- |
| data/raw/analysis_v1/final_case_states_v1.parquet | phenotype_values | 41858 | 41860 | 5 | 2 |
| data/raw/analysis_v1/final_case_states_v1.parquet | ast_evidence_ids | 41858 | 41880 | 41880 | 3 |
| data/raw/analysis_v1/final_case_states_v1.parquet | genotype_evidence_ids_evaluated | 41858 | 469755 | 117677 | 104 |
| data/raw/analysis_v1/final_case_states_v1.parquet | genotype_evidence_ids_supporting | 11006 | 26972 | 26972 | 13 |
| data/raw/analysis_v1/final_case_states_v1.parquet | mapping_rule_ids_evaluated | 41858 | 344526 | 6227 | 50 |
| data/raw/analysis_v1/final_case_states_v1.parquet | mapping_rule_ids_supporting | 11006 | 20009 | 456 | 5 |
| data/raw/analysis_v1/final_case_states_v1.parquet | determinants_evaluated | 41858 | 344526 | 871 | 50 |
| data/raw/analysis_v1/final_case_states_v1.parquet | determinants_supporting | 11006 | 20009 | 250 | 5 |
| data/raw/curated_v1/isolates_curated.parquet | isolate_identifiers | 10584 | 25380 | 25223 | 6 |
| data/raw/curated_v1/isolates_curated.parquet | AMR_genotypes | 10584 | 87851 | - | 52 |
| data/raw/curated_v1/isolates_curated.parquet | AMR_genotypes_core | 8705 | 56745 | 1013 | 46 |
| data/raw/curated_v1/isolates_curated.parquet | virulence_genotypes | 10553 | 148383 | - | 38 |
| data/raw/curated_v1/isolates_curated.parquet | stress_genotypes | 10490 | 53596 | - | 40 |
| data/raw/curated_v1/isolates_curated.parquet | AST_phenotypes | 10584 | 166487 | - | 36 |

### Table schemas

### `data/raw/analysis_v1/final_case_states_v1.parquet`

41,858 rows x 27 columns, sha256 `bccfa970be376b2c...`

Candidate keys (no nulls, no duplicates): `case_id`, `case_state_id`

Composite candidates: `target_acc` + `antibiotic`

- `phenotype_values` is a nested column (list<element: string>); 0 empty values. Needs JSONB or a child table.

- `ast_evidence_ids` is a nested column (list<element: string>); 0 empty values. Needs JSONB or a child table.

- `genotype_evidence_ids_evaluated` is a nested column (list<element: string>); 0 empty values. Needs JSONB or a child table.

- `genotype_evidence_ids_supporting` is a nested column (list<element: string>); 30852 empty values. Needs JSONB or a child table.

- `mapping_rule_ids_evaluated` is a nested column (list<element: string>); 0 empty values. Needs JSONB or a child table.

- `mapping_rule_ids_supporting` is a nested column (list<element: string>); 30852 empty values. Needs JSONB or a child table.

- `determinants_evaluated` is a nested column (list<element: string>); 0 empty values. Needs JSONB or a child table.

- `determinants_supporting` is a nested column (list<element: string>); 30852 empty values. Needs JSONB or a child table.

| # | column | arrow type | suggested postgres type | nulls | null % | distinct | values |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | case_id | large_string | TEXT | 0 | 0.0% | 41858 | e.g. CASE_8851d3505775b1fb06efac..., CASE_4400ac4aba381716e8d2ce..., CASE_c062ff8e7860b7d0bedd73... |
| 2 | case_state_id | large_string | TEXT | 0 | 0.0% | 41858 | e.g. STATEV1_681871984a8c9407b5b..., STATEV1_d7c051ca0ec8bf7677e..., STATEV1_5919b773214a031234b... |
| 3 | target_acc | large_string | TEXT | 0 | 0.0% | 10396 | e.g. PDT000041778.1, PDT000041780.1, PDT000045580.1 |
| 4 | antibiotic | large_string | TEXT | 0 | 0.0% | 5 | gentamicin (9715); trimethoprim-sulfamethoxazole (9031); ciprofloxacin (8787); ceftriaxone (7220); meropenem (7105) |
| 5 | phenotype_state | large_string | TEXT | 0 | 0.0% | 4 | PHENOTYPE_S (30630); PHENOTYPE_R (5944); PHENOTYPE_UNRESOLVED_NONBINARY (5282); PHENOTYPE_CONFLICT (2) |
| 6 | phenotype_values | list<element: string> | JSONB | 0 | 0.0% | 6 | ["S"] (30630); ["R"] (5944); ["NOT_DEFINED"] (4978); ["I"] (287); ["NS"] (17); ["I", "R"] (2) |
| 7 | genotype_state | large_string | TEXT | 0 | 0.0% | 3 | GENOTYPE_NO_MAPPED_SUPPORT (30852); GENOTYPE_DECISIVE_SUPPORT (7472); GENOTYPE_CONTEXTUAL_SUPPORT (3534) |
| 8 | case_state | large_string | TEXT | 0 | 0.0% | 5 | CONCORDANT_SUSCEPTIBLE (26532); UNRESOLVED (8389); CONCORDANT_RESISTANT (5223); DISCORDANT_GENOTYPE_POSITIV... (1288); DISCORDANT_PHENOTYPE_R_NO_M... (426) |
| 9 | unresolved_reason | large_string | TEXT | 33469 | 80.0% | 3 | NONBINARY_PHENOTYPE (5282); CONTEXTUAL_GENOTYPE_EVIDENCE (3105); PHENOTYPE_CONFLICT (2) |
| 10 | ast_evidence_ids | list<element: string> | JSONB | 0 | 0.0% | 41858 | e.g. ["ASTV1_35b737b8a8810b2ca65..., ["ASTV1_3517ce7bf835c11afbf..., ["ASTV1_ed26461da078e06e963... |
| 11 | genotype_evidence_ids_evaluated | list<element: string> | JSONB | 0 | 0.0% | 10396 | e.g. ["GMV1_05c91ceeb57f620bc8b1..., ["GMV1_0cf0e8e8a244a3729d4c..., ["GMV1_085a8219a62f9bcc3aa6... |
| 12 | genotype_evidence_ids_supporting | list<element: string> | JSONB | 0 | 0.0% | 11007 | e.g. [], [], [] |
| 13 | mapping_rule_ids_evaluated | list<element: string> | JSONB | 0 | 0.0% | 17695 | e.g. ["DDMV1_20a4576d75278545a27..., ["DDMV1_20a4576d75278545a27..., ["DDMV1_20a4576d75278545a27... |
| 14 | mapping_rule_ids_supporting | list<element: string> | JSONB | 0 | 0.0% | 762 | e.g. [], [], [] |
| 15 | determinants_evaluated | list<element: string> | JSONB | 0 | 0.0% | 4244 | e.g. ["aadA5", "acrF", "aph(3'')..., ["aadA5", "acrF", "aph(3'')..., ["acrF", "aph(3'')-Ib", "ap... |
| 16 | determinants_supporting | list<element: string> | JSONB | 0 | 0.0% | 521 | e.g. [], [], [] |
| 17 | genotype_representation_used | large_string | TEXT | 0 | 0.0% | 2 | MICROBIGGE (40823); ISOLATE_AMR_SUMMARY (1035) |
| 18 | genotype_analysis_valid | bool | BOOLEAN | 0 | 0.0% | 1 | True (41858) |
| 19 | amrfinderplus_analysis_type | large_string | TEXT | 0 | 0.0% | 2 | COMBINED (27927); NUCLEOTIDE (13931) |
| 20 | amrfinderplus_version | large_string | TEXT | 0 | 0.0% | 1 | 4.2.7 (41858) |
| 21 | refgene_db_version | large_string | TEXT | 0 | 0.0% | 3 | 2026-03-24.1 (40402); 2026-05-15.1 (767); 2026-08-07.1 (689) |
| 22 | source_snapshot_id | large_string | TEXT | 0 | 0.0% | 1 | AMRTRACE_RAW_V1 (41858) |
| 23 | curation_rule_version | large_string | TEXT | 0 | 0.0% | 1 | CURATION_RULES_V1 (41858) |
| 24 | curated_dataset_id | large_string | TEXT | 0 | 0.0% | 1 | AMRTRACE_CURATED_V1 (41858) |
| 25 | mapping_version | large_string | TEXT | 0 | 0.0% | 1 | DETERMINANT_DRUG_MAPPING_V1 (41858) |
| 26 | panel_id | large_string | TEXT | 0 | 0.0% | 1 | ANTIBIOTIC_PANEL_V1 (41858) |
| 27 | case_rule_version | large_string | TEXT | 0 | 0.0% | 1 | CASE_RULES_V1 (41858) |

Case states by `antibiotic` (TMP-SMX names are merged):

| antibiotic | CONCORDANT_RESISTANT | CONCORDANT_SUSCEPTIBLE | DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S | DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE | UNRESOLVED | TOTAL |
| --- | --- | --- | --- | --- | --- | --- |
| ceftriaxone | 1516 | 4861 | 702 | 50 | 91 | 7220 |
| ciprofloxacin | 1165 | 4923 | 229 | 34 | 2436 | 8787 |
| gentamicin | 1102 | 6193 | 94 | 177 | 2149 | 9715 |
| meropenem | 93 | 6075 | 118 | 121 | 698 | 7105 |
| tmp-smx | 1347 | 4480 | 145 | 44 | 3015 | 9031 |

### `data/raw/curated_v1/ast_evidence_curated.parquet`

57,228 rows x 33 columns, sha256 `dda9567ad91865fa...`

Candidate keys (no nulls, no duplicates): `id`, `checksum`, `ast_evidence_id`

- `collection_date` text formats: full date 59.9%, year-month 3.3%, year only 36.8%, iso timestamp 0.0%, other 0.0%. Keep as TEXT unless cleaned.

- `creation_date` text formats: full date 0.0%, year-month 0.0%, year only 0.0%, iso timestamp 100.0%, other 0.0%. Looks like a full timestamp.

| # | column | arrow type | suggested postgres type | nulls | null % | distinct | values |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | id | string | TEXT | 0 | 0.0% | 57228 | e.g. 015_PDT000041778.1, 016_PDT000041778.1, 017_PDT000041778.1 |
| 2 | biosample_acc | string | TEXT | 0 | 0.0% | 10584 | e.g. SAMN03075588, SAMN03075588, SAMN03075588 |
| 3 | taxgroup_name | string | TEXT | 0 | 0.0% | 1 | E.coli and Shigella (57228) |
| 4 | scientific_name | string | TEXT | 0 | 0.0% | 1 | Escherichia coli (57228) |
| 5 | epi_type | string | TEXT | 0 | 0.0% | 2 | clinical (30459); environmental/other (26769) |
| 6 | isolation_source | string | TEXT | 991 | 1.7% | 488 | e.g. Surveillance swab - Groin, Surveillance swab - Groin, Surveillance swab - Groin |
| 7 | geo_loc_name | string | TEXT | 777 | 1.4% | 106 | e.g. USA, USA, USA |
| 8 | target_acc | string | TEXT | 0 | 0.0% | 10584 | e.g. PDT000041778.1, PDT000041778.1, PDT000041778.1 |
| 9 | antibiotic | string | TEXT | 0 | 0.0% | 8 | gentamicin (9721); trimethoprim-sulfamethoxazole (9036); ciprofloxacin (8793); ceftriaxone (7224); meropenem (7106); ceftazidime (5750); imipenem (4952); cefepime (4646) |
| 10 | phenotype | string | TEXT | 0 | 0.0% | 6 | susceptible (39440); not defined (9278); resistant (7914); intermediate (526); susceptible-dose dependent (53); nonsusceptible (17) |
| 11 | measurement_sign | string | TEXT | 0 | 0.0% | 5 | <= (36841); == (13109); > (4408); >= (1848); < (1022) |
| 12 | mic | double | DOUBLE PRECISION | 553 | 1.0% | 40 | e.g. 16.0, 4.0, 4.0 [min 0.004, max 1024.0] |
| 13 | mic_secondary | double | DOUBLE PRECISION | 48241 | 84.3% | 16 | e.g. 304.0, 38.0, 38.0 [min 0.5, max 608.0] |
| 14 | disk_diffusion | double | DOUBLE PRECISION | 56675 | 99.0% | 34 | e.g. 6.0, 6.0, 6.0 [min 6.0, max 40.0] |
| 15 | disk_diffusion_secondary | double | DOUBLE PRECISION | 57228 | 100.0% | 0 | all null |
| 16 | standard | string | TEXT | 26 | 0.0% | 3 | CLSI (50142); EUCAST (6933); SFM (127) |
| 17 | reagent | string | TEXT | 11320 | 19.8% | 9 | 96-Well Plate (27753); GM-NEG (13328); Panel: CMV2AGNF (4508); E-Test (217); AST-GN98 (65); Disk difussion method in Mu... (16); CMV3AGNF (8); CMV2AGNF (8); agar dilution (5) |
| 18 | platform | string | TEXT | 6878 | 12.0% | 10 | Sensititre (26192); Phoenix (16613); Vitek (6222); Sensititer (1264); Microscan (19); Scan 500 (16); KB panel (8); Phoenix NMIC-203 card (8); Sensititre microbroth dilut... (6); Etest (2) |
| 19 | vendor | string | TEXT | 12242 | 21.4% | 8 | Trek (21856); Becton Dickinson (16652); Biomérieux (6421); Siemens (17); Interscience (16); TREK Diagnostic Systems (16); Thermo Scientific (6); SIRSCAN (2) |
| 20 | host | string | TEXT | 17364 | 30.3% | 25 | e.g. Homo sapiens, Homo sapiens, Homo sapiens |
| 21 | collection_date | string | TEXT | 972 | 1.7% | 1347 | e.g. 2013-09-24, 2013-09-24, 2013-09-24 |
| 22 | creation_date | string | TEXT | 0 | 0.0% | 6289 | e.g. 2014-10-31T11:01:40Z, 2014-10-31T11:01:40Z, 2014-10-31T11:01:40Z |
| 23 | bioproject_acc | string | TEXT | 0 | 0.0% | 74 | e.g. PRJNA261723, PRJNA261723, PRJNA261723 |
| 24 | checksum | string | TEXT | 0 | 0.0% | 57228 | e.g. 9bd6a5cba8aef6f6452b7cb8ee8..., c4f2dedeb3f0156f285ab7bc1e3..., 7389cd13a00e8baa457ea08093d... |
| 25 | ast_evidence_id | string | TEXT | 0 | 0.0% | 57228 | e.g. ASTV1_555cd14351ec32ce85cf7..., ASTV1_b701c6d46fe13fe5f3bcc..., ASTV1_1e6dcb8858398172e5c6e... |
| 26 | antibiotic_raw | string | TEXT | 0 | 0.0% | 8 | gentamicin (9721); trimethoprim-sulfamethoxazole (9036); ciprofloxacin (8793); ceftriaxone (7224); meropenem (7106); ceftazidime (5750); imipenem (4952); cefepime (4646) |
| 27 | antibiotic_normalized | string | TEXT | 0 | 0.0% | 8 | gentamicin (9721); trimethoprim-sulfamethoxazole (9036); ciprofloxacin (8793); ceftriaxone (7224); meropenem (7106); ceftazidime (5750); imipenem (4952); cefepime (4646) |
| 28 | phenotype_raw | string | TEXT | 0 | 0.0% | 6 | susceptible (39440); not defined (9278); resistant (7914); intermediate (526); susceptible-dose dependent (53); nonsusceptible (17) |
| 29 | phenotype_normalized | string | TEXT | 0 | 0.0% | 6 | S (39440); NOT_DEFINED (9278); R (7914); I (526); SDD (53); NS (17) |
| 30 | binary_state_eligible | bool | BOOLEAN | 0 | 0.0% | 2 | True (47354); False (9874) |
| 31 | phenotype_resolvability | string | TEXT | 0 | 0.0% | 2 | BINARY_ELIGIBLE (47354); NON_BINARY (9874) |
| 32 | source_snapshot_id | string | TEXT | 0 | 0.0% | 1 | AMRTRACE_RAW_V1 (57228) |
| 33 | curation_rule_version | string | TEXT | 0 | 0.0% | 1 | CURATION_RULES_V1 (57228) |

### `data/raw/curated_v1/genotype_evidence_curated.parquet`

413,116 rows x 21 columns, sha256 `ea4bbf14ce1a321e...`

Candidate keys (no nulls, no duplicates): `genotype_evidence_id`, `source_row_signature_sha256`

| # | column | arrow type | suggested postgres type | nulls | null % | distinct | values |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | genotype_evidence_id | string | TEXT | 0 | 0.0% | 413116 | e.g. GMV1_7e8fb0293020cea184a532..., GMV1_3eef4d18e5029e73cc1e13..., GMV1_45005222f9876f8efcf443... |
| 2 | representation_source | string | TEXT | 0 | 0.0% | 2 | MICROBIGGE (325265); ISOLATE_AMR_SUMMARY (87851) |
| 3 | target_acc | string | TEXT | 0 | 0.0% | 10584 | e.g. PDT000041778.1, PDT000041778.1, PDT000041778.1 |
| 4 | biosample_acc | string | TEXT | 0 | 0.0% | 10584 | e.g. SAMN03075588, SAMN03075588, SAMN03075588 |
| 5 | asm_acc | string | TEXT | 3162 | 0.8% | 10369 | e.g. GCA_000770275.1, GCA_000770275.1, GCA_000770275.1 |
| 6 | element_raw | string | TEXT | 0 | 0.0% | 1090 | e.g. ariR, aadA5, acrF |
| 7 | element_symbol_raw | string | TEXT | 87851 | 21.3% | 1065 | e.g. ariR, aadA5, acrF |
| 8 | element_name_raw | string | TEXT | 87851 | 21.3% | 522 | e.g. biofilm/acid-resistance reg..., ANT(3'')-Ia family aminogly..., multidrug efflux RND transp... |
| 9 | subtype_raw | string | TEXT | 87851 | 21.3% | 9 | VIRULENCE (149987); AMR (98621); METAL (29033); POINT (16420); BIOCIDE (13731); ACID (9735); HEAT (5410); POINT_DISRUPT (2138); STX_TYPE (190) |
| 10 | subclass_raw | string | TEXT | 252446 | 61.1% | 108 | e.g. STREPTOMYCIN, EFFLUX, STREPTOMYCIN |
| 11 | scope_raw | string | TEXT | 87851 | 21.3% | 2 | plus (241588); core (83677) |
| 12 | amr_method_raw | string | TEXT | 87851 | 21.3% | 17 | e.g. BLASTP, EXACTP, BLASTP |
| 13 | summary_method_raw | string | TEXT | 325265 | 78.7% | 6 | COMPLETE (65566); POINT (19226); PARTIAL_END_OF_CONTIG (1880); PARTIAL (769); MISTRANSLATION (367); HMM (43) |
| 14 | plus_raw | bool | BOOLEAN | 325265 | 78.7% | 2 | False (56745); True (31106) |
| 15 | source_array_offset | int64 | BIGINT | 325265 | 78.7% | 52 | e.g. 0.0, 1.0, 2.0 [min 0.0, max 51.0] |
| 16 | amrfinderplus_analysis_type | string | TEXT | 0 | 0.0% | 2 | COMBINED (314018); NUCLEOTIDE (99098) |
| 17 | amrfinderplus_version | string | TEXT | 0 | 0.0% | 1 | 4.2.7 (413116) |
| 18 | refgene_db_version | string | TEXT | 0 | 0.0% | 3 | 2026-03-24.1 (392195); 2026-05-15.1 (13954); 2026-08-07.1 (6967) |
| 19 | source_row_signature_sha256 | string | TEXT | 0 | 0.0% | 413116 | e.g. 7e8fb0293020cea184a5322bd50..., 3eef4d18e5029e73cc1e13d0a66..., 45005222f9876f8efcf443f6270... |
| 20 | source_snapshot_id | string | TEXT | 0 | 0.0% | 1 | AMRTRACE_RAW_V1 (413116) |
| 21 | curation_rule_version | string | TEXT | 0 | 0.0% | 1 | CURATION_RULES_V1 (413116) |

### `data/raw/curated_v1/isolates_curated.parquet`

10,584 rows x 81 columns, sha256 `438c3834d3c5f15b...`

Candidate keys (no nulls, no duplicates): `target_acc`, `biosample_acc`, `checksum`

- `isolate_identifiers` is a nested column (list<element: string>); 0 empty values. Needs JSONB or a child table.

- `creation_date` text formats: full date 0.0%, year-month 0.0%, year only 0.0%, iso timestamp 100.0%, other 0.0%. Looks like a full timestamp.

- `AMR_genotypes` is a nested column (list<element: struct<element: string, method: string, plus: bool>>); 0 empty values. Needs JSONB or a child table.

- `AMR_genotypes_core` is a nested column (list<element: string>); 1879 empty values. Needs JSONB or a child table.

- `virulence_genotypes` is a nested column (list<element: struct<element: string, method: string>>); 31 empty values. Needs JSONB or a child table.

- `stress_genotypes` is a nested column (list<element: struct<element: string, method: string>>); 94 empty values. Needs JSONB or a child table.

- `AST_phenotypes` is a nested column (list<element: struct<phenotype: string, antibiotic: string>>); 0 empty values. Needs JSONB or a child table.

- `computed_types` is a nested column (struct<antigen_formula: string, serotype: string>); 0 empty values. Needs JSONB or a child table.

- `collection_date` text formats: full date 57.8%, year-month 4.0%, year only 38.2%, iso timestamp 0.0%, other 0.0%. Keep as TEXT unless cleaned.

- `sra_release_date` text formats: full date 0.0%, year-month 0.0%, year only 0.0%, iso timestamp 100.0%, other 0.0%. Looks like a full timestamp.

- `collection_date_raw` text formats: full date 57.8%, year-month 4.0%, year only 38.2%, iso timestamp 0.0%, other 0.0%. Keep as TEXT unless cleaned.

| # | column | arrow type | suggested postgres type | nulls | null % | distinct | values |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | taxgroup_name | string | TEXT | 0 | 0.0% | 1 | E.coli and Shigella (10584) |
| 2 | strain | string | TEXT | 1945 | 18.4% | 8584 | e.g. MRSN17749, MRSN22624, CVM N36963PS |
| 3 | isolate_identifiers | list<element: string> | JSONB | 0 | 0.0% | 10584 | e.g. ["MRSN17749"], ["MRSN22624"], ["CVM N36963PS", "CVM_N3696... |
| 4 | serovar | string | TEXT | 10584 | 100.0% | 0 | all null |
| 5 | serotype | string | TEXT | 10138 | 95.8% | 200 | e.g. O157, O111, O45 |
| 6 | target_acc | string | TEXT | 0 | 0.0% | 10584 | e.g. PDT000041778.1, PDT000041780.1, PDT000045580.1 |
| 7 | creation_date | string | TEXT | 0 | 0.0% | 6289 | e.g. 2014-10-31T15:01:40Z, 2014-10-31T15:02:41Z, 2014-12-07T19:02:55Z |
| 8 | geo_loc_name | string | TEXT | 99 | 0.9% | 106 | e.g. USA, USA, USA |
| 9 | isolation_source | string | TEXT | 168 | 1.6% | 488 | e.g. Surveillance swab - Groin, Wound - sacrum, farm |
| 10 | epi_type | string | TEXT | 0 | 0.0% | 2 | environmental/other (5967); clinical (4617) |
| 11 | erd_group | string | TEXT | 6451 | 61.0% | 2084 | e.g. PDS000117091.425, PDS000117091.425, PDS000248670.1 |
| 12 | minsame | int64 | BIGINT | 6782 | 64.1% | 64 | e.g. 3.0, 3.0, 6.0 [min 0.0, max 73.0] |
| 13 | mindiff | int64 | BIGINT | 9470 | 89.5% | 75 | e.g. 18.0, 21.0, 32.0 [min 0.0, max 82.0] |
| 14 | biosample_acc | string | TEXT | 0 | 0.0% | 10584 | e.g. SAMN03075588, SAMN03075589, SAMN03177674 |
| 15 | asm_acc | string | TEXT | 215 | 2.0% | 10369 | e.g. GCA_000770275.1, GCA_000770285.1, GCA_000797605.1 |
| 16 | AMR_genotypes | list<element: struct<element: string, method: string, plus: bool>> | JSONB | 0 | 0.0% | 4754 | e.g. ["{'element': 'aadA5', 'met..., ["{'element': 'aadA5', 'met..., ["{'element': 'acrF', 'meth... |
| 17 | number_amr_genes | int64 | BIGINT | 0 | 0.0% | 36 | e.g. 20, 23, 9 [min 2, max 52] |
| 18 | AMR_genotypes_core | list<element: string> | JSONB | 0 | 0.0% | 4219 | e.g. ["aadA5=COMPLETE", "aph(3''..., ["aadA5=COMPLETE", "aph(3''..., ["aph(3'')-Ib=COMPLETE", "a... |
| 19 | number_core_amr_genes | int64 | BIGINT | 0 | 0.0% | 35 | e.g. 17, 20, 6 [min 0, max 46] |
| 20 | virulence_genotypes | list<element: struct<element: string, method: string>> | JSONB | 0 | 0.0% | 5457 | e.g. ["{'element': 'fdeC', 'meth..., ["{'element': 'fdeC', 'meth..., ["{'element': 'espX1', 'met... |
| 21 | number_virulence_genes | int64 | BIGINT | 0 | 0.0% | 39 | e.g. 15, 15, 5 [min 0, max 38] |
| 22 | stress_genotypes | list<element: struct<element: string, method: string>> | JSONB | 0 | 0.0% | 1120 | e.g. ["{'element': 'ariR', 'meth..., ["{'element': 'ariR', 'meth..., ["{'element': 'ariR', 'meth... |
| 23 | number_stress_genes | int64 | BIGINT | 0 | 0.0% | 41 | e.g. 3, 3, 1 [min 0, max 40] |
| 24 | AST_phenotypes | list<element: struct<phenotype: string, antibiotic: string>> | JSONB | 0 | 0.0% | 1965 | e.g. ["{'phenotype': 'susceptibl..., ["{'phenotype': 'susceptibl..., ["{'phenotype': 'susceptibl... |
| 25 | number_drugs_tested | int64 | BIGINT | 0 | 0.0% | 34 | e.g. 22, 23, 15 [min 1, max 36] |
| 26 | number_drugs_resistant | int64 | BIGINT | 0 | 0.0% | 28 | e.g. 13, 18, 5 [min 0, max 29] |
| 27 | number_drugs_intermediate | int64 | BIGINT | 0 | 0.0% | 7 | 0 (8800); 1 (1272); 2 (395); 3 (84); 4 (26); 5 (6); 6 (1) [min 0, max 6] |
| 28 | number_drugs_sensitive | int64 | BIGINT | 10584 | 100.0% | 0 | all null |
| 29 | number_drugs_susceptible | int64 | BIGINT | 0 | 0.0% | 26 | e.g. 11, 7, 10 [min 0, max 26] |
| 30 | computed_types | struct<antigen_formula: string, serotype: string> | JSONB | 10584 | 100.0% | 0 | all null |
| 31 | IFSAC_category | string | TEXT | 9784 | 92.4% | 10 | veterinary clinical/researc... (556); turkey (65); pork (45); veterinary clinical/researc... (40); beef (40); chicken (32); companion animal (14); clinical/research, human (4); clinical/research (3); veterinary clinic... |
| 32 | source_type | string | TEXT | 7205 | 68.1% | 4 | animal (1801); food (1451); human (126); other (1) |
| 33 | host | string | TEXT | 3440 | 32.5% | 25 | e.g. Homo sapiens, Homo sapiens, Homo sapiens |
| 34 | kmer_group_acc | string | TEXT | 0 | 0.0% | 1 | PDG000000004 (10584) |
| 35 | scientific_name | string | TEXT | 0 | 0.0% | 1 | Escherichia coli (10584) |
| 36 | amrfinderplus_version | string | TEXT | 0 | 0.0% | 1 | 4.2.7 (10584) |
| 37 | refgene_db_version | string | TEXT | 0 | 0.0% | 3 | 2026-03-24.1 (10179); 2026-05-15.1 (267); 2026-08-07.1 (138) |
| 38 | amrfinderplus_analysis_type | string | TEXT | 0 | 0.0% | 2 | COMBINED (7655); NUCLEOTIDE (2929) |
| 39 | amrfinderplus_applied | int64 | BIGINT | 0 | 0.0% | 1 | 1 (10584) [min 1, max 1] |
| 40 | bioproject_acc | string | TEXT | 0 | 0.0% | 74 | e.g. PRJNA261723, PRJNA261723, PRJNA266657 |
| 41 | collected_by | string | TEXT | 315 | 3.0% | 145 | e.g. MRSN, MRSN, Brigham and Women's Hospital |
| 42 | collection_date | string | TEXT | 181 | 1.7% | 1347 | e.g. 2013-09-24, 2014-05-01, 2012-01-20 |
| 43 | lat_lon | string | TEXT | 5883 | 55.6% | 48 | e.g. 23.986278 S 46.30836899 W, 23.02 N 120.22 E, 24.1955 N 55.65 E |
| 44 | asm_stats_contig_n50 | int64 | BIGINT | 0 | 0.0% | 9695 | e.g. 191197, 191617, 185187 [min 12344, max 5449567] |
| 45 | asm_stats_length_bp | int64 | BIGINT | 0 | 0.0% | 10506 | e.g. 5046460, 5184392, 4836410 [min 4396710, max 6095512] |
| 46 | asm_stats_n_contig | int64 | BIGINT | 0 | 0.0% | 499 | e.g. 92, 114, 85 [min 1, max 747] |
| 47 | LibraryLayout | string | TEXT | 3165 | 29.9% | 1 | PAIRED (7419) |
| 48 | Platform | string | TEXT | 3165 | 29.9% | 1 | ILLUMINA (7419) |
| 49 | Run | string | TEXT | 3165 | 29.9% | 7419 | e.g. SRR2134675, SRR2134681, SRR2976832 |
| 50 | sra_center | string | TEXT | 3165 | 29.9% | 38 | e.g. BRIGHAM & WOMEN'S HOSPITAL, BRIGHAM & WOMEN'S HOSPITAL, BRIGHAM & WOMEN'S HOSPITAL |
| 51 | sra_release_date | string | TEXT | 3165 | 29.9% | 1447 | e.g. 2015-08-04T04:23:50Z, 2015-08-04T04:25:21Z, 2015-12-13T01:41:52Z |
| 52 | species_taxid | int64 | BIGINT | 0 | 0.0% | 1 | 562 (10584) [min 562, max 562] |
| 53 | outbreak | string | TEXT | 10584 | 100.0% | 0 | all null |
| 54 | host_disease | string | TEXT | 6706 | 63.4% | 87 | e.g. Wound, Wound, skin lesion |
| 55 | asm_level | string | TEXT | 215 | 2.0% | 4 | Contig (9877); Scaffold (410); Complete Genome (70); Chromosome (12) |
| 56 | assembly_method | string | TEXT | 215 | 2.0% | 45 | e.g. Newbler v. 2.7, Newbler v. 2.7, CLC Genomics Workbench v. 7.5 |
| 57 | PFGE_PrimaryEnzyme_pattern | string | TEXT | 10578 | 99.9% | 5 | EXDX01.0152 (2); EXHX01.4022 (1); EH2X01.0008 (1); EXWX01.2662 (1); EVCX01.2593 (1) |
| 58 | PFGE_SecondaryEnzyme_pattern | string | TEXT | 10578 | 99.9% | 5 | EXDA26.0010 (2); EXHA26.3807 (1); EH2A26.0127 (1); EXWA26.2383 (1); EVCA26.1634 (1) |
| 59 | taxid | int64 | BIGINT | 0 | 0.0% | 1 | 562 (10584) [min 562, max 562] |
| 60 | wgs_acc_prefix | string | TEXT | 297 | 2.8% | 10287 | e.g. JRKU, JRKV, JUCB |
| 61 | wgs_master_acc | string | TEXT | 297 | 2.8% | 10287 | e.g. JRKU00000000.1, JRKV00000000.1, JUCB00000000.1 |
| 62 | new | int64 | BIGINT | 0 | 0.0% | 1 | 0 (10584) [min 0, max 0] |
| 63 | checksum | string | TEXT | 0 | 0.0% | 10584 | e.g. 2fe9f34b047659c8104d1f32c2e..., 3931e8aa21ea86a6ce9a26155d9..., a39277be33f4b87dd7f4265903a... |
| 64 | strain_raw | string | TEXT | 1945 | 18.4% | 8584 | e.g. MRSN17749, MRSN22624, CVM N36963PS |
| 65 | collection_date_raw | string | TEXT | 181 | 1.7% | 1347 | e.g. 2013-09-24, 2014-05-01, 2012-01-20 |
| 66 | geo_loc_name_raw | string | TEXT | 99 | 0.9% | 106 | e.g. USA, USA, USA |
| 67 | isolation_source_raw | string | TEXT | 168 | 1.6% | 488 | e.g. Surveillance swab - Groin, Wound - sacrum, farm |
| 68 | host_raw | string | TEXT | 3440 | 32.5% | 25 | e.g. Homo sapiens, Homo sapiens, Homo sapiens |
| 69 | host_disease_raw | string | TEXT | 6706 | 63.4% | 87 | e.g. Wound, Wound, skin lesion |
| 70 | erd_group_raw | string | TEXT | 6451 | 61.0% | 2084 | e.g. PDS000117091.425, PDS000117091.425, PDS000248670.1 |
| 71 | epi_type_raw | string | TEXT | 0 | 0.0% | 2 | environmental/other (5967); clinical (4617) |
| 72 | source_type_raw | string | TEXT | 7205 | 68.1% | 4 | animal (1801); food (1451); human (126); other (1) |
| 73 | collection_year | int16 | SMALLINT | 181 | 1.7% | 16 | e.g. 2013.0, 2014.0, 2012.0 [min 2009.0, max 2025.0] |
| 74 | collection_date_precision | string | TEXT | 0 | 0.0% | 4 | FULL_DATE (6018); YEAR (3974); YEAR_MONTH (411); MISSING (181) |
| 75 | isolation_source_key | string | TEXT | 168 | 1.6% | 438 | e.g. surveillance swab - groin, wound - sacrum, farm |
| 76 | host_key | string | TEXT | 3440 | 32.5% | 24 | e.g. homo sapiens, homo sapiens, homo sapiens |
| 77 | geo_loc_name_key | string | TEXT | 99 | 0.9% | 106 | e.g. usa, usa, usa |
| 78 | geo_country_raw | string | TEXT | 99 | 0.9% | 32 | e.g. USA, USA, USA |
| 79 | geo_subregion_raw | string | TEXT | 1930 | 18.2% | 76 | e.g. Boston, Boston, Boston |
| 80 | source_snapshot_id | string | TEXT | 0 | 0.0% | 1 | AMRTRACE_RAW_V1 (10584) |
| 81 | curation_rule_version | string | TEXT | 0 | 0.0% | 1 | CURATION_RULES_V1 (10584) |

### `data/raw/mapping_v1/determinant_drug_mapping_v1.parquet`

43,536 rows x 21 columns, sha256 `5b91c1c47b13e678...`

Candidate keys (no nulls, no duplicates): `mapping_rule_id`

Composite candidates: `source_classification_id` + `candidate_antibiotic`

| # | column | arrow type | suggested postgres type | nulls | null % | distinct | values |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | mapping_rule_id | string | TEXT | 0 | 0.0% | 43536 | e.g. DDMV1_5d443bbcd5abed941e39b..., DDMV1_0c73fdcfda5c387a0c03a..., DDMV1_15ae118eb79865ca27b97... |
| 2 | mapping_version | string | TEXT | 0 | 0.0% | 1 | DETERMINANT_DRUG_MAPPING_V1 (43536) |
| 3 | mapping_context | string | TEXT | 0 | 0.0% | 2 | SOURCE_CLASSIFICATION (22128); SUMMARY_SYMBOL (21408) |
| 4 | source_reference_id | string | TEXT | 0 | 0.0% | 1 | AMRTRACE_MAPPING_REFERENCE_V1 (43536) |
| 5 | source_db_version | string | TEXT | 0 | 0.0% | 3 | 2026-03-24.1 (14512); 2026-05-15.1 (14512); 2026-08-07.1 (14512) |
| 6 | determinant_identity | string | TEXT | 0 | 0.0% | 892 | e.g. aac(2')-IIa, aac(2')-IIa, aac(2')-IIa |
| 7 | source_classification_id | string | TEXT | 0 | 0.0% | 5442 | e.g. CLV1_51f78b8b8880622190e9e3..., CLV1_51f78b8b8880622190e9e3..., CLV1_51f78b8b8880622190e9e3... |
| 8 | source_type | string | TEXT | 0 | 0.0% | 2 | AMR (22128);  (21408) |
| 9 | source_subtype | string | TEXT | 0 | 0.0% | 4 |  (21408); POINT_DISRUPT (12528); AMR (7008); POINT (2592) |
| 10 | source_class | string | TEXT | 0 | 0.0% | 29 | e.g. AMINOGLYCOSIDE, AMINOGLYCOSIDE, AMINOGLYCOSIDE |
| 11 | source_subclass | string | TEXT | 0 | 0.0% | 65 | e.g. KASUGAMYCIN, KASUGAMYCIN, KASUGAMYCIN |
| 12 | source_tables | string | TEXT | 0 | 0.0% | 6 |  (21408); AMRProt-susceptible (12528); ReferenceGeneCatalog;Refere... (6384); AMRProt-mutation;ReferenceG... (2352); ReferenceGeneCatalog (600); ReferenceGeneHierarchy (264) |
| 13 | source_match_types | string | TEXT | 0 | 0.0% | 3 |  (21408); POINT_DISRUPT_GENE_PREFIX (12528); EXACT (9600) |
| 14 | source_match_fields | string | TEXT | 0 | 0.0% | 10 |  (21408); gene_symbol (12528); gene_family;symbol (3360); allele;symbol (2952); allele;reported_mutation_sy... (2328); gene_family (432); symbol (264); allele (168); allele;gene_family;symbol (72); allele;reported_mut... |
| 15 | source_classifications_json | string | TEXT | 0 | 0.0% | 103 | e.g. [{"class":"AMINOGLYCOSIDE",..., [{"class":"AMINOGLYCOSIDE",..., [{"class":"AMINOGLYCOSIDE",... |
| 16 | candidate_antibiotic | string | TEXT | 0 | 0.0% | 8 | cefepime (5442); ceftazidime (5442); ceftriaxone (5442); ciprofloxacin (5442); gentamicin (5442); imipenem (5442); meropenem (5442); trimethoprim-sulfamethoxazole (5442) |
| 17 | mapping_strength | string | TEXT | 0 | 0.0% | 5 | NO_CANDIDATE_MAPPING (39693); CLASS_SUPPORT (3516); COMPONENT_SUPPORT (162); DIRECT_DRUG_SUPPORT (96); REQUIRES_CONTEXT (69) |
| 18 | relationship | string | TEXT | 0 | 0.0% | 3 | UNMAPPED (39693); SUPPORTS_RESISTANCE (3612); REQUIRES_CONTEXT (231) |
| 19 | mapping_reason | string | TEXT | 0 | 0.0% | 16 | e.g. No exact candidate or CEPHA..., No exact candidate or CEPHA..., No exact candidate or CEPHA... |
| 20 | ambiguity_policy_id | string | TEXT | 0 | 0.0% | 1 | DETERMINANT_REFERENCE_AMBIG... (43536) |
| 21 | rule_status | string | TEXT | 0 | 0.0% | 1 | ACTIVE (43536) |

<!-- END GENERATED -->

## Decisions (hand-written, not regenerated)

### OD-1
- Question: which per-drug splits are the true frozen V1? (plan, section 11)
- Evidence: OD-1 mismatch list above; all checks pass and every row reads "files match value 1".
- Decision: the frozen files win (plan default). Value 1 is the frozen V1 (for example ciprofloxacin 8,787, gentamicin 9,715, G+/S 1,288, unresolved 8,389 = 20.04%). Value 2 matches no frozen file and is treated as superseded.

### Proposed column mapping for ADR-003 (to confirm in the design session)
| draft column | frozen column |
| --- | --- |
| isolate_target_acc (all tables) | target_acc |
| snapshot_id (all tables) | source_snapshot_id |
| ast_evidence.testing_standard | standard |
| genotype_evidence.element_symbol | element_symbol_raw |
| genotype_evidence.element_subclass | subclass_raw |
| genotype_evidence.element_class | no counterpart (only subtype_raw and subclass_raw exist) |
| genotype_evidence.evidence_type | representation_source (proposed) |
| mapping_rule.determinant | determinant_identity |
| mapping_rule.antibiotic | candidate_antibiotic |
| mapping_rule.relation | relationship |
| mapping_rule.status | rule_status |
| mapping_rule.organism | no column; constant E. coli |
| case.panel_version | panel_id |

### Open points for the design session
- Case grain is target_acc + antibiotic (unique); case_id is a hash, so fixtures should use real ids.
- Case list columns hold the dependency ids; explode them into edge rows at ingest. Counts are in "List columns" above.
- 91% of mapping rows are explicit UNMAPPED rows; keep them, they matter for applicability dependencies.
- asm_acc is nullable (215 isolates): never a key. checksum differs per table: rename on ingest.
- Antibiotic lookup has 8 entries (cefepime, ceftazidime, imipenem are outside the panel).
- To verify: the 188 isolates without a case have only non-panel AST rows.
