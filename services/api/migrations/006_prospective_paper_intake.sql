-- Prospective paper intake producer state. Evidence only; never live execution.

CREATE TABLE IF NOT EXISTS paper_intake_producer_state (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    producer_version TEXT NOT NULL,
    prospective_started_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_prospective_candidate (
    candidate_id TEXT PRIMARY KEY,
    source_event_id TEXT NOT NULL UNIQUE,
    mint TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    source_event_occurred_at TIMESTAMPTZ NOT NULL,
    source_event_ingested_at TIMESTAMPTZ NOT NULL,
    producer_version TEXT NOT NULL,
    filter_version TEXT NOT NULL,
    cohort_pattern_hash TEXT NOT NULL,
    t0_evidence JSONB NOT NULL,
    t0_evidence_sha256 TEXT NOT NULL CHECK (length(t0_evidence_sha256) = 64),
    frozen_bundle JSONB,
    frozen_bundle_sha256 TEXT CHECK (frozen_bundle_sha256 IS NULL OR length(frozen_bundle_sha256) = 64),
    reference_entry_price NUMERIC,
    close_due_at TIMESTAMPTZ,
    open_intake_id TEXT UNIQUE,
    close_intake_id TEXT UNIQUE,
    canonical_outcome TEXT CHECK (canonical_outcome IS NULL OR canonical_outcome IN ('RUNNER','HELD','FADE','UNKNOWN')),
    outcome_observed_at TIMESTAMPTZ,
    outcome_event_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (source_event_ingested_at >= source_event_occurred_at),
    CHECK (decided_at = source_event_ingested_at),
    CHECK (outcome_observed_at IS NULL OR outcome_observed_at > decided_at)
);
CREATE INDEX IF NOT EXISTS ix_paper_candidate_pattern_decided
    ON paper_prospective_candidate(cohort_pattern_hash, decided_at);
CREATE INDEX IF NOT EXISTS ix_paper_candidate_close_due
    ON paper_prospective_candidate(close_due_at) WHERE close_intake_id IS NULL;
CREATE INDEX IF NOT EXISTS ix_paper_candidate_outcome
    ON paper_prospective_candidate(canonical_outcome, outcome_observed_at);

CREATE OR REPLACE FUNCTION protect_paper_candidate_t0() RETURNS trigger AS $$
BEGIN
    IF NEW.source_event_id IS DISTINCT FROM OLD.source_event_id
       OR NEW.mint IS DISTINCT FROM OLD.mint
       OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
       OR NEW.source_event_occurred_at IS DISTINCT FROM OLD.source_event_occurred_at
       OR NEW.source_event_ingested_at IS DISTINCT FROM OLD.source_event_ingested_at
       OR NEW.producer_version IS DISTINCT FROM OLD.producer_version
       OR NEW.filter_version IS DISTINCT FROM OLD.filter_version
       OR NEW.cohort_pattern_hash IS DISTINCT FROM OLD.cohort_pattern_hash
       OR NEW.t0_evidence IS DISTINCT FROM OLD.t0_evidence
       OR NEW.t0_evidence_sha256 IS DISTINCT FROM OLD.t0_evidence_sha256
       OR NEW.frozen_bundle IS DISTINCT FROM OLD.frozen_bundle
       OR NEW.frozen_bundle_sha256 IS DISTINCT FROM OLD.frozen_bundle_sha256
       OR NEW.reference_entry_price IS DISTINCT FROM OLD.reference_entry_price
       OR NEW.close_due_at IS DISTINCT FROM OLD.close_due_at
       OR NEW.open_intake_id IS DISTINCT FROM OLD.open_intake_id THEN
        RAISE EXCEPTION 'paper prospective T0 evidence is immutable';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_protect_paper_candidate_t0 ON paper_prospective_candidate;
CREATE TRIGGER trg_protect_paper_candidate_t0
BEFORE UPDATE ON paper_prospective_candidate
FOR EACH ROW EXECUTE FUNCTION protect_paper_candidate_t0();
