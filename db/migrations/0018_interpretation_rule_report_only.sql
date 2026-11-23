-- 0018: report-only rules (task A-28). A source can say a drug is approved for a species but has no breakpoint for
-- it, so only the measurement should be reported (CLSI VET01S Ed7 Table 1, group D). The table marks such a rule and
-- chooses, once for the whole table, what the engine does with it:
--
--   not_defined      the result gets no category and the case shows NOT_DEFINED
--   keep_submitted   the laboratory's label stands
--   NULL             the categories are applied as before (the default, so no stored rule changes meaning)
--
-- Both columns are optional, so every rule stored before this migration reads exactly as it did.
ALTER TABLE interpretation_rule ADD COLUMN report_only boolean;        -- TRUE or NULL, never FALSE
ALTER TABLE interpretation_rule ADD COLUMN report_only_policy text;

ALTER TABLE interpretation_rule ADD CONSTRAINT interpretation_rule_report_only_true
    CHECK (report_only IS NULL OR report_only);
ALTER TABLE interpretation_rule ADD CONSTRAINT interpretation_rule_report_only_policy_known
    -- IS TRUE, because a NULL marker would make the whole check NULL, and PostgreSQL lets a NULL check pass
    CHECK (report_only_policy IS NULL OR (report_only IS TRUE AND report_only_policy IN ('not_defined', 'keep_submitted')));
