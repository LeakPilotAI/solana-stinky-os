-- Durable, non-execution state for explicit read-only reference DEX observation triggers.
CREATE TABLE IF NOT EXISTS evm_reference_observation_trigger_state (
    chain TEXT NOT NULL,
    pool_address TEXT NOT NULL,
    last_completed_block BIGINT NOT NULL CHECK (last_completed_block >= 0),
    last_completed_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chain, pool_address)
);

CREATE INDEX IF NOT EXISTS idx_evm_reference_observation_trigger_state_completed
    ON evm_reference_observation_trigger_state (last_completed_at DESC);
