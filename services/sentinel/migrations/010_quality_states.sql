-- Quality state transitions. Append-only. Never rewrite history.
CREATE TABLE IF NOT EXISTS quality_state_transitions (
    id BIGSERIAL PRIMARY KEY,
    mint TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL,
    previous_state TEXT,
    severity TEXT,
    row JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quality_mint_time ON quality_state_transitions (mint, as_of DESC);
