# ADR-023 — Genesis coordination (intel-v2.0.0)

Status: Accepted
Date: 2026-09-03

## Context

Tabs, services, and stores already exist. They did not share one investigation
identity in the desk. Operators saw independent widgets.

## Decision

1. Canonical identity is the existing `correlation_id` (`mint` + `gate1_at`).
   No second investigation table.
2. `stinky_core.coordination` is an **assembler** over IntelligenceMemory,
   observation slices, quality state, analogues, recipes, and outcomes.
3. Evidence quality is `LIVE | FIXTURE | SIMULATION | HISTORICAL`. Missing is
   UNKNOWN. UNKNOWN is not a zero and not a risk score.
4. Lifecycle is derived from stored gate/status/quality/outcome fields, not UI.
5. SIMULATION is labeled SIMULATION and cannot be LIVE.
6. As-of queries hide later ticks (existing observation_slices / quality_state).
7. Command Center synthesis uses already-fetched desk rows. Full case file is
   on-demand at `/v1/coordination/{mint}` so the 6s poll does not hydrate the
   entire book again.
8. Gate 1 remains $150,000 / 5m, clamp $200,000. No ML. No trading.

## Consequences

Empty books stay empty. Analogue sample < 5 stays UNKNOWN. Health probes stay
non-destructive (`_reset` forbidden on ping).
