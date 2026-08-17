-- Filter evaluation audit trail (axiom-parity-v1.0.0+)
CREATE TABLE IF NOT EXISTS filter_evaluations (
    id              BIGSERIAL PRIMARY KEY,
    mint            TEXT NOT NULL,
    filter_version  TEXT NOT NULL,
    accepted        BOOLEAN NOT NULL,
    evaluated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    protocol        TEXT,
    global_fees_sol DOUBLE PRECISION,
    global_fees_source TEXT,
    global_fees_verified BOOLEAN,
    liquidity_usd   DOUBLE PRECISION,
    volume_usd      DOUBLE PRECISION,
    market_cap_usd  DOUBLE PRECISION,
    social_verified BOOLEAN,
    synthetic_risk_score DOUBLE PRECISION,
    failed_filters  JSONB NOT NULL DEFAULT '[]'::jsonb,
    passed_filters  JSONB NOT NULL DEFAULT '[]'::jsonb,
    provenance      JSONB NOT NULL DEFAULT '{}'::jsonb,
    rejection_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_filter_eval_mint ON filter_evaluations (mint);
CREATE INDEX IF NOT EXISTS idx_filter_eval_evaluated_at ON filter_evaluations (evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_filter_eval_accepted ON filter_evaluations (accepted);
CREATE INDEX IF NOT EXISTS idx_filter_eval_version ON filter_evaluations (filter_version);
CREATE INDEX IF NOT EXISTS idx_filter_eval_rejection ON filter_evaluations (rejection_reason)
    WHERE rejection_reason IS NOT NULL;
