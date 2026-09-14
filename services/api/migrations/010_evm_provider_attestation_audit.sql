-- Successful explicit observation receipts share the observation transaction.
CREATE TABLE IF NOT EXISTS evm_provider_attestation_audit (
    chain TEXT NOT NULL CHECK (btrim(chain) <> ''),
    pool_address TEXT NOT NULL CHECK (btrim(pool_address) <> ''),
    block_number BIGINT NOT NULL CHECK (block_number >= 0),
    completed_at TIMESTAMPTZ NOT NULL,
    audit_payload JSONB NOT NULL CHECK (jsonb_typeof(audit_payload) = 'object'),
    PRIMARY KEY (chain, pool_address, block_number)
);

CREATE OR REPLACE FUNCTION reject_evm_provider_attestation_audit_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'provider attestation audit is append-only';
END;
$$;

DROP TRIGGER IF EXISTS evm_provider_attestation_audit_immutable ON evm_provider_attestation_audit;
CREATE TRIGGER evm_provider_attestation_audit_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON evm_provider_attestation_audit
FOR EACH STATEMENT EXECUTE FUNCTION reject_evm_provider_attestation_audit_mutation();
