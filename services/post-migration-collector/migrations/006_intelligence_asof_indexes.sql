-- Intelligence Engine as-of query support.
--
-- Performance-only index. This does not alter evidence semantics, scoring,
-- prospective boundaries, policy thresholds, or trading authority.
--
-- The prospective T+60 shadow scorer filters migration_buyers by:
--   track_id = ?
--   bought_at <= migration_at + horizon
--
-- Without this access path PostgreSQL must scan the full buyer projection
-- for each eligible migration track.

CREATE INDEX IF NOT EXISTS idx_migration_buyers_track_bought_at
    ON migration_buyers (track_id, bought_at);
