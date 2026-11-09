SELECT
  i.target_acc,
  i.biosample_acc,
  i.asm_acc,
  i.amrfinderplus_analysis_type,
  i.amrfinderplus_version,
  i.refgene_db_version,
  g.element,
  g.method,
  g.plus,
  source_array_offset
FROM `ncbi-pathogen-detect.pdbrowser.isolates` AS i
CROSS JOIN UNNEST(i.AMR_genotypes) AS g
WITH OFFSET AS source_array_offset
WHERE
  i.scientific_name = 'Escherichia coli'
  AND EXISTS (
    SELECT 1
    FROM `ncbi-pathogen-detect.pdbrowser.ast` AS a
    WHERE
      a.target_acc = i.target_acc
      AND a.antibiotic IN (
        'gentamicin',
        'trimethoprim-sulfamethoxazole',
        'ciprofloxacin',
        'ceftriaxone',
        'meropenem',
        'ceftazidime',
        'imipenem',
        'cefepime'
      )
  )
ORDER BY
  i.target_acc,
  source_array_offset;
