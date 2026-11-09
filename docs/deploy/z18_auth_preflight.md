# Z-18 production authentication preflight (review-only; DO NOT execute on production in this task)

## Release gate and prerequisite

This application is auto-published from **main** through Z-12 CI/CD, but the deployed database **does not automatically apply new SQL migrations**. The deployment owner reports the Azure VM is currently stopped; verify this before any merge or restart, since automatic polling may resume after startup. Z-18 must remain unmerged until the deployment owner verifies these steps on the actual VM. A passing local suite cannot replace the production readiness check.

1. Obtain a current successful build/CI record and inventory the installed image tag, deployed `runtime.env`, PostgreSQL target, current migration state and existing Caddy Basic Auth proxy. Do not print secrets or entire environment files. The rollback image tag must be recorded before changing anything.
2. Confirm the production API container receives `AMRTRACE_ENV=production` and `AMRTRACE_COOKIE_SECURE=true` through `/opt/amrtrace-studio/runtime.env` (or equivalent configured `env_file`). Check the *presence and boolean values* of these flags without disclosing other variables. The TLS-terminating public proxy must send the HTTPS site host correctly. Do not remove Caddy Basic Auth.
3. Verify current PostgreSQL privileges: the migration account can create `app_user`, `app_session`, trigger functions and constraints. Runtime `amrtrace_app` is not a login Admin and must not have permission to create accounts or modify roles/password hashes.
4. Take and verify a **recoverable** PostgreSQL backup with the project's established retention/access policy; separately retain the existing app release image and configs. Do not store passwords, backup contents or production database dumps in GitHub.
5. In an approved maintenance window, first apply `0013_application_identity.sql` with `psql -v ON_ERROR_STOP=1 --single-transaction -f db/migrations/0013_application_identity.sql` against the **confirmed production database**, using an operator-managed connection. On error, halt rollout. Apply exactly once after the existing migrations `0001` through `0012`.
6. As an authorized database operator, create at least one active Admin using `PYTHONPATH=src python -m amrtrace.api.user_admin create --username <operator-account> --role ADMIN`, entering the password interactively; never pass passwords on a command line, in CI logs, or in repository files. Verify the account exists and the password hash is stored, not plaintext.
7. Only **after** migration and flags are verified, allow the reviewed application image rollout. Validate live `/health`, existing read-only `/api/cases?limit=1`, Dashboard, Change Events, Review Queue, Runs, Exports and Dossier. On HTTPS, login cookies must include `Secure`, `HttpOnly` and `SameSite=Strict`; test Admin directory, Analyst allowed/Reviewer forbidden and vice versa, 401/403, CSRF denial, logout revocation, no release publishing by Analysts, and actor-user attribution. Confirm existing Z-12 proxy/health checks still pass.
8. If the new app fails, roll back the **application image only** according to Z-12's reviewed rollback procedure. The identity migration is additive, so the previous application may ignore its new tables and nullable columns; do not delete ledger records or apply destructive schema rollback. Retain an incident record.

## Query-only database preflight examples (operator-supplied connection)

```sql
SELECT to_regclass('public.app_user') AS users_table,
       to_regclass('public.app_session') AS sessions_table;
SELECT table_name, column_name, is_nullable
FROM information_schema.columns
WHERE table_schema='public'
  AND table_name IN ('change_event', 'review_event', 'reeval_run')
  AND column_name='actor_user_id'
ORDER BY table_name;
SELECT tgrelid::regclass AS rel, tgname
FROM pg_trigger
WHERE tgname IN ('change_event_authenticated_actor',
                 'review_event_authenticated_actor',
                 'reeval_run_authenticated_actor')
ORDER BY rel::text;
```

## Evidence that must be retained before any merge

- Actual disposable PostgreSQL 16 migration run + before/after row count checks.
- Authenticated existing HTTP API tests and Change Events / Review Queue / release-gate equivalence regressions.
- Current feature-branch GitHub Actions green **eight-job** CI; main CI from before Z-18 is not sufficient.
- Real-browser login, logout, account directory, CSRF-error, review and non-publishing Analyst run paths.
- Secure cookie and migration **production preflight confirmation by deployment owner** before triggering an auto-deploy.
- No secrets committed; reviewer Insharah approves PR with `Closes #134` and PROJECT_PLAN.md §16.4 update.

**Status on 2026-11-09:** Prepared instructions only; production is not inspected, migrated, restarted, or changed.
