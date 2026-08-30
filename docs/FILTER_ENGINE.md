# Stinky Filter Engine — axiom-parity-v1.0.0

## Purpose

Single canonical **admission** decision for every opportunity / alert path.

API: `evaluate_market(market) -> EligibilityResult`

```
eligible: bool
failed_filters: []
passed_filters: []
normalized_metrics: {}
source_metadata: {}
reason_codes: []
```

Filtering happens **before** scoring. A Stinky Score of 99 cannot override a failed hard gate.

## Critical rule

> If `global_fees_sol` is unavailable or cannot be authoritatively verified, **REJECT** the token. Never treat missing fee data as passing.

A token with `fees < 1 SOL` MUST NOT enter candidate lists, Live Runners, Discord, wallet intelligence, pattern discovery, score-driven lists, or backtest populations.

## Hard gates (all must pass)

| Gate | Default | Fail closed on missing? | Reason code |
|------|---------|-------------------------|-------------|
| Protocol allowlist | pump + listed launchpads; deny raydium/meteora/orca/pumpAmm | Yes | PROTOCOL_DISABLED / PROTOCOL_UNKNOWN |
| Migrated tab | migrated | Yes | NOT_MIGRATED |
| Global fees | ≥ **1.0 SOL** | **Yes** | FEES_BELOW_MIN / FEES_UNKNOWN |
| Liquidity | ≥ **8 USD** | Yes | LIQUIDITY_BELOW_MIN |
| Volume | ≥ **$100,000** (5m) | Yes | VOLUME_BELOW_MIN |
| Market cap | ≥ **$31,333** | Yes | MARKET_CAP_BELOW_MIN |
| Social | ≥ 1 verified presence | Yes | NO_SOCIAL |

## Authoritative fee metric

**Name:** `global_fees_sol`

**Meaning:** Cumulative / all-time protocol global fees associated with the
token, expressed in SOL. **Not** creator fees, pool fees, tx fees, or volume.

**Resolver:** `stinky_core.fees.FeeResolver` (`fee-resolver-v1.0.0`).

**Sources (in order, all explicit):**

1. pump.fun public coin API fields `total_fees`, `total_fees_sol`, `fees_sol`,
   `fee_sol`, `global_fees_paid`, `global_fees_sol`, `accumulated_fees`.
2. On-chain SOL/WSOL credited to published pump.fun protocol fee recipients
   (pump family including mayhem). Lower bound. PASS if observed ≥ 1 SOL.

**Not acceptable substitutes:** creator fees, pool fees, estimated fees,
transaction count, volume, liquidity, protocol revenue, `volume * bps`.

When neither source can establish a verified value the candidate is
`FEES_UNKNOWN` and **cannot alert**. Incomplete on-chain scans below 1 SOL
are UNKNOWN, not BELOW_MIN.

**Unit normalization:** if a raw numeric value is `> 1_000_000`, treat as
lamports and divide by `1e9`. Non-finite / negative → invalid / unknown.

**Provenance required:** `global_fees_sol`, `global_fees_source`,
`global_fees_timestamp`, `global_fees_verified=true`.

A bare number is **not** verification. See `docs/adr/ADR-009-fee-resolver.md`.

## Reason codes

`FEES_BELOW_MIN` `FEES_UNKNOWN` `LIQUIDITY_BELOW_MIN` `VOLUME_BELOW_MIN` `MARKET_CAP_BELOW_MIN` `PROTOCOL_DISABLED` `PROTOCOL_UNKNOWN` `NO_SOCIAL` `DEX_PAID` `NOT_MIGRATED` `INVALID_MARKET_DATA` `SYNTHETIC_ACTIVITY_SUSPECTED`

## Layers

1. **Early gate** (`qualify_fresh_pump_migration`) — mint + DEX + fees. Wrapper around `evaluate_market` with `EARLY_GATE_CONFIG`.
2. **Full admission** (`evaluate_market` / `evaluate_admission`) — all hard gates.
3. **Intelligence gate** (`can_alert`) — score ≥ 55 and meaningful early buyers ≥ 3. Only after admission.

## Backtest

`stinky_core.backtest.backtest_candidates` deduplicates by mint, then applies the same `evaluate_market`, then `can_alert`, then outcome labels (RUNNER / HELD / FADE / UNKNOWN).

Reported: `total_candidates`, `fee_verified`, `fee_unknown`, `fee_rejected`, `fee_passed`, `final_candidates`, `fee_verified_rate`.
Historical unknown fees stay rejected.
