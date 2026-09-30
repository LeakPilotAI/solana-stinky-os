-- First-class immutable paper policy identity for runtime evidence.
-- Existing rows remain NULL/legacy; never infer historical identity from current active policy.
ALTER TABLE paper_runtime_record
  ADD COLUMN IF NOT EXISTS policy_version TEXT,
  ADD COLUMN IF NOT EXISTS policy_sha256 TEXT,
  ADD COLUMN IF NOT EXISTS policy_evidence_backed BOOLEAN;

ALTER TABLE paper_runtime_record
  DROP CONSTRAINT IF EXISTS paper_runtime_record_policy_sha256_len;
ALTER TABLE paper_runtime_record
  ADD CONSTRAINT paper_runtime_record_policy_sha256_len
  CHECK (policy_sha256 IS NULL OR length(policy_sha256) = 64);

CREATE INDEX IF NOT EXISTS idx_paper_runtime_record_policy_identity
  ON paper_runtime_record(policy_sha256, policy_version, created_at DESC);
