CREATE TABLE IF NOT EXISTS market_pattern_calibration_snapshots (
    id BIGSERIAL PRIMARY KEY,
    pattern_hash TEXT NOT NULL,
    evidence_through_observed_at TIMESTAMPTZ NOT NULL,
    as_of TIMESTAMPTZ NULL,
    computed_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trend_status TEXT NOT NULL,
    window_count INTEGER NOT NULL DEFAULT 0,
    evaluated_window_count INTEGER NOT NULL DEFAULT 0,
    criteria_hash TEXT NOT NULL,
    criteria JSONB NOT NULL DEFAULT '{}'::jsonb,
    snapshot JSONB NOT NULL,
    evidence_basis TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (pattern_hash, evidence_through_observed_at, criteria_hash)
);

CREATE INDEX IF NOT EXISTS ix_market_pattern_calibration_snapshots_pattern_time
    ON market_pattern_calibration_snapshots (pattern_hash, evidence_through_observed_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_market_pattern_calibration_snapshots_trend_time
    ON market_pattern_calibration_snapshots (trend_status, evidence_through_observed_at DESC);
