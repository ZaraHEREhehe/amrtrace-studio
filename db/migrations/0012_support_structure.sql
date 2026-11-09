-- 0012: how each case's state holds together (task A-15, plan section 3.1).
--
-- The dependency table says what a case depended on. This table says how those items hold its state:
--   contradiction        AST results that disagree, which together keep the case in conflict
--   composite            items that are needed together (both halves of a combination, an anchor plus a second gene)
--   alternative_support  items any one of which is enough, so losing one leaves the state standing
-- Each row is one item in one group; a group needs `need` distinct members for the state to hold.
-- The rows are written beside the dependency rows but are not part of the evaluation hash or the equivalence
-- comparison, so releases stored before this table existed are unchanged and simply have no rows here.
-- Like dependency, the table is insert-only. release_id has no foreign key on purpose, as in impact_set (0006):
-- release is a protected ledger table, and a new table pointing at it would change what a TRUNCATE of the ledger
-- tables has to list. The materializer only writes rows for a release it has just checked exists.

CREATE TABLE support_structure (
    case_id     text NOT NULL REFERENCES "case" (case_id),
    release_id  text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('contradiction', 'composite', 'alternative_support')),
    group_key   text NOT NULL,
    need        integer NOT NULL CHECK (need >= 1),
    node_type   text NOT NULL,
    node_id     text NOT NULL,
    member      text NOT NULL
);
CREATE INDEX support_structure_node_idx ON support_structure (node_type, node_id);
CREATE INDEX support_structure_case_release_idx ON support_structure (case_id, release_id);

-- its own function, like the impact tables, so forbid_mutation still guards only the four ledger tables
CREATE FUNCTION forbid_support_structure_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only table: % is not allowed on support_structure', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER support_structure_no_update_delete
    BEFORE UPDATE OR DELETE ON support_structure
    FOR EACH ROW EXECUTE FUNCTION forbid_support_structure_mutation();
CREATE TRIGGER support_structure_no_truncate
    BEFORE TRUNCATE ON support_structure
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_support_structure_mutation();

GRANT SELECT, INSERT ON support_structure TO amrtrace_app;

-- what the selector expects a selected case's re-evaluation to show, read from the rows above; empty when unknown
ALTER TABLE impact_item ADD COLUMN expected_effect text;
