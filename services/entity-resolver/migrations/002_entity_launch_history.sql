CREATE TABLE IF NOT EXISTS entity_launches (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       UUID NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    deployer_wallet TEXT NOT NULL,
    mint            TEXT,
    event_id        TEXT NOT NULL,
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome_status  TEXT,
    outcome_meta    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id),
    UNIQUE (deployer_wallet, mint)
);
CREATE INDEX IF NOT EXISTS idx_entity_launches_entity ON entity_launches (entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_launches_deployer ON entity_launches (deployer_wallet);
CREATE INDEX IF NOT EXISTS idx_entity_launches_observed ON entity_launches (observed_at);
