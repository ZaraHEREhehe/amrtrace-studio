-- 0007: guards for re-evaluation runs (task I-09).
--
-- reeval_run was created in 0002 and the application role may update a few of its columns (0003). Nothing yet
-- stopped a finished run from being rewritten or two live runs from existing for one change. This adds:
--   * release_id: the release a run wrote (null when it wrote none: failed, or nothing was selected)
--   * at most one live (PENDING, RUNNING or COMPLETE) run per change and mode; a FAILED run can be retried
--   * a guard on UPDATE: identity columns never change, a run only moves forward, COMPLETE and FAILED are final,
--     a finished run has a finish time, and a COMPLETE run re-evaluated exactly the cases it selected
--   * runs can never be deleted or truncated
-- forbid_impact_mutation() (migration 0006) is reused for delete and truncate, so the count of
-- forbid_mutation() triggers on the four ledger tables stays as it was.

ALTER TABLE reeval_run ADD COLUMN release_id text;
GRANT UPDATE (release_id) ON reeval_run TO amrtrace_app;

CREATE UNIQUE INDEX reeval_run_one_live_idx
    ON reeval_run (change_id, mode) WHERE status IN ('PENDING', 'RUNNING', 'COMPLETE');

CREATE FUNCTION guard_reeval_run_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.change_id IS DISTINCT FROM OLD.change_id
       OR NEW.mode IS DISTINCT FROM OLD.mode THEN
        RAISE EXCEPTION 'reeval_run %: run_id, change_id and mode cannot change', OLD.run_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status IN ('COMPLETE', 'FAILED') THEN
        RAISE EXCEPTION 'reeval_run %: a % run is final', OLD.run_id, OLD.status
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NOT (NEW.status = OLD.status
            OR (OLD.status = 'PENDING' AND NEW.status IN ('RUNNING', 'FAILED'))
            OR (OLD.status = 'RUNNING' AND NEW.status IN ('COMPLETE', 'FAILED'))) THEN
        RAISE EXCEPTION 'reeval_run %: status cannot change from % to %', OLD.run_id, OLD.status, NEW.status
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status IN ('COMPLETE', 'FAILED') AND NEW.finished_at IS NULL THEN
        RAISE EXCEPTION 'reeval_run %: a % run needs a finish time', OLD.run_id, NEW.status
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status = 'COMPLETE' AND NEW.reevaluated_count IS DISTINCT FROM NEW.selected_count THEN
        RAISE EXCEPTION 'reeval_run %: a COMPLETE run must have re-evaluated every selected case (% of %)',
            OLD.run_id, NEW.reevaluated_count, NEW.selected_count
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER reeval_run_guard_update
    BEFORE UPDATE ON reeval_run
    FOR EACH ROW EXECUTE FUNCTION guard_reeval_run_update();
CREATE TRIGGER reeval_run_no_delete
    BEFORE DELETE ON reeval_run
    FOR EACH ROW EXECUTE FUNCTION forbid_impact_mutation();
CREATE TRIGGER reeval_run_no_truncate
    BEFORE TRUNCATE ON reeval_run
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_impact_mutation();
