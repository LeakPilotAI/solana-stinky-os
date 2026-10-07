-- A new registry only; V1 and existing prospective/historical evidence are untouched.
CREATE TABLE IF NOT EXISTS intelligence_execution_v2_registry (
    policy_version TEXT PRIMARY KEY CHECK (policy_version = 'genesis-paper-execution-v2'),
    policy_sha256 TEXT NOT NULL CHECK (length(policy_sha256) = 64),
    policy JSONB NOT NULL,
    prospective_boundary TIMESTAMPTZ NOT NULL
);
CREATE OR REPLACE FUNCTION genesis_forbid_execution_v2_registry_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'intelligence_execution_v2_registry is immutable';
END $$;
DROP TRIGGER IF EXISTS execution_v2_registry_immutable ON intelligence_execution_v2_registry;
CREATE TRIGGER execution_v2_registry_immutable BEFORE UPDATE OR DELETE
ON intelligence_execution_v2_registry FOR EACH ROW
EXECUTE FUNCTION genesis_forbid_execution_v2_registry_mutation();
DROP TRIGGER IF EXISTS execution_v2_registry_no_truncate ON intelligence_execution_v2_registry;
CREATE TRIGGER execution_v2_registry_no_truncate BEFORE TRUNCATE
ON intelligence_execution_v2_registry FOR EACH STATEMENT
EXECUTE FUNCTION genesis_forbid_execution_v2_registry_mutation();
