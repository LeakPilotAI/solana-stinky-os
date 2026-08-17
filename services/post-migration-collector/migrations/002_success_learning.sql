-- Success Learning: token outcomes + early-buyer attribution
-- Replayable from market_snapshots + migration_buyers (ADR-002)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS token_outcomes (
    mint                TEXT PRIMARY KEY,
    evaluated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    migration_at        TIMESTAMPTZ,
    snapshots_n         INT NOT NULL DEFAULT 0,
    peak_volume_m5_usd  NUMERIC,
    peak_liquidity_usd  NUMERIC,
    peak_market_cap_usd NUMERIC,
    peak_price_usd      NUMERIC,
    -- Labels measured only from snapshots (no narrative invent)
    -- mega_runner: peak_mcap >= 1e6 OR peak_vol_m5 >= 250k
    -- runner:      peak_mcap >= 5e5 OR peak_vol_m5 >= 100k
    -- mid:         peak_vol_m5 >= 50k
    -- fade:        had snapshots but never cleared mid
    -- unknown:     insufficient snapshots
    label               TEXT NOT NULL,
    hours_observed      NUMERIC,
    notes               TEXT,
    meta                JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_token_outcomes_label ON token_outcomes (label);
CREATE INDEX IF NOT EXISTS idx_token_outcomes_eval ON token_outcomes (evaluated_at DESC);

-- Per-wallet success as early buyer on labeled tokens
CREATE TABLE IF NOT EXISTS wallet_early_success (
    wallet              TEXT PRIMARY KEY,
    early_entries       INT NOT NULL DEFAULT 0,
    early_on_mega       INT NOT NULL DEFAULT 0,
    early_on_runner     INT NOT NULL DEFAULT 0,
    early_on_mid        INT NOT NULL DEFAULT 0,
    early_on_fade       INT NOT NULL DEFAULT 0,
    early_on_unknown    INT NOT NULL DEFAULT 0,
    -- success_rate = (mega + runner) / (mega+runner+mid+fade) when denom > 0
    success_rate        NUMERIC,
    sample_size         INT NOT NULL DEFAULT 0,
    last_success_at     TIMESTAMPTZ,
    last_fade_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wallet_early_success_rate
    ON wallet_early_success (success_rate DESC NULLS LAST, sample_size DESC);
CREATE INDEX IF NOT EXISTS idx_wallet_early_success_mega
    ON wallet_early_success (early_on_mega DESC);

-- Extend wallet_performance with success columns (safe if already present)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'wallet_performance' AND column_name = 'early_success_rate'
    ) THEN
        ALTER TABLE wallet_performance
            ADD COLUMN early_success_rate NUMERIC,
            ADD COLUMN early_on_runner INT NOT NULL DEFAULT 0,
            ADD COLUMN early_on_mega INT NOT NULL DEFAULT 0,
            ADD COLUMN early_success_sample INT NOT NULL DEFAULT 0;
    END IF;
END $$;
