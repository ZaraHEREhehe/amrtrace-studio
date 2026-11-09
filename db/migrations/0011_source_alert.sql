-- 0011: alerts from the change detection engine (task A-18, decision D-25).
--
-- Some changes cannot become a draft by themselves: a new breakpoint edition is a licensed document a person must
-- enter, and a new AMRFinderPlus database needs mapping rules before its results can be read. The engine raises an
-- alert for these instead. An alert is never a change event; a person acknowledges it once they have acted on it.
--   * an alert can only move OPEN -> ACKNOWLEDGED, once, together with who acknowledged it
--   * nothing else about an alert ever changes, and an alert can never be deleted

CREATE TABLE source_alert (
    alert_id              text PRIMARY KEY,                 -- a hash of what was found, so a re-run finds the same id
    source                text NOT NULL,                    -- the watcher that raised it, for example 'standards'
    kind                  text NOT NULL,                    -- what was found, for example 'NEW_STANDARD_EDITION'
    subject               text NOT NULL,                    -- what it is about, for example 'CLSI M100 Ed36'
    message               text NOT NULL,                    -- what a person should do, in plain words
    details               jsonb NOT NULL DEFAULT '{}'::jsonb,
    detected_at           timestamptz NOT NULL DEFAULT clock_timestamp(),
    status                text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'ACKNOWLEDGED')),
    acknowledged_by       text,
    acknowledged_at       timestamptz,
    acknowledgement_note  text,
    CHECK (status = 'OPEN' OR (acknowledged_by IS NOT NULL AND acknowledged_at IS NOT NULL))
);

CREATE INDEX source_alert_status_idx ON source_alert (status, detected_at);

CREATE FUNCTION guard_source_alert_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.alert_id IS DISTINCT FROM OLD.alert_id
       OR NEW.source IS DISTINCT FROM OLD.source
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.subject IS DISTINCT FROM OLD.subject
       OR NEW.message IS DISTINCT FROM OLD.message
       OR NEW.details IS DISTINCT FROM OLD.details
       OR NEW.detected_at IS DISTINCT FROM OLD.detected_at THEN
        RAISE EXCEPTION 'source alert %: only the acknowledgement can change', OLD.alert_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status = 'OPEN' AND NEW.status = 'ACKNOWLEDGED' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'source alert %: status cannot change from % to %', OLD.alert_id, OLD.status, NEW.status
        USING ERRCODE = 'restrict_violation';
END;
$$;

-- its own function, like change_draft, so forbid_mutation still guards only the four ledger tables
CREATE FUNCTION forbid_source_alert_removal() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'append-only table: % is not allowed on source_alert', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER source_alert_guard_update
    BEFORE UPDATE ON source_alert
    FOR EACH ROW EXECUTE FUNCTION guard_source_alert_update();
CREATE TRIGGER source_alert_no_delete
    BEFORE DELETE ON source_alert
    FOR EACH ROW EXECUTE FUNCTION forbid_source_alert_removal();
CREATE TRIGGER source_alert_no_truncate
    BEFORE TRUNCATE ON source_alert
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_source_alert_removal();

GRANT SELECT, INSERT ON source_alert TO amrtrace_app;
GRANT UPDATE (status, acknowledged_by, acknowledged_at, acknowledgement_note) ON source_alert TO amrtrace_app;
