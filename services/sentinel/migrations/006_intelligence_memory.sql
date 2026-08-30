-- As-of intelligence memory (ADR-012). Never stores fabricated scores.
CREATE TABLE IF NOT EXISTS wallet_observations (
    id BIGSERIAL PRIMARY KEY,
    wallet TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    role TEXT NOT NULL DEFAULT 'early_buyer',
    sol_spent DOUBLE PRECISION,
    source TEXT NOT NULL DEFAULT 'observed',
    UNIQUE (wallet, mint, role)
);
CREATE INDEX IF NOT EXISTS idx_wallet_obs_wallet_time ON wallet_observations (wallet, observed_at);
CREATE INDEX IF NOT EXISTS idx_wallet_obs_mint ON wallet_observations (mint);

CREATE TABLE IF NOT EXISTS wallet_outcome_labels (
    id BIGSERIAL PRIMARY KEY,
    wallet TEXT NOT NULL,
    mint TEXT NOT NULL,
    labeled_at TIMESTAMPTZ NOT NULL,
    label TEXT NOT NULL,
    label_version TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'outcome-v1.0.0',
    UNIQUE (wallet, mint)
);
CREATE INDEX IF NOT EXISTS idx_wallet_out_wallet_time ON wallet_outcome_labels (wallet, labeled_at);

CREATE TABLE IF NOT EXISTS creator_observations (
    id BIGSERIAL PRIMARY KEY,
    creator TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    migrated BOOLEAN,
    source TEXT NOT NULL DEFAULT 'observed',
    UNIQUE (creator, mint)
);
CREATE INDEX IF NOT EXISTS idx_creator_obs_creator_time ON creator_observations (creator, observed_at);

CREATE TABLE IF NOT EXISTS creator_outcome_labels (
    id BIGSERIAL PRIMARY KEY,
    creator TEXT NOT NULL,
    mint TEXT NOT NULL,
    labeled_at TIMESTAMPTZ NOT NULL,
    label TEXT NOT NULL,
    label_version TEXT NOT NULL,
    UNIQUE (creator, mint)
);

CREATE TABLE IF NOT EXISTS wallet_relationships (
    id BIGSERIAL PRIMARY KEY,
    wallet_a TEXT NOT NULL,
    wallet_b TEXT NOT NULL,
    kind TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    confidence DOUBLE PRECISION,
    reason TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_rel_a ON wallet_relationships (wallet_a, observed_at);
CREATE INDEX IF NOT EXISTS idx_rel_b ON wallet_relationships (wallet_b, observed_at);

CREATE TABLE IF NOT EXISTS pattern_fingerprints (
    id BIGSERIAL PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    mint TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    features JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (fingerprint, mint)
);
CREATE INDEX IF NOT EXISTS idx_fp_key_time ON pattern_fingerprints (fingerprint, observed_at);

CREATE TABLE IF NOT EXISTS pattern_outcomes (
    id BIGSERIAL PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    mint TEXT NOT NULL,
    labeled_at TIMESTAMPTZ NOT NULL,
    label TEXT NOT NULL,
    label_version TEXT NOT NULL,
    UNIQUE (fingerprint, mint)
);

CREATE TABLE IF NOT EXISTS intelligence_decisions (
    mint TEXT PRIMARY KEY,
    decision_timestamp TIMESTAMPTZ NOT NULL,
    protocol TEXT,
    volume_m5_usd DOUBLE PRECISION,
    pipeline_status TEXT,
    has_intelligence BOOLEAN,
    promote BOOLEAN,
    stinky_score DOUBLE PRECISION,
    alert_ok BOOLEAN,
    alert_reason TEXT,
    synthetic_level TEXT,
    rug_level TEXT,
    outcome_label TEXT,
    label_version TEXT,
    model_version TEXT,
    row JSONB NOT NULL
);
