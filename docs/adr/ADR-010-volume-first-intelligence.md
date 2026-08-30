# ADR-010 — Volume-First Discovery and Progressive Intelligence Pipeline

Status: Accepted
Date: 2026-08-30

## Context

The previous admission profile (`axiom-parity-v1.0.0`, ADR-009) required
verified `global_fees_sol ≥ 1` as a hard Gate 1 reject.

In production that created a data problem, not a strategy problem:

- public APIs usually do not expose authoritative lifetime global fees
- RPC cannot reconstruct all historical protocol-recipient credits
- a recent-trade window is not lifetime fees
- creator fees are not global fees
- `volume × assumed bps` is forbidden
- unknown fees therefore rejected almost every otherwise interesting market

Volume of $150k–$200k in 5 minutes is also not a buy signal. A coin can print
that volume and still be garbage.

## Decision

1. **Gate 1 is an investigation trigger**, not approval.
   - protocol allowlist
   - valid mint / CA
   - valid market data
   - migrated
   - 5-minute volume ≥ `STINKY_GATE1_VOLUME_5M_USD` (default **150000**,
     configurable up to **200000**)
2. After Gate 1, run a progressive intelligence pipeline:
   inspect → synthetic risk → creator → wallets/entities → patterns →
   rug risk → runner potential → Stinky Score → maybe alert.
3. **Do not alert because Gate 1 passed.**
   Alert requires: Gate 1 + inspection complete + not CRITICAL risk +
   meaningful intelligence + score ≥ 55.
4. **FeeResolver remains** as optional evidence (`VERIFIED` / `UNKNOWN` /
   `UNSUPPORTED`). Unknown fees do not reject. Verified ≥ 1 SOL is a small
   positive factor; verified < 1 SOL is a small negative factor.
5. Backtest Gate 1 uses **decision-time volume only**. Peak / future volume
   may label outcomes after the decision, never admission.

Canonical profile: `volume-first-v1.0.0`.
Legacy fee-hard profile remains as `LEGACY_FEE_GATE_CONFIG`
(`axiom-parity-v1.0.0`) and is not the default.

## Consequences

- More CAs enter the desk.
- Deeper analysis is required before any alert.
- Live verification may produce **NO LIVE ALERT QUALIFIED** even with
  several Gate 1 passes. That is correct.
- ADR-009 FeeResolver architecture is preserved; only its role as a
  mandatory admission gate is superseded.

## Non-goals

- Do not estimate fees from volume.
- Do not treat creator fees as global fees.
- Do not call runner potential a calibrated probability until measured.
- Do not invent wallets, scores, or historical similarity.
