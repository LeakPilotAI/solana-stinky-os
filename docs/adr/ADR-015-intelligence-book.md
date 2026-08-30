# ADR-015 — Intelligence book, why-engine, information advantage

Status: Accepted
Date: 2026-08-30

## Context

As-of memory exists. The operator still cannot see the book, replay a Gate 1
moment, or measure how much Stinky added beyond a volume print.

## Decision

1. One canonical engine. `IntelligenceMemory` remains the store. `book.py`
   is a ledger/time-machine layer over it, not a second intelligence system.
2. Fingerprint **key** stays 10-band (`fingerprint-v1.1.0-book`). Extra
   dimensions (mcap, ratios) live in features. Missing stays None/U.
3. `why_this_ca` is human-readable evidence. `information_advantage` counts
   extra layers beyond volume. It is **not** financial alpha.
   `calibrated_probability = false`.
4. Outcomes may be labeled from post-decision market ticks. No ticks → UNKNOWN.
5. Time Machine answers: "what would Stinky have known at T?" Future hidden.
6. Gate 1 remains $150k 5m. Fees are not a gate. UNKNOWN does not promote.
7. No ML. No Neo4j.

## Consequences

Live scans can accumulate market fingerprints and later ticks without inventing
wallets. Wallet/creator books stay empty until buyers persist. The UI must say
UNKNOWN, not zero.
