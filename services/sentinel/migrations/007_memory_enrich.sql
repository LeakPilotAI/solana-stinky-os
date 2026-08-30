-- Optional observation fields. Production Postgres. Never stores fabricated returns.
ALTER TABLE wallet_observations ADD COLUMN IF NOT EXISTS side TEXT DEFAULT 'buy';
ALTER TABLE wallet_observations ADD COLUMN IF NOT EXISTS entry_price DOUBLE PRECISION;
ALTER TABLE wallet_observations ADD COLUMN IF NOT EXISTS exit_size DOUBLE PRECISION;
ALTER TABLE wallet_observations ADD COLUMN IF NOT EXISTS exit_price DOUBLE PRECISION;
ALTER TABLE wallet_observations ADD COLUMN IF NOT EXISTS ret_pct DOUBLE PRECISION;
