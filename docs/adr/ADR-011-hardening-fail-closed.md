# ADR-011 — Fail-closed investigation semantics (hardening)

Status: Accepted
Date: 2026-08-30
Supersedes (partially): investigation claims in ADR-010. Gate 1 thresholds in
ADR-010 are unchanged.

## Context

Volume-first Gate 1 (`$150k` 5m) is an investigation trigger. The first
implementation still collapsed missing evidence into LOW / QUALIFIED, treated
empty buyer lists as intelligence, let pool programs contaminate wallet
scoring, and allowed future `wallet_performance` on a historical row to leak
into backtest scores.

That made the desk look smarter than the data.

## Decision

1. **UNKNOWN stays UNKNOWN.** Synthetic LOW requires ≥3 independent observed
   signals including concentration or diversity. A single clean print is not
   LOW. Rug with no risk findings is UNKNOWN, not LOW. Unknown creator is
   missing data, not a rug hit.
2. **Pipeline statuses** actually assigned:
   `REJECTED` → `DISCOVERED` (Gate 1, no inspect yet) → `INVESTIGATING` →
   `UNKNOWN` (inspect complete, no meaningful intelligence) /
   `QUALIFIED` / `HIGH_RISK` / `ALERT`.
   QUALIFIED is not a buy signal and is not rendered as green/pass.
3. **Intelligence bar.** `_has_intelligence` requires stored smart-money
   (sample ≥ 3) **or** a known creator with ≥1 stored launch. Unique-wallet
   counts and DexScreener txn counts are not intelligence. Volume alone
   cannot alert and cannot QUALIFY.
4. **Wallet scoring.** Pool/program addresses are dropped. Duplicate trades
   are dropped by `(signature, wallet, side)`. Insufficient history is
   `OBSERVED`, never smart money.
5. **Score v0.5 weights unchanged.** Components are labeled
   (`volume_component`, `wallet_component`, …). Runner potential remains a
   0–100 score with `calibrated_probability = false`. Serial-deployer
   pattern matches do not add the structural +8.
6. **Backtest as-of.** `decision_time_snapshot` strips peak/outcome fields
   and drops `wallet_performance` / `historical_patterns` unless the row is
   explicitly marked as-of-decision. Metrics are unique-mint:
   `unique_candidates`, `gate1_passed`, `investigated`, `qualified`,
   `alerts`, `runners`, `held`, `fades`, `unknown`, `precision`, `coverage`,
   `false_positive_rate`.
7. **One admission path.** `FilterConfig.min_volume_usd` is clamped to
   ≤ `$200k`. `qualify_fresh_pump_migration`, Discord, replay, and discovery
   consume `evaluate_gate1` / `StinkyFilterEngine`. Fees are never Gate 1.
8. **Do not retune** the $150k threshold or score weights from the current
   tiny sample.

## Consequences

- Live tokens that only print volume will sit in `UNKNOWN` / `DISCOVERED`,
  not `QUALIFIED`.
- UI must not paint QUALIFIED or UNKNOWN as pass/green.
- Historical similarity is still UNKNOWN until an as-of store exists.
  Do not invent "we've seen this 14 times."
