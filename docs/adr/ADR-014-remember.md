# ADR-014 — Accumulating memory that can be queried as-of

Status: Accepted
Date: 2026-08-30

## Context

Gate 1 still only knocks on the door. IntelligenceMemory existed but resemblance
was a runner count, fingerprints were thin, hydration was process-local plus
SQL inserts, and UNKNOWN books could theoretically match other empty books.

## Decision

1. Decision-time fingerprints cover MARKET / WALLET / CREATOR / ENTITY /
   SYNTHETIC buckets. Missing stays `U`. A key with fewer than 3 informative
   bands cannot claim resemblance.
2. As-of resemblance returns the outcome distribution (RUNNER / HELD / FADE /
   UNKNOWN) and matching mints. Sample ≥ 5 is still required. This is evidence,
   not a probability (`calibrated_probability = false`).
3. Runner-support vs fade-support are labeled separately from historical
   counts. They are not hardcoded universal goods/bads.
4. Wallet/creator stats are as-of, exclude the current mint, and never invent
   returns.
5. SQLite is the hydration proof when Postgres is not running. Postgres remains
   the production contract (`006` + `007`).
6. Volume is still not a bullish score. UNKNOWN still does not promote.

## Consequences

Later mints can use earlier labeled evidence. Restart reconstructs state from
the store. Empty books do not become a fake pattern.
