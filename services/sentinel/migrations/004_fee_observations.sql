-- Append-only authoritative fee observations (fee-resolver-v1.0.0)
CREATE TABLE IF NOT EXISTS fee_observations (
    id BIGSERIAL PRIMARY KEY,
    mint TEXT NOT NULL,
    protocol TEXT,
    global_fees_sol DOUBLE PRECISION,
    source TEXT NOT NULL,
    verified BOOLEAN NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolver_version TEXT NOT NULL,
    fees_status TEXT NOT NULL,
    fees_error TEXT,
    fees_confidence DOUBLE PRECISION,
    scan_complete BOOLEAN,
    txs_parsed INTEGER,
    lower_bound BOOLEAN,
    raw_reference JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_fee_obs_mint_observed
    ON fee_observations (mint, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_fee_obs_verified
    ON fee_observations (verified, observed_at DESC);
