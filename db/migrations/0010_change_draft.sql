-- 0010: drafts written by the change detection engine (task A-13, decision D-25).
--
-- A watcher compares two source snapshots and proposes typed change events. A proposal is only a draft: nothing
-- reaches change_event (the official, append-only record) until a person applies it, and a dismissed draft is
-- kept with who dismissed it and why. Migrations 0001 to 0009 are applied on other machines, so this is a new file.
--   * a draft can only move PENDING -> APPLIED or PENDING -> DISMISSED, once
--   * only the decision columns change, and only together with that move
--   * an applied draft must name the change event it became; a draft can never be deleted

CREATE TABLE change_draft (
    draft_id          text PRIMARY KEY,                     -- a hash of what was found, so a re-run finds the same id
    watcher           text NOT NULL,
    change_type       text NOT NULL,                        -- validated by the differ registry when applied
    old_version       text NOT NULL,
    new_version       text NOT NULL,
    changed_entities  jsonb NOT NULL,
    summary           jsonb NOT NULL DEFAULT '{}'::jsonb,
    old_snapshot_id   text NOT NULL,
    new_snapshot_id   text NOT NULL,
    detected_at       timestamptz NOT NULL DEFAULT clock_timestamp(),
    status            text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPLIED', 'DISMISSED')),
    decided_by        text,
    decided_at        timestamptz,
    decision_note     text,
    applied_change_id text REFERENCES change_event (change_id),
    CHECK (status <> 'APPLIED' OR applied_change_id IS NOT NULL),
    CHECK (status = 'PENDING' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL))
);

CREATE INDEX change_draft_status_idx ON change_draft (status, detected_at);

CREATE FUNCTION guard_change_draft_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.draft_id IS DISTINCT FROM OLD.draft_id
       OR NEW.watcher IS DISTINCT FROM OLD.watcher
       OR NEW.change_type IS DISTINCT FROM OLD.change_type
       OR NEW.old_version IS DISTINCT FROM OLD.old_version
       OR NEW.new_version IS DISTINCT FROM OLD.new_version
       OR NEW.changed_entities IS DISTINCT FROM OLD.changed_entities
       OR NEW.summary IS DISTINCT FROM OLD.summary
       OR NEW.old_snapshot_id IS DISTINCT FROM OLD.old_snapshot_id
       OR NEW.new_snapshot_id IS DISTINCT FROM OLD.new_snapshot_id
       OR NEW.detected_at IS DISTINCT FROM OLD.detected_at THEN
        RAISE EXCEPTION 'change draft %: only the decision can change', OLD.draft_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status = 'PENDING' AND NEW.status IN ('APPLIED', 'DISMISSED') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'change draft %: status cannot change from % to %', OLD.draft_id, OLD.status, NEW.status
        USING ERRCODE = 'restrict_violation';
END;
$$;

-- its own function, like the impact tables, so forbid_mutation still guards only the four ledger tables
CREATE FUNCTION forbid_change_draft_removal() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only table: % is not allowed on change_draft', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER change_draft_guard_update
    BEFORE UPDATE ON change_draft
    FOR EACH ROW EXECUTE FUNCTION guard_change_draft_update();
CREATE TRIGGER change_draft_no_delete
    BEFORE DELETE ON change_draft
    FOR EACH ROW EXECUTE FUNCTION forbid_change_draft_removal();
CREATE TRIGGER change_draft_no_truncate
    BEFORE TRUNCATE ON change_draft
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_change_draft_removal();

GRANT SELECT, INSERT ON change_draft TO amrtrace_app;
GRANT UPDATE (status, decided_by, decided_at, decision_note, applied_change_id) ON change_draft TO amrtrace_app;
