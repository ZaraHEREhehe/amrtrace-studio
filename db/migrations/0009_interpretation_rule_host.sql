-- D-22: host-specific breakpoints (CLSI VET01S). All three columns are optional, so every rule stored before
-- this migration reads exactly as it did. A host rule's rule_key carries the host as a fifth part.
ALTER TABLE interpretation_rule ADD COLUMN host text;                -- host group, e.g. dog; NULL = applies to any host
ALTER TABLE interpretation_rule ADD COLUMN source text;              -- document and row the numbers were copied from
ALTER TABLE interpretation_rule ADD COLUMN breakpoint_species text;  -- species the breakpoint was set for
