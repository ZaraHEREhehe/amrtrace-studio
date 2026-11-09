-- 0014: Review Copilot summaries (task I-19, decision D-27, rule 9).
--
-- A summary is generated text: a plain-language account of why a case changed, written from stored records. It is
-- kept in its own table, apart from evidence, and no engine step (evaluation, selection, re-evaluation, comparison,
-- release gate) reads it. Each row says which two states it explains and what wrote it (the templates, or the model
-- that reworded them). Rows are append-only: a new summary is a new row. Migrations 0001 to 0013 are applied on other
-- machines, so this is a new file.

CREATE TABLE copilot_summary (
    summary_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id          text NOT NULL REFERENCES "case" (case_id),
    -- the two states it explains, as read from the ledger; deliberately no foreign key into case_state, so generated
    -- text never takes part in the ledger's own guards (a ledger table must not depend on, or be held by, this one)
    before_state_id  bigint,
    after_state_id   bigint,
    generator        text NOT NULL,                     -- 'templates', or 'local:<model>' / 'hosted:<model>'
    template_version text NOT NULL,
    body             jsonb NOT NULL,                    -- sentences, each with the stored records it came from
    created_at       timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX copilot_summary_case_idx ON copilot_summary (case_id, after_state_id, created_at DESC);

-- its own function, like the impact and draft tables, so forbid_mutation still guards only the four ledger tables
CREATE FUNCTION forbid_copilot_summary_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only table: % is not allowed on copilot_summary', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER copilot_summary_no_update_delete
    BEFORE UPDATE OR DELETE ON copilot_summary
    FOR EACH ROW EXECUTE FUNCTION forbid_copilot_summary_change();
CREATE TRIGGER copilot_summary_no_truncate
    BEFORE TRUNCATE ON copilot_summary
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_copilot_summary_change();

GRANT SELECT, INSERT ON copilot_summary TO amrtrace_app;
