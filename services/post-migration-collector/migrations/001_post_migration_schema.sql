-- Stinky OS â€“ Post-Migration Intelligence Collector
-- Migration 001
-- Materialized views derived from events; still event-sourced (ADR-002)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- Tracking sessions (one per migrated mint)
-- ============================================================
CREATE TABLE IF NOT EXISTS migration_tracks (
    track_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mint                TEXT NOT NULL UNIQUE,
    pool                TEXT,
    creator             TEXT,
    destination         TEXT,
    migration_signature TEXT,
    migration_slot      BIGINT,
    migration_at        TIMESTAMPTZ NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'completed', 'failed')),
    buyers_captured     INTEGER NOT NULL DEFAULT 0,
    trades_observed     INTEGER NOT NULL DEFAULT 0,
    snapshots_taken     INTEGER NOT NULL DEFAULT 0,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ,
    meta                JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_migration_tracks_status ON migration_tracks (status);
CREATE INDEX IF NOT EXISTS idx_migration_tracks_creator ON migration_tracks (creator)
    WHERE creator IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_migration_tracks_migration_at
    ON migration_tracks (migration_at DESC);

-- ============================================================
-- Ranked early buyers (first N meaningful post-migration)
-- ============================================================
CREATE TABLE IF NOT EXISTS migration_buyers (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    track_id            UUID NOT NULL REFERENCES migration_tracks (track_id),
    mint                TEXT NOT NULL,
    wallet              TEXT NOT NULL,
    rank                INTEGER NOT NULL,          -- 1 = first meaningful buyer
    signature           TEXT NOT NULL,
    bought_at           TIMESTAMPTZ NOT NULL,
    slot                BIGINT,
    token_amount        NUMERIC,
    sol_spent           NUMERIC,
    usd_spent           NUMERIC,
    entry_price_usd     NUMERIC,
    is_meaningful       BOOLEAN NOT NULL DEFAULT TRUE,
    meta                JSONB NOT NULL DEFAULT '{}',
    UNIQUE (mint, wallet),
    UNIQUE (mint, rank)
);

CREATE INDEX IF NOT EXISTS idx_migration_buyers_wallet ON migration_buyers (wallet);
CREATE INDEX IF NOT EXISTS idx_migration_buyers_mint_rank ON migration_buyers (mint, rank);

-- ============================================================
-- All observed trades (buys AND sells) â€“ never stop after first buy
-- ============================================================
CREATE TABLE IF NOT EXISTS wallet_trades (
    trade_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mint                TEXT NOT NULL,
    wallet              TEXT NOT NULL,
    side                TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    signature           TEXT NOT NULL,
    traded_at           TIMESTAMPTZ NOT NULL,
    slot                BIGINT,
    token_amount        NUMERIC,
    sol_amount          NUMERIC,
    usd_amount          NUMERIC,
    price_usd           NUMERIC,
    is_early_buyer      BOOLEAN NOT NULL DEFAULT FALSE,
    early_rank          INTEGER,
    meta                JSONB NOT NULL DEFAULT '{}',
    UNIQUE (signature, wallet, side)
);

CREATE INDEX IF NOT EXISTS idx_wallet_trades_mint_time ON wallet_trades (mint, traded_at);
CREATE INDEX IF NOT EXISTS idx_wallet_trades_wallet_time ON wallet_trades (wallet, traded_at DESC);
CREATE INDEX IF NOT EXISTS idx_wallet_trades_wallet_mint ON wallet_trades (wallet, mint);

-- ============================================================
-- Open / closed positions per wallet Ã— mint
-- ============================================================
CREATE TABLE IF NOT EXISTS wallet_token_positions (
    position_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    wallet              TEXT NOT NULL,
    mint                TEXT NOT NULL,
    tokens_bought       NUMERIC NOT NULL DEFAULT 0,
    tokens_sold         NUMERIC NOT NULL DEFAULT 0,
    tokens_remaining    NUMERIC NOT NULL DEFAULT 0,
    sol_spent           NUMERIC NOT NULL DEFAULT 0,
    sol_received        NUMERIC NOT NULL DEFAULT 0,
    usd_spent           NUMERIC NOT NULL DEFAULT 0,
    usd_received        NUMERIC NOT NULL DEFAULT 0,
    avg_entry_price_usd NUMERIC,
    realized_pnl_usd    NUMERIC,
    realized_pnl_sol    NUMERIC,
    first_buy_at        TIMESTAMPTZ,
    last_trade_at       TIMESTAMPTZ,
    is_open             BOOLEAN NOT NULL DEFAULT TRUE,
    trade_count         INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (wallet, mint)
);

CREATE INDEX IF NOT EXISTS idx_positions_wallet ON wallet_token_positions (wallet);
CREATE INDEX IF NOT EXISTS idx_positions_mint ON wallet_token_positions (mint);
CREATE INDEX IF NOT EXISTS idx_positions_open ON wallet_token_positions (is_open)
    WHERE is_open = TRUE;

-- ============================================================
-- Reusable wallet performance aggregates (Smart Money foundation)
-- ============================================================
CREATE TABLE IF NOT EXISTS wallet_performance (
    wallet              TEXT PRIMARY KEY,
    total_trades        INTEGER NOT NULL DEFAULT 0,
    total_buys          INTEGER NOT NULL DEFAULT 0,
    total_sells         INTEGER NOT NULL DEFAULT 0,
    tokens_purchased    INTEGER NOT NULL DEFAULT 0,
    early_buy_count     INTEGER NOT NULL DEFAULT 0,
    qualifying_trades   INTEGER NOT NULL DEFAULT 0,
    wins                INTEGER NOT NULL DEFAULT 0,
    losses              INTEGER NOT NULL DEFAULT 0,
    loss_rate           NUMERIC,
    hit_rate            NUMERIC,
    avg_return_pct      NUMERIC,
    median_return_pct   NUMERIC,
    max_return_pct      NUMERIC,
    avg_holding_seconds NUMERIC,
    realized_pnl_usd    NUMERIC NOT NULL DEFAULT 0,
    realized_pnl_sol    NUMERIC NOT NULL DEFAULT 0,
    milestones_hit      JSONB NOT NULL DEFAULT '{}',
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wallet_perf_hit_rate
    ON wallet_performance (hit_rate DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_wallet_perf_early
    ON wallet_performance (early_buy_count DESC);

-- ============================================================
-- Market / holder progression snapshots
-- ============================================================
CREATE TABLE IF NOT EXISTS market_snapshots (
    snapshot_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mint                TEXT NOT NULL,
    captured_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    price_usd           NUMERIC,
    liquidity_usd       NUMERIC,
    volume_m5_usd       NUMERIC,
    volume_h1_usd       NUMERIC,
    volume_h24_usd      NUMERIC,
    fdv_usd             NUMERIC,
    market_cap_usd      NUMERIC,
    pair_address        TEXT,
    dex_id              TEXT,
    source              TEXT NOT NULL DEFAULT 'dexscreener'
);

CREATE INDEX IF NOT EXISTS idx_market_snapshots_mint_time
    ON market_snapshots (mint, captured_at DESC);

CREATE TABLE IF NOT EXISTS holder_snapshots (
    snapshot_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mint                TEXT NOT NULL,
    captured_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    holder_count        INTEGER,
    top10_pct           NUMERIC,
    source              TEXT NOT NULL DEFAULT 'rpc',
    meta                JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_holder_snapshots_mint_time
    ON holder_snapshots (mint, captured_at DESC);

COMMENT ON TABLE migration_tracks IS 'Post-migration tracking sessions â€“ one per graduated mint';
COMMENT ON TABLE wallet_trades IS 'All observed post-migration buys and sells; continuous tracking';
COMMENT ON TABLE wallet_performance IS 'Reusable wallet stats for Smart Money / Stinky Score';

