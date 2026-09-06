-- Turn the existing measured market_snapshot stream into bounded lifecycle evidence.
-- The first snapshot for a mint is the observed anchor. A horizon is recorded
-- only when an actual later snapshot reaches that elapsed time. Missing horizons
-- remain absent/UNKNOWN; no interpolation or outcome classification occurs.

CREATE OR REPLACE FUNCTION ingest_market_outcome_observation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    anchor_at TIMESTAMPTZ;
    horizon_name TEXT;
    horizon_seconds INTEGER;
BEGIN
    SELECT MIN(ms.captured_at)
      INTO anchor_at
      FROM market_snapshots ms
     WHERE ms.mint = NEW.mint;

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
        IF NEW.captured_at >= anchor_at + make_interval(secs => horizon_seconds)
           AND NOT EXISTS (
               SELECT 1
                 FROM market_outcome_observations moo
                WHERE moo.mint = NEW.mint
                  AND moo.horizon = horizon_name
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
