SELECT
  target_acc,
  biosample_acc,
  scientific_name,
  taxgroup_name,
  strain,
  serovar,
  serotype,
  computed_types,
  geo_loc_name,
  isolation_source,
  epi_type,
  source_type,
  IFSAC_category,
  host,
  host_disease,
  erd_group,
  bioproject_acc,
  collection_date,
  creation_date,
  asm_acc,
  amrfinderplus_analysis_type,
  amrfinderplus_version,
  refgene_db_version,
  checksum
FROM `ncbi-pathogen-detect.pdbrowser.isolates`
WHERE scientific_name = 'Escherichia coli'
ORDER BY target_acc;