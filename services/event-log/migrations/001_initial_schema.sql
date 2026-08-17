-- Stinky OS – Event Log & Core Schema
-- PostgreSQL 16 + TimescaleDB
-- Migration 001 – Initial

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============================================================
-- Immutable Event Log (source of truth for event sourcing)
-- ============================================================
CREATE TABLE events (
    event_id        UUID PRIMARY KEY,
    event_type      TEXT NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL,
    slot            BIGINT,
    block_time      TIMESTAMPTZ,
    signature       TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    schema_version  TEXT NOT NULL DEFAULT '1.0.0',
    correlation_id  UUID,
    causation_id    UUID,
    producer        TEXT NOT NULL DEFAULT 'unknown',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Convert to hypertable on occurred_at (or ingested_at for pure ingestion order)
SELECT create_hypertable('events', 'occurred_at', if_not_exists => TRUE);

CREATE INDEX idx_events_type_time ON events (event_type, occurred_at DESC);
CREATE INDEX idx_events_slot ON events (slot) WHERE slot IS NOT NULL;
CREATE INDEX idx_events_signature ON events (signature) WHERE signature IS NOT NULL;
CREATE INDEX idx_events_correlation ON events (correlation_id) WHERE correlation_id IS NOT NULL;

-- ============================================================
-- Wallets
-- ============================================================
CREATE TABLE wallets (
    wallet_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    address         TEXT NOT NULL UNIQUE,
    first_seen      TIMESTAMPTZ,
    last_seen       TIMESTAMPTZ,
    labels          TEXT[] DEFAULT '{}',
    meta            JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_wallets_labels ON wallets USING GIN (labels);

-- ============================================================
-- Entities (resolved identities)
-- ============================================================
CREATE TABLE entities (
    entity_id       UUID PRIMARY KEY,
    canonical_name  TEXT,
    entity_type     TEXT NOT NULL,          -- developer, sniper, whale, ...
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    confidence      REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    status          TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'merged', 'split', 'retired')),
    meta            JSONB DEFAULT '{}'
);

CREATE INDEX idx_entities_type ON entities (entity_type);
CREATE INDEX idx_entities_status ON entities (status);

-- ============================================================
-- Entity ↔ Wallet membership (temporal)
-- ============================================================
CREATE TABLE entity_wallets (
    entity_id       UUID NOT NULL REFERENCES entities (entity_id),
    wallet_id       UUID NOT NULL REFERENCES wallets (wallet_id),
    confidence      REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    added_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    removed_at      TIMESTAMPTZ,
    evidence        JSONB DEFAULT '{}',
    PRIMARY KEY (entity_id, wallet_id, added_at)
);

CREATE INDEX idx_entity_wallets_wallet ON entity_wallets (wallet_id);
CREATE INDEX idx_entity_wallets_active ON entity_wallets (entity_id)
    WHERE removed_at IS NULL;

-- ============================================================
-- Versioned Scores (hypertable)
-- ============================================================
CREATE TABLE scores (
    score_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id       UUID NOT NULL REFERENCES entities (entity_id),
    score           REAL NOT NULL CHECK (score >= 0 AND score <= 100),
    confidence      REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    model_version   TEXT NOT NULL,
    scored_at       TIMESTAMPTZ NOT NULL,
    explanation     JSONB NOT NULL DEFAULT '{}',
    data_points     INTEGER,
    launches        INTEGER,
    feature_set_hash TEXT
);

SELECT create_hypertable('scores', 'scored_at', if_not_exists => TRUE);

CREATE INDEX idx_scores_entity_time ON scores (entity_id, scored_at DESC);

-- ============================================================
-- Features (versioned)
-- ============================================================
CREATE TABLE features (
    feature_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id       UUID NOT NULL,
    feature_set_hash TEXT NOT NULL,
    feature_def_version TEXT NOT NULL,
    values          JSONB NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_features_entity ON features (entity_id, computed_at DESC);

-- ============================================================
-- Behavioral Fingerprints
-- ============================================================
CREATE TABLE fingerprints (
    fingerprint_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id       UUID NOT NULL REFERENCES entities (entity_id),
    pattern_type    TEXT NOT NULL,
    pattern_value   JSONB NOT NULL,
    strength        REAL,
    first_observed  TIMESTAMPTZ,
    last_observed   TIMESTAMPTZ,
    UNIQUE (entity_id, pattern_type)
);

-- ============================================================
-- Model Registry
-- ============================================================
CREATE TABLE models (
    model_id        TEXT PRIMARY KEY,       -- semantic version e.g. score-v1.2.0
    model_type      TEXT NOT NULL,
    trained_at      TIMESTAMPTZ,
    training_window TSTZRANGE,
    feature_set_hash TEXT,
    metrics         JSONB DEFAULT '{}',
    artifact_uri    TEXT,                   -- s3/minio path
    status          TEXT NOT NULL DEFAULT 'candidate'
                        CHECK (status IN ('candidate', 'production', 'retired'))
);

-- ============================================================
-- DNA Profiles
-- ============================================================
CREATE TABLE dna_profiles (
    entity_id           UUID PRIMARY KEY REFERENCES entities (entity_id),
    risk_style          TEXT,
    growth_speed        TEXT,
    liquidity_style     TEXT,
    holder_quality      TEXT,
    volume_authenticity TEXT,
    marketing_style     TEXT,
    community_strength  TEXT,
    consistency         REAL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_model        TEXT
);

-- ============================================================
-- Data Quality dead-letter / rejected events
-- ============================================================
CREATE TABLE rejected_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_payload     JSONB NOT NULL,
    errors          TEXT[] NOT NULL,
    rejected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    source          TEXT
);

COMMENT ON TABLE events IS 'Immutable event log – system of record for event sourcing (ADR-002)';
COMMENT ON TABLE scores IS 'Versioned, explainable Stinky Scores with full attribution';
COMMENT ON TABLE models IS 'Model registry – every prediction references a model_id';
