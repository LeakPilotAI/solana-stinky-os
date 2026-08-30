# Stinky OS free-tier operation

Helius is **not required**. Monthly Helius credit exhaustion must not stop the OS.

## What each surface uses (no paid key)

| Job | Source | Cost |
|---|---|---|
| Fresh pump migrations | Public Solana websocket | Free |
| 5m volume / liquidity | DexScreener | Free |
| Admission ($50k/5m, pump-only) | Local filter engine | Free |
| Buyer wallets + early ranks | pump.fun swap-api v2 `/v2/coins/:mint/trades` | Free |
| Fallback if pump API is down | Public RPC `getSignaturesForAddress` + `getTransaction` | Free |
| Market snapshots in UI | DexScreener via collector | Free |

## Helius

`STINKY_ENABLE_HELIUS=false` (default).

Even if `STINKY_HELIUS_API_KEY` is set in `.env`, the collector will **not** call Helius unless you flip the flag. This is how the OS keeps working through Sept 12 (and every month after) when the free Helius plan is maxed.

When credits reset and you *want* Helius as a third source:

```
STINKY_ENABLE_HELIUS=true
STINKY_HELIUS_API_KEY=...
```

On `429` / `max usage reached` Helius is auto-disabled for 30 minutes. Pump v2 keeps filling buyers.

## Verify after restart

Look in `logs/collector.log` for:

```
collector.started trade_source=pump.v2 enable_helius=False
chain.pump_v2_ok
chain.trades_parsed source=pump.v2 buys=N
track.early_buyers captured=N
```

Then:

```
docker exec -i stinky-postgres psql -U stinky -d stinky -c "
SELECT mint, buyers_captured, trades_observed
FROM migration_tracks
WHERE COALESCE(buyers_captured,0) > 0
ORDER BY buyers_captured DESC
LIMIT 10;"
```
