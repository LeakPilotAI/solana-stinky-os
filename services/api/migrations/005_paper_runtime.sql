CREATE TABLE IF NOT EXISTS paper_runtime_intake (
  intake_id text PRIMARY KEY,
  mint text NOT NULL,
  observed_at timestamptz NOT NULL,
  payload jsonb NOT NULL,
  payload_sha256 text NOT NULL,
  processed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (length(payload_sha256) = 64)
);

CREATE TABLE IF NOT EXISTS paper_runtime_record (
  intake_id text PRIMARY KEY REFERENCES paper_runtime_intake(intake_id),
  mint text NOT NULL,
  decided_at timestamptz,
  shadow_status text NOT NULL,
  shadow_action text,
  paper_status text NOT NULL,
  record jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_paper_runtime_intake_unprocessed
  ON paper_runtime_intake(created_at) WHERE processed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_paper_runtime_record_mint_created
  ON paper_runtime_record(mint, created_at DESC);

CREATE OR REPLACE FUNCTION genesis_forbid_paper_runtime_record_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'paper_runtime_record is immutable';
END $$;

DROP TRIGGER IF EXISTS paper_runtime_record_immutable ON paper_runtime_record;
CREATE TRIGGER paper_runtime_record_immutable
BEFORE UPDATE OR DELETE ON paper_runtime_record
FOR EACH ROW EXECUTE FUNCTION genesis_forbid_paper_runtime_record_mutation();
