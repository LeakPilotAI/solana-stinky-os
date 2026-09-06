CREATE TABLE IF NOT EXISTS market_path_patterns (
    pattern_hash       TEXT PRIMARY KEY,
    signature          JSONB NOT NULL,
    evidence_basis     TEXT NOT NULL,
    first_observed_at  TIMESTAMPTZ NOT NULL,
    last_observed_at   TIMESTAMPTZ NOT NULL,
    occurrence_count   INTEGER NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_path_pattern_occurrences (
    id                 BIGSERIAL PRIMARY KEY,
    pattern_hash       TEXT NOT NULL REFERENCES market_path_patterns(pattern_hash) ON DELETE CASCADE,
    mint               TEXT NOT NULL,
    observed_at        TIMESTAMPTZ NOT NULL,
    ingested_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    source             TEXT NOT NULL,
    evidence_basis     TEXT NOT NULL,
    signature          JSONB NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (pattern_hash, mint, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_market_path_pattern_occurrences_hash
    ON market_path_pattern_occurrences(pattern_hash, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_path_pattern_occurrences_mint
    ON market_path_pattern_occurrences(mint, observed_at DESC);
