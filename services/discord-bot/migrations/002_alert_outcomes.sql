-- Alert log + outcomes (precision measurement)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS alert_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mint            TEXT NOT NULL,
    alerted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    score           DOUBLE PRECISION,
    confidence      DOUBLE PRECISION,
    volume_m5_usd   DOUBLE PRECISION,
    meaningful_buyers INT,
    entity_launch_count INT,
    score_model     TEXT,
    name            TEXT,
    symbol          TEXT,
    deployer        TEXT,
    dm_sent         BOOLEAN NOT NULL DEFAULT TRUE,
    channel_posted  BOOLEAN NOT NULL DEFAULT FALSE,
    payload         JSONB,
    UNIQUE (mint, alerted_at)
);

CREATE INDEX IF NOT EXISTS idx_alert_log_mint ON alert_log (mint);
CREATE INDEX IF NOT EXISTS idx_alert_log_alerted ON alert_log (alerted_at DESC);

CREATE TABLE IF NOT EXISTS alert_outcomes (
    alert_id        UUID PRIMARY KEY REFERENCES alert_log(id) ON DELETE CASCADE,
    mint            TEXT NOT NULL,
    evaluated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    hours_since     DOUBLE PRECISION,
    peak_volume_m5_usd DOUBLE PRECISION,
    peak_liquidity_usd DOUBLE PRECISION,
    peak_price_usd  DOUBLE PRECISION,
    last_volume_m5_usd DOUBLE PRECISION,
    snapshots_n     INT NOT NULL DEFAULT 0,
    volume_multiple DOUBLE PRECISION,
    -- simple labels from measured data only
    label           TEXT,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_alert_outcomes_label ON alert_outcomes (label);
