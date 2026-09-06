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
-- descriptive relationship-kind schema existed. CREATE TABLE IF NOT EXISTS does
-- not converge an existing table, so add the missing discriminator explicitly.
-- The sentinel preserves UNKNOWN semantics: it does not infer what historical
-- relationship kind those pre-existing rows represented.
ALTER TABLE wallet_relationships
    ADD COLUMN IF NOT EXISTS relationship_kind TEXT;
UPDATE wallet_relationships
SET relationship_kind = 'legacy_unspecified'
WHERE relationship_kind IS NULL;
ALTER TABLE wallet_relationships
    ALTER COLUMN relationship_kind SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wallet_relationships_a ON wallet_relationships (wallet_a);
CREATE INDEX IF NOT EXISTS idx_wallet_relationships_b ON wallet_relationships (wallet_b);
CREATE INDEX IF NOT EXISTS idx_wallet_relationships_kind ON wallet_relationships (relationship_kind);

-- record_relationship() uses ON CONFLICT (wallet_a, wallet_b, relationship_kind).
-- Fresh schemas already have the equivalent table constraint; this named index
-- supplies the same conflict arbiter for legacy tables without dropping data.
CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_relationships_identity_unique
    ON wallet_relationships (wallet_a, wallet_b, relationship_kind);
