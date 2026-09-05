CREATE TABLE IF NOT EXISTS entity_behavior_fingerprints (
    entity_id                    UUID PRIMARY KEY REFERENCES entities(entity_id) ON DELETE CASCADE,
    launch_count                 INT NOT NULL DEFAULT 0,
    outcomes_known               INT NOT NULL DEFAULT 0,
    completed_count              INT NOT NULL DEFAULT 0,
    outcomes_unknown             INT NOT NULL DEFAULT 0,
    first_launch_at              TIMESTAMPTZ,
    last_launch_at               TIMESTAMPTZ,
    median_launch_interval_sec   DOUBLE PRECISION,
    cadence_bucket               TEXT NOT NULL DEFAULT 'unknown',
    fingerprint                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_entity_behavior_cadence ON entity_behavior_fingerprints(cadence_bucket);
CREATE INDEX IF NOT EXISTS idx_entity_behavior_computed ON entity_behavior_fingerprints(computed_at);
