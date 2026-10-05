-- 0004: release ordering and lifecycle guards (task I-02).
--
-- Migrations 0001 to 0003 are already applied on other machines and must not change, so this is a new file.
--   * release gets release_seq, a gapless-enough, strictly increasing order used for "as of release R" reads
--   * created_at defaults use clock_timestamp(), so rows made in one transaction still differ
--   * a release can only move DRAFT -> VALIDATED | PUBLISHED | BLOCKED | FAILED and VALIDATED -> PUBLISHED | BLOCKED
--   * only the status of a release can change, and a release can never be deleted
--   * case_state rows can only be added to a DRAFT release: a published release is immutable
-- Ledger rules live in the database as well as in src/amrtrace/ledger, so nothing can bypass them.

ALTER TABLE release ADD COLUMN release_seq bigint GENERATED ALWAYS AS IDENTITY;
ALTER TABLE release ADD CONSTRAINT release_release_seq_key UNIQUE (release_seq);
ALTER TABLE release ALTER COLUMN created_at SET DEFAULT clock_timestamp();
ALTER TABLE case_state ALTER COLUMN created_at SET DEFAULT clock_timestamp();

CREATE FUNCTION guard_release_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.release_id IS DISTINCT FROM OLD.release_id
       OR NEW.release_seq IS DISTINCT FROM OLD.release_seq
       OR NEW.version_vector IS DISTINCT FROM OLD.version_vector
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.triggered_by_change_id IS DISTINCT FROM OLD.triggered_by_change_id THEN
        RAISE EXCEPTION 'release %: only the status can change', OLD.release_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;
    IF (OLD.status = 'DRAFT' AND NEW.status IN ('VALIDATED', 'PUBLISHED', 'BLOCKED', 'FAILED'))
       OR (OLD.status = 'VALIDATED' AND NEW.status IN ('PUBLISHED', 'BLOCKED')) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'release %: status cannot change from % to %', OLD.release_id, OLD.status, NEW.status
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER release_guard_update
    BEFORE UPDATE ON release
    FOR EACH ROW EXECUTE FUNCTION guard_release_update();
CREATE TRIGGER release_no_delete
    BEFORE DELETE ON release
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER release_no_truncate
    BEFORE TRUNCATE ON release
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation();

CREATE FUNCTION guard_case_state_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    current_status text;
BEGIN
    SELECT status INTO current_status FROM release WHERE release_id = NEW.release_id;
    IF current_status IS DISTINCT FROM 'DRAFT' THEN
        RAISE EXCEPTION 'release % is % : states can only be added to a DRAFT release',
            NEW.release_id, coalesce(current_status, 'missing')
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER case_state_insert_guard
    BEFORE INSERT ON case_state
    FOR EACH ROW EXECUTE FUNCTION guard_case_state_insert();
