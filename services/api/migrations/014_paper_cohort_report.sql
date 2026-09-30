-- Bounded chronological cohort scan, including a stable tie breaker.
CREATE INDEX IF NOT EXISTS idx_paper_runtime_record_cohort_report
  ON paper_runtime_record(policy_sha256, created_at, intake_id);
