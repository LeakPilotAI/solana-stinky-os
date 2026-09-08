-- Immutable first-buyer evidence history for Genesis wallet intelligence.
--
-- migration_buyers remains the current ranked projection for compatibility.
-- This table records every INSERT/UPDATE to that projection before a later
-- re-track can replace the current rows. All rows written in one ranking save
-- share PostgreSQL's transaction id and transaction timestamp, giving Genesis
-- an immutable capture boundary that can be replayed as first-5/10/20 evidence.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS migration_buyer_history (
    history_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    track_id            UUID NOT NULL REFERENCES migration_tracks (track_id),
    mint                TEXT NOT NULL,
    wallet              TEXT NOT NULL,
    rank                INTEGER NOT NULL CHECK (rank > 0),
    signature           TEXT NOT NULL,
    bought_at           TIMESTAMPTZ NOT NULL,
    slot                BIGINT,
    token_amount        NUMERIC,
    sol_spent           NUMERIC,
    usd_spent           NUMERIC,
    entry_price_usd     NUMERIC,
    is_meaningful       BOOLEAN NOT NULL,
    meta                JSONB NOT NULL DEFAULT '{}',
    operation           TEXT NOT NULL CHECK (operation IN ('INSERT', 'UPDATE')),
    capture_txid        BIGINT NOT NULL,
    evidence_hash       TEXT NOT NULL,
    observed_at         TIMESTAMPTZ NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL,
    CHECK (ingested_at = observed_at)
);

CREATE INDEX IF NOT EXISTS idx_migration_buyer_history_mint_capture
    ON migration_buyer_history (mint, observed_at, capture_txid, rank);
CREATE INDEX IF NOT EXISTS idx_migration_buyer_history_wallet
    ON migration_buyer_history (wallet, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_migration_buyer_history_evidence_hash
    ON migration_buyer_history (evidence_hash);

CREATE OR REPLACE FUNCTION capture_migration_buyer_history()
RETURNS trigger AS $$
DECLARE
    capture_ts TIMESTAMPTZ := transaction_timestamp();
    semantic_hash TEXT;
BEGIN
    semantic_hash := encode(
        digest(
            concat_ws(
                '|',
                NEW.mint,
                NEW.wallet,
                NEW.rank::TEXT,
                NEW.signature,
                NEW.bought_at::TEXT,
                COALESCE(NEW.slot::TEXT, ''),
                COALESCE(NEW.token_amount::TEXT, ''),
                COALESCE(NEW.sol_spent::TEXT, ''),
                COALESCE(NEW.usd_spent::TEXT, ''),
                COALESCE(NEW.entry_price_usd::TEXT, ''),
                NEW.is_meaningful::TEXT,
                COALESCE(NEW.meta::TEXT, '{}')
            ),
            'sha256'
        ),
        'hex'
    );

    INSERT INTO migration_buyer_history (
        track_id, mint, wallet, rank, signature, bought_at, slot,
        token_amount, sol_spent, usd_spent, entry_price_usd,
        is_meaningful, meta, operation, capture_txid, evidence_hash,
        observed_at, ingested_at
    ) VALUES (
        NEW.track_id, NEW.mint, NEW.wallet, NEW.rank, NEW.signature,
        NEW.bought_at, NEW.slot, NEW.token_amount, NEW.sol_spent,
        NEW.usd_spent, NEW.entry_price_usd, NEW.is_meaningful, NEW.meta,
        TG_OP, txid_current(), semantic_hash, capture_ts, capture_ts
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_capture_migration_buyer_history ON migration_buyers;
CREATE TRIGGER trg_capture_migration_buyer_history
AFTER INSERT OR UPDATE ON migration_buyers
FOR EACH ROW
EXECUTE FUNCTION capture_migration_buyer_history();

COMMENT ON TABLE migration_buyer_history IS
    'Immutable ranked early-buyer evidence. Rows sharing mint + capture_txid are one capture; rank <= 5/10/20 yields frozen first-buyer cohorts.';
