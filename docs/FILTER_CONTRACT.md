# Filter contract — volume-first-v1.0.0

Canonical market-quality gate. Do not mutate thresholds in place; introduce a
new versioned profile if strategy changes.

**Rule:** 5-minute volume ≥ $150,000 (configurable up to $200,000) is the
investigation trigger. Unknown `global_fees_sol` does **not** reject Gate 1.
Never treat missing fee data as zero. Never substitute volume for fees.

Gate 1 is **not** a buy signal. Alerts require completed inspection.

Public API: `evaluate_market(market) -> EligibilityResult`
(`eligible`, `failed_filters`, `passed_filters`, `normalized_metrics`,
`source_metadata`, `reason_codes`).

Profile: `FILTER_VERSION=volume-first-v1.0.0`
Env: `STINKY_GATE1_VOLUME_5M_USD=150000` (max 200000)

## Gate 1

| Filter | Operator | Threshold | Unit | Source | Failure code |
| --- | --- | --- | --- | --- | --- |
| protocol | allowlist | see lists | str | DexScreener `dexId` | PROTOCOL_DISABLED / PROTOCOL_UNKNOWN |
| mint | non-empty | — | str | chain / DexScreener | INVALID_MINT |
| migrated | = | migrated | — | tab | NOT_MIGRATED |
| volume | >= | **150000** | USD | DexScreener 5m volume (`volume.m5`) | VOLUME_BELOW_MIN / VOLUME_UNKNOWN |

## Optional evidence (not admission)

| Field | Role |
| --- | --- |
| global_fees_sol | FeeResolver VERIFIED / UNKNOWN / UNSUPPORTED. ≥1 SOL positive, <1 negative. |
| liquidity_usd | inspection / rug |
| market_cap_usd | recorded |
| social | recorded |

## Fee source

Authoritative metric name: `global_fees_sol`. See ADR-009. `creator_fees_sol`
is not global fees. Forbidden substitutes: volume, liquidity, `volume * bps`.

## Intelligence after Gate 1

`investigate()` → synthetic, rug, creator, wallets, patterns, runner potential,
Stinky Score (`score-v1.0.0-volume-first`).

Alert: Gate 1 + inspection complete + not CRITICAL + intelligence + score ≥ 55.
