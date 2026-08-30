-- Derived intelligence after Gate 1. Never stores fabricated scores.
CREATE TABLE IF NOT EXISTS market_inspections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mint TEXT NOT NULL,
    inspected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_version TEXT NOT NULL,
    pipeline_status TEXT NOT NULL,
    gate1_passed BOOLEAN NOT NULL DEFAULT TRUE,
    volume_m5_usd DOUBLE PRECISION,
    synthetic_score DOUBLE PRECISION,
    synthetic_level TEXT,
    rug_score DOUBLE PRECISION,
    rug_level TEXT,
    stinky_score DOUBLE PRECISION,
    runner_potential DOUBLE PRECISION,
    score_confidence DOUBLE PRECISION,
    fee_status TEXT,
    global_fees_sol DOUBLE PRECISION,
    has_intelligence BOOLEAN,
    evidence JSONB,
    missing_data JSONB,
    alert_ok BOOLEAN,
    alert_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_market_inspections_mint_time
    ON market_inspections (mint, inspected_at DESC);
