CREATE TABLE IF NOT EXISTS paper_policy_registry (
  policy_version text PRIMARY KEY,
  horizon text NOT NULL CHECK (horizon IN ('5m','15m','30m','1h','4h','24h')),
  min_runner_probability double precision NOT NULL CHECK (min_runner_probability >= 0 AND min_runner_probability <= 1),
  max_fade_probability double precision NOT NULL CHECK (max_fade_probability >= 0 AND max_fade_probability <= 1),
  min_nonnegative_market_cap_probability double precision NOT NULL CHECK (min_nonnegative_market_cap_probability >= 0 AND min_nonnegative_market_cap_probability <= 1),
  entry_slippage_bps double precision NOT NULL CHECK (entry_slippage_bps >= 0),
  exit_slippage_bps double precision NOT NULL CHECK (exit_slippage_bps >= 0),
  entry_fee_bps double precision NOT NULL CHECK (entry_fee_bps >= 0),
  exit_fee_bps double precision NOT NULL CHECK (exit_fee_bps >= 0),
  latency_ms double precision NOT NULL CHECK (latency_ms >= 0),
  paper_notional_usd double precision NOT NULL CHECK (paper_notional_usd > 0 AND paper_notional_usd <= 20),
  policy_sha256 text NOT NULL UNIQUE CHECK (length(policy_sha256) = 64),
  policy_payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_policy_active (
  singleton boolean PRIMARY KEY DEFAULT TRUE CHECK (singleton = TRUE),
  policy_version text NOT NULL REFERENCES paper_policy_registry(policy_version),
  activated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_policy_activation_audit (
  audit_id bigserial PRIMARY KEY,
  policy_version text NOT NULL REFERENCES paper_policy_registry(policy_version),
  activated_at timestamptz NOT NULL DEFAULT now(),
  policy_sha256 text NOT NULL CHECK (length(policy_sha256) = 64)
);

CREATE OR REPLACE FUNCTION genesis_forbid_paper_policy_registry_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'paper_policy_registry is immutable';
END $$;

DROP TRIGGER IF EXISTS paper_policy_registry_immutable ON paper_policy_registry;
CREATE TRIGGER paper_policy_registry_immutable
BEFORE UPDATE OR DELETE ON paper_policy_registry
FOR EACH ROW EXECUTE FUNCTION genesis_forbid_paper_policy_registry_mutation();
