# ADR-013 — UNKNOWN is not bullish

Status: Accepted
Date: 2026-08-30

## Context

ADR-012 made `promote=false` on UNKNOWN. The numeric score still started at 50
and added +6/+12 for Gate 1 volume, so a volume-only print looked like a
mid-pack maybe-buy. That is the failure mode:

> "We don't know if this is bad, therefore it might be good."

$150k–$200k 5m volume is the discovery funnel. It is not what makes Stinky
bullish.

## Decision

1. `volume_component` is always 0. Volume already ran Gate 1.
2. Buyer count without measured edge is not a positive score delta.
3. When `has_intelligence` is false: `interpretation=INSUFFICIENT_EVIDENCE`,
   `actionable=false`, `runner_potential=None`, `promote=false`.
4. `can_alert` / `can_alert_investigation` reject `INTELLIGENCE_INSUFFICIENT`
   **before** comparing the numeric score. A 50 is not a near-miss.
5. Buyer count is not a substitute for stored intelligence.
6. The UI shows `UNK` / `INSUFFICIENT — not a grade` instead of the 50-point
   number. QUALIFIED is not painted as a pass/buy.

`calibrated_probability` stays false. No ML.

## Consequences

- Two tokens at $150k and $400k with no wallet/creator history receive the
  same non-actionable score and neither promotes.
- Stored as-of intelligence (ADR-012) remains the only path to a grade.
- Process-local memory hydrates from Postgres on sentinel start so UNKNOWN
  can become KNOWN later without leaking the future into the past.
