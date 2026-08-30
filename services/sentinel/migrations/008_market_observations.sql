-- Post-decision market ticks. Used only to label outcomes later.
-- Never leak these ticks into the original decision fingerprint.
CREATE TABLE IF NOT EXISTS market_observations (
    id BIGSERIAL PRIMARY KEY,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    volume_m5_usd DOUBLE PRECISION,
    price_usd DOUBLE PRECISION,
    liquidity_usd DOUBLE PRECISION,
    source TEXT NOT NULL DEFAULT 'observed'
);
CREATE INDEX IF NOT EXISTS idx_mkt_obs_mint_time ON market_observations (mint, observed_at);
