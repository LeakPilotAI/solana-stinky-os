-- Stinky OS – Durable event outbox (ADR-002 hardening)
-- Write events to Postgres FIRST; stream is secondary.
-- Idempotent inserts; Redis outage must not lose observations.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Optional signature-level dedupe helper (chain events)
CREATE TABLE IF NOT EXISTS event_idempotency (
    idem_key       TEXT PRIMARY KEY,
    event_id       UUID NOT NULL,
    event_type     TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS event_outbox (
    id             BIGSERIAL PRIMARY KEY,
    event_id       UUID NOT NULL,
    occurred_at    TIMESTAMPTZ NOT NULL,
    stream         TEXT NOT NULL DEFAULT 'stinky.events',
    envelope       JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at   TIMESTAMPTZ,
    attempts       INT NOT NULL DEFAULT 0,
    last_error     TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_event_outbox_event_id
    ON event_outbox (event_id);

CREATE INDEX IF NOT EXISTS idx_event_outbox_unpublished
    ON event_outbox (created_at)
    WHERE published_at IS NULL;

COMMENT ON TABLE event_outbox IS
  'Transactional outbox: durable first, then Redis/stream publish';
