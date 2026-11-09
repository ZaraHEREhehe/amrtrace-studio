SELECT
  i.*
FROM `ncbi-pathogen-detect.pdbrowser.isolates` AS i
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
ORDER BY i.target_acc;