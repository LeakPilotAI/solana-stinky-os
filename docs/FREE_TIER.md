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
