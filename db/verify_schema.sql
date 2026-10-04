-- Structural check for I-01: run after the migrations. Prints SCHEMA OK or raises an error.
-- Usage (docker): Get-Content db\verify_schema.sql | docker exec -i amrtrace-pg psql -U postgres -d amrtrace -v ON_ERROR_STOP=1
DO $$
DECLARE
    expected_tables text[] := ARRAY[
        'snapshot', 'antibiotic', 'isolate', 'ast_evidence', 'genotype_evidence', 'mapping_rule', 'case',
        'version_node', 'interpretation_rule', 'change_event', 'release', 'case_state', 'dependency',
        'applicability', 'reeval_run', 'review_event'];
    t text;
    n integer;
BEGIN
    -- 1. every expected table exists, and nothing unexpected (schema_migration belongs to the runner)
    FOREACH t IN ARRAY expected_tables LOOP
        IF to_regclass('public.' || quote_ident(t)) IS NULL THEN
            RAISE EXCEPTION 'missing table: %', t;
        END IF;
    END LOOP;
    SELECT count(*) INTO n FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
          AND table_name <> ALL (expected_tables || ARRAY['schema_migration']);
    IF n <> 0 THEN
        RAISE EXCEPTION '% unexpected table(s) in schema public', n;
    END IF;

    -- 2. column counts match ADR-003 section 3
    FOR t, n IN VALUES ('isolate', 74), ('ast_evidence', 22), ('genotype_evidence', 19),
                       ('mapping_rule', 21), ('case', 4) LOOP
        IF (SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = t) <> n THEN
            RAISE EXCEPTION 'table % should have % columns', t, n;
        END IF;
    END LOOP;

    -- 3. antibiotic lookup: 8 rows, 5 in the panel
    IF (SELECT count(*) FROM antibiotic) <> 8 OR (SELECT count(*) FROM antibiotic WHERE in_panel) <> 5 THEN
        RAISE EXCEPTION 'antibiotic lookup should have 8 rows with 5 in the panel';
    END IF;

    -- 4. append-only triggers exist and are enabled on the three ledger tables (a row trigger and a truncate trigger each)
    FOREACH t IN ARRAY ARRAY['case_state', 'review_event', 'change_event'] LOOP
        SELECT count(*) INTO n FROM pg_trigger
            WHERE tgrelid = ('public.' || t)::regclass AND NOT tgisinternal AND tgenabled = 'O';
        IF n <> 2 THEN
            RAISE EXCEPTION 'table % should have 2 enabled append-only triggers, found %', t, n;
        END IF;
    END LOOP;

    -- 5. application role: can insert into the ledger, cannot update or delete it
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'amrtrace_app') THEN
        RAISE EXCEPTION 'role amrtrace_app is missing';
    END IF;
    IF NOT has_table_privilege('amrtrace_app', 'case_state', 'INSERT')
       OR has_table_privilege('amrtrace_app', 'case_state', 'UPDATE')
       OR has_table_privilege('amrtrace_app', 'case_state', 'DELETE')
       OR has_table_privilege('amrtrace_app', 'case_state', 'TRUNCATE') THEN
        RAISE EXCEPTION 'amrtrace_app privileges on case_state are wrong';
    END IF;

    RAISE NOTICE 'SCHEMA OK';
END
$$;
