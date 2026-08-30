# ADR-009: Authoritative Global Fee Resolver

**Status:** Accepted (admission role superseded by ADR-010)  
**Date:** 2026-08-30  
**Version:** fee-resolver-v1.0.0

> ADR-010 demotes verified global fees from a mandatory Gate 1 reject to
> optional intelligence evidence. This resolver remains the only allowed
> producer of `global_fees_sol`. Do not fabricate fees.

## Context

The canonical admission gate (`evaluate_market`, profile `axiom-parity-v1.0.0`)
requires `global_fees_sol >= 1.0` with `global_fees_verified=true`. Missing or
unverified fees MUST reject (`FEES_UNKNOWN`). Volume, liquidity, market cap,
creator fees, tx count, and guessed bps MUST NOT substitute.

Pump.fun's public coin API currently does **not** expose `total_fees*` fields.
BondingCurve accounts have **no** per-mint all-time fee accumulator. The
creator-vault PDA `["creator-vault", creator]` is a **per-creator unclaimed
remainder**, not per-mint all-time global fees.

A previous path treated any finite Birdeye/meme/overview number as verified
fees. That is forbidden.

## Decision

Introduce `stinky_core.fees.FeeResolver` as the only producer of
`global_fees_sol` for live paths. Admission stays fail-closed and unchanged.

### Output

```
global_fees_sol, fees_source, fees_verified, fees_confidence,
fees_observed_at, fees_error, fees_status
```

Unknown:

```
global_fees_sol = null, fees_verified = false, fees_status = UNKNOWN
```

Unknown fails the existing gate. A bare number never implies verified.

### Allowed sources (in order)

1. **Explicit public API fee field** on pump.fun coin JSON. Keys:
   `total_fees`, `total_fees_sol`, `fees_sol`, `fee_sol`,
   `global_fees_paid`, `global_fees_sol`, `accumulated_fees`.
   Nested under `coin` / `data` / `result` only.
   **Not** `creator_fees_sol`.
2. **On-chain protocol fee recipients** (pump family only, including mayhem):
   sum SOL **or** WSOL credited to the published recipient set in parsed
   transactions. Per recipient take `max(native, WSOL)` to avoid wrap
   double-count. Sort trades by `amountSol` desc and **early-exit when the
   observed lower bound ≥ 1 SOL**.
3. Nothing else. No `fees = volume * bps`. No Helius (optional, currently off).

### Lower-bound semantics

If observed protocol-recipient credits ≥ 1 SOL → `VERIFIED` (lower bound is
sufficient to pass the ≥1 SOL gate).

If the scan is incomplete **or** the observed lower bound is < 1 SOL →
`UNKNOWN`, not `FEES_BELOW_MIN`. We cannot prove all-time fees are below the
floor without a complete per-mint accumulator.

`FEES_BELOW_MIN` is emitted only when an authoritative verified value exists
and is < 1 SOL (explicit API field).

### Protocol derivation

| Protocol | Mechanism | Result if no explicit API field |
| --- | --- | --- |
| pump, pumpfun, pumpswap, pump.fun, mayhem | Published fee-recipient native/WSOL credits | VERIFIED iff lower bound ≥ 1 SOL; else UNKNOWN |
| launchLab, virtualCurve, launchACoin, bonk, bonkers, boop, surge, moonshot, moonshotApp, heaven, daosFun, candle, sugar, jupiterStudio, bags, soar, printr, liquidAf, liquidAfAmm, riseRich, stonkfun, pve, wavebreak | No documented per-mint all-time accumulator or published recipient set in this repo | `NO_FEE_MECHANISM` → UNKNOWN → REJECT |
| raydium, pumpAmm, meteoraAmm, meteoraAmmV2, orca | Disabled by protocol allowlist | PROTOCOL_DISABLED (fees not reached) |

### Persistence

Append-only `fee_observations` (never UPDATE historical rows) with mint,
protocol, value, source, verified, observed_at, resolver_version, raw tx refs.

### Consumers

Sentinel, discovery, API, Discord, replay, and backtest consume
`evaluate_market` only. They MUST NOT auto-verify a number. Backtest reports
`fee_verified_rate` plus fee verified/unknown/rejected/passed/final counts.
Historical unknown records stay rejected.

### Observability

Structured events: `fee_resolve_start`, `fee_resolve_success`,
`fee_resolve_unknown`, `fee_resolve_error` with mint, protocol, source,
latency_ms, status, resolver_version. Never log secrets.

## Consequences

- Live PASS of the fee gate requires either an explicit API field ≥ 1 SOL or
  enough large recent trades that protocol-recipient credits sum to ≥ 1 SOL.
- Garbage / low-activity tokens typically reject as `FEES_UNKNOWN`.
- Public RPC rate limits may leave a hot token UNKNOWN on a given scan;
  that still fails closed.
- Helius remains unused (`STINKY_ENABLE_HELIUS=false`).
