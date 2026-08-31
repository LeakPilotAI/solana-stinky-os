CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE TABLE IF NOT EXISTS entities (
    entity_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type     TEXT NOT NULL DEFAULT 'operator',
    display_label   TEXT,
    primary_wallet  TEXT,
    wallet_count    INT NOT NULL DEFAULT 0,
    launch_count    INT NOT NULL DEFAULT 0,
    early_buy_count INT NOT NULL DEFAULT 0,
    confidence      DOUBLE PRECISION NOT NULL DEFAULT 0.3,
    meta            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_entities_primary_wallet ON entities (primary_wallet);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities (entity_type);
CREATE TABLE IF NOT EXISTS entity_wallets (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       UUID NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    wallet          TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'member',
    link_reason     TEXT NOT NULL,
    confidence      DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    first_seen_at   TIMESTAMPTZ,
    last_seen_at    TIMESTAMPTZ,
    evidence        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (wallet)
);
CREATE INDEX IF NOT EXISTS idx_entity_wallets_entity ON entity_wallets (entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_wallets_wallet ON entity_wallets (wallet);

CREATE TABLE IF NOT EXISTS entity_link_events (
    id              BIGSERIAL PRIMARY KEY,
    event_kind      TEXT NOT NULL,
    entity_id       UUID NOT NULL,
    wallet          TEXT,
    other_entity_id UUID,
    reason          TEXT NOT NULL,
    confidence      DOUBLE PRECISION,
    evidence        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_entity_link_events_entity ON entity_link_events (entity_id);
