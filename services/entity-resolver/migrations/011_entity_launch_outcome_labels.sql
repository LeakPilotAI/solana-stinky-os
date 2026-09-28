-- Immutable dual-time ledger for canonical measured launch outcomes.
-- observed_at = factual completion/outcome boundary.
-- ingested_at = when Genesis durably learned the label.
CREATE TABLE IF NOT EXISTS entity_launch_outcome_labels (
    id BIGSERIAL PRIMARY KEY,
    mint TEXT NOT NULL,
    entity_id UUID NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK (label IN ('RUNNER', 'HELD', 'FADE')),
    label_version TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (mint, label_version)
);

CREATE INDEX IF NOT EXISTS idx_entity_launch_outcome_labels_entity_time
    ON entity_launch_outcome_labels(entity_id, observed_at DESC, ingested_at DESC);

CREATE INDEX IF NOT EXISTS idx_entity_launch_outcome_labels_mint_time
    ON entity_launch_outcome_labels(mint, observed_at DESC, ingested_at DESC);
