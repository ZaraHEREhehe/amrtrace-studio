SELECT
  m.*
FROM `ncbi-pathogen-detect.pdbrowser.microbigge` AS m
WHERE EXISTS (
  SELECT 1
  FROM `ncbi-pathogen-detect.pdbrowser.isolates` AS i
  WHERE
    i.target_acc = m.target_acc
    AND i.scientific_name = 'Escherichia coli'
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
)
ORDER BY
  m.target_acc,
  m.subtype,
  m.element_symbol;