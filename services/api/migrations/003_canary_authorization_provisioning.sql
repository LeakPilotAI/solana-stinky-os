-- Provenance for single-use canary authorization state.
-- Rows may only be provisioned from a passed isolated-canary authorization.

ALTER TABLE canary_authorization_state
    ADD COLUMN IF NOT EXISTS authorized_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS authorized_notional_usd NUMERIC,
    ADD COLUMN IF NOT EXISTS max_loss_usd NUMERIC,
    ADD COLUMN IF NOT EXISTS authorization_evidence JSONB,
    ADD COLUMN IF NOT EXISTS provisioned_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE canary_authorization_state
    DROP CONSTRAINT IF EXISTS canary_authorization_notional_positive,
    ADD CONSTRAINT canary_authorization_notional_positive CHECK (
        authorized_notional_usd IS NULL OR authorized_notional_usd > 0
    ),
    DROP CONSTRAINT IF EXISTS canary_authorization_notional_max_20,
    ADD CONSTRAINT canary_authorization_notional_max_20 CHECK (
        authorized_notional_usd IS NULL OR authorized_notional_usd <= 20
    ),
    DROP CONSTRAINT IF EXISTS canary_authorization_loss_cap_valid,
    ADD CONSTRAINT canary_authorization_loss_cap_valid CHECK (
        max_loss_usd IS NULL OR (
            max_loss_usd > 0
            AND authorized_notional_usd IS NOT NULL
            AND max_loss_usd <= authorized_notional_usd
        )
    );

CREATE TABLE IF NOT EXISTS canary_authorization_provision_audit (
    authorization_id        TEXT PRIMARY KEY REFERENCES canary_authorization_state (authorization_id),
    policy_version          TEXT NOT NULL,
    authorized_at           TIMESTAMPTZ NOT NULL,
    authorized_notional_usd NUMERIC NOT NULL,
    max_loss_usd            NUMERIC NOT NULL,
    authorization_evidence  JSONB NOT NULL,
    provisioned_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT canary_provision_notional_positive CHECK (authorized_notional_usd > 0),
    CONSTRAINT canary_provision_notional_max_20 CHECK (authorized_notional_usd <= 20),
    CONSTRAINT canary_provision_loss_cap CHECK (max_loss_usd > 0 AND max_loss_usd <= authorized_notional_usd)
);

CREATE OR REPLACE FUNCTION reject_canary_authorization_provision_audit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'canary_authorization_provision_audit is immutable';
END;
$$;

DROP TRIGGER IF EXISTS trg_canary_authorization_provision_audit_immutable ON canary_authorization_provision_audit;
CREATE TRIGGER trg_canary_authorization_provision_audit_immutable
BEFORE UPDATE OR DELETE ON canary_authorization_provision_audit
FOR EACH ROW
EXECUTE FUNCTION reject_canary_authorization_provision_audit_mutation();
