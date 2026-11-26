-- 0019: Review Copilot cache and pins (task I-30, decision D-27, rule 9).
--
-- Until now every "Write and store a summary" press asked the model again and appended a row to copilot_summary, and
-- every saved chat answer appended a row to copilot_chat_answer. Generated text is now kept once per set of inputs:
--
--   copilot_cache  one row per fingerprint, a SHA-256 of everything the text was written from (the case, the two
--                  ledger states, the stored records it cites, the template, narrative and prompt versions and the
--                  configured models). Same inputs, same row: the model is asked again only when an input changes.
--                  A cache, not a record: rows may be pruned, so it is not append-only.
--   copilot_pin    a Reviewer or Admin keeps a summary or an answer on the case. The pin holds a copy of the text
--                  and the fingerprint it came from, so it stands alone after its cache row is pruned. Append-only.
--
-- Both are generated text, apart from evidence; no engine step (evaluation, selection, re-evaluation, comparison,
-- release gate) reads them. copilot_summary (0015) and copilot_chat_answer (0016) stay as read-only history.
-- Migrations 0001 to 0018 are applied on other machines, so this is a new file.

CREATE TABLE copilot_cache (
    fingerprint  text PRIMARY KEY CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    kind         text NOT NULL CHECK (kind IN ('summary', 'answer')),
    -- the case it is about, if any (a chat answer may be about a change or a gene); no foreign key into case_state,
    -- as for copilot_summary, so generated text never takes part in the ledger's own guards
    case_id      text REFERENCES "case" (case_id),
    state_id     bigint,
    generator    text NOT NULL,                     -- 'templates', 'records', or 'local:<model>' / 'hosted:<model>'
    body         jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_used_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX copilot_cache_case_idx ON copilot_cache (case_id, kind);
CREATE INDEX copilot_cache_used_idx ON copilot_cache (kind, last_used_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON copilot_cache TO amrtrace_app;

CREATE TABLE copilot_pin (
    pin_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind         text NOT NULL CHECK (kind IN ('summary', 'answer')),
    case_id      text NOT NULL REFERENCES "case" (case_id),
    state_id     bigint,
    -- the cache row it was pinned from; no foreign key, because cache rows may be pruned
    fingerprint  text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    question     text,                              -- answers only
    generator    text NOT NULL,
    body         jsonb NOT NULL,                    -- the text as it was pinned
    pinned_by    text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (kind = 'answer' OR question IS NULL)
);

CREATE INDEX copilot_pin_case_idx ON copilot_pin (case_id, created_at DESC);

-- its own function, like copilot_summary, so forbid_mutation still guards only the four ledger tables
CREATE FUNCTION forbid_copilot_pin_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only table: % is not allowed on copilot_pin', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER copilot_pin_no_update_delete
    BEFORE UPDATE OR DELETE ON copilot_pin
    FOR EACH ROW EXECUTE FUNCTION forbid_copilot_pin_change();
CREATE TRIGGER copilot_pin_no_truncate
    BEFORE TRUNCATE ON copilot_pin
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_copilot_pin_change();

GRANT SELECT, INSERT ON copilot_pin TO amrtrace_app;
