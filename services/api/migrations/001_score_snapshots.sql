-- Score snapshots for Time Machine reputation curves
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS score_snapshots (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject_type    TEXT NOT NULL,  -- wallet | entity | mint
    subject_id      TEXT NOT NULL,
    score           DOUBLE PRECISION NOT NULL,
    confidence      DOUBLE PRECISION,
    model_version   TEXT,
    context         TEXT,           -- alert_candidate | launch | recompute | backfill
    mint            TEXT,
    explanation     JSONB,
    signals         JSONB,
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_score_snap_subject
    ON score_snapshots (subject_type, subject_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_score_snap_mint
    ON score_snapshots (mint, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_score_snap_captured
    ON score_snapshots (captured_at DESC);
