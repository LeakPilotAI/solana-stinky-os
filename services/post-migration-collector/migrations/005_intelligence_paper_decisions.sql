CREATE TABLE IF NOT EXISTS intelligence_paper_decisions (
  id bigserial PRIMARY KEY,
  shadow_score_id bigint NOT NULL REFERENCES intelligence_shadow_scores(id),
  track_id uuid NOT NULL,
  mint text NOT NULL,
  policy_version text NOT NULL,
  score_version text NOT NULL,
  prospective_boundary timestamptz NOT NULL,
  decided_at timestamptz NOT NULL,
  decision text NOT NULL CHECK (decision IN ('PAPER_WOULD_ENTER','PAPER_PASS','NO_DECISION')),
  rationale jsonb NOT NULL,
  authority jsonb NOT NULL,
  UNIQUE(shadow_score_id, policy_version)
);
CREATE OR REPLACE FUNCTION genesis_forbid_intelligence_paper_decision_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'intelligence_paper_decisions is immutable';
END $$;
DROP TRIGGER IF EXISTS intelligence_paper_decisions_immutable ON intelligence_paper_decisions;
CREATE TRIGGER intelligence_paper_decisions_immutable
BEFORE UPDATE OR DELETE ON intelligence_paper_decisions
FOR EACH ROW EXECUTE FUNCTION genesis_forbid_intelligence_paper_decision_mutation();
