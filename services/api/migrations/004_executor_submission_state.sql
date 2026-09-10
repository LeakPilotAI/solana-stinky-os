-- Durable non-broadcasting executor submission/reconciliation state.
-- This schema records state-machine evidence only. It stores no private keys,
-- signatures, raw transactions, wallet secrets, or live execution authority.

CREATE TABLE IF NOT EXISTS executor_submission_state (
    attempt_id          TEXT PRIMARY KEY,
    authorization_id    TEXT NOT NULL,
    policy_version      TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL UNIQUE,
    submission_state    TEXT NOT NULL DEFAULT 'NOT_SENT',
    version             INTEGER NOT NULL DEFAULT 0,
    last_event          TEXT,
    reconciliation_required BOOLEAN NOT NULL DEFAULT FALSE,
    manual_retry_review_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    state_evidence      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT executor_submission_state_allowed CHECK (
        submission_state IN ('NOT_SENT','SUBMISSION_UNKNOWN','SUBMITTED','CONFIRMED','FAILED')
    ),
    CONSTRAINT executor_submission_version_nonnegative CHECK (version >= 0),
    CONSTRAINT executor_submission_identity_unique UNIQUE (authorization_id, attempt_id),
    CONSTRAINT executor_submission_no_secret_fields CHECK (
        NOT (state_evidence ?| ARRAY['private_key','private_key_material','secret_key','seed_phrase','mnemonic','signature','signed_transaction','raw_transaction'])
    )
);

CREATE TABLE IF NOT EXISTS executor_submission_transition_audit (
    audit_id            BIGSERIAL PRIMARY KEY,
    attempt_id          TEXT NOT NULL REFERENCES executor_submission_state (attempt_id),
    authorization_id    TEXT NOT NULL,
    policy_version      TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL,
    prior_state         TEXT NOT NULL,
    new_state           TEXT NOT NULL,
    event               TEXT NOT NULL,
    prior_version       INTEGER NOT NULL,
    new_version         INTEGER NOT NULL,
    reconciliation_required BOOLEAN NOT NULL,
    manual_retry_review_eligible BOOLEAN NOT NULL,
    transition_evidence JSONB NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT executor_transition_prior_state_allowed CHECK (
        prior_state IN ('NOT_SENT','SUBMISSION_UNKNOWN','SUBMITTED','CONFIRMED','FAILED')
    ),
    CONSTRAINT executor_transition_new_state_allowed CHECK (
        new_state IN ('NOT_SENT','SUBMISSION_UNKNOWN','SUBMITTED','CONFIRMED','FAILED')
    ),
    CONSTRAINT executor_transition_version_step CHECK (new_version = prior_version + 1),
    CONSTRAINT executor_transition_no_secret_fields CHECK (
        NOT (transition_evidence ?| ARRAY['private_key','private_key_material','secret_key','seed_phrase','mnemonic','signature','signed_transaction','raw_transaction'])
    ),
    CONSTRAINT executor_transition_once UNIQUE (attempt_id, new_version)
);

CREATE OR REPLACE FUNCTION reject_executor_submission_transition_audit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'executor_submission_transition_audit is immutable';
END;
$$;

DROP TRIGGER IF EXISTS trg_executor_submission_transition_audit_immutable ON executor_submission_transition_audit;
CREATE TRIGGER trg_executor_submission_transition_audit_immutable
BEFORE UPDATE OR DELETE ON executor_submission_transition_audit
FOR EACH ROW
EXECUTE FUNCTION reject_executor_submission_transition_audit_mutation();

CREATE OR REPLACE FUNCTION protect_executor_submission_state_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.submission_state IN ('CONFIRMED','FAILED') THEN
        RAISE EXCEPTION 'terminal executor submission state is immutable';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'executor submission version must advance exactly once';
    END IF;
    IF NEW.attempt_id <> OLD.attempt_id
       OR NEW.authorization_id <> OLD.authorization_id
       OR NEW.policy_version <> OLD.policy_version
       OR NEW.idempotency_key <> OLD.idempotency_key THEN
        RAISE EXCEPTION 'executor submission identity is immutable';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_executor_submission_state_transition ON executor_submission_state;
CREATE TRIGGER trg_executor_submission_state_transition
BEFORE UPDATE ON executor_submission_state
FOR EACH ROW
EXECUTE FUNCTION protect_executor_submission_state_transition();
