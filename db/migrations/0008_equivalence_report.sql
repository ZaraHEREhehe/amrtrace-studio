-- 0008: stored equivalence reports (task I-10).
--
-- After a selective re-evaluation (I-09) the exhaustive comparator re-evaluates every case and compares the two
-- results on three axes (state, uncertainty, dependency explanation). One row here records the outcome, so the
-- gate decision (publish or block the release) can always be shown and checked later. Append-only: a report is a
-- record of what was found, so it can never be edited or removed.
--
-- No foreign keys on purpose, for the same reason as impact_set.release_id (0006): a new table pointing at the
-- protected ledger tables would change what a TRUNCATE of those tables has to list. The run ids and the release id
-- are checked by the comparator when it writes the row. exhaustive_run_id is unique, so one run gives one report.
-- forbid_impact_mutation() (0006) is reused, so the count of forbid_mutation() triggers stays as it was.

CREATE TABLE equivalence_report (
    report_id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    change_id              text NOT NULL,
    selective_run_id       text NOT NULL,
    exhaustive_run_id      text NOT NULL UNIQUE,
    release_id             text,                                   -- the selective release compared; null if nothing was selected
    passed                 boolean NOT NULL,
    total_cases            integer NOT NULL CHECK (total_cases >= 0),
    selected               integer NOT NULL CHECK (selected >= 0),
    affected               integer NOT NULL CHECK (affected >= 0),
    missed                 integer NOT NULL CHECK (missed >= 0 AND missed <= affected),
    state_mismatches       integer NOT NULL CHECK (state_mismatches >= 0),
    uncertainty_mismatches integer NOT NULL CHECK (uncertainty_mismatches >= 0),
    dependency_mismatches  integer NOT NULL CHECK (dependency_mismatches >= 0),
    report                 jsonb NOT NULL,                         -- the full report, with example mismatches
    created_at             timestamptz NOT NULL DEFAULT clock_timestamp(),
    -- a report can only say "passed" when all three axes agree
    CONSTRAINT equivalence_report_passed_matches_counts CHECK (
        passed = (state_mismatches = 0 AND uncertainty_mismatches = 0 AND dependency_mismatches = 0))
);
CREATE INDEX equivalence_report_change_idx ON equivalence_report (change_id);

CREATE TRIGGER equivalence_report_no_update_delete
    BEFORE UPDATE OR DELETE ON equivalence_report
    FOR EACH ROW EXECUTE FUNCTION forbid_impact_mutation();
CREATE TRIGGER equivalence_report_no_truncate
    BEFORE TRUNCATE ON equivalence_report
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_impact_mutation();

GRANT SELECT, INSERT ON equivalence_report TO amrtrace_app;
