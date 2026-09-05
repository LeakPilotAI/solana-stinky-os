CREATE TABLE IF NOT EXISTS market_outcome_observations (
    id                  BIGSERIAL PRIMARY KEY,
    mint                TEXT NOT NULL,
    horizon             TEXT NOT NULL,
    horizon_seconds     INTEGER NOT NULL CHECK (horizon_seconds >= 0),
    anchor_observed_at  TIMESTAMPTZ,
    observed_at         TIMESTAMPTZ NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    source              TEXT NOT NULL,
    evidence_basis      TEXT NOT NULL,
    metrics             JSONB NOT NULL DEFAULT '{}'::jsonb,
    event_id            TEXT,
    signature           TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (mint, horizon, observed_at, source)
);

CREATE INDEX IF NOT EXISTS idx_market_outcomes_mint
    ON market_outcome_observations (mint);
CREATE INDEX IF NOT EXISTS idx_market_outcomes_observed
    ON market_outcome_observations (observed_at);
CREATE INDEX IF NOT EXISTS idx_market_outcomes_horizon
    ON market_outcome_observations (horizon, horizon_seconds);
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_outcomes_event_id
    ON market_outcome_observations (event_id)
    WHERE event_id IS NOT NULL;
