-- 0017: selective-only publication with a recorded verification level (task I-27; supervisor decision 17 Nov 2026).
--
-- A selective run alone may now publish the release a change wrote. The exhaustive comparison becomes optional and
-- Admin-only: before publishing (the gate, as before) or later against a published release (an audit). The release
-- records how it was verified, once, in the same update that publishes it:
--
--   SELECTIVE    only the selected cases were re-evaluated (the release is "selectively verified")
--   EXHAUSTIVE   a stored exhaustive comparison passed before publishing
--
-- A release no change wrote (a baseline, a full load) has no level. A release published before this migration has
-- none either and is shown as "not recorded". The rule is enforced here as well as in ledger/publication.py, so no
-- code path can skip it:
--
--   * a change-written release reaches PUBLISHED only with a COMPLETE selective run of its change that wrote it, and
--     with a level; EXHAUSTIVE also needs the newest stored comparison of that release by that change to have passed
--     with a COMPLETE exhaustive run, and SELECTIVE is refused when that newest comparison failed
--   * the level is set once, when the release is published, and never changes afterwards (a later audit is a stored
--     equivalence_report row; it never rewrites the release)
--
-- Migrations 0001 to 0016 are applied on other machines, so this is a new file. guard_release_update() (0004) is not
-- changed: this is a second BEFORE UPDATE trigger, which PostgreSQL runs after release_guard_update (name order).

ALTER TABLE release ADD COLUMN verification_level text;
ALTER TABLE release ADD CONSTRAINT release_verification_level_known
    CHECK (verification_level IS NULL OR verification_level IN ('SELECTIVE', 'EXHAUSTIVE'));
ALTER TABLE release ADD CONSTRAINT release_verification_level_needs_change
    CHECK (verification_level IS NULL OR triggered_by_change_id IS NOT NULL);
GRANT UPDATE (verification_level) ON release TO amrtrace_app;

CREATE FUNCTION guard_release_publication() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    latest_passed boolean;
    latest_exhaustive text;
BEGIN
    IF NEW.verification_level IS DISTINCT FROM OLD.verification_level
       AND NOT (OLD.verification_level IS NULL AND OLD.status <> 'PUBLISHED' AND NEW.status = 'PUBLISHED') THEN
        RAISE EXCEPTION 'release %: the verification level is recorded once, when the release is published',
            OLD.release_id
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF NEW.status = 'PUBLISHED' AND OLD.status <> 'PUBLISHED' AND NEW.triggered_by_change_id IS NOT NULL THEN
        IF NEW.verification_level IS NULL THEN
            RAISE EXCEPTION 'release % was written by change % and needs a verification level to be published',
                NEW.release_id, NEW.triggered_by_change_id
                USING ERRCODE = 'restrict_violation';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM reeval_run
            WHERE change_id = NEW.triggered_by_change_id AND mode = 'SELECTIVE' AND status = 'COMPLETE'
              AND release_id = NEW.release_id
        ) THEN
            RAISE EXCEPTION 'release %: no COMPLETE selective run of change % wrote it, so it cannot be published',
                NEW.release_id, NEW.triggered_by_change_id
                USING ERRCODE = 'restrict_violation';
        END IF;

        SELECT passed, exhaustive_run_id INTO latest_passed, latest_exhaustive
        FROM equivalence_report
        WHERE release_id = NEW.release_id AND change_id = NEW.triggered_by_change_id
        ORDER BY report_id DESC
        LIMIT 1;

        IF NEW.verification_level = 'EXHAUSTIVE' THEN
            IF latest_passed IS NOT TRUE OR NOT EXISTS (
                SELECT 1 FROM reeval_run
                WHERE run_id = latest_exhaustive AND change_id = NEW.triggered_by_change_id AND mode = 'EXHAUSTIVE'
                  AND status = 'COMPLETE' AND release_id = NEW.release_id
            ) THEN
                RAISE EXCEPTION 'release %: EXHAUSTIVE needs a passing stored comparison by change %',
                    NEW.release_id, NEW.triggered_by_change_id
                    USING ERRCODE = 'restrict_violation';
            END IF;
        ELSIF latest_passed IS FALSE THEN
            RAISE EXCEPTION 'release %: its stored comparison by change % failed, so it cannot be published',
                NEW.release_id, NEW.triggered_by_change_id
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER release_publication_guard
    BEFORE UPDATE ON release
    FOR EACH ROW EXECUTE FUNCTION guard_release_publication();
