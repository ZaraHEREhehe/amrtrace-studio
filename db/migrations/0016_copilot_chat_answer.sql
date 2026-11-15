-- 0016: saved Review Copilot chat answers (task I-25, decision D-27, rule 9).
--
-- Asking the copilot a question is read-only. A Reviewer or Admin may save an answer, the same rule as a summary
-- (I-19, Z-18). A saved answer is generated text: the question, the sentences, the stored records each sentence cites,
-- and what wrote it (templates, a model, or the retrieved records alone). It is kept in its own table, apart from
-- evidence, and no engine step (evaluation, selection, re-evaluation, comparison, release gate) reads it. Rows are
-- append-only. Migrations 0001 to 0015 are applied on other machines, so this is a new file.

CREATE TABLE copilot_chat_answer (
    answer_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id          text NOT NULL REFERENCES "case" (case_id),
    -- the state the answer was written about; no foreign key into case_state, as for copilot_summary (0015)
    state_id         bigint,
    question         text NOT NULL CHECK (length(btrim(question)) > 0),
    mode             text NOT NULL CHECK (mode IN ('template', 'local', 'hosted', 'records_only')),
    generator        text NOT NULL,                     -- 'templates', 'records', or 'local:<model>' / 'hosted:<model>'
    saved_by         text NOT NULL,
    body             jsonb NOT NULL,                    -- answer sentences with their source ids, and the sources
    created_at       timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX copilot_chat_answer_case_idx ON copilot_chat_answer (case_id, created_at DESC);

-- its own function, like copilot_summary, so forbid_mutation still guards only the four ledger tables
CREATE FUNCTION forbid_copilot_chat_answer_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only table: % is not allowed on copilot_chat_answer', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER copilot_chat_answer_no_update_delete
    BEFORE UPDATE OR DELETE ON copilot_chat_answer
    FOR EACH ROW EXECUTE FUNCTION forbid_copilot_chat_answer_change();
CREATE TRIGGER copilot_chat_answer_no_truncate
    BEFORE TRUNCATE ON copilot_chat_answer
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_copilot_chat_answer_change();

GRANT SELECT, INSERT ON copilot_chat_answer TO amrtrace_app;
