# ADR-021 Live pipeline validation

Status: Accepted
Date: 2026-08-30

## Decision

intel-v1.10.0-live-validation proves the existing Genesis path. It does not add a new brain.

## Live path (production)

1. Market data: DexScreener `latest/dex/tokens/{mint}` (`sentinel.volume.DexScreenerClient`)
2. Migration: public Solana WS logsSubscribe (`sentinel.migration_watcher.MigrationWatcher`)
3. Backfill: DexScreener boosts/profiles → Gate 1 (`sentinel.discovery.HighVolumeDiscovery`)
4. Gate 1: `qualify_fresh_pump_migration` → `evaluate_gate1` $150k / $200k clamp. Fees optional.
5. Watch: `VolumeMonitor._run_watch` investigate once, tick until T+1800
6. Investigation: `stinky_core.intelligence.investigate` — immutable `ON CONFLICT DO NOTHING`
7. Ticks: `market_observations` + in-process `IntelligenceMemory`
8. Quality: `evaluate_quality_state` on each followup tick; `quality.state_changed` event
9. Outcome: computed on-read from ticks (`what_happened_next` / `label_outcome`)
10. Analogues: `slice_analogues` same-offset only
11. Browser (GitHub): API hydrates Postgres. Preview: live DexScreener scan, no Postgres.
12. Discord: `discord_bot.policy.should_alert` then `format_quality_alert` (not a buy/sell)

## Bugs found and fixed

- After Gate 1, volume dropping below $150k skipped followup ticks, so quality could not observe dumps. Contract: `watch_tick_decision`.
- Sentinel restart did not resume T+1800 watches. Contract: `watch_should_resume` + `VolumeMonitor.start()`.
- Memory hydrate ran only on the next investigation, not on process start.
- pumpfun bonding pairs were treated as migrated. Contract: `is_post_migration_dex`.
- Analogue/outcome labels were read from the immutable investigation row (usually UNKNOWN) instead of later ticks.
- Observation as-of was exclusive (`ts < cutoff`) while quality was inclusive (`ts <= cutoff`). A tick at T+15 was invisible to slices/analogues at as_of T+15. Now inclusive everywhere: the current tick is visible; later ticks are not.

## Not claimed

A live $150k Gate 1 print during this sandbox run. If DexScreener shows none: LIVE GATE-1 EVENT: NOT OBSERVED.
