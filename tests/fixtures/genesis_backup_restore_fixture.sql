CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE events(event_id text PRIMARY KEY,event_type text,payload jsonb);
CREATE TABLE market_snapshots(snapshot_id text PRIMARY KEY,mint text,captured_at timestamptz,price_usd numeric,source text);
CREATE TABLE market_inspections(id text PRIMARY KEY,mint text,inspected_at timestamptz,stinky_score double precision,evidence jsonb);
CREATE TABLE score_snapshots(id text PRIMARY KEY,subject_id text,score double precision,captured_at timestamptz);
CREATE TABLE entity_launches(id bigint PRIMARY KEY,mint text,event_id text,outcome_status text,outcome_meta jsonb);
CREATE TABLE entity_launch_outcome_labels(id bigint PRIMARY KEY,mint text,label text,observed_at timestamptz,ingested_at timestamptz,metadata jsonb);
CREATE TABLE developer_longitudinal_snapshots(id text PRIMARY KEY,entity_id text,snapshot jsonb);
CREATE TABLE developer_correlation_snapshots(id text PRIMARY KEY,entity_id text,snapshot jsonb);
CREATE TABLE market_outcome_observations(id bigint PRIMARY KEY,mint text,horizon text,observed_at timestamptz,metrics jsonb);
CREATE TABLE market_path_patterns(pattern_hash text PRIMARY KEY,signature jsonb,occurrence_count integer);
CREATE TABLE market_path_pattern_occurrences(id bigint PRIMARY KEY,pattern_hash text,mint text,observed_at timestamptz,signature jsonb);
CREATE TABLE market_pattern_calibration_snapshots(id bigint PRIMARY KEY,pattern_hash text,snapshot jsonb);
CREATE TABLE paper_intake_producer_state(singleton boolean PRIMARY KEY,producer_version text,prospective_started_at timestamptz);
CREATE TABLE paper_prospective_candidate(
  candidate_id text PRIMARY KEY,
  t0_evidence jsonb NOT NULL,
  t0_evidence_sha256 text NOT NULL,
  frozen_bundle jsonb,
  frozen_bundle_sha256 text
);
CREATE TABLE paper_policy_registry(
  policy_version text PRIMARY KEY,
  policy_sha256 text NOT NULL,
  policy_payload jsonb NOT NULL
);
CREATE TABLE paper_policy_active(singleton boolean PRIMARY KEY,policy_version text NOT NULL,activated_at timestamptz NOT NULL);
CREATE TABLE paper_policy_activation_audit(audit_id bigint PRIMARY KEY,policy_version text,policy_sha256 text,activated_at timestamptz);
CREATE TABLE paper_runtime_intake(intake_id text PRIMARY KEY,payload jsonb NOT NULL,payload_sha256 text NOT NULL);
CREATE TABLE paper_runtime_record(
  intake_id text PRIMARY KEY,
  policy_version text,
  policy_sha256 text,
  policy_evidence_backed boolean,
  record jsonb NOT NULL
);

INSERT INTO events VALUES ('event-1','alert.candidate','{"mint":"fixture"}');
INSERT INTO market_snapshots VALUES ('snapshot-1','fixture','2026-09-01T00:00:00Z',1.0,'fixture');
INSERT INTO market_inspections VALUES ('inspection-1','fixture','2026-09-01T00:00:00Z',42.0,'{"fixture":true}');
INSERT INTO score_snapshots VALUES ('score-1','fixture',42.0,'2026-09-01T00:00:00Z');
INSERT INTO entity_launches VALUES (1,'fixture','launch-1','RUNNER','{"observed_at":"2026-09-02T00:00:00Z"}');
INSERT INTO entity_launch_outcome_labels VALUES (1,'fixture','RUNNER','2026-09-02T00:00:00Z','2026-09-02T00:00:01Z','{"fixture":true}');
INSERT INTO developer_longitudinal_snapshots VALUES ('long-1','entity-1','{"fixture":true}');
INSERT INTO developer_correlation_snapshots VALUES ('corr-1','entity-1','{"fixture":true}');
INSERT INTO market_outcome_observations VALUES (1,'fixture','15m','2026-09-02T00:00:00Z','{"return_pct":10}');
INSERT INTO market_path_patterns VALUES ('pattern-1','{"fixture":true}',1);
INSERT INTO market_path_pattern_occurrences VALUES (1,'pattern-1','fixture','2026-09-01T00:00:00Z','{"fixture":true}');
INSERT INTO market_pattern_calibration_snapshots VALUES (1,'pattern-1','{"fixture":true}');
INSERT INTO paper_intake_producer_state VALUES (TRUE,'fixture-producer','2026-09-01T00:00:00Z');
INSERT INTO paper_policy_registry VALUES (
  'fixture-v1',
  '023c1026097f512df8a2a840860768ec037d78aea4f7cfc9aeb3ab6c3227a3a9',
  $json${"paper_policy":{"policy_version":"fixture-v1"},"provenance":{"candidate_cutoff":"2026-09-01T00:00:00+00:00","candidate_evidence_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","candidate_version":"score-paper-candidate-v1:aaaaaaaaaaaaaaaa","comparison_as_of":"2026-09-02T00:00:00+00:00","comparison_evidence_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","evidence_backed":true,"mode":"EVIDENCE_BACKED_SCORE_CANDIDATE","provenance_sha256":"436192b558085bb10b538a5cfce6929122e852bedd36f025612b493d24b20d3b","readiness_checks":{"sufficient_later_sample":true},"readiness_criteria":{"min_later_sample":1}}}$json$::jsonb
);
INSERT INTO paper_policy_active VALUES (TRUE,'fixture-v1','2026-09-03T00:00:00Z');
INSERT INTO paper_policy_activation_audit VALUES (1,'fixture-v1','023c1026097f512df8a2a840860768ec037d78aea4f7cfc9aeb3ab6c3227a3a9','2026-09-03T00:00:00Z');
INSERT INTO paper_prospective_candidate VALUES (
  'candidate-1',
  $json${"future_evidence_used":false,"source_event":{"event_id":"event-1"}}$json$::jsonb,
  '1fd4d62e1ad3615b8eea3e853470483aa3f8dcf51d2e8c3f9215f90588c9fa42',
  $json${"fixture":true,"paper_policy":{"policy_version":"fixture-v1"},"policy_identity":{"policy_sha256":"023c1026097f512df8a2a840860768ec037d78aea4f7cfc9aeb3ab6c3227a3a9","provenance":{"candidate_cutoff":"2026-09-01T00:00:00+00:00","candidate_evidence_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","candidate_version":"score-paper-candidate-v1:aaaaaaaaaaaaaaaa","comparison_as_of":"2026-09-02T00:00:00+00:00","comparison_evidence_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","evidence_backed":true,"mode":"EVIDENCE_BACKED_SCORE_CANDIDATE","provenance_sha256":"436192b558085bb10b538a5cfce6929122e852bedd36f025612b493d24b20d3b","readiness_checks":{"sufficient_later_sample":true},"readiness_criteria":{"min_later_sample":1}}}}$json$::jsonb,
  '53278b69f396b2e1c6b9cc78dbd0f96ae7326224947ceb2cf9e44ee1d985aa10'
);
INSERT INTO paper_runtime_intake VALUES (
  'intake-1',
  $json${"fixture":true,"paper_policy":{"policy_version":"fixture-v1"},"policy_identity":{"policy_sha256":"023c1026097f512df8a2a840860768ec037d78aea4f7cfc9aeb3ab6c3227a3a9","provenance":{"candidate_cutoff":"2026-09-01T00:00:00+00:00","candidate_evidence_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","candidate_version":"score-paper-candidate-v1:aaaaaaaaaaaaaaaa","comparison_as_of":"2026-09-02T00:00:00+00:00","comparison_evidence_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","evidence_backed":true,"mode":"EVIDENCE_BACKED_SCORE_CANDIDATE","provenance_sha256":"436192b558085bb10b538a5cfce6929122e852bedd36f025612b493d24b20d3b","readiness_checks":{"sufficient_later_sample":true},"readiness_criteria":{"min_later_sample":1}}}}$json$::jsonb,
  '53278b69f396b2e1c6b9cc78dbd0f96ae7326224947ceb2cf9e44ee1d985aa10'
);
INSERT INTO paper_runtime_record VALUES (
  'intake-1',
  'fixture-v1',
  '023c1026097f512df8a2a840860768ec037d78aea4f7cfc9aeb3ab6c3227a3a9',
  TRUE,
  $json${"policy_identity":{"policy_sha256":"023c1026097f512df8a2a840860768ec037d78aea4f7cfc9aeb3ab6c3227a3a9","policy_version":"fixture-v1","provenance":{"candidate_cutoff":"2026-09-01T00:00:00+00:00","candidate_evidence_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","candidate_version":"score-paper-candidate-v1:aaaaaaaaaaaaaaaa","comparison_as_of":"2026-09-02T00:00:00+00:00","comparison_evidence_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","evidence_backed":true,"mode":"EVIDENCE_BACKED_SCORE_CANDIDATE","provenance_sha256":"436192b558085bb10b538a5cfce6929122e852bedd36f025612b493d24b20d3b","readiness_checks":{"sufficient_later_sample":true},"readiness_criteria":{"min_later_sample":1}}},"status":"OBSERVED"}$json$::jsonb
);
