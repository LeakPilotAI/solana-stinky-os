# Filter contract — axiom-parity-v1.0.0

Canonical market-quality gate. **Immutable profile.** Do not mutate thresholds
in place; introduce a new versioned profile if strategy changes.

**Rule:** If `global_fees_sol` is unavailable or cannot be authoritatively
verified, **REJECT**. Never treat missing fee data as passing.

Filtering happens **before** scoring. A Stinky Score of 94 with fees 0.42 SOL
is **REJECTED**, not an alert.

Public API: `evaluate_market(market) -> EligibilityResult`
(`eligible`, `failed_filters`, `passed_filters`, `normalized_metrics`,
`source_metadata`, `reason_codes`).

## Hard gates

| Filter | Operator | Threshold | Unit | Source | Failure code |
| --- | --- | --- | --- | --- | --- |
| protocol | allowlist | see lists | str | DexScreener `dexId` | PROTOCOL_DISABLED / PROTOCOL_UNKNOWN |
| migrated | = | migrated | — | tab | NOT_MIGRATED |
| global_fees_sol | >= | **1** | SOL | pump.fun `total_fees*` (authoritative). **Not** DexScreener, not tx fee, not LP fee, not volume. | FEES_UNKNOWN / FEES_BELOW_MIN |
| liquidity | >= | 8 | USD | DexScreener `liquidity.usd` | LIQUIDITY_BELOW_MIN |
| volume | >= | 100000 | USD | DexScreener 5m volume (`volume.m5`) | VOLUME_BELOW_MIN |
| market_cap | >= | 31333 | USD | DexScreener `marketCap` else `fdv` | MARKET_CAP_BELOW_MIN |
| social | atLeastOne | true | bool | twitter / website / telegram / tiktok | NO_SOCIAL |
| mint suffix | mustEndInPump | **false** | — | mint string | not required |
| tab | = | migrated | — | strategy | NOT_MIGRATED |

Unknown / missing required metric → REJECT. Null is not zero.

## Fee source

Authoritative metric name: `global_fees_sol`.

Current source: pump.fun public coin API
`https://frontend-api-v3.pump.fun/coins/{mint}` fields `total_fees`,
`total_fees_sol`, `fees_sol`. As of 2026-08-30 those fields are **absent**
from the public payload; candidates are `FEES_UNKNOWN` and cannot alert.

Forbidden substitutes: creator fees, pool fees, estimated fees, txn count,
volume, liquidity, protocol revenue.

## Protocol lists

**Denied:** raydium, pumpAmm, meteoraAmm, meteoraAmmV2, orca (plus phoenix/lifinity/saber/aldrin/fluxbeam).

**Allowed:** pump, pumpfun, pumpswap, mayhem, launchLab, virtualCurve, launchACoin, bonk, bonkers, boop, surge, moonshot, moonshotApp, heaven, daosFun, candle, sugar, jupiterStudio, bags, soar, printr, liquidAf, liquidAfAmm, riseRich, stonkfun, pve, wavebreak.

## Intelligence gate (after market quality)

- `STINKY_ALERT_MIN_SCORE=55`
- `STINKY_ALERT_MIN_MEANINGFUL_BUYERS=3`

Score cannot override a failed hard gate. `can_alert()` enforces this.

## Backtest

`stinky_core.backtest.backtest_candidates` uses the same `evaluate_market`.
Deduplicate by mint first. Outcome labels: RUNNER / HELD / FADE / UNKNOWN
(`outcome-v1.0.0`). Unknown remains unknown.

## Env

```
STINKY_MIN_FEES_SOL=1
STINKY_MIN_VOLUME_USD=100000
STINKY_MIN_LIQUIDITY_USD=8
STINKY_MIN_MARKET_CAP_USD=31333
STINKY_ALERT_MIN_SCORE=55
STINKY_ALERT_MIN_MEANINGFUL_BUYERS=3
STINKY_FILTER_VERSION=axiom-parity-v1.0.0
STINKY_ENABLE_HELIUS=false
```
