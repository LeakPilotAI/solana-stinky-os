# ADR-017 Live evidence, stages, and dataset health

- Status: Accepted
- Date: 2026-08-30

## Context

Recognition v2 remembers wallets, creators, fingerprints, and analogues.
The remaining bottleneck is sample size plus making evidence first-class so
UNKNOWN is a research queue, not a missing row.

## Decision

- Do not change Gate 1 ($150k 5m, max $200k, fees not required).
- Do not retune score weights. `calibrated_probability` stays false.
- Do not replace the 10-band fingerprint key.
- Stages (DISCOVERY / INVESTIGATION / RECOGNITION / CONFIDENCE / OUTCOME)
  are labels on the existing pipeline, not a second engine.
- Evidence findings (`finding`, `status`, `confidence`, `evidence_count`)
  are derived from the existing evidence ledger. Tiny samples stay OBSERVED
  or UNKNOWN. STRONG is never auto-promoted here.
- Empty fingerprint bands stay UNKNOWN, never zero.
- Dataset health, UNKNOWN queue, and radars read the same as-of book.
- Backtest reports a chronological 70/15/15 holdout. Holdout is never used
  to retune thresholds.
- Structured investigation logs (DISCOVERED … OUTCOME) are in-process events.

## Consequences

Stinky gets smarter only by accumulating observations. A $150k token with
no stored intelligence remains UNKNOWN / INSUFFICIENT_EVIDENCE.
