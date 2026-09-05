CREATE TABLE IF NOT EXISTS wallet_relationships (
    id                 BIGSERIAL PRIMARY KEY,
    wallet_a           TEXT NOT NULL,
    wallet_b           TEXT NOT NULL,
    relationship_kind  TEXT NOT NULL,
    observation_count  INT NOT NULL DEFAULT 1,
    first_seen_at      TIMESTAMPTZ,
    last_seen_at       TIMESTAMPTZ,
    confidence         DOUBLE PRECISION,
    evidence           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (wallet_a < wallet_b),
    UNIQUE (wallet_a, wallet_b, relationship_kind)
);
CREATE INDEX IF NOT EXISTS idx_wallet_relationships_a ON wallet_relationships (wallet_a);
CREATE INDEX IF NOT EXISTS idx_wallet_relationships_b ON wallet_relationships (wallet_b);
CREATE INDEX IF NOT EXISTS idx_wallet_relationships_kind ON wallet_relationships (relationship_kind);
