ALTER TABLE entity_behavior_fingerprints
    ADD COLUMN IF NOT EXISTS wallet_count INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS early_buyer_wallet_count INT,
    ADD COLUMN IF NOT EXISTS early_buyer_mint_count INT,
    ADD COLUMN IF NOT EXISTS repeat_early_buyer_wallet_count INT,
    ADD COLUMN IF NOT EXISTS wallet_role_counts JSONB NOT NULL DEFAULT '{}'::jsonb;
