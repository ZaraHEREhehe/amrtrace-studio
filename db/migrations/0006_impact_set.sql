-- 0006: stored impact sets (task I-08).
--
-- When a change is applied, the selector's result is written here so that it can be shown, compared and
-- re-used later without running the selector again. One impact_set row per change, one impact_item row per
-- selected case. Both tables are append-only: a stored selection is a record of what was decided, so it can
-- never be edited or removed. The mechanism column is free text on purpose (the selector may add new ones).
--
-- release_id has no foreign key on purpose: release is a protected ledger table and a new table pointing at it
-- would change what a TRUNCATE of the ledger tables has to list. The selector only ever names an existing release.
--
-- A separate trigger function is used instead of forbid_mutation() so the checks that count forbid_mutation
-- triggers on the four ledger tables stay as they are.

CREATE TABLE impact_set (
    change_id   text PRIMARY KEY REFERENCES change_event (change_id),
    release_id  text NOT NULL,                                    -- the release the selector ran against (no foreign key: see below)
    level1_size integer NOT NULL CHECK (level1_size >= 0),        -- every case with an edge to a changed node
    level2_size integer NOT NULL CHECK (level2_size >= 0 AND level2_size <= level1_size),
    created_at  timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE impact_item (
    change_id text NOT NULL REFERENCES impact_set (change_id),
    case_id   text NOT NULL REFERENCES "case" (case_id),
    mechanism text NOT NULL,
    reason    text NOT NULL,
    PRIMARY KEY (change_id, case_id)
);
CREATE INDEX impact_item_case_idx ON impact_item (case_id);

CREATE FUNCTION forbid_impact_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only table: % is not allowed on %', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER impact_set_no_update_delete
    BEFORE UPDATE OR DELETE ON impact_set
    FOR EACH ROW EXECUTE FUNCTION forbid_impact_mutation();
CREATE TRIGGER impact_set_no_truncate
    BEFORE TRUNCATE ON impact_set
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_impact_mutation();
CREATE TRIGGER impact_item_no_update_delete
    BEFORE UPDATE OR DELETE ON impact_item
    FOR EACH ROW EXECUTE FUNCTION forbid_impact_mutation();
CREATE TRIGGER impact_item_no_truncate
    BEFORE TRUNCATE ON impact_item
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_impact_mutation();

GRANT SELECT, INSERT ON impact_set, impact_item TO amrtrace_app;
