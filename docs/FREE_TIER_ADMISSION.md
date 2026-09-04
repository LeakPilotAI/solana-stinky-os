# Free-tier admission (vol-first)

## Goal
Detect fresh pump migrations with >= $50k 5m volume, log early wallets,
backtest patterns -- without Birdeye paid fees.

## Gates (default)
- mint ends with `pump`
- dex in pumpswap / pumpfun / pump
- volume: runners $50k / trending $100k (DexScreener)
- global fees: OPTIONAL (`STINKY_REQUIRE_GLOBAL_FEES=false`)

## Strict fees (optional later)
`STINKY_REQUIRE_GLOBAL_FEES=true` restores fail-closed >= 5 SOL via Birdeye.

## Env
```
STINKY_VOLUME_THRESHOLD_USD=50000
STINKY_MIN_FEES_SOL=5.0
STINKY_REQUIRE_GLOBAL_FEES=false
```
