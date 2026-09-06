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

-- Legacy installations can already have wallet_relationships from before the
-- descriptive relationship evidence schema existed. CREATE TABLE IF NOT EXISTS
-- does not converge an existing table, so add every column required by current
-- reads/writes explicitly and preserve UNKNOWN provenance for old rows.
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

-- Historical relationship kind is not recoverable from the legacy schema.
-- Preserve that uncertainty rather than inferring funding, ownership,
-- coordination, intent, risk, quality, or any other stronger meaning.
UPDATE wallet_relationships
SET relationship_kind = 'legacy_unspecified'
WHERE relationship_kind IS NULL;

-- A pre-existing relationship row is one observed relationship fact at minimum;
-- this is a storage-count baseline, not a confidence/quality/risk inference.
UPDATE wallet_relationships
SET observation_count = 1
WHERE observation_count IS NULL;

-- Empty JSON means no structured evidence payload was preserved on the legacy
-- row. It does not add or infer evidence.
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
-- supplies the same conflict arbiter for legacy tables without dropping data.
CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_relationships_identity_unique
    ON wallet_relationships (wallet_a, wallet_b, relationship_kind);
