-- Append-only storage for already-collected DEX provenance evidence.
-- This table stores evidence payloads verbatim as JSONB; it does not infer or reconstruct evidence.

CREATE TABLE IF NOT EXISTS dex_provenance_evidence_snapshots (
    id BIGSERIAL PRIMARY KEY,
    chain TEXT NOT NULL CHECK (btrim(chain) <> ''),
    pool_address TEXT NOT NULL CHECK (btrim(pool_address) <> ''),
    evidence_block BIGINT NOT NULL CHECK (evidence_block >= 0),
    evidence_key TEXT NOT NULL CHECK (btrim(evidence_key) <> ''),
    record_payload JSONB NOT NULL,
    sources_payload JSONB NOT NULL CHECK (jsonb_typeof(sources_payload) = 'array'),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chain, pool_address, evidence_block, evidence_key)
);

CREATE INDEX IF NOT EXISTS idx_dex_provenance_evidence_lookup
    ON dex_provenance_evidence_snapshots (chain, pool_address, evidence_block DESC, id DESC);

CREATE OR REPLACE FUNCTION reject_dex_provenance_evidence_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'dex provenance evidence snapshots are append-only';
END;
$$;

DROP TRIGGER IF EXISTS dex_provenance_evidence_no_update ON dex_provenance_evidence_snapshots;
CREATE TRIGGER dex_provenance_evidence_no_update
BEFORE UPDATE ON dex_provenance_evidence_snapshots
FOR EACH ROW EXECUTE FUNCTION reject_dex_provenance_evidence_mutation();

DROP TRIGGER IF EXISTS dex_provenance_evidence_no_delete ON dex_provenance_evidence_snapshots;
CREATE TRIGGER dex_provenance_evidence_no_delete
BEFORE DELETE ON dex_provenance_evidence_snapshots
FOR EACH ROW EXECUTE FUNCTION reject_dex_provenance_evidence_mutation();
