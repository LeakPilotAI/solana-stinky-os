-- Durable prospective executable-depth evidence.
-- Observation/research only: no admission, paper, signing, or execution semantics.
CREATE TABLE IF NOT EXISTS depth_quote_observations (
    id BIGSERIAL PRIMARY KEY,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    input_lamports BIGINT NOT NULL,
    out_amount_atomic NUMERIC,
    price_impact_pct DOUBLE PRECISION,
    route_found BOOLEAN NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    error TEXT,
    quote_context_slot BIGINT,
    quote_time_taken_sec DOUBLE PRECISION
);

-- Converge databases created while the depth schema was still runtime-created.
ALTER TABLE depth_quote_observations ADD COLUMN IF NOT EXISTS quote_context_slot BIGINT;
ALTER TABLE depth_quote_observations ADD COLUMN IF NOT EXISTS quote_time_taken_sec DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_depth_quote_mint_time
    ON depth_quote_observations (mint, observed_at DESC);
