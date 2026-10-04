-- 0003: append-only enforcement in the database (plan hard rule 1) and the application role.
--
-- case_state, review_event and change_event can only ever grow. Row triggers block UPDATE and DELETE,
-- statement triggers block TRUNCATE. The triggers fire for every role, the table owner included.
-- Limit, stated honestly: a superuser can still disable triggers or set session_replication_role to
-- replica. The application role below never has those rights.

CREATE FUNCTION forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only table: % is not allowed on %', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER case_state_no_update_delete
    BEFORE UPDATE OR DELETE ON case_state
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER case_state_no_truncate
    BEFORE TRUNCATE ON case_state
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();

CREATE TRIGGER review_event_no_update_delete
    BEFORE UPDATE OR DELETE ON review_event
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER review_event_no_truncate
    BEFORE TRUNCATE ON review_event
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();

CREATE TRIGGER change_event_no_update_delete
    BEFORE UPDATE OR DELETE ON change_event
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER change_event_no_truncate
    BEFORE TRUNCATE ON change_event
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();

-- Application role. NOLOGIN here: no password lives in the repo. Deployment creates a login role from
-- environment variables and grants it membership in amrtrace_app.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'amrtrace_app') THEN
        CREATE ROLE amrtrace_app NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO amrtrace_app;

-- Everything is insert-and-read only for the application...
GRANT SELECT, INSERT ON
    snapshot, antibiotic, isolate, ast_evidence, genotype_evidence, mapping_rule, "case",
    version_node, interpretation_rule, change_event, release, case_state, dependency, applicability,
    reeval_run, review_event
TO amrtrace_app;

-- ...except two narrow, deliberate updates: a release moves DRAFT -> PUBLISHED (status only),
-- and a re-evaluation run records its progress.
GRANT UPDATE (status) ON release TO amrtrace_app;
GRANT UPDATE (status, selected_count, reevaluated_count, started_at, finished_at, error) ON reeval_run TO amrtrace_app;

-- No DELETE or TRUNCATE is granted anywhere. dependency and applicability are insert-only too;
-- task A-03 can widen that with its own migration if it needs idempotent rebuilds.
