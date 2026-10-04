-- 0002: engine tables (plan section 5.3 as amended by ADR-003 sections 4 to 7).
-- These hold versions, releases, ledger states, dependencies, change events and review events.
-- The engine packages stay generic (ADR-001): nothing here encodes a specific drug, standard or edition,
-- apart from the five case-state codes, which are the project's data model.

CREATE TABLE version_node (
    node_type    text NOT NULL,
    node_id      text NOT NULL,
    version      text NOT NULL,
    effective_at timestamptz,
    metadata     jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (node_type, node_id, version)
);

-- Interpretation tables loaded from data/interpretation/*.yaml (ADR-002). Organism, antibiotic and standard
-- are free text on purpose: any drug, standard or edition is just a row.
CREATE TABLE interpretation_rule (
    rule_key               text NOT NULL,                -- canonical (standard, organism, antibiotic, method)
    interpretation_version text NOT NULL,
    standard               text NOT NULL,
    organism               text NOT NULL,
    antibiotic             text NOT NULL,
    method                 text NOT NULL,
    categories             jsonb NOT NULL,               -- [{"label":"susceptible","op":"<=","value":2}, ...]
    PRIMARY KEY (rule_key, interpretation_version)
);

CREATE TABLE change_event (
    change_id        text PRIMARY KEY,
    type             text NOT NULL,                      -- validated by the differ registry, not by a CHECK
    old_version      text,
    new_version      text,
    changed_entities jsonb NOT NULL DEFAULT '[]'::jsonb,
    declared_scope   jsonb NOT NULL DEFAULT '{}'::jsonb,
    initiator        text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE release (
    release_id             text PRIMARY KEY,             -- R1 is the frozen V1 baseline
    version_vector         jsonb NOT NULL,
    created_at             timestamptz NOT NULL DEFAULT now(),
    triggered_by_change_id text REFERENCES change_event (change_id),
    status                 text NOT NULL
        CHECK (status IN ('DRAFT', 'VALIDATED', 'PUBLISHED', 'BLOCKED', 'FAILED'))
);

CREATE TABLE case_state (
    state_id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id                text NOT NULL REFERENCES "case" (case_id),
    release_id             text NOT NULL REFERENCES release (release_id),
    state_code             text NOT NULL
        CHECK (state_code IN ('CONCORDANT_RESISTANT', 'CONCORDANT_SUSCEPTIBLE',
                              'DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S',
                              'DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE', 'UNRESOLVED')),
    phenotype_state        text,                         -- evaluator stage 1 (ADR-004)
    genotype_state         text,                         -- evaluator stage 2 (ADR-004)
    uncertainty_reason     text,
    explanation            jsonb NOT NULL,
    verification_status    text NOT NULL
        CHECK (verification_status IN ('EVALUATED', 'RE_VERIFIED_UNCHANGED', 'STATE_CHANGED')),
    refgene_db_version     text,                         -- per case (3 values in V1), not only per release
    evaluator_version      text,
    input_hash             text,
    output_hash            text,
    source_state_id        text,                         -- frozen case_state_id (R1 rows only)
    supersedes_state_id    bigint REFERENCES case_state (state_id),
    triggered_by_change_id text REFERENCES change_event (change_id),
    created_at             timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, release_id)
);
CREATE INDEX case_state_case_created_idx ON case_state (case_id, created_at);
CREATE INDEX case_state_release_idx ON case_state (release_id);

-- Realised dependency edges plus provenance/version edges (ADR-003 section 5). About 1.2 million rows for R1.
CREATE TABLE dependency (
    dep_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id      text NOT NULL REFERENCES "case" (case_id),
    release_id   text NOT NULL REFERENCES release (release_id),
    dep_type     text NOT NULL,                          -- input_evidence | positive_support | applicability | provenance_version | ...
    edge_type    text NOT NULL
        CHECK (edge_type IN ('derived_from', 'evaluated_against', 'composed_of')),
    node_type    text NOT NULL,
    node_id      text NOT NULL,
    node_version text,
    node_context jsonb                                    -- e.g. {"mic": 4.0, "sign": "=="} for region refinement
);
-- reverse reachability: from a changed node to the cases that depend on it
CREATE INDEX dependency_node_idx ON dependency (node_type, node_id, node_version);
CREATE INDEX dependency_case_release_idx ON dependency (case_id, release_id);

-- Rule space each case was evaluated against, keyed on the pair, not on the rule id (ADR-003 section 6).
CREATE TABLE applicability (
    case_id              text NOT NULL REFERENCES "case" (case_id),
    release_id           text NOT NULL REFERENCES release (release_id),
    determinant_identity text NOT NULL,
    candidate_antibiotic text NOT NULL,
    organism             text,
    evidence_type        text,
    rule_set_version     text
);
CREATE INDEX applicability_pair_idx ON applicability (candidate_antibiotic, determinant_identity);
CREATE INDEX applicability_case_release_idx ON applicability (case_id, release_id);

CREATE TABLE reeval_run (
    run_id           text PRIMARY KEY,
    change_id        text NOT NULL REFERENCES change_event (change_id),
    mode             text NOT NULL CHECK (mode IN ('SELECTIVE', 'EXHAUSTIVE')),
    status           text NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETE', 'FAILED')),
    selected_count   integer,
    reevaluated_count integer,
    started_at       timestamptz,
    finished_at      timestamptz,
    error            text
);

CREATE TABLE review_event (
    review_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id    text NOT NULL REFERENCES "case" (case_id),
    state_id   bigint NOT NULL REFERENCES case_state (state_id),
    reviewer   text NOT NULL,
    action     text NOT NULL CHECK (action IN ('CONFIRM', 'CORRECT', 'MARK_UNRESOLVED')),
    reason     text NOT NULL CHECK (length(btrim(reason)) > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX review_event_case_idx ON review_event (case_id, created_at);
