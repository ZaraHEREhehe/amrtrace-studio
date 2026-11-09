SELECT
  a.*
FROM `ncbi-pathogen-detect.pdbrowser.ast` AS a
WHERE
  a.antibiotic IN (
    'gentamicin',
    'trimethoprim-sulfamethoxazole',
    'ciprofloxacin',
    'ceftriaxone',
    'meropenem',
    'ceftazidime',
    'imipenem',
    'cefepime'
  )
  AND EXISTS (
    SELECT 1
    FROM `ncbi-pathogen-detect.pdbrowser.isolates` AS i
    WHERE
      i.target_acc = a.target_acc
      AND i.scientific_name = 'Escherichia coli'
  )
ORDER BY
  a.target_acc,
  a.antibiotic,
  a.id;