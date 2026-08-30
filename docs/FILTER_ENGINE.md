# Stinky Filter Engine — volume-first-v1.0.0

## Purpose

Single canonical **admission** decision for every opportunity / alert path.

API: `evaluate_market(market) -> EligibilityResult`

Gate 1 is an **investigation trigger**, not a buy signal.

```
eligible: bool   # Gate 1 passed
failed_filters: []
passed_filters: []
normalized_metrics: {}
source_metadata: {}
reason_codes: []
```

Filtering happens **before** scoring. A Stinky Score of 99 cannot override a failed Gate 1.

## Gate 1 (required)

| Gate | Default | Fail closed on missing? | Reason code |
|------|---------|-------------------------|-------------|
| Protocol allowlist | pump + listed launchpads; deny raydium/meteora/orca/pumpAmm | Yes | PROTOCOL_DISABLED / PROTOCOL_UNKNOWN |
| Valid mint | non-empty | Yes | INVALID_MINT |
| Migrated tab | migrated | Yes | NOT_MIGRATED |
| 5m volume | ≥ **$150,000** (configurable up to $200,000) | Yes | VOLUME_BELOW_MIN / VOLUME_UNKNOWN |

## Not Gate 1

| Signal | Role |
|--------|------|
| Global fees | Optional evidence via FeeResolver. Unknown does **not** reject. |
| Liquidity | Recorded; used in inspection / rug model |
| Market cap | Recorded |
| Social | Recorded; not required |

## Alert policy

`can_alert` / `can_alert_investigation` after Gate 1:

- inspection complete
- synthetic and rug not CRITICAL
- meaningful intelligence (stored wallets / creator / observed flow)
- score ≥ 55

Volume alone cannot alert.

## Authoritative fee metric (optional)

**Name:** `global_fees_sol`

Resolver: `stinky_core.fees.FeeResolver` (`fee-resolver-v1.0.0`). See ADR-009
and ADR-010.

When unknown: `global_fees_sol = NULL`, `fee_status = UNKNOWN`. Never label unknown as zero.

## Reason codes

`VOLUME_BELOW_MIN` `VOLUME_UNKNOWN` `PROTOCOL_DISABLED` `PROTOCOL_UNKNOWN` `NOT_MIGRATED` `INVALID_MARKET_DATA` `INVALID_MINT` `FEES_BELOW_MIN` `FEES_UNKNOWN` (legacy / optional-fees profile) `INSPECTION_INCOMPLETE` `RISK_CRITICAL` `INTELLIGENCE_INSUFFICIENT` `SCORE_BELOW_MIN`

## Layers

1. **Gate 1** (`evaluate_gate1` / `qualify_fresh_pump_migration`) — mint + protocol + migrated + 5m volume.
2. **Deep inspection** (`stinky_core.inspect` + `stinky_core.intelligence.investigate`).
3. **Intelligence gate** (`can_alert_investigation`) — only after inspection.

## Backtest

`stinky_core.backtest.backtest_candidates` (`stinky-backtest-v1.1.0-volume-first`):

- unique mint
- Gate 1 at **decision-time volume** (peak_volume stripped)
- investigate
- alert
- outcome labels from future observations only after the decision

Reported: `unique_candidates`, `gate1_passed`, `deep_inspected`, `alerts`, `runners`, `held`, `fades`, `unknown`, `precision_runner`.
