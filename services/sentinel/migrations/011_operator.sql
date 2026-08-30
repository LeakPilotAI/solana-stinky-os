-- Operator observability. Append-only events. Watch state upserted by mint.
CREATE TABLE IF NOT EXISTS operator_events (
    id BIGSERIAL PRIMARY KEY,
    mint TEXT,
    at TIMESTAMPTZ NOT NULL,
    kind TEXT NOT NULL,
    message TEXT,
    evidence_label TEXT,
    row JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_operator_events_mint ON operator_events (mint, at);

CREATE TABLE IF NOT EXISTS watch_states (
    mint TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ,
    last_observation_at TIMESTAMPTZ,
    observation_count INTEGER,
    next_due_at TIMESTAMPTZ,
    status TEXT,
    resumed BOOLEAN NOT NULL DEFAULT FALSE,
    interrupted BOOLEAN NOT NULL DEFAULT FALSE,
    persistence_status TEXT,
    stop_reason TEXT,
    row JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_probes (
    provider TEXT PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    latency_ms DOUBLE PRECISION,
    last_success_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    error TEXT,
    row JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS discord_deliveries (
    id BIGSERIAL PRIMARY KEY,
    mint TEXT,
    at TIMESTAMPTZ NOT NULL,
    policy TEXT,
    category TEXT,
    delivery TEXT,
    error TEXT,
    row JSONB NOT NULL
);
