CREATE TABLE IF NOT EXISTS wallet_relationships (
    id                 BIGSERIAL PRIMARY KEY,
    wallet_a           TEXT NOT NULL,
    wallet_b           TEXT NOT NULL,
    relationship_kind  TEXT NOT NULL,
    observation_count  INT NOT NULL DEFAULT 1,
    first_seen_at      TIMESTAMPTZ,
    last_seen_at       TIMESTAMPTZ,
    confidence         DOUBLE PRECISION,
    evidence           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (wallet_a < wallet_b),
    UNIQUE (wallet_a, wallet_b, relationship_kind)
);

-- Legacy installations can already have wallet_relationships from the older
-- ADR-012 per-observation schema. CREATE TABLE IF NOT EXISTS does not converge
-- an existing table, so add every column required by the current aggregate
-- relationship store while preserving the older columns and evidence in place.
ALTER TABLE wallet_relationships
    ADD COLUMN IF NOT EXISTS relationship_kind TEXT;
ALTER TABLE wallet_relationships
    ADD COLUMN IF NOT EXISTS observation_count INT;
ALTER TABLE wallet_relationships
    ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ;
ALTER TABLE wallet_relationships
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
ALTER TABLE wallet_relationships
    ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION;
ALTER TABLE wallet_relationships
    ADD COLUMN IF NOT EXISTS evidence JSONB;
ALTER TABLE wallet_relationships
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE wallet_relationships
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

-- Bridge factual provenance from the ADR-012 schema only when those legacy
-- columns actually exist. Dynamic SQL keeps this block safe on fresh schemas.
-- kind and observed_at are direct stored facts, not inferred classifications or
-- fabricated timestamps. The legacy columns remain present after convergence.
DO $bridge$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'wallet_relationships'
          AND column_name = 'kind'
    ) THEN
        EXECUTE 'UPDATE wallet_relationships
                 SET relationship_kind = kind
                 WHERE relationship_kind IS NULL
                   AND kind IS NOT NULL';
        EXECUTE 'UPDATE wallet_relationships
                 SET relationship_kind = kind
                 WHERE relationship_kind = ''legacy_unspecified''
                   AND kind IS NOT NULL';
        EXECUTE 'ALTER TABLE wallet_relationships ALTER COLUMN kind DROP NOT NULL';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'wallet_relationships'
          AND column_name = 'observed_at'
    ) THEN
        EXECUTE 'UPDATE wallet_relationships
                 SET first_seen_at = observed_at
                 WHERE first_seen_at IS NULL
                   AND observed_at IS NOT NULL';
        EXECUTE 'UPDATE wallet_relationships
                 SET last_seen_at = observed_at
                 WHERE last_seen_at IS NULL
                   AND observed_at IS NOT NULL';
        EXECUTE 'ALTER TABLE wallet_relationships ALTER COLUMN observed_at DROP NOT NULL';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'wallet_relationships'
          AND column_name = 'mint'
    ) THEN
        EXECUTE 'ALTER TABLE wallet_relationships ALTER COLUMN mint DROP NOT NULL';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'wallet_relationships'
          AND column_name = 'reason'
    ) THEN
        EXECUTE 'ALTER TABLE wallet_relationships ALTER COLUMN reason DROP NOT NULL';
    END IF;
END
$bridge$;

-- Rows from an even older or partially migrated schema may have no recoverable
-- kind at all. Preserve that uncertainty rather than inferring funding,
-- ownership, coordination, intent, risk, quality, or another stronger meaning.
UPDATE wallet_relationships
SET relationship_kind = 'legacy_unspecified'
WHERE relationship_kind IS NULL;

-- A pre-existing aggregate relationship row is one stored relationship fact at
-- minimum. This is a storage-count baseline, not a confidence/quality/risk
-- inference. Per-observation ADR-012 rows also remain individually preserved.
UPDATE wallet_relationships
SET observation_count = 1
WHERE observation_count IS NULL;

-- Empty JSON means no structured evidence payload was preserved on the row. It
-- does not add or infer evidence.
UPDATE wallet_relationships
SET evidence = '{}'::jsonb
WHERE evidence IS NULL;

ALTER TABLE wallet_relationships
    ALTER COLUMN relationship_kind SET NOT NULL;
ALTER TABLE wallet_relationships
    ALTER COLUMN observation_count SET DEFAULT 1;
ALTER TABLE wallet_relationships
    ALTER COLUMN observation_count SET NOT NULL;
ALTER TABLE wallet_relationships
    ALTER COLUMN evidence SET DEFAULT '{}'::jsonb;
ALTER TABLE wallet_relationships
    ALTER COLUMN evidence SET NOT NULL;

-- Defaults apply to future writes only. Existing legacy rows intentionally keep
-- NULL created_at/updated_at when those timestamps were not historically stored;
-- migration time must not masquerade as relationship observation provenance.
ALTER TABLE wallet_relationships
    ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE wallet_relationships
    ALTER COLUMN updated_at SET DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_wallet_relationships_a ON wallet_relationships (wallet_a);
CREATE INDEX IF NOT EXISTS idx_wallet_relationships_b ON wallet_relationships (wallet_b);
CREATE INDEX IF NOT EXISTS idx_wallet_relationships_kind ON wallet_relationships (relationship_kind);

-- record_relationship() uses ON CONFLICT (wallet_a, wallet_b, relationship_kind).
-- Fresh schemas already have the equivalent table constraint; this named index
-- supplies the same conflict arbiter for converged legacy tables without
-- deleting or rewriting historical evidence rows.
CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_relationships_identity_unique
    ON wallet_relationships (wallet_a, wallet_b, relationship_kind);
