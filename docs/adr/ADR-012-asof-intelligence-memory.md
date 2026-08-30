# ADR-012 — As-of intelligence memory

Status: Accepted
Date: 2026-08-30

## Context

Volume-first Gate 1 ($150k 5m) is an investigation trigger. The desk still
could not *accumulate* wallet, creator, relationship, or pattern evidence
with temporal integrity. Live `wallet_performance` is a running aggregate.
Backtest rows that carry future stats leak.

UNKNOWN was collapsing into a numeric score that looked like a maybe-buy.

## Decision

1. `IntelligenceMemory` is the as-of store. Queries use strictly
   `observed_at < decision_timestamp` and `exclude_mint`.
2. Observations are recorded at decision time. Outcomes are recorded at
   `labeled_at`. A later mint may use earlier outcomes only if they were
   labeled before its decision.
3. Smart money still requires sample ≥ 3. A creator with < 3 prior launches
   is OBSERVED, not intelligence.
4. Pattern resemblance requires fingerprint sample ≥ 5. Below that: UNKNOWN,
   not a positive.
5. Co-buy relationships require ≥ 2 prior shared mints. No aggressive merge.
6. Synthetic HIGH/CRITICAL requires ≥ 2 independent risk families.
7. `promote = False` unless pipeline is QUALIFIED and `has_intelligence`.
   UNKNOWN is insufficient evidence. It is never a reason to like a CA.
8. `calibrated_probability` stays false. No ML in this phase.
9. Postgres tables (`006_intelligence_memory.sql`) persist the same facts.
   Neo4j is still not deployed.

## Consequences

- Backtest can learn across a sequence of unique mints without leakage.
- Live sentinel keeps a process-local memory and records buyers at Gate 1.
- Historical similarity stays UNKNOWN until enough as-of samples exist.
- Score remains explainable. Volume does not promote.
