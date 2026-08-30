# ADR-016 — Recognition: reputation, similarity, life slices

Status: Accepted
Date: 2026-08-30

## Context

The book remembers Gate 1 snapshots. Operators still cannot say "I've seen this
structure before" with sample-aware wallet/creator tiers, analogue explanations,
or a T+ path that hides the future.

## Decision

1. Wallet gate status stays UNKNOWN / OBSERVED / KNOWN. Reputation tiers
   OBSERVED / DEVELOPING / MEASURED / STRONG are extra labels. 2/2 is never STRONG.
2. Creator reputation: UNKNOWN / OBSERVED / DEVELOPING / MEASURED /
   HIGH_CONFIDENCE / HIGH_RISK. Serial (≥15 launches) is HIGH_RISK.
3. Similarity v2 sits on IntelligenceMemory. Exact 10-band match is strong
   (sample ≥ 5). Partial match is overlapping informative bands. All outcome
   classes are returned. `calibrated_probability = false`. Not a chance of running.
4. Life slices T+0/30/60/120/180/300/600 use market ticks only. Wallet/creator
   stay the T+0 as-of snapshot. Future ticks after `as_of` are hidden.
5. Score weights are not retuned. `historical_similarity_component` is labeled 0.
   Volume remains the funnel. Fingerprint **key** stays 10-band.
6. No ML. No Neo4j. Gate 1 remains $150k 5m. Fees are not a gate.

## Consequences

Every investigated CA can accumulate reputation and analogues without promoting
UNKNOWN. Time Machine can show what was known at T+ offsets without leakage.
