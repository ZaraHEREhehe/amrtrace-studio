-- 0005: a CORRECT review states what the reviewer believes the state should be (task I-12).
--
-- review_event stays append-only (migration 0003 triggers are untouched); this only adds a column.
-- Ledger states (case_state) are NOT changed by a review: the corrected value is the reviewer's view,
-- shown next to the evaluator's state. Existing rows get NULL, which is valid for CONFIRM and MARK_UNRESOLVED.

ALTER TABLE review_event ADD COLUMN corrected_state_code text;

ALTER TABLE review_event ADD CONSTRAINT review_event_corrected_code_valid
    CHECK (corrected_state_code IS NULL OR corrected_state_code IN (
        'CONCORDANT_RESISTANT', 'CONCORDANT_SUSCEPTIBLE', 'DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S',
        'DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE', 'UNRESOLVED'));

-- exactly the CORRECT reviews carry a corrected value
ALTER TABLE review_event ADD CONSTRAINT review_event_correct_has_value
    CHECK ((action = 'CORRECT') = (corrected_state_code IS NOT NULL));