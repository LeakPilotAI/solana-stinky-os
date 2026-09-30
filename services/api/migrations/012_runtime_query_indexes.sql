-- Runtime read-path indexes proven necessary by sustained Windows evidence.
-- Idempotent and additive; no execution/trading semantics.
CREATE INDEX IF NOT EXISTS idx_filter_eval_mint_evaluated_at
    ON filter_evaluations (mint, evaluated_at DESC);

-- Existing collector migration normally owns this index. Keep an API-side
-- idempotent convergence guard because command-center reads the shared table.
CREATE INDEX IF NOT EXISTS idx_market_snapshots_mint_time
    ON market_snapshots (mint, captured_at DESC);
