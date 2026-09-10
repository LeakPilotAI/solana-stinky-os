-- Dry-run canary single-use authorization state and immutable adapter audit.
-- This schema is intentionally DRY_RUN only. It grants no live execution authority.

CREATE TABLE IF NOT EXISTS canary_authorization_state (
    authorization_id        TEXT PRIMARY KEY,
    policy_version          TEXT NOT NULL,
    consumed                BOOLEAN NOT NULL DEFAULT FALSE,
    use_count               INTEGER NOT NULL DEFAULT 0,
    version                 INTEGER NOT NULL DEFAULT 0,
    consumed_by_attempt_id  TEXT,
    consumed_at             TIMESTAMPTZ,
    idempotency_key         TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT canary_authorization_version_nonnegative CHECK (version >= 0),
    CONSTRAINT canary_authorization_single_use_state CHECK (
        (
            consumed = FALSE
            AND use_count = 0
            AND consumed_by_attempt_id IS NULL
            AND consumed_at IS NULL
            AND idempotency_key IS NULL
        )
        OR
        (
            consumed = TRUE
            AND use_count = 1
            AND consumed_by_attempt_id IS NOT NULL
            AND consumed_at IS NOT NULL
            AND idempotency_key IS NOT NULL
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_canary_authorization_consumed_attempt
    ON canary_authorization_state (consumed_by_attempt_id)
    WHERE consumed_by_attempt_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_canary_authorization_idempotency
    ON canary_authorization_state (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS dry_run_execution_audit (
    attempt_id                      TEXT PRIMARY KEY,
    idempotency_key                 TEXT NOT NULL UNIQUE,
    authorization_id                TEXT NOT NULL REFERENCES canary_authorization_state (authorization_id),
    policy_version                  TEXT NOT NULL,
    requested_at                    TIMESTAMPTZ NOT NULL,
    requested_notional_usd          NUMERIC NOT NULL,
    max_loss_usd                    NUMERIC NOT NULL,
    adapter_mode                    TEXT NOT NULL,
    authorization_version_before    INTEGER NOT NULL,
    authorization_version_after     INTEGER NOT NULL,
    authorization_transition_applied BOOLEAN NOT NULL,
    rpc_contacted                   BOOLEAN NOT NULL DEFAULT FALSE,
    transaction_signed              BOOLEAN NOT NULL DEFAULT FALSE,
    order_submitted                 BOOLEAN NOT NULL DEFAULT FALSE,
    wallet_mutated                  BOOLEAN NOT NULL DEFAULT FALSE,
    external_side_effects           BOOLEAN NOT NULL DEFAULT FALSE,
    audit_payload                    JSONB NOT NULL,
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT dry_run_adapter_mode_only CHECK (adapter_mode = 'DRY_RUN'),
    CONSTRAINT dry_run_notional_positive CHECK (requested_notional_usd > 0),
    CONSTRAINT dry_run_notional_max_20 CHECK (requested_notional_usd <= 20),
    CONSTRAINT dry_run_loss_cap_positive CHECK (max_loss_usd > 0),
    CONSTRAINT dry_run_version_transition CHECK (
        authorization_version_before >= 0
        AND authorization_version_after = authorization_version_before + 1
    ),
    CONSTRAINT dry_run_transition_was_applied CHECK (authorization_transition_applied = TRUE),
    CONSTRAINT dry_run_no_external_side_effects CHECK (
        rpc_contacted = FALSE
        AND transaction_signed = FALSE
        AND order_submitted = FALSE
        AND wallet_mutated = FALSE
        AND external_side_effects = FALSE
    )
);

CREATE INDEX IF NOT EXISTS idx_dry_run_execution_audit_authorization
    ON dry_run_execution_audit (authorization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dry_run_execution_audit_created
    ON dry_run_execution_audit (created_at DESC);

CREATE OR REPLACE FUNCTION reject_dry_run_execution_audit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'dry_run_execution_audit is immutable';
END;
$$;

DROP TRIGGER IF EXISTS trg_dry_run_execution_audit_immutable ON dry_run_execution_audit;
CREATE TRIGGER trg_dry_run_execution_audit_immutable
BEFORE UPDATE OR DELETE ON dry_run_execution_audit
FOR EACH ROW
EXECUTE FUNCTION reject_dry_run_execution_audit_mutation();
