-- 0013: Z-18 application identity and RBAC (after 0011 source alerts and 0012 support structure). PostgreSQL role amrtrace_app is NOT an application user.
-- Compatible with existing populated databases: no existing ledger row is updated.
-- New actor_user_id is NULL for historical/CLI rows; every authenticated HTTP write binds
-- amrtrace.actor_user_id on its request-scoped connection before any INSERT.

CREATE TABLE app_user (
    user_id text PRIMARY KEY,
    username text NOT NULL,
    role text NOT NULL CHECK (role IN ('ANALYST', 'REVIEWER', 'ADMIN')),
    password_hash text NOT NULL,
    active boolean NOT NULL DEFAULT TRUE,
    failed_attempts integer NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_login_at timestamptz,
    CHECK (length(btrim(username)) > 0)
);
CREATE UNIQUE INDEX app_user_username_ci_idx ON app_user (lower(username));

CREATE TABLE app_session (
    session_hash text PRIMARY KEY CHECK (session_hash ~ '^[0-9a-f]{64}$'),
    user_id text NOT NULL REFERENCES app_user(user_id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX app_session_user_idx ON app_session (user_id, expires_at DESC);
CREATE INDEX app_session_expiry_idx ON app_session (expires_at);

ALTER TABLE change_event ADD COLUMN actor_user_id text REFERENCES app_user(user_id);
ALTER TABLE review_event ADD COLUMN actor_user_id text REFERENCES app_user(user_id);
ALTER TABLE reeval_run ADD COLUMN actor_user_id text REFERENCES app_user(user_id);

-- INSERT-time attribution only; immutable ledger UPDATE/DELETE triggers remain intact.
-- Attribute engine-generated runs and draft-applied changes without changing generic
-- evaluator/change/ledger service function signatures. The HTTP dependency sets the
-- variable for the life of its one database connection, including inner commits.
CREATE FUNCTION stamp_authenticated_actor() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    authenticated_user text;
BEGIN
    authenticated_user := NULLIF(current_setting('amrtrace.actor_user_id', true), '');
    IF authenticated_user IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM app_user
            WHERE user_id = authenticated_user AND active = TRUE
        ) THEN
            RAISE EXCEPTION 'Authenticated actor is no longer active'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    -- Never accept a supplied actor_user_id on an unbound connection.
    -- Legacy/CLI operations remain NULL; authenticated HTTP operations are stamped.
    NEW.actor_user_id := authenticated_user;
    RETURN NEW;
END;
$$;

CREATE TRIGGER change_event_authenticated_actor
    BEFORE INSERT ON change_event
    FOR EACH ROW EXECUTE FUNCTION stamp_authenticated_actor();
CREATE TRIGGER review_event_authenticated_actor
    BEFORE INSERT ON review_event
    FOR EACH ROW EXECUTE FUNCTION stamp_authenticated_actor();
CREATE TRIGGER reeval_run_authenticated_actor
    BEFORE INSERT ON reeval_run
    FOR EACH ROW EXECUTE FUNCTION stamp_authenticated_actor();

-- Only the administrator CLI can create accounts, change their roles,
-- disable them, or set password hashes. The runtime DB role has read access
-- plus the exact login/session lifecycle updates it needs.
GRANT SELECT ON app_user, app_session TO amrtrace_app;
GRANT UPDATE (failed_attempts, locked_until, last_login_at) ON app_user TO amrtrace_app;
GRANT INSERT ON app_session TO amrtrace_app;
GRANT UPDATE (revoked_at) ON app_session TO amrtrace_app;
