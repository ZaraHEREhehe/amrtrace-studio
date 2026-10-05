-- Live demo of the failure case: the ledger refuses to be rewritten (task I-03).
-- Safe to run: everything happens in one transaction that is rolled back at the end.
--
-- Usage (docker):
--   Get-Content db\demo_append_only.sql | docker exec -i amrtrace-pg psql -U postgres -d amrtrace -X
--
-- Every statement marked "should FAIL" prints an ERROR line. That is the expected, desired result.

\set ON_ERROR_STOP off
\set ON_ERROR_ROLLBACK on
\pset pager off
\pset border 2

\echo
\echo ============================================================
\echo  AMRTrace append-only ledger demo (all changes rolled back)
\echo ============================================================

BEGIN;

INSERT INTO isolate (target_acc) VALUES ('PDT_DEMO');
INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES ('CASE_DEMO', 'PDT_DEMO', 'gentamicin', 'DEMO');
INSERT INTO release (release_id, version_vector, status) VALUES ('R_DEMO', '{}', 'DRAFT');
INSERT INTO case_state (case_id, release_id, state_code, explanation, verification_status)
    VALUES ('CASE_DEMO', 'R_DEMO', 'CONCORDANT_SUSCEPTIBLE', '{"why": "original conclusion"}', 'EVALUATED');
UPDATE release SET status = 'PUBLISHED' WHERE release_id = 'R_DEMO';

\echo
\echo 0. The stored conclusion:
SELECT case_id, release_id, state_code, explanation FROM case_state WHERE case_id = 'CASE_DEMO';

\echo
\echo 1. Rewrite the conclusion with UPDATE (should FAIL):
UPDATE case_state SET state_code = 'CONCORDANT_RESISTANT' WHERE case_id = 'CASE_DEMO';

\echo
\echo 2. Erase it with DELETE (should FAIL):
DELETE FROM case_state WHERE case_id = 'CASE_DEMO';

\echo
\echo 3. Wipe the ledger with TRUNCATE ... CASCADE (should FAIL):
TRUNCATE change_event CASCADE;

\echo
\echo 4. Add a new state to the PUBLISHED release (should FAIL, published releases are frozen):
INSERT INTO isolate (target_acc) VALUES ('PDT_DEMO2');
INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES ('CASE_DEMO2', 'PDT_DEMO2', 'gentamicin', 'DEMO');
INSERT INTO case_state (case_id, release_id, state_code, explanation, verification_status)
    VALUES ('CASE_DEMO2', 'R_DEMO', 'UNRESOLVED', '{}', 'EVALUATED');

\echo
\echo 5. Un-publish the release (should FAIL):
UPDATE release SET status = 'DRAFT' WHERE release_id = 'R_DEMO';

\echo
\echo 6. The application role tries the same UPDATE (should FAIL, no permission):
SET ROLE amrtrace_app;
UPDATE case_state SET state_code = 'CONCORDANT_RESISTANT';
RESET ROLE;

\echo
\echo 7. A correction is made the only allowed way: a new review row (should SUCCEED):
INSERT INTO review_event (case_id, state_id, reviewer, action, reason)
    SELECT 'CASE_DEMO', state_id, 'demo reviewer', 'CORRECT', 'manual check disagrees' FROM case_state WHERE case_id = 'CASE_DEMO';
SELECT action, reason FROM review_event;

\echo
\echo 8. After all of that, the original conclusion is exactly as it was:
SELECT case_id, release_id, state_code, explanation FROM case_state WHERE case_id = 'CASE_DEMO';

ROLLBACK;

\echo
\echo Demo finished: nothing was saved (ROLLBACK).
