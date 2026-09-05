CREATE TABLE IF NOT EXISTS wallet_funding_observations (
    signature          TEXT PRIMARY KEY,
    source_wallet      TEXT NOT NULL,
    destination_wallet TEXT NOT NULL,
    observed_at        TIMESTAMPTZ NOT NULL,
    amount_lamports    BIGINT,
    evidence           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wallet_funding_observations_source
    ON wallet_funding_observations (source_wallet);
CREATE INDEX IF NOT EXISTS idx_wallet_funding_observations_destination
    ON wallet_funding_observations (destination_wallet);
CREATE INDEX IF NOT EXISTS idx_wallet_funding_observations_observed
    ON wallet_funding_observations (observed_at);
