-- 0013: a later snapshot's evidence is stored beside the V1 rows (task I-20, decision D-30).
--
-- Loading a later snapshot adds only its new and edited AST and genotype rows, under their own ids and their own
-- source_snapshot_id; nothing already stored is changed. An edited AST row keeps NCBI's row id ("id", loaded as
-- source_row_id), and an edited summary row can keep its signature, so these two columns are unique within one
-- snapshot, no longer across all of them. Migrations 0001 to 0012 are applied on other machines, so this is a new file.

ALTER TABLE ast_evidence DROP CONSTRAINT ast_evidence_source_row_id_key;
ALTER TABLE ast_evidence
    ADD CONSTRAINT ast_evidence_source_row_snapshot_key UNIQUE (source_row_id, source_snapshot_id);

ALTER TABLE genotype_evidence DROP CONSTRAINT genotype_evidence_source_row_signature_sha256_key;
ALTER TABLE genotype_evidence
    ADD CONSTRAINT genotype_evidence_signature_snapshot_key UNIQUE (source_row_signature_sha256, source_snapshot_id);

-- the loader and the re-evaluation find a snapshot's rows by isolate
CREATE INDEX ast_evidence_snapshot_target_idx ON ast_evidence (source_snapshot_id, target_acc);
CREATE INDEX genotype_evidence_snapshot_target_idx ON genotype_evidence (source_snapshot_id, target_acc);
