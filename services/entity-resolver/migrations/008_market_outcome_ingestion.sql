-- Turn measured market_snapshot inserts into bounded lifecycle evidence.
-- Two distinct factual memories are preserved:
--   1) the first actual snapshot at/after a lifecycle horizon;
--   2) one prospective Phase-10 feature snapshot shortly BEFORE each research cutoff.
-- The second path exists only for new inserts after this migration is active. It never
-- backfills historical rows and never treats captured_at as a historical ingestion time.

CREATE OR REPLACE FUNCTION ingest_market_outcome_observation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    anchor_at TIMESTAMPTZ;
    horizon_name TEXT;
    horizon_seconds INTEGER;
    feature_cutoff TIMESTAMPTZ;
    seconds_before_cutoff NUMERIC;
BEGIN
    -- Prefer the factual migration time. Fall back to the first observed market
    -- snapshot only for older/non-migration callers that lack migration_tracks.
    SELECT mt.migration_at
      INTO anchor_at
      FROM migration_tracks mt
     WHERE mt.mint = NEW.mint
     LIMIT 1;

    IF anchor_at IS NULL THEN
        SELECT MIN(ms.captured_at)
          INTO anchor_at
          FROM market_snapshots ms
         WHERE ms.mint = NEW.mint;
    END IF;

    IF anchor_at IS NULL OR NEW.captured_at < anchor_at THEN
        RETURN NEW;
    END IF;

    FOR horizon_name, horizon_seconds IN
        SELECT * FROM (VALUES
            ('5m', 300),
            ('15m', 900),
            ('30m', 1800),
            ('1h', 3600),
            ('4h', 14400),
            ('24h', 86400)
        ) AS horizons(name, seconds)
    LOOP
        feature_cutoff := anchor_at + make_interval(secs => horizon_seconds);
        seconds_before_cutoff := EXTRACT(EPOCH FROM (feature_cutoff - NEW.captured_at));

        -- Prospective Phase-10 feature memory. Record one real snapshot in the final
        -- 90 seconds before the cutoff. The trigger transaction itself supplies the
        -- durable ingestion time, so both observed_at and ingested_at must be <= the
        -- feature cutoff for the research dataset to accept it.
        IF horizon_name IN ('5m', '15m', '30m')
           AND seconds_before_cutoff >= 0
           AND seconds_before_cutoff <= 90
           AND NOT EXISTS (
               SELECT 1
                 FROM market_outcome_observations moo
                WHERE moo.mint = NEW.mint
                  AND moo.horizon = horizon_name
                  AND moo.evidence_basis = 'phase10_pre_cutoff_market_snapshot'
           )
        THEN
            INSERT INTO market_outcome_observations (
                mint,
                horizon,
                horizon_seconds,
                anchor_observed_at,
                observed_at,
                ingested_at,
                source,
                evidence_basis,
                metrics
            ) VALUES (
                NEW.mint,
                horizon_name,
                horizon_seconds,
                anchor_at,
                NEW.captured_at,
                now(),
                COALESCE(NULLIF(NEW.source, ''), 'market_snapshots'),
                'phase10_pre_cutoff_market_snapshot',
                jsonb_build_object(
                    'price_usd', NEW.price_usd,
                    'liquidity_usd', NEW.liquidity_usd,
                    'volume_m5_usd', NEW.volume_m5_usd,
                    'volume_h1_usd', NEW.volume_h1_usd,
                    'volume_h24_usd', NEW.volume_h24_usd,
                    'fdv_usd', NEW.fdv_usd,
                    'market_cap_usd', NEW.market_cap_usd,
                    'pair_address', NEW.pair_address,
                    'dex_id', NEW.dex_id,
                    'elapsed_seconds', EXTRACT(EPOCH FROM (NEW.captured_at - anchor_at)),
                    'seconds_before_feature_cutoff', seconds_before_cutoff,
                    'phase10_prospective', true
                )
            ) ON CONFLICT DO NOTHING;
        END IF;

        -- Preserve the original lifecycle observation: the first measured snapshot
        -- at/after the horizon. It remains separate from the pre-cutoff research feature.
        IF NEW.captured_at >= feature_cutoff
           AND NOT EXISTS (
               SELECT 1
                 FROM market_outcome_observations moo
                WHERE moo.mint = NEW.mint
                  AND moo.horizon = horizon_name
                  AND moo.evidence_basis = 'market_snapshot_observation'
           )
        THEN
            INSERT INTO market_outcome_observations (
                mint,
                horizon,
                horizon_seconds,
                anchor_observed_at,
                observed_at,
                ingested_at,
                source,
                evidence_basis,
                metrics
            ) VALUES (
                NEW.mint,
                horizon_name,
                horizon_seconds,
                anchor_at,
                NEW.captured_at,
                now(),
                COALESCE(NULLIF(NEW.source, ''), 'market_snapshots'),
                'market_snapshot_observation',
                jsonb_build_object(
                    'price_usd', NEW.price_usd,
                    'liquidity_usd', NEW.liquidity_usd,
                    'volume_m5_usd', NEW.volume_m5_usd,
                    'volume_h1_usd', NEW.volume_h1_usd,
                    'volume_h24_usd', NEW.volume_h24_usd,
                    'fdv_usd', NEW.fdv_usd,
                    'market_cap_usd', NEW.market_cap_usd,
                    'pair_address', NEW.pair_address,
                    'dex_id', NEW.dex_id,
                    'elapsed_seconds', EXTRACT(EPOCH FROM (NEW.captured_at - anchor_at))
                )
            ) ON CONFLICT DO NOTHING;
        END IF;
    END LOOP;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_market_snapshot_outcome_ingestion ON market_snapshots;

CREATE TRIGGER trg_market_snapshot_outcome_ingestion
AFTER INSERT ON market_snapshots
FOR EACH ROW
EXECUTE FUNCTION ingest_market_outcome_observation();
