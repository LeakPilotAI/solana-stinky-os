CREATE TABLE IF NOT EXISTS intelligence_execution_v2_plans (
 id BIGSERIAL PRIMARY KEY,
 policy_version TEXT NOT NULL REFERENCES intelligence_execution_v2_registry(policy_version),
 policy_sha256 TEXT NOT NULL,
 paper_decision_id BIGINT NOT NULL REFERENCES intelligence_paper_decisions(id),
 track_id UUID NOT NULL, mint TEXT NOT NULL,
 planned_at TIMESTAMPTZ NOT NULL, entry_target TIMESTAMPTZ NOT NULL, exit_target TIMESTAMPTZ NOT NULL,
 plan JSONB NOT NULL, plan_sha256 TEXT NOT NULL,
 CHECK(planned_at < entry_target), CHECK(exit_target > entry_target),
 UNIQUE(policy_version,paper_decision_id)
);
CREATE TABLE IF NOT EXISTS intelligence_execution_v2_results (
 plan_id BIGINT PRIMARY KEY REFERENCES intelligence_execution_v2_plans(id),
 recorded_at TIMESTAMPTZ NOT NULL,
 result JSONB NOT NULL, result_sha256 TEXT NOT NULL
);
CREATE OR REPLACE FUNCTION genesis_forbid_execution_v2_evidence_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'execution V2 evidence is immutable'; END $$;
DROP TRIGGER IF EXISTS execution_v2_plans_immutable ON intelligence_execution_v2_plans;
CREATE TRIGGER execution_v2_plans_immutable BEFORE UPDATE OR DELETE ON intelligence_execution_v2_plans
FOR EACH ROW EXECUTE FUNCTION genesis_forbid_execution_v2_evidence_mutation();
DROP TRIGGER IF EXISTS execution_v2_results_immutable ON intelligence_execution_v2_results;
CREATE TRIGGER execution_v2_results_immutable BEFORE UPDATE OR DELETE ON intelligence_execution_v2_results
FOR EACH ROW EXECUTE FUNCTION genesis_forbid_execution_v2_evidence_mutation();
DROP TRIGGER IF EXISTS execution_v2_plans_no_truncate ON intelligence_execution_v2_plans;
CREATE TRIGGER execution_v2_plans_no_truncate BEFORE TRUNCATE ON intelligence_execution_v2_plans
FOR EACH STATEMENT EXECUTE FUNCTION genesis_forbid_execution_v2_evidence_mutation();
DROP TRIGGER IF EXISTS execution_v2_results_no_truncate ON intelligence_execution_v2_results;
CREATE TRIGGER execution_v2_results_no_truncate BEFORE TRUNCATE ON intelligence_execution_v2_results
FOR EACH STATEMENT EXECUTE FUNCTION genesis_forbid_execution_v2_evidence_mutation();
