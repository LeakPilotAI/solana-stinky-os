-- Additive observation columns. Do not drop existing data.
ALTER TABLE market_observations ADD COLUMN IF NOT EXISTS market_cap_usd DOUBLE PRECISION;
ALTER TABLE market_observations ADD COLUMN IF NOT EXISTS buys INTEGER;
ALTER TABLE market_observations ADD COLUMN IF NOT EXISTS sells INTEGER;
ALTER TABLE market_observations ADD COLUMN IF NOT EXISTS txns INTEGER;
ALTER TABLE market_observations ADD COLUMN IF NOT EXISTS unique_buyers INTEGER;
ALTER TABLE market_observations ADD COLUMN IF NOT EXISTS unique_sellers INTEGER;
ALTER TABLE market_observations ADD COLUMN IF NOT EXISTS volume_since_gate DOUBLE PRECISION;

CREATE TABLE IF NOT EXISTS intelligence_investigations (
    mint TEXT PRIMARY KEY,
    gate1_at TIMESTAMPTZ NOT NULL,
    discovered_at TIMESTAMPTZ,
    protocol TEXT,
    volume_5m_at_gate DOUBLE PRECISION,
    liquidity_at_gate DOUBLE PRECISION,
    market_cap_at_gate DOUBLE PRECISION,
    price_at_gate DOUBLE PRECISION,
    pair_identifier TEXT,
    creator TEXT,
    gate_decision TEXT,
    investigation_status TEXT,
    correlation_id TEXT,
    row JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intel_inv_gate1 ON intelligence_investigations (gate1_at DESC);
